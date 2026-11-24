"""Classify tool responses and identify archived backtests and write targets."""

from __future__ import annotations

from src.tools.path_utils import FileRoots

import json
import logging
import re
import shutil
from pathlib import Path

from src.tools.path_utils import safe_run_dir

# Track archive ownership so replacement removes only the prior archive’s files.
ARCHIVE_MANIFEST = ".archived_backtest.json"

logger = logging.getLogger(__name__)

def parse_tool_payload(result: str) -> dict | None:
    """Decode a structured result while allowing plain text."""
    try:
        value = json.loads(result)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _failure_code(result: str) -> str:
    """The error code or refusal text for the stop message."""
    payload = parse_tool_payload(result) or {}
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
        head = (result or "").lstrip()[:160].lower()
        if head.startswith("{") and ('"status": "error"' in head or '"status":"error"' in head):
            return False
    return True


# Recognize plain XML and both ASCII and fullwidth DSML bar spellings.
_FORCED_TEXT_TOOL_CALL_RE = re.compile(
    r"<\s*/?\s*(?:invoke|parameter|tool_calls|dsml)\b",
    re.IGNORECASE,
)
_DSML_BAR_TOOL_CALL_RE = re.compile(
    r"<\s*/?\s*[|\u2502\uFF5C]{2}\s*(?:dsml|tool_calls|invoke)\b",
    re.IGNORECASE,
)


def _looks_like_tool_call_syntax(content: str) -> bool:
    """Detect provider tool-call markup in a forced-text response."""
    if not content:
        return False
    return bool(
        _FORCED_TEXT_TOOL_CALL_RE.search(content)
        or _DSML_BAR_TOOL_CALL_RE.search(content)
    )


# Allow spaces in Windows drive paths and stop at the first .md suffix.
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
    """Return unique .md paths, including Windows absolute paths with spaces."""
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



def _previously_archived(target: Path) -> set[str]:
    """Read the previous archive manifest, limiting deletion candidates to the resolved target."""
    try:
        payload = json.loads((target / ARCHIVE_MANIFEST).read_text(encoding="utf-8"))
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
    result: str, active_run_dir: str | None, *, roots: FileRoots, source_call_id: str | None = None
) -> bool:
    """Archive a detached backtest after revalidating both paths and pruning only previously copied files."""
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
        source = safe_run_dir(str(source_value), roots=roots)
        target = safe_run_dir(str(active_run_dir), roots=roots)
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
    (target / ARCHIVE_MANIFEST).write_text(
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
