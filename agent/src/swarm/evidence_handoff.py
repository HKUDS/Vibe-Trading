"""Carry observations between committee roles without granting sibling access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from src.product.result_artifacts import _write_original, save_result_parts
from src.session.thread import ThreadLog
from src.swarm.artifacts import agent_artifact_dir, node_thread
from src.tools.path_utils import safe_path
from src.tools.redaction import redact_tool_result


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


def _observations(source: Path, task_id: str, errors: list[str], thread_path: Path | None = None) -> list[tuple[dict, str]]:
    """Read recorded observations, retaining their original producing role."""
    found = []
    inherited = safe_path("upstream/index.json", source)
    if inherited.is_file():
        for entry in json.loads(inherited.read_text()).get("observations", []):
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
            # Resumed logs can still name the old workspace. Resolve by content
            # hash inside the copied source task, never by trusting that path.
            try:
                if not isinstance(ref, dict):
                    raise ValueError("Invalid observation receipt")
                digest = ref.get("sha256")
                if not isinstance(digest, str) or len(digest) != 64 or any(
                    c not in "0123456789abcdef" for c in digest
                ):
                    raise ValueError("Invalid observation digest")
                relative = f"tool-results/{digest}/result.json"
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


def prepare_handoff(run_dir: Path, task, destination: Path) -> str:
    """Copy upstream observations into this task's readable workspace."""
    from src.swarm.task_store import TaskStore

    if not task.input_from:
        return ""
    root = destination.resolve()
    folder = safe_path("upstream", root)
    entries, errors, seen = [], [], set()
    store = TaskStore(run_dir)
    for task_id in dict.fromkeys(task.input_from.values()):
        try:
            source_task = store.load_task(task_id)
            source = agent_artifact_dir(run_dir, source_task.agent_id, task_id)
            thread = node_thread(run_dir, source_task.agent_id, task_id)
            observations = _observations(source, task_id, errors, thread if thread.is_file() else None)
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
    if not entries and not errors:
        return ""
    content = json.dumps({"observations": entries, "unavailable": errors}, ensure_ascii=False)
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
        "still apply. Missing evidence does not invalidate the available report."
    )
