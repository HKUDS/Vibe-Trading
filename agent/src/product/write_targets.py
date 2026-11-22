"""Track requested file writes and record the model that produced each file."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from src.product.tool_results import _TARGET_ACTION_RE, _named_target_paths

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
        relative = ""
    if relative not in {"config.json", "code/signal_engine.py"}:
        # Adaptation code is written to a separate, prepared run. Resolve its
        # identity from that run's own config; never stamp the active run's
        # code identity onto a file written somewhere else.
        candidate = resolved.parent.parent if resolved.name == "signal_engine.py" and resolved.parent.name == "code" else resolved.parent
        if resolved.name not in {"config.json", "signal_engine.py"}:
            return
        try:
            from src.tools.path_utils import safe_run_dir

            candidate = safe_run_dir(str(candidate))
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
