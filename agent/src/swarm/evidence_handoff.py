"""Carry observations between committee roles without granting sibling access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from src.config.accessor import get_env_config
from src.product.result_artifacts import _write_original, save_result_parts
from src.session.thread import ThreadLog
from src.swarm.artifacts import agent_artifact_dir, node_thread
from src.tools.path_utils import is_runtime_path, safe_path
from src.tools.redaction import redact_text, redact_tool_result


def _recorded_results(source: Path, thread_path: Path) -> Iterator[tuple[dict, str, str, str, str | None]]:
    """Yield recorded calls and their results, including from pre-cutover runs."""
    if thread_path.is_file():
        calls = {}
        for item in ThreadLog(thread_path).read():
            if item.type == "assistant":
                for call in item.get("tool_calls") or []:
                    calls[item.turn_id, call["id"]] = call.get("function", {})
            elif item.type == "tool_result":
                call_id = item.get("tool_call_id", "")
                call = calls.pop((item.turn_id, call_id), None)
                if call is not None and item.get("status") == "ok":
                    yield call, call_id, item.get("name", "unknown"), item.get("content", ""), item.turn_id
        return

    messages_path = safe_path("messages.json", source)
    if messages_path.is_file():
        calls = {}
        for message in json.loads(messages_path.read_text()):
            for call in message.get("tool_calls", []):
                calls[call["id"]] = call.get("function", {})
            if message.get("role") == "tool":
                call_id = message.get("tool_call_id", "")
                yield (
                    calls.get(call_id, {}), call_id, message.get("name", "unknown"),
                    message.get("content", ""), None,
                )


def _in_workspace(recorded: str, agent_id: str, task_id: str) -> str | None:
    """Return a recorded absolute path relative to the producer workspace, whichever run directory it names."""
    marker = f"/artifacts/{agent_id}/{task_id}/"
    posix = Path(recorded).as_posix()
    return posix[posix.rindex(marker) + len(marker):] if marker in posix else None


def _observations(source: Path, agent_id: str, task_id: str, errors: list[str],
                  thread_path: Path | None = None) -> list[tuple[dict, str]]:
    """Read recorded observations, retaining their original producing role."""
    found = []
    inherited = safe_path("upstream/index.json", source)
    if inherited.is_file():
        # A bad inherited index costs only the inherited part, never this task's own observations.
        try:
            listed = json.loads(inherited.read_text())
            listed = listed.get("observations", []) if isinstance(listed, dict) else None
            if not isinstance(listed, list):
                raise ValueError("not an evidence index")
        except (OSError, ValueError) as exc:
            errors.append(f"{task_id} inherited index unavailable: {exc}")
            listed = []
        for entry in listed:
            try:
                path = safe_path(entry["path"], source)
                raw = path.read_text()
                if hashlib.sha256(raw.encode()).hexdigest() != entry["sha256"]:
                    raise ValueError("Inherited evidence file changed")
                found.append((entry, raw))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{task_id} inherited observation unavailable: {exc}")
    thread_path = thread_path or safe_path("thread.jsonl", source)
    canonical = thread_path.is_file()
    for call, call_id, name, raw, turn_id in _recorded_results(source, thread_path):
        tool = call.get("name", name)
        # Methodology/file plumbing is already in the transcript; it is not a
        # fresh observation. This selection never decides whether a task passes.
        if tool in {"load_skill", "read_file", "write_file", "edit_file", "bash"}:
            continue
        args = call.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        if tool == "quantlib_call" and args.get("action") != "call":
            continue
        if not isinstance(raw, str):
            continue
        try:
            result = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(result, dict):
            continue
        if "_result_file" in result:
            ref = result["_result_file"]
            # Resumed logs can still name the old workspace. Resolve inside the copied
            # source task, at the tool's own run_dir (a workspace subdirectory) when the
            # receipt names one, and accept only the content hash it recorded.
            try:
                if not isinstance(ref, dict):
                    raise ValueError("Invalid observation receipt")
                digest = ref.get("sha256")
                if not isinstance(digest, str) or len(digest) != 64 or any(
                    c not in "0123456789abcdef" for c in digest
                ):
                    raise ValueError("Invalid observation digest")
                relative = f"tool-results/{digest}/result.json"
                recorded = _in_workspace(str(ref.get("path") or ""), agent_id, task_id)
                if recorded is not None and Path(recorded).parts[-3:] == ("tool-results", digest, "result.json"):
                    relative = recorded
                path = safe_path(relative, source)
                if canonical and not path.is_file():
                    path = safe_path(f"workspace/{relative}", source)
                raw = path.read_text()
                if hashlib.sha256(raw.encode()).hexdigest() != digest:
                    raise ValueError("Source observation file changed")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{task_id}/{call_id} observation unavailable: {exc}")
                continue
        entry = {"source_task": task_id, "tool": tool, "call_id": call_id,
                 "request": {key: args[key] for key in
                             ("codes", "symbol", "code", "start_date", "end_date", "module", "function")
                             if key in args}}
        if turn_id is not None:
            entry["turn_id"] = turn_id
        found.append((entry, raw))
    return found


def _produced_files(source: Path, thread_path: Path, agent_id: str, task_id: str,
                    errors: list[str]) -> dict[str, tuple[str, str]]:
    """Map each workspace file a node's successful write or shell call produced to that call."""
    produced: dict[str, tuple[str, str]] = {}
    for call, call_id, name, raw, _ in _recorded_results(source, thread_path):
        tool = call.get("name", name)
        if tool not in {"write_file", "edit_file", "bash"}:
            continue
        try:
            result = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            continue
        if not isinstance(result, dict) or result.get("status") != "ok":
            continue
        if tool == "bash":
            paths = [ref.get("path") for ref in result.get("artifacts") or [] if isinstance(ref, dict)]
        else:
            # Recorded paths are absolute and may name the run directory a resumed run came from.
            written = str(result.get("path") or "")
            relative = _in_workspace(written, agent_id, task_id)
            if relative is not None:
                paths = [relative]
            elif written and not Path(written).is_absolute():
                paths = [written]
            else:
                errors.append(f"{task_id}/{call_id}: {tool} output is outside the producer workspace")
                continue
        for relative in paths:
            if isinstance(relative, str) and relative and not is_runtime_path(relative):
                produced[relative] = (tool, call_id)
    return produced


def _read_produced(source: Path, relative: str, budget: int) -> bytes:
    """Read one produced file within the budget, refusing escapes, symlinks and non-files."""
    path = safe_path(relative, source)
    current = source
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("is a symlink")
    if not path.is_file():
        raise ValueError("is no longer a regular file")
    size = path.stat().st_size
    if size > budget:
        raise ValueError(f"{size} bytes exceed the remaining file copy budget")
    return path.read_bytes()


def _write_bytes(path: Path, content: bytes, root: Path) -> None:
    """Save an immutable copy inside the workspace, or refuse a changed one."""
    if not path.resolve().is_relative_to(root):
        raise ValueError("Copied file escapes workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("Existing copied file was modified")


def prepare_handoff(run_dir: Path, task, destination: Path) -> str:
    """Copy upstream observations into this task's readable workspace.

    Args:
        run_dir: Current swarm run directory, including copied artifacts when resumed.
        task: Consumer task whose input_from identifies the upstream producers.
        destination: Consumer artifact directory.

    Returns:
        Prompt note pointing to the paged provenance index, which lists the copied observations,
        the files each upstream task produced (copied by content hash under ``upstream/files``)
        and anything unavailable. Returns an empty string if there is nothing to report.

    Raises:
        ValueError: If the index would escape the workspace or differs from one already written.
        OSError: If the index or its parts cannot be written.
    """
    from src.swarm.task_store import TaskStore

    if not task.input_from:
        return ""
    root = destination.resolve()
    folder = safe_path("upstream", root)
    entries, files, errors, seen = [], [], [], set()
    cap = budget = get_env_config().swarm.swarm_handoff_max_file_bytes
    store = TaskStore(run_dir)
    for task_id in dict.fromkeys(task.input_from.values()):
        try:
            source_task = store.load_task(task_id)
            source = agent_artifact_dir(run_dir, source_task.agent_id, task_id)
            thread = node_thread(run_dir, source_task.agent_id, task_id)
            if thread.is_file():
                produced = _produced_files(source, thread, source_task.agent_id, task_id, errors)
                for relative, (tool, call_id) in produced.items():
                    try:
                        original = _read_produced(source.resolve(), relative, budget)
                        try:
                            content = redact_text(original.decode("utf-8")).encode("utf-8")
                        except UnicodeDecodeError:
                            content = original
                        if len(content) > budget:
                            raise ValueError(f"{len(content)} bytes exceed the remaining file copy budget")
                        digest = hashlib.sha256(content).hexdigest()
                        path = folder / "files" / digest / Path(relative).name
                        _write_bytes(path, content, root)
                    except (OSError, ValueError) as exc:
                        errors.append(f"{task_id}/{relative}: produced file not copied: {exc} "
                                      f"({budget} of {cap} bytes left, SWARM_HANDOFF_MAX_FILE_BYTES)")
                        continue
                    budget -= len(content)
                    files.append({"source_task": task_id, "tool": tool, "call_id": call_id,
                                  "original_path": relative, "path": str(path.relative_to(root)),
                                  "sha256": digest, "size": len(content), "redacted": content != original})
            observations = _observations(source, source_task.agent_id, task_id, errors, thread if thread.is_file() else None)
            for entry, raw in observations:
                raw = redact_tool_result(raw)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                identity = (entry["source_task"], entry.get("turn_id"), entry["call_id"], digest)
                if identity in seen:
                    continue
                seen.add(identity)
                path = folder / f"{digest}.json"
                _write_original(path, raw, root)
                parts = save_result_parts(raw, folder / digest / "parts", root)
                entries.append({**entry, "path": str(path.relative_to(root)), "sha256": digest,
                                "parts_dir": str((folder / digest / "parts").relative_to(root)),
                                "part_count": len(parts)})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{task_id}: {type(exc).__name__}: {exc}")
    if not entries and not files and not errors:
        return ""
    content = json.dumps({"observations": entries, "files": files, "unavailable": errors}, ensure_ascii=False)
    # Same dependencies yield identical bytes on retry/continuation. No report
    # text is rewritten and no source status is promoted by copying its files.
    index = folder / "index.json"
    _write_original(index, content, root)
    parts = save_result_parts(content, folder / "index-parts", root)
    tools = ", ".join(sorted({entry["tool"] for entry in entries})) or "none recorded"
    return (
        "## Inherited evidence\n"
        f"{len(entries)} recorded observations ({tools}). Read upstream/index.json; "
        f"For paged reading, use upstream/index-parts/1.txt through upstream/index-parts/{len(parts)}.txt. "
        "Each entry identifies its producing task/tool and a local JSON path usable "
        "by quantlib_call __data_ref__. These are inherited observations, not fresh "
        "fetches by you. Independent analysis can reuse them; describe what you "
        "actually recalculated or newly retrieved. Original dates and assumptions "
        "still apply. Missing evidence does not invalidate the available report.\n"
        f"{len(files)} files produced by upstream tasks are copied under upstream/files/; the "
        "\"files\" entries in upstream/index.json give each one's source task, original path, "
        "sha256 and size."
    )
