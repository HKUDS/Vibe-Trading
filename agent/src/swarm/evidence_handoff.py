"""Carry observations between committee roles without granting sibling access."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

from src.config.accessor import get_env_config
from src.config.limits import TOOL_RESULT_LIMIT
from src.product.result_artifacts import _write_original, save_result_parts
from src.product.tool_results import _is_tool_success
from src.session.thread import ThreadLog
from src.swarm.artifacts import agent_artifact_dir, collect_artifacts, node_thread
from src.tools.bash_tool import _workspace_files
from src.tools.path_utils import is_runtime_path, safe_path
from src.tools.redaction import redact_payload, redact_text, redact_tool_result
from src.tools.workspace_writes import workspace_write_receipt


def _recorded_results(source: Path, thread_path: Path) -> Iterator[tuple[dict, str, str, str, str | None, bool]]:
    """Yield recorded calls, their results and whether each succeeded, including from pre-cutover runs."""
    if thread_path.is_file():
        calls = {}
        for item in ThreadLog(thread_path).read():
            if item.type == "assistant":
                for call in item.get("tool_calls") or []:
                    calls[item.turn_id, call["id"]] = call.get("function", {})
            elif item.type == "tool_result":
                call_id = item.get("tool_call_id", "")
                call = calls.pop((item.turn_id, call_id), None)
                if call is not None:
                    yield (call, call_id, item.get("name", "unknown"), item.get("content", ""), item.turn_id,
                           item.get("status") == "ok")
        return

    messages_path = safe_path("messages.json", source)
    if messages_path.is_file():
        calls = {}
        for message in json.loads(messages_path.read_text()):
            for call in message.get("tool_calls", []):
                calls[call["id"]] = call.get("function", {})
            if message.get("role") == "tool":
                call_id = message.get("tool_call_id", "")
                raw = message.get("content", "")
                yield (
                    calls.get(call_id, {}), call_id, message.get("name", "unknown"),
                    raw, None, _is_tool_success(raw),
                )


def _in_workspace(recorded: str, agent_id: str, task_id: str) -> str | None:
    """Return a recorded absolute path relative to the producer workspace, whichever run directory it names."""
    marker = f"/artifacts/{agent_id}/{task_id}/"
    posix = Path(recorded).as_posix()
    return posix[posix.rindex(marker) + len(marker):] if marker in posix else None


#: Fields an observation entry carries from one handoff to the next; copy locations are
#: rewritten per consumer, and selection tags belong to the consumer that chose them.
_ENTRY_FIELDS = ("source_task", "tool", "call_id", "request", "turn_id")
#: Tools whose recorded results are calculations rather than source observations.
_CALCULATION_TOOLS = frozenset({"bash", "quantlib_call"})
_FAILED_CALLS_PATH = "upstream/failed-calls.json"


def _failed_call(task_id: str, tool: str, call_id: str, turn_id: str | None, raw: str) -> dict:
    """Extract failure diagnostics without copying result data or call arguments."""
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        result = raw
    failure = {"source_task": task_id, "tool": tool, "call_id": call_id, "status": "failed"}
    if turn_id is not None:
        failure["turn_id"] = turn_id
    if isinstance(result, dict):
        failure.update({key: result[key] for key in ("error_code", "exit_code", "skipped", "outcome") if key in result})
        result = result.get("error") or result.get("message") or result.get("reason") or result.get("stderr")
    failure["error"] = result or "The tool did not return an error detail."
    return failure


def _observations(source: Path, agent_id: str, task_id: str, errors: list[str], failures: list[dict],
                  thread_path: Path | None = None) -> list[tuple[dict, str]]:
    """Read recorded observations, retaining their original producing role."""
    found = []
    inherited = safe_path("upstream/index.json", source)
    if inherited.is_file():
        # A bad inherited index costs only the inherited part, never this task's own observations.
        try:
            index = json.loads(inherited.read_text())
            if not isinstance(index, dict):
                raise ValueError("not an evidence index")
            gaps = index.get("unavailable", [])
            if not isinstance(gaps, list) or any(not isinstance(gap, str) for gap in gaps):
                raise ValueError("invalid inherited limitations")
            listed = index.get("observations", [])
            if "audit_file" in index:
                # A selected handoff indexes only what its task chose; the audit keeps everything.
                ref = index["audit_file"]
                raw = safe_path(ref["path"], source).read_text()
                if hashlib.sha256(raw.encode()).hexdigest() != ref["sha256"]:
                    raise ValueError("Inherited audit index changed")
                listed = json.loads(raw).get("observations", [])
            if not isinstance(listed, list):
                raise ValueError("not an evidence index")
            # What an earlier role could not get is still missing for every later one.
            errors.extend(gaps)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"{task_id} inherited index unavailable: {exc}")
            listed = []
        for entry in listed:
            try:
                path = safe_path(entry["path"], source)
                raw = path.read_text()
                if hashlib.sha256(raw.encode()).hexdigest() != entry["sha256"]:
                    raise ValueError("Inherited evidence file changed")
                found.append(({key: entry[key] for key in _ENTRY_FIELDS if key in entry}, raw))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{task_id} inherited observation unavailable: {exc}")
    thread_path = thread_path or safe_path("thread.jsonl", source)
    canonical = thread_path.is_file()
    for call, call_id, name, raw, turn_id, ok in _recorded_results(source, thread_path):
        tool = call.get("name", name)
        if not ok:
            failures.append(_failed_call(task_id, tool, call_id, turn_id, raw))
            continue
        # Methodology/file plumbing is already in the transcript, and written files
        # travel as files; neither is a fresh observation. A shell command is kept:
        # its command and output are how a calculation was done. This selection
        # never decides whether a task passes.
        if tool in {"load_skill", "read_file", "write_file", "edit_file"}:
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
        if not isinstance(result, dict) or (tool == "bash" and result.get("status") != "ok"):
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
                 "request": redact_payload({key: args[key] for key in
                                            ("codes", "symbol", "code", "start_date", "end_date", "module",
                                             "function", "kwargs", "command")
                                            if key in args})}
        if turn_id is not None:
            entry["turn_id"] = turn_id
        found.append((entry, raw))
    return found


def _produced_files(source: Path, thread_path: Path, agent_id: str, task_id: str,
                    errors: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """Map each file a node's tools left in its workspace to the successful call that wrote it, if recorded."""
    produced: dict[str, tuple[str | None, str | None]] = {}
    failed: set[str] = set()
    for call, call_id, name, raw, _, ok in _recorded_results(source, thread_path):
        tool = call.get("name", name)
        if tool not in {"write_file", "edit_file", "bash"}:
            continue
        try:
            result = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            continue
        if not isinstance(result, dict):
            continue
        if not ok or result.get("status") != "ok":
            if tool == "bash":
                failed.update(ref.get("path") for ref in result.get("artifacts") or [] if isinstance(ref, dict))
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
    # Other tools (backtests, factor analysis, exports) name their outputs in no common
    # receipt, so every other file in the producer's own workspace is its output too,
    # except partial output only a failed command reported.
    for relative in collect_artifacts(source, source):
        if relative not in failed and not is_runtime_path(relative):
            produced.setdefault(relative, (None, None))
    return produced


def _attributed_files(
    source: Path, receipt: Path, task_id: str, errors: list[str],
) -> dict[str, tuple[str | None, str | None, tuple[int, int]]]:
    """Read the sealed receipt and list gaps for visible files it cannot authorize."""
    data = json.loads(receipt.read_text())
    if data["sealed"] is not True:
        errors.append(f"{task_id}: workspace write receipt was not sealed")
        return {}
    calls, files, legacy = data["calls"], data["files"], data["legacy"]
    produced = {}
    for relative, stat in sorted((_workspace_files(source, require_request=False) or {}).items()):
        entry = files.get(relative)
        candidates = [calls[index] for index in entry["writers"]] if entry else []
        rejected = []
        for call in candidates:
            if call["outcome"] == "ok":
                continue
            identity = f"{call['tool']} {call['call_id']}"
            if call["task_id"]:
                identity += f" (task {call['task_id']})"
            outcome = call["outcome"]
            if "exit_code" in call:
                outcome += f" with exit code {call['exit_code']}"
            rejected.append(f"{identity}: {outcome}")
        if rejected:
            reason = "; ".join(rejected)
        elif not entry or entry["stat"] != list(stat):
            reason = "no candidate writer for the current file version"
        elif relative in legacy:
            produced[relative] = (*legacy[relative], stat)
            continue
        elif entry["latest"]:
            # Keep the old single-writer fields only when the last change identifies one.
            writer = calls[entry["latest"][0]] if len(entry["latest"]) == 1 else {}
            produced[relative] = (writer.get("tool"), writer.get("call_id"), stat)
            continue
        else:
            reason = "no candidate writer"
        errors.append(f"{task_id}/{relative}: produced file not copied: {reason}")
    return produced


def _read_produced(
    source: Path, relative: str, budget: int, expected: tuple[int, int] | None,
) -> bytes:
    """Read one produced file within the budget, refusing escapes, symlinks and non-files."""
    path = safe_path(relative, source)
    current = source
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("is a symlink")
    if not path.is_file():
        raise ValueError("is no longer a regular file")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > budget:
            raise ValueError(f"{before.st_size} bytes exceed the remaining file copy budget")
        if expected is not None and (before.st_mtime_ns, before.st_size) != expected:
            raise ValueError("changed after the node recorded its writers")
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
        if expected is not None and (after.st_mtime_ns, after.st_size) != expected:
            raise ValueError("changed while reading the produced file")
        if len(data) > before.st_size:
            raise ValueError("grew while reading the produced file")
        return data


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


def _copy_upstream(run_dir: Path, task_ids, root: Path, name: str, *, tag: bool) -> tuple[dict | None, str]:
    """Copy every observation and produced file of the given producers and index them.

    Args:
        run_dir: Current swarm run directory, including copied artifacts when resumed.
        task_ids: Upstream task ids, in binding order.
        root: Resolved consumer workspace.
        name: Index file stem under ``upstream/``: ``index`` or ``audit``.
        tag: Record on each entry the direct producer (``input_task``) it arrived through.

    Returns:
        The written evidence index or None, and a prompt note for any failed calls.

    Raises:
        ValueError: If a copy would escape the workspace or differs from one already written.
        OSError: If the index or its parts cannot be written.
    """
    from src.swarm.task_store import TaskStore

    folder = safe_path("upstream", root)
    entries, files, errors, seen = [], [], [], set()
    failures, unreadable_failures = [], []
    cap = budget = get_env_config().swarm.swarm_handoff_max_file_bytes
    store = TaskStore(run_dir)
    for task_id in dict.fromkeys(task_ids):
        tagged = {"input_task": task_id} if tag else {}
        try:
            source_task = store.load_task(task_id)
            source = agent_artifact_dir(run_dir, source_task.agent_id, task_id)
            thread = node_thread(run_dir, source_task.agent_id, task_id)
            try:
                inherited_failures = safe_path(_FAILED_CALLS_PATH, source)
                if inherited_failures.is_file():
                    records = json.loads(inherited_failures.read_text())
                    if not isinstance(records, list) or any(
                        not isinstance(record, dict) or record.get("status") != "failed" for record in records
                    ):
                        raise ValueError("Invalid failure records")
                    failures.extend(records)
            except (OSError, ValueError):
                unreadable_failures.append(task_id)
            if thread.is_file():
                receipt = workspace_write_receipt(thread)
                if receipt.exists():
                    produced = _attributed_files(source, receipt, task_id, errors)
                else:
                    produced = {path: (*writer, None) for path, writer in
                                _produced_files(source, thread, source_task.agent_id, task_id, errors).items()}
                for relative, (tool, call_id, expected) in produced.items():
                    try:
                        original = _read_produced(source.resolve(), relative, budget, expected)
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
                    entry = {"source_task": task_id, "tool": tool, "call_id": call_id,
                             "original_path": relative, "path": str(path.relative_to(root)),
                             "sha256": digest, "size": len(content), "redacted": content != original}
                    if content != original:
                        # An execution record names the bytes it wrote, before redaction.
                        entry["source_sha256"] = hashlib.sha256(original).hexdigest()
                    files.append({**entry, **tagged})
            observations = _observations(source, source_task.agent_id, task_id, errors, failures,
                                         thread if thread.is_file() else None)
            for entry, raw in observations:
                raw = redact_tool_result(raw)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                identity = (entry["source_task"], entry.get("turn_id"), entry["call_id"], digest, task_id if tag else None)
                if identity in seen:
                    continue
                seen.add(identity)
                path = folder / f"{digest}.json"
                _write_original(path, raw, root)
                parts = save_result_parts(raw, folder / digest / "parts", root)
                entries.append({**entry, "path": str(path.relative_to(root)), "sha256": digest,
                                "parts_dir": str((folder / digest / "parts").relative_to(root)),
                                "part_count": len(parts), **tagged})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{task_id}: {type(exc).__name__}: {exc}")
    failure_note = ""
    if failures:
        # Existing attempts can already have an immutable evidence index on disk.
        # Keep diagnostics independent of that index and of selected evidence.
        records = list(dict.fromkeys(redact_tool_result(json.dumps(item, ensure_ascii=False)) for item in failures))
        content = "[" + ", ".join(records) + "]"
        _write_original(safe_path(_FAILED_CALLS_PATH, root), content, root)
        pages = save_result_parts(content, folder / "failed-calls-parts", root)
        failure_note = (
            f"\n{len(records)} unsuccessful upstream tool calls are recorded as diagnostics in {_FAILED_CALLS_PATH}. "
            f"For paged reading, use upstream/failed-calls-parts/1.txt through upstream/failed-calls-parts/{len(pages)}.txt. "
            "Use these failures to explain gaps in the available evidence."
        )
        if len(content) <= TOOL_RESULT_LIMIT:
            failure_note += f"\n{content}"
    if unreadable_failures:
        failure_note += "\nUpstream failure diagnostics could not be read for: " + ", ".join(unreadable_failures) + "."
    if not entries and not files and not errors:
        return None, failure_note.lstrip()
    index = {"observations": entries, "files": files, "unavailable": errors}
    content = json.dumps(index, ensure_ascii=False)
    # Same dependencies yield identical bytes on retry/continuation. No report
    # text is rewritten and no source status is promoted by copying its files.
    _write_original(folder / f"{name}.json", content, root)
    parts = save_result_parts(content, folder / f"{name}-parts", root)
    return {**index, "content": content, "pages": len(parts)}, failure_note


def prepare_handoff(run_dir: Path, task, destination: Path) -> str:
    """Copy upstream observations into this task's readable workspace.

    A plain ``input_from`` binding hands over everything its producer recorded behind a paged
    index. When any binding is a selection, only the selected evidence is indexed and supplied
    as task data (see ``selected_inputs``); the complete copy stays in ``upstream/audit.json``.

    Args:
        run_dir: Current swarm run directory, including copied artifacts when resumed.
        task: Consumer task whose input_from identifies the upstream producers.
        destination: Consumer artifact directory.

    Returns:
        Prompt note pointing to the provenance index, which lists the copied observations,
        the files each upstream task produced (copied by content hash under ``upstream/files``)
        and anything unavailable, plus a pointer to unsuccessful call diagnostics when present.
        Returns an empty string if there is nothing to report.

    Raises:
        ValueError: If the index would escape the workspace, differs from one already written,
            or a selected copy would overwrite a changed consumer file.
        OSError: If the index or its parts cannot be written.
    """
    if not task.input_from:
        return ""
    root = destination.resolve()
    if any(isinstance(binding, dict) for binding in task.input_from.values()):
        return _prepare_selected(run_dir, task, root)
    copied, failure_note = _copy_upstream(run_dir, task.input_tasks().values(), root, "index", tag=False)
    if copied is None:
        return failure_note
    entries, files, pages = copied["observations"], copied["files"], copied["pages"]
    tools = ", ".join(sorted({entry["tool"] for entry in entries})) or "none recorded"
    return (
        "## Inherited evidence\n"
        f"{len(entries)} recorded observations ({tools}). Read upstream/index.json; "
        f"For paged reading, use upstream/index-parts/1.txt through upstream/index-parts/{pages}.txt. "
        "Each entry identifies its producing task/tool and a local JSON path usable "
        "by quantlib_call __data_ref__. These are inherited observations, not fresh "
        "fetches by you. Independent analysis can reuse them; describe what you "
        "actually recalculated or newly retrieved. Original dates and assumptions "
        "still apply. A bash entry's request.command is the command its recorded output "
        "came from. Missing evidence does not invalidate the available report.\n"
        f"{len(files)} files produced by upstream tasks are copied under upstream/files/; the "
        "\"files\" entries in upstream/index.json give each one's source task, original path, "
        "sha256 and size, and the writing tool call when one recorded it." + failure_note
    )


def _kind(entry: dict) -> str:
    """Classify an audit entry as a produced file, a calculation or an observation."""
    if "original_path" in entry:
        return "analysis"
    return "calculation" if entry.get("tool") in _CALCULATION_TOOLS else "observation"


def _verified_bytes(ref: dict, root: Path, changed: str) -> bytes:
    """Read a ``{path, sha256}`` copy inside ``root``, refusing changed bytes."""
    raw = safe_path(ref["path"], root).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError(changed)
    return raw


def _records_output(raw: bytes, path: str, digest: str) -> bool:
    """Whether a calculation result succeeded and recorded writing ``path`` with ``digest``."""
    try:
        result = json.loads(raw)
    except ValueError:
        return False
    return isinstance(result, dict) and result.get("status") == "ok" and any(
        isinstance(ref, dict) and ref.get("path") == path and ref.get("sha256") == digest
        for ref in result.get("artifacts") or []
    )


def _prepare_selected(run_dir: Path, task, root: Path) -> str:
    """Index only the selected evidence and keep the complete copy as an audit file.

    Args:
        run_dir: Swarm run containing the producing tasks.
        task: Consumer with at least one selection binding.
        root: Resolved consumer workspace.

    Returns:
        Prompt note naming the selected index and the audit file.

    Raises:
        ValueError: If a copy differs from one already written, or ``copy_to`` would overwrite a
            consumer file that changed since it was copied.
        OSError: If a copy or index cannot be written.
    """
    from src.swarm.task_store import TaskStore

    copied, failure_note = _copy_upstream(run_dir, task.input_tasks().values(), root, "audit", tag=True)
    if copied is None:
        copied = {"observations": [], "files": [], "unavailable": []}
        copied["content"] = json.dumps(copied)
        _write_original(safe_path("upstream/audit.json", root), copied["content"], root)
    audit = [*copied["observations"], *copied["files"]]
    errors, inputs = list(copied["unavailable"]), {}
    store = TaskStore(run_dir)
    for alias, binding in task.input_from.items():
        upstream = binding if isinstance(binding, str) else binding["task"]
        # A plain binding beside selections still receives everything its producer recorded.
        kinds = sorted(_SELECTABLE) if isinstance(binding, str) else binding.get("kinds", [])
        try:
            status = store.load_task(upstream).status.value
        except (OSError, ValueError) as exc:
            status = f"unreadable ({type(exc).__name__})"
        if status != "completed":
            errors.append(f"{upstream}: selected input producer is {status}")
        candidates = [entry for entry in audit if entry["input_task"] == upstream]
        # Transitive observations travel with a producer; its upstream's calculations and
        # files do not, so a role never passes off another role's work as its own.
        chosen = [entry for entry in candidates if _kind(entry) in kinds
                  and (entry["source_task"] == upstream or _kind(entry) == "observation")]
        if not isinstance(binding, str):
            for kind in kinds:
                if not any(_kind(entry) == kind for entry in chosen):
                    errors.append(f"{upstream}: requested input kind {kind} unavailable")
        for item in [] if isinstance(binding, str) else binding.get("files", []):
            item = {"path": item} if isinstance(item, str) else item
            name = item["path"]
            matches = [entry for entry in candidates
                       if _kind(entry) == "analysis" and entry["original_path"] == name]
            if len(matches) != 1:
                errors.append(f"{upstream}: requested input file {name} unavailable")
                continue
            entry = dict(matches[0])
            content = _verified_bytes(entry, root, "Selected input copy changed")
            if item.get("copy_to"):
                if status != "completed":
                    errors.append(f"{upstream}: {name} not copied to {item['copy_to']}: producer is {status}")
                else:
                    _write_bytes(safe_path(item["copy_to"], root), content, root)
                    entry["copy_to"] = item["copy_to"]
            if item.get("execution"):
                # Only a successful calculation that recorded these exact bytes as its output is
                # the file's producer. A missing record is a gap, never a rerun.
                digest = entry.get("source_sha256", entry["sha256"])
                record = next((
                    record for record in candidates
                    if _kind(record) == "calculation" and record["source_task"] == upstream
                    and _records_output(_verified_bytes(record, root, "Execution record changed"), name, digest)
                ), None)
                if record is None:
                    errors.append(f"{upstream}: no successful execution recorded for {name} at its current hash")
                else:
                    entry["execution"] = {key: record[key] for key in
                                          ("path", "sha256", "tool", "call_id", "request") if key in record}
            # A named file replaces the same file chosen by kind, carrying its transfer details.
            chosen = [other for other in chosen if other is not matches[0]] + [entry]
        inputs[alias] = chosen
    selected = []
    for item in (item for chosen in inputs.values() for item in chosen):
        if item not in selected:
            selected.append(item)
    content = json.dumps({
        "observations": [item for item in selected if _kind(item) != "analysis"],
        "files": [item for item in selected if _kind(item) == "analysis"],
        "unavailable": errors, "inputs": inputs,
        "audit_file": {"path": "upstream/audit.json",
                       "sha256": hashlib.sha256(copied["content"].encode()).hexdigest()},
    }, ensure_ascii=False)
    index = safe_path("upstream/index.json", root)
    _write_original(index, content, root)
    save_result_parts(content, safe_path("upstream/index-parts", root), root)
    return (
        "## Inherited evidence\n"
        f"Selected input index SHA256: {hashlib.sha256(content.encode()).hexdigest()}. "
        "The selected upstream values are supplied in the upstream data message. "
        "upstream/index.json records their paths, hashes and missing inputs; "
        "upstream/audit.json keeps every upstream observation, calculation and produced file "
        "for tracing a specific gap. These are inherited results, not fresh retrievals by you." + failure_note
    )


#: Every selectable kind; a plain binding next to selections receives all of them.
_SELECTABLE = ("analysis", "calculation", "observation")
#: Source metadata a selected observation carries inline; its rows stay in the file at path.
_OBSERVATION_METADATA = ("ok", "status", "error", "error_code", "truncated", "source_truncated",
                         "total_chars", "_provenance", "_unresolved", "_diagnostics", "input_sources",
                         "source", "coverage", "metadata")
#: Result fields a selected calculation carries inline; shell stdout stays in the record.
_CALCULATION_FIELDS = ("status", "exit_code", "artifacts", "stderr", "result", "error", "input_sources")


def selected_inputs(destination: Path) -> dict | None:
    """Read a consumer's selected upstream values, bounded by the tool-result budget.

    Args:
        destination: Consumer workspace whose handoff has already been prepared.

    Returns:
        ``{"inputs": {alias: [value, ...]}, "unavailable": [...]}`` for a selected handoff, or
        None for a plain one. Each value names its source task, kind and copied path; a file
        carries its content (parsed JSON when it is JSON), an observation its source metadata
        and request, a calculation its request and result fields. A value that would push the
        whole payload past the tool-result budget keeps only its file reference.

    Raises:
        ValueError: If the index, the audit file, a selected copy or a transferred file changed.
        OSError: If a selected file cannot be read.
    """
    path = safe_path("upstream/index.json", destination)
    if not path.is_file():
        return None
    index = json.loads(path.read_text())
    if not isinstance(index, dict) or "audit_file" not in index:
        return None
    root = destination.resolve()
    _verified_bytes(index["audit_file"], root, "Upstream audit index changed")
    result = {"inputs": {}, "unavailable": index["unavailable"]}

    def oversized() -> bool:
        return len(json.dumps(result, ensure_ascii=False)) > TOOL_RESULT_LIMIT

    for alias, entries in index["inputs"].items():
        values = result["inputs"][alias] = []
        for entry in entries:
            kind = _kind(entry)
            item = {"source_task": entry["source_task"], "kind": kind, "path": entry["path"]}
            values.append(item)
            raw = _verified_bytes(entry, root, "Selected input changed")
            if kind == "analysis":
                item["file"] = entry["original_path"]
                if "copy_to" in entry:
                    item["copy_to"] = entry["copy_to"]
                    if safe_path(entry["copy_to"], root).read_bytes() != raw:
                        raise ValueError("Transferred output changed")
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    item["content_omitted"] = "Binary file; read it at path."
                else:
                    try:
                        item["content"] = json.loads(text)
                    except ValueError:
                        item["content"] = text
                record = entry.get("execution")
                if record:
                    executed = json.loads(_verified_bytes(record, root, "Execution record changed"))
                    item["execution"] = {"path": record["path"], "tool": record["tool"],
                                         "request": record.get("request", {}),
                                         "result": {key: executed[key] for key in _CALCULATION_FIELDS
                                                    if key in executed}}
                    if oversized():
                        item["execution"] = {"path": record["path"], "tool": record["tool"],
                                             "content_omitted": "Read the execution record at path."}
            else:
                payload = json.loads(raw)
                fields = _OBSERVATION_METADATA if kind == "observation" else _CALCULATION_FIELDS
                item.update(tool=entry["tool"], request=entry.get("request", {}),
                            content={key: payload[key] for key in fields
                                     if isinstance(payload, dict) and key in payload})
            if oversized():
                item.pop("content", None)
                item.pop("request", None)
                item["content_omitted"] = "Read the selected value at path; it exceeds the inline input budget."
    return result
