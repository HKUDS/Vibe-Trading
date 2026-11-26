"""Track requested file writes and record the model that produced each file."""

from __future__ import annotations

from src.tools.path_utils import FileRoots

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from src.product.tool_results import _TARGET_ACTION_RE, _named_target_paths

logger = logging.getLogger(__name__)


def record_written_target(
    arguments: Mapping[str, Any],
    *,
    roots: FileRoots,
    written_files: set[str],
    run_dir: str | None,
    llm_runtime: Any,
    active_model_id: str | None,
    active_model_source: str,
) -> None:
    """Remember a file written by write_file or edit_file for completion checks.

    Args:
        arguments: Tool arguments containing path or file_path.
        roots: Authorized file roots used to validate a separate adaptation run.
        written_files: Set to update with the case-folded target path.
        run_dir: Current run directory for resolving relative paths and model provenance.
        llm_runtime: Runtime snapshot supplying the provider for strategy provenance.
        active_model_id: Model identifier to record for this write, if available.
        active_model_source: Label for the source of the recorded model identifier.
    """
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
        relative = ""
    if relative not in {"config.json", "code/signal_engine.py"}:
        # Use the prepared adaptation run’s own config to verify its identity.
        candidate = resolved.parent.parent if resolved.name == "signal_engine.py" and resolved.parent.name == "code" else resolved.parent
        if resolved.name not in {"config.json", "signal_engine.py"}:
            return
        try:
            from src.tools.path_utils import safe_run_dir

            candidate = safe_run_dir(str(candidate), roots=roots)
            config = json.loads((candidate / "config.json").read_text(encoding="utf-8"))
            token = config["strategy_adaptation"]["token"]
            if not isinstance(token, str) or candidate.name != f"adaptation-{token}":
                return
            relative = resolved.relative_to(candidate).as_posix()
            if relative not in {"config.json", "code/signal_engine.py"}:
                return
            run_root = candidate
        except (OSError, ValueError, KeyError, TypeError):
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
    user_message: str, run_started_wall: float, *, written_files: set[str], run_dir: str | None
) -> str:
    """Build a reminder when a task asks for file writes and none of its targets is confirmed.

    Args:
        user_message: User prompt containing write intent and named target paths.
        run_started_wall: Run start as a Unix timestamp used to recognize recent writes.
        written_files: Case-folded target paths already recorded for this run.
        run_dir: Directory the run's tools write to, if known. Relative targets resolve
            here rather than in the server's working directory, so a file any tool (bash
            included) created there counts.

    Returns:
        A directive listing the named targets, or an empty string when there is
        no recognized request or any target was recorded or modified since run start.
    """
    if not _TARGET_ACTION_RE.search(user_message or ""):
        return ""
    targets = _named_target_paths(user_message)
    if not targets:
        return ""
    # Bare targets may be siblings of absolute targets named in the same request.
    base_dirs = [p.parent for p in targets if p.parent != Path(".")]
    for target in targets:
        candidates = [target]
        if not target.is_absolute() and target.parent == Path("."):
            candidates += [directory / target.name for directory in base_dirs]
        if run_dir:
            candidates = [Path(run_dir) / candidate for candidate in candidates]
        for candidate in candidates:
            try:
                key = str(candidate.resolve()).casefold()
            except (OSError, ValueError):
                key = str(candidate).casefold()
            if key in written_files:
                return ""
            try:
                if candidate.exists() and candidate.stat().st_mtime >= run_started_wall:
                    return ""
            except OSError:
                pass
    return (
        "[SYSTEM] The following task target file(s) have NOT been written "
        "yet in this run: " + ", ".join(map(str, targets)) + ". Write them NOW using "
        "write_file/edit_file (or bash for file operations). If your task "
        "was to create or update a file, a plain-text answer without the "
        "file write is a failure."
    )
