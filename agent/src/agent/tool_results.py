"""Tool-result classification, target-path detection, and backtest archiving.

Extracted verbatim from ``src/agent/loop.py`` (issue #1624, roadmap item 3:
split ``loop.py`` along its existing seams). This module owns the module-level
helpers that judge a finished tool call: success/failure classification of a
JSON result envelope, detection of provider tool-call DSL left in final text,
the user-message target-file scan, ``run_dir`` normalization, and the
replace-not-merge archive of a successful detached backtest into the active
run. ``loop.py`` re-exports every moved name, so existing imports keep
working.

Behavior is unchanged: every function body, docstring, and comment moved
byte-for-byte; only the leading indentation of the module changed.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from src.agent.grounding.evidence import ARCHIVE_MANIFEST as _ARCHIVE_MANIFEST
from src.tools.path_utils import safe_run_dir

logger = logging.getLogger(__name__)

def _failure_code(result: str) -> str:
    """The ``error_code`` (else error text) of a refused call, for the stop message."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("error_code") or payload.get("reason") or payload.get("error") or "")[:120]


def _is_tool_success(result: str) -> bool:
    """Return True if the tool result does not look like an error response."""
    try:
        data = json.loads(result)
        if isinstance(data, dict):
            status = str(data.get("status") or "").strip().casefold()
            if status in {"error", "failed", "failure", "cancelled", "canceled"}:
                return False
            if data.get("ok") is False or data.get("success") is False:
                return False
    except (json.JSONDecodeError, TypeError):
        pass
    return True


# Provider tool-call markup that a model can emit as plain text on the
# forced-text final iteration, where tool definitions are withheld. Releasing
# it verbatim hands the user mojibake instead of an answer. Both DSML bar
# spellings are covered: ASCII double bars and fullwidth double bars, opening
# and closing tags (a draft ending in "</｜｜DSML｜｜invoke>" once reached the
# grounding gate as three unreadable figures-block lines).
_FORCED_TEXT_TOOL_CALL_RE = re.compile(
    r"<\s*/?\s*(?:invoke|parameter|tool_calls|dsml)\b",
    re.IGNORECASE,
)
_DSML_BAR_TOOL_CALL_RE = re.compile(
    r"<\s*/?\s*[|\u2502\uFF5C]{2}\s*(?:dsml|tool_calls|invoke)\b",
    re.IGNORECASE,
)


def _looks_like_tool_call_syntax(content: str) -> bool:
    """Return whether final text still contains provider tool-call DSL.

    When tool calling is unavailable, a model may nonetheless answer with its
    native tool-call markup as prose - ``<DSML>tool_calls>``, ``<invoke
    name=...>``, or the fullwidth-vbar mojibake of the same. Such content is
    not an answer and must not be released to the user as one.
    """
    if not content:
        return False
    return bool(
        _FORCED_TEXT_TOOL_CALL_RE.search(content)
        or _DSML_BAR_TOOL_CALL_RE.search(content)
    )


# Task target-file detection: a user message usually names the file to
# create or update ("update C:\\...\\plan.md"). If a run approaches its
# iteration cap without having written that file, the loop must remind the
# model instead of ending "answered but incomplete".
# Windows absolute paths may contain spaces (e.g. C:\Users\Emad Karimi\...),
# so the drive-letter branch allows spaces and stops non-greedily at the first
# ".md"; the POSIX and bare-name branches stay space-free word matches.
_TARGET_PATH_RE = re.compile(
    r"[A-Za-z]:\\[^<>|?*\x22\x27\r\n]+?\.md\b"
    r"|/[\w./\\-]+\.md\b"
    r"|\b[\w./\\-]+\.md\b"
)
_TARGET_ACTION_RE = re.compile(
    r"update|create|write|add|make|edit|generate|overwrite|append"
    r"|更新|创建|写|添加|修改|生成|建立|编制",
    re.IGNORECASE,
)


def _named_target_paths(text: str) -> list[Path]:
    """Return the .md file paths named in a user message (deduped).

    Both absolute Windows paths and bare or relative filenames are matched.
    """
    seen: set[str] = set()
    paths: list[Path] = []
    for match in _TARGET_PATH_RE.finditer(text or ""):
        raw = match.group(0).strip().strip("\x22\x27")
        try:
            p = Path(raw)
        except (ValueError, OSError):
            continue
        if p.suffix != ".md":
            continue
        key = str(p).casefold()
        if key in seen:
            continue
        seen.add(key)
        paths.append(p)
    return paths
def _normalize_tool_run_dir(args: dict[str, Any], memory_run_dir: str | None) -> dict[str, Any]:
    """Normalize ``run_dir`` in tool args to an absolute path when possible.

    If the model supplies a relative ``run_dir`` (for example ``"."`` or
    ``"risk_parity_run"``), resolve it against the active run directory.
    """
    normalized = dict(args)
    if not memory_run_dir:
        return normalized

    if "run_dir" not in normalized:
        normalized["run_dir"] = memory_run_dir
        return normalized

    run_dir_value = str(normalized["run_dir"]).strip()
    if not run_dir_value:
        normalized["run_dir"] = memory_run_dir
        return normalized

    candidate = Path(run_dir_value)
    if not candidate.is_absolute():
        normalized["run_dir"] = str((Path(memory_run_dir) / candidate).resolve())
    return normalized


# ``_ARCHIVE_MANIFEST`` names the backtest an archived run currently describes,
# and the files that archive placed there, so the next one can replace exactly
# its own output. The grounding ledger reads it to tell whose copy it is.


def _previously_archived(target: Path) -> set[str]:
    """Return the run-relative files the previous archive copied into ``target``.

    The caller deletes what this returns, and the names are read back off disk,
    so each one is confined to ``target`` here — a manifest carrying ``..`` must
    not become a way to delete a file elsewhere. An unreadable or malformed
    manifest yields an empty set: the worst case is the pre-#1094 merge for one
    turn, which beats refusing to archive a backtest the user is waiting for.
    """
    try:
        payload = json.loads((target / _ARCHIVE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return set()
    root = target.resolve()
    return {
        str(name)
        for name in files
        if isinstance(name, str)
        and (root / name).resolve().is_relative_to(root)
        and (root / name).resolve() != root
    }


def _archive_backtest_result(
    result: str, active_run_dir: str | None, *, source_call_id: str | None = None
) -> bool:
    """Copy a successful detached backtest into the active, reportable run.

    The model may choose another allowed run directory while iterating.  The
    CLI and web API, however, identify the turn by ``active_run_dir``.  Keep
    that public identity stable by copying only deterministic backtest output
    into the active run as soon as the backtest tool succeeds.

    Both paths are re-validated here.  ``backtest`` already refuses a run_dir
    outside the allowed roots, so today the source cannot be arbitrary — but
    that invariant lives in another module and this function reads its path back
    out of a *tool result* rather than from the validated arguments.  Checking
    locally keeps a copy loop from depending on a guarantee made elsewhere.

    The copy REPLACES the previous archive rather than merging with it (#1094).
    An agent may backtest more than once in a turn, and the copy is a plain
    merge, so a file only the earlier backtest produced used to survive
    alongside the later one's output — one artifacts directory describing two
    different runs, which ``/runs/{id}`` then lists as artifacts of the current
    one.  Only files a previous archive placed here are removed, recorded in
    :data:`_ARCHIVE_MANIFEST`; anything the active run wrote itself (notably
    ``code/signal_engine.py``, written before ``backtest`` is called) is
    untouched, which is why the manifest exists instead of a blanket wipe.

    Args:
        result: Serialized successful backtest tool result.
        active_run_dir: Active turn directory that receives reportable output.
        source_call_id: Exact tool call recorded with the archive's source path.

    Returns:
        Whether a detached backtest's output was archived.
    """
    if not active_run_dir:
        return False
    try:
        payload = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False

    source_value = payload.get("run_dir")
    if not source_value:
        return False
    try:
        source = safe_run_dir(str(source_value))
        target = safe_run_dir(str(active_run_dir))
    except ValueError:
        logger.warning("Refusing to archive backtest output from outside the allowed run roots")
        return False
    if source == target or not (source / "artifacts" / "metrics.csv").is_file():
        return False

    target.mkdir(parents=True, exist_ok=True)
    previously_archived = _previously_archived(target)
    archived: list[str] = []
    for directory in ("artifacts", "code", "logs"):
        source_dir = source / directory
        if source_dir.is_dir():
            shutil.copytree(source_dir, target / directory, dirs_exist_ok=True)
            archived += [
                path.relative_to(source).as_posix()
                for path in source_dir.rglob("*")
                if path.is_file()
            ]
    for stale in previously_archived - set(archived):
        (target / stale).unlink(missing_ok=True)
    (target / _ARCHIVE_MANIFEST).write_text(
        json.dumps({
            "source_run": source.name,
            "source_run_dir": str(source.resolve()),
            "source_call_id": source_call_id,
            "files": sorted(archived),
        }, indent=2),
        encoding="utf-8",
    )
    for filename in (
        "config.json",
        "design_spec.json",
        "planner_output.json",
        "rag_metadata.json",
        "review_report.json",
        "run_card.json",
        "run_card.md",
        "llm_usage.json",
    ):
        source_file = source / filename
        if source_file.is_file():
            shutil.copy2(source_file, target / filename)
    return (target / "artifacts" / "metrics.csv").is_file()
