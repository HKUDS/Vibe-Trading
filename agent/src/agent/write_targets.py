"""Write-target tracking: written-file ledger + pending-write directive.

Extracted from ``AgentLoop`` (issue #1624, roadmap item: split ``loop.py``
along its existing seams). The regex/path helpers this builds on —
``_TARGET_ACTION_RE`` and ``_named_target_paths`` — already moved to
``src.agent.tool_results`` in the first extraction (#1636); this completes
that relocation by moving the two class methods that consumed them, so all
of write-target tracking lives together and ``loop.py`` stays the
orchestrator.

State stays on the loop: ``written_files`` is passed in and mutated in
place by ``record_written_target``; the provenance identity fields are
read at delegation time in ``loop.py``. Behavior is unchanged — every
branch condition, regex, and message string moved verbatim.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from src.agent.tool_results import _TARGET_ACTION_RE, _named_target_paths

logger = logging.getLogger(__name__)


def record_written_target(
    arguments: Mapping[str, Any],
    *,
    written_files: set[str],
    run_dir: str | None,
    llm_runtime: Any,
    active_model_id: str | None,
    active_model_source: str,
) -> None:
    """Remember a file written by write_file/edit_file for completion checks."""
    raw = arguments.get("path") or arguments.get("file_path")
    if not raw:
        return
    p = Path(str(raw))
    if not p.is_absolute() and run_dir:
        p = Path(run_dir) / p
    try:
        resolved = p.resolve()
        written_files.add(str(resolved).casefold())
    except (OSError, ValueError):
        resolved = p
        written_files.add(str(p).casefold())

    if not run_dir:
        return
    run_root = Path(run_dir).resolve()
    try:
        relative = resolved.relative_to(run_root).as_posix()
    except ValueError:
        return
    if relative not in {"config.json", "code/signal_engine.py"}:
        return

    metadata_path = run_root / "strategy_provenance.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        files = {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not read strategy model provenance; update skipped: %s",
            exc,
        )
        return
    else:
        if not isinstance(metadata, dict):
            logger.warning("Invalid strategy model provenance; update skipped.")
            return
        files = metadata.get("files", {})
        if not isinstance(files, dict):
            logger.warning("Invalid strategy model provenance files; update skipped.")
            return
    files[relative] = {
        "provider": llm_runtime.provider or None,
        "model_id": active_model_id or None,
        "model_source": active_model_source,
    }
    try:
        metadata_path.write_text(
            json.dumps({"files": files}, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not write strategy model provenance: %s", exc)


def pending_write_directive(
    user_message: str, run_started_wall: float, *, written_files: set[str]
) -> str:
    """Return a directive naming task target files not yet written this run.

    Empty when the message names no .md targets, carries no create/update
    intent, or every named target has been written (directly via
    write_file/edit_file, or by any process whose mtime is newer than the
    run start - which covers the bash workaround).
    """
    if not _TARGET_ACTION_RE.search(user_message or ""):
        return ""
    targets = _named_target_paths(user_message)
    if not targets:
        return ""
    pending: list[str] = []
    # A bare target ("create X.md at the same folder") carries no directory;
    # resolve it against the folders of the absolute targets named in the
    # same message, or the run would never see the file the model wrote to
    # the intended folder and would report a false "not written".
    base_dirs = [p.parent for p in targets if p.parent != Path(".")]
    any_written = False
    for p in targets:
        candidates = [p]
        if not p.is_absolute() and p.parent == Path("."):
            candidates += [d / p.name for d in base_dirs]
        written = False
        for cand in candidates:
            try:
                key = str(cand.resolve()).casefold()
            except (OSError, ValueError):
                key = str(cand).casefold()
            if key in written_files:
                written = True
                break
            if not written:
                try:
                    if cand.exists() and cand.stat().st_mtime >= run_started_wall:
                        written = True
                        break
                except OSError:
                    pass
        if written:
            any_written = True
        else:
            pending.append(str(p))
    # If any named target was written this run, the create/update task is
    # addressed; reference files named alongside (e.g. "refer to A, create B")
    # are never "written" and must not trigger the directive.
    if any_written or not pending:
        return ""
    return (
        "[SYSTEM] The following task target file(s) have NOT been written "
        "yet in this run: " + ", ".join(pending) + ". Write them NOW using "
        "write_file/edit_file (or bash for file operations). If your task "
        "was to create or update a file, a plain-text answer without the "
        "file write is a failure."
    )
