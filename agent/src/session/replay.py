"""Project canonical thread items without granting tool or instrument permissions."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from src.kernel.contracts import ModelMessage
from src.providers import messages as provider_messages
from src.providers.messages import MessagePairing, assistant_message
from src.session.thread import last_compaction
from src.session.thread_schema import ThreadItem, _is_int, _is_number
from src.tools.redaction import redact_text

TRAIL_ARGUMENT_CHARS = 200
TRAIL_PREVIEW_CHARS = 200

# Keep these user-role notices after the last item of the affected turn.
STOPPED_TURN_NOTES = {
    status: (
        f"<system>{opening} Tool results recorded above for that turn are still valid and can be used. "
        "A tool call marked interrupted may have partly run; check its effect "
        "before repeating anything it could have changed.</system>"
    )
    for status, opening in {
        "cancelled": "The user stopped the previous turn before it finished.",
        "interrupted": "The previous turn was interrupted (the service stopped) before it finished.",
        "failed": "The previous turn ended with an error before it finished.",
    }.items()
}


def durable_tool_calls(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Copy tool calls and redact their serialized argument objects."""
    from src.tools.redaction import redact_payload

    calls = copy.deepcopy(list(message.get("tool_calls") or []))
    for call in calls:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                original = json.loads(arguments)
                redacted = redact_payload(original)
                if redacted != original:
                    function["arguments"] = json.dumps(redacted, ensure_ascii=False)
            except (ValueError, TypeError):
                function["arguments"] = redact_text(arguments)
    return calls


def _item_message(
    item: ThreadItem,
    *,
    target_provider: Optional[str] = None,
    target_model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build the provider message represented by one thread item."""
    if item.type == "user":
        return {"role": "user", "content": copy.deepcopy(item.get("llm_content"))}
    if item.type == "assistant":
        return assistant_message(
            item, target_provider=target_provider, target_model=target_model
        )
    if item.type == "tool_result":
        content: Any = item.get("content")
        images = item.get("images") or []
        if isinstance(images, list) and images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": str(content or "")}]
            for image in images:
                if isinstance(image, dict) and isinstance(image.get("path"), str):
                    parts.append({"type": "image_url", "image_url": {"url": image["path"], "detail": "auto"}})
            content = parts
        return {
            "role": "tool",
            "tool_call_id": item.get("tool_call_id"),
            "name": item.get("name"),
            "content": content,
        }
    if item.type == "inject":
        return {"role": item.get("role"), "content": copy.deepcopy(item.get("content"))}
    return None


def replay(
    items: Iterable[ThreadItem],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> list[ModelMessage]:
    """Project compacted history into fresh model messages with repaired tool pairs and interruption notices."""
    return replay_with_seqs(items, provider=provider, model=model)[0]


def replay_with_seqs(
    items: Iterable[ThreadItem],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[list[dict[str, Any]], list[Optional[int]]]:
    """Pair messages while retaining source seqs for compaction and recovery."""
    items = list(items)
    compaction = last_compaction(items)
    replayer = MessagePairing()
    start_after = compaction.get("replaces_through_seq") if compaction is not None else 0

    # Layers 1/2 overlay the raw record; L3 moves the replay boundary.
    message_by_seq: Dict[int, Dict[str, Any]] = {}
    replacements = {}
    for event in items:
        if event.type == "compaction" and event.get("layer", 3) in {1, 2}:
            for change in event.get("changes") or []:
                if isinstance(change, dict) and _is_int(change.get("seq")) and isinstance(change.get("message"), dict):
                    replacements[change["seq"]] = change["message"]
    for item in items:
        if item.seq <= start_after:
            continue
        message = _item_message(item, target_provider=provider, target_model=model)
        if message is None:
            continue
        replacement = replacements.get(item.seq)
        if replacement is not None and replacement.get("role") == message["role"]:
            if item.type == "assistant":
                message = assistant_message(
                    {
                        **replacement,
                        "tool_calls": durable_tool_calls(replacement),
                        "provider": item.get("provider"),
                        "model": item.get("model"),
                    },
                    target_provider=provider, target_model=model,
                )
            else:
                message = copy.deepcopy(replacement)
        message_by_seq[item.seq] = message

    if compaction is not None:
        replayer.messages.append({"role": "user", "content": compaction.get("summary")})

    open_turn: Optional[str] = None
    finished: set = set()
    # Skip stopped-turn notices for turns already covered by the summary.
    visible: set = set()

    def finish_turn(turn_id: str, status: Optional[str]) -> None:
        finished.add(turn_id)
        replayer.close_block()
        note = STOPPED_TURN_NOTES.get(status or "")
        if note is not None and turn_id in visible:
            replayer.messages.append({"role": "user", "content": note})

    for item in items:
        if item.seq > start_after:
            visible.add(item.turn_id)
        if item.type == "turn_start":
            if open_turn is not None and open_turn != item.turn_id:
                finish_turn(open_turn, "interrupted")
            open_turn = item.turn_id
            continue
        if item.type == "turn_end":
            if item.turn_id not in finished:
                finish_turn(item.turn_id, item.get("status"))
            if item.turn_id == open_turn:
                open_turn = None
            continue
        if item.seq <= start_after:
            continue
        effective = message_by_seq.get(item.seq)
        if effective is not None:
            replayer.add(effective)
    replayer.close_block()
    source_seqs = {id(message): seq for seq, message in message_by_seq.items()}
    return replayer.messages, [source_seqs.get(id(message)) for message in replayer.messages]


# Display projection


@dataclass
class TurnProjection:
    """A read-only view of one finished turn."""

    turn_id: str
    status: Optional[str]
    content: Optional[str]
    tool_results: List[Dict[str, Any]]
    usage: Optional[Dict[str, Any]] = None
    elapsed_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def trail_arguments(raw: Any, run_dir: Optional[str]) -> Dict[str, Any]:
    from src.tools._arguments import normalize_tool_run_dir
    from src.tools.redaction import redact_payload

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = None
    if not isinstance(parsed, dict):
        return {}
    redacted = redact_payload(normalize_tool_run_dir(parsed, run_dir))
    return {key: str(value)[:TRAIL_ARGUMENT_CHARS] for key, value in redacted.items()}


def project_turn(
    items: Iterable[ThreadItem],
    turn_id: str,
    *,
    run_dir: Optional[str] = None,
) -> TurnProjection:
    """Project one turn's items onto the legacy display row."""
    turn = [item for item in items if item.turn_id == turn_id]
    if run_dir is None:
        run_dir = next((item.get("run_dir") for item in reversed(turn) if item.type == "turn_end"), None)
    trail: List[Dict[str, Any]] = []
    final_content: Optional[str] = None
    fallback_content: Optional[str] = None
    status: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    elapsed_ms: Optional[float] = None
    metadata: Dict[str, Any] = {}

    for item in turn:
        if item.type == "assistant":
            tool_calls = item.get("tool_calls") or []
            content = item.get("content")
            if item.get("phase") == "final" and isinstance(content, str):
                final_content = content
            elif not tool_calls and isinstance(content, str) and content.strip():
                fallback_content = content
            for call in tool_calls:
                function = call.get("function") or {}
                trail.append(
                    {
                        "tool": function.get("name") or "",
                        "status": "running",
                        "arguments": trail_arguments(function.get("arguments"), run_dir),
                        "timestamp": int(item.ts * 1000),
                        "call_id": call.get("id"),
                    }
                )
        elif item.type == "tool_result":
            call_id = item.get("tool_call_id")
            name = item.get("name") or ""
            match = next(
                (e for e in trail if e.get("call_id") == call_id and e["status"] == "running"),
                None,
            )
            if match is None:
                match = next(
                    (e for e in trail if e["tool"] == name and e["status"] == "running"),
                    None,
                )
            if match is None:
                match = {"tool": name, "arguments": {}, "timestamp": int(item.ts * 1000)}
                trail.append(match)
            match["status"] = "ok" if item.get("status") == "ok" else "error"
            elapsed = item.get("elapsed_ms")
            if _is_number(elapsed):
                match["elapsed_ms"] = max(0, int(elapsed))
            match["preview"] = str(item.get("content") or "")[:TRAIL_PREVIEW_CHARS]
            if match["status"] == "ok" and isinstance(item.get("artifact"), dict):
                match["artifact"] = dict(item.get("artifact"))
            match["call_id"] = call_id
        elif item.type == "turn_end":
            status = item.get("status")
            usage = copy.deepcopy(item.get("usage"))
            elapsed_ms = item.get("elapsed_ms")
            if isinstance(item.get("summary"), str) and item.get("summary"):
                final_content = item.get("summary")
            if isinstance(item.get("metadata"), dict):
                metadata = copy.deepcopy(item.get("metadata"))

    if status is not None:
        for entry in trail:
            if entry["status"] == "running":
                entry["status"] = "error"
                entry["preview"] = provider_messages.INTERRUPTED_RESULT_CONTENT[:TRAIL_PREVIEW_CHARS]

    return TurnProjection(
        turn_id=turn_id,
        status=status,
        content=final_content if final_content is not None else fallback_content,
        tool_results=trail,
        usage=usage,
        elapsed_ms=elapsed_ms,
        metadata=metadata,
    )


def diagnostic_records(items: Sequence[ThreadItem]) -> list[dict[str, Any]]:
    """Derive the run diagnostic view used by evaluation and CLI readers."""
    records: list[dict[str, Any]] = []
    executions = {item.get("data", {}).get("call_id"): item.get("data", {})
                  for item in items if item.type == "event" and item.get("name") == "tool_execution"}
    for item in items:
        if item.type == "turn_start":
            records.append({"type": "start", "ts": item.ts, "prompt": item.get("prompt"), "_line": item.seq})
        elif item.type == "user":
            records.append({"type": "message", "role": "user", "content": item.get("content"), "_line": item.seq})
        elif item.type == "assistant":
            for call in item.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    args = json.loads(function.get("arguments", "{}"))
                except (TypeError, ValueError):
                    args = function.get("arguments")
                records.append({
                    "type": "tool_call", "ts": item.ts, "tool": function.get("name"),
                    "call_id": call.get("id"), "args": args, "_line": item.seq,
                    **executions.get(call.get("id"), {}),
                })
            if item.get("content") is not None:
                records.append({"type": "answer" if item.get("phase") == "final" else "message", "role": "assistant", "content": item.get("content"), "_line": item.seq})
        elif item.type == "tool_result":
            records.append({
                "type": "tool_result", "ts": item.ts, "tool": item.get("name"),
                "call_id": item.get("tool_call_id"), "status": item.get("status"),
                "result": item.get("content"), "preview": str(item.get("content") or "")[:500],
                "elapsed_ms": item.get("elapsed_ms"), "_line": item.seq,
            })
        elif item.type == "event":
            data = item.get("data") or {}
            if item.get("name") == "identity_dependency":
                records.append({"type": "tool_call", "ts": item.ts, "tool": data.get("tool"),
                                "call_id": data.get("call_id"), "args": {"query": data.get("query")},
                                "_line": item.seq, **executions.get(data.get("call_id"), {})})
            if isinstance(data, dict) and item.get("name") != "tool_execution":
                records.append({"type": item.get("name", "event"), "ts": item.ts, **data, "_line": item.seq})
        elif item.type == "turn_end":
            status = {"completed": "success", "interrupted": "failed"}.get(item.get("status"), item.get("status"))
            previous = next((record for record in reversed(records) if record.get("type") in {"start", "end"}), None)
            if previous is not None and previous["type"] == "end":
                previous.update(status=status, _line=item.seq)
            else:
                records.append({"type": "end", "ts": item.ts, "status": status, "_line": item.seq})
    return records
