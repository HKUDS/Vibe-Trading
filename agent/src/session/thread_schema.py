"""Canonical thread item fields, validation and on-disk representation."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

from src.tools.redaction import RESULT_SINK, redact_payload, redact_text, redact_tool_result

ASSISTANT_PHASES = frozenset({"commentary", "final"})
TOOL_RESULT_STATUSES = frozenset({"ok", "error"})
TURN_END_STATUSES = frozenset({"completed", "cancelled", "failed", "interrupted", "waiting_user"})

_COMMON_FIELDS = ("seq", "ts", "turn_id", "type")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _optional(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda value: value is None or check(value)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_message_content(value: Any) -> bool:
    # OpenAI message content: a string or a list of content parts.
    return isinstance(value, (str, list))


def _is_tool_calls(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for call in value:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str):
            return False
        function = call.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            return False
    return True


@dataclass(frozen=True)
class _Field:
    check: Callable[[Any], bool]
    required: bool = False
    default: Any = None


# Per-type payload schema. ``state`` is open: its keys (identity records,
# loaded tool names, workspace) are owned by the session runtime.
_SCHEMA: Dict[str, Optional[Dict[str, _Field]]] = {
    "turn_start": {
        "prompt": _Field(_is_message_content, required=True),
        "model": _Field(_optional(_is_str)),
        "provider": _Field(_optional(_is_str)),
    },
    "user": {
        "content": _Field(_is_message_content, required=True),
        "llm_content": _Field(_is_message_content, required=True),
        "input_id": _Field(_optional(_is_str)),
        "answer_to_question_id": _Field(_optional(_is_str)),
    },
    "assistant": {
        "llm_content": _Field(_optional(_is_message_content)),
        "content": _Field(_optional(_is_message_content)),
        "tool_calls": _Field(_is_tool_calls, default=[]),
        "reasoning_content": _Field(_optional(_is_str)),
        "provider_items": _Field(_optional(_is_list)),
        "provider": _Field(_optional(_is_str)),
        "model": _Field(_optional(_is_str)),
        "phase": _Field(_optional(lambda v: v in ASSISTANT_PHASES)),
    },
    "tool_result": {
        "tool_call_id": _Field(lambda v: isinstance(v, str) and bool(v), required=True),
        "name": _Field(_is_str, required=True),
        "content": _Field(_is_str, required=True),
        "status": _Field(lambda v: v in TOOL_RESULT_STATUSES, required=True),
        "elapsed_ms": _Field(_optional(_is_number)),
        # Display-only: the report link the live event carried. Never replayed.
        "artifact": _Field(_optional(_is_dict)),
        "images": _Field(_optional(_is_list)),
    },
    "event": {
        "name": _Field(_is_str, required=True),
        "data": _Field(_is_dict, default={}),
    },
    "plan": {
        "plan_id": _Field(_is_str, required=True),
        "steps": _Field(_is_list, required=True),
    },
    "question": {
        "question_id": _Field(_is_str, required=True),
        "prompt": _Field(_is_str, required=True),
        "options": _Field(_is_list, required=True),
        "allow_free_text": _Field(lambda v: isinstance(v, bool), default=True),
    },
    "inject": {
        "content": _Field(_is_message_content, required=True),
        "role": _Field(lambda v: v in {"user", "system"}, default="user"),
    },
    "checkpoint": {
        "content": _Field(_is_str, required=True),
    },
    "hook_decision": {
        "event": _Field(_is_str, required=True),
        "decision": _Field(_is_str, required=True),
        "reason": _Field(_is_str, default=""),
        "elapsed_ms": _Field(_optional(_is_number)),
        "timed_out": _Field(lambda v: isinstance(v, bool), default=False),
        "exit_code": _Field(_optional(lambda v: _is_int(v))),
        "tool": _Field(_optional(_is_str)),
    },
    "compaction": {
        "summary": _Field(_is_str, default=""),
        "replaces_through_seq": _Field(_is_int, default=0),
        "layer": _Field(lambda v: _is_int(v) and v in {1, 2, 3}, default=3),
        # Layer 1 and 2 preserve raw items and record the exact message
        # replacements that the model saw after an in-memory compaction.
        "changes": _Field(_is_list, default=[]),
    },
    "state": None,
    "turn_end": {
        "status": _Field(lambda v: v in TURN_END_STATUSES, required=True),
        "usage": _Field(_optional(_is_dict)),
        "elapsed_ms": _Field(_optional(_is_number)),
        "summary": _Field(_optional(_is_str)),
        "error": _Field(_optional(_is_str)),
        "run_dir": _Field(_optional(_is_str)),
        "provider": _Field(_optional(_is_str)),
        "model": _Field(_optional(_is_str)),
        "pending_inputs": _Field(_optional(_is_list)),
        "metadata": _Field(_optional(_is_dict)),
        "display": _Field(_optional(_is_dict)),
    },
}

class ThreadItemError(ValueError):
    """Raised when an item does not match the thread schema."""


def _validate_payload(item_type: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Check one item's payload against its type schema and fill defaults."""
    if item_type not in _SCHEMA:
        raise ThreadItemError(f"unknown thread item type {item_type!r}")
    for name in _COMMON_FIELDS:
        if name in payload:
            raise ThreadItemError(f"{name!r} is assigned by the log, not the caller")
    schema = _SCHEMA[item_type]
    if schema is None:
        return copy.deepcopy(dict(payload))
    unknown = set(payload) - set(schema)
    if unknown:
        raise ThreadItemError(
            f"{item_type} item has unknown fields: {', '.join(sorted(unknown))}"
        )
    result: Dict[str, Any] = {}
    for name, spec in schema.items():
        if name not in payload:
            if spec.required:
                raise ThreadItemError(f"{item_type} item is missing {name!r}")
            result[name] = copy.deepcopy(spec.default)
            continue
        value = payload[name]
        if not spec.check(value):
            raise ThreadItemError(f"{item_type} item has an invalid {name!r}")
        result[name] = copy.deepcopy(value)
    if item_type == "assistant" and result.get("llm_content") is None:
        result.pop("llm_content", None)
    if item_type == "turn_end":
        if result.get("display") is None:
            result.pop("display", None)
        if result.get("error"):
            result["error"] = redact_text(result["error"])
        if result["status"] == "failed" and result.get("summary"):
            result["summary"] = redact_text(result["summary"])
    if item_type == "event" and result["name"] == "end" and result["data"].get("reason"):
        result["data"]["reason"] = redact_text(result["data"]["reason"])
    if item_type == "compaction":
        # Keep the legacy on-disk shape byte-for-byte for summary-only
        # records. New layer events carry these fields explicitly.
        if "layer" not in payload:
            result.pop("layer", None)
        if "changes" not in payload:
            result.pop("changes", None)
    if item_type == "user" and result.get("input_id") is None:
        # Preserve the legacy user-item shape. Queued inputs carry a real id.
        result.pop("input_id", None)
    if item_type == "tool_result":
        result["content"] = redact_tool_result(result["content"], preserve_format=True)
        for key in ("images", "artifact"):
            result[key] = redact_payload(result[key], sink=RESULT_SINK)
        if result["images"] is None:
            result.pop("images")
    if item_type == "assistant":
        # Older thread records did not identify the provider/model. Keep their
        # on-disk shape stable while new responses record both fields.
        for name in ("provider", "model"):
            if name not in payload:
                result.pop(name, None)
    if item_type == "user" and result.get("answer_to_question_id") is None:
        result.pop("answer_to_question_id", None)
    return result


@dataclass(frozen=True)
class ThreadItem:
    """One record of ``thread.jsonl``."""

    seq: int
    ts: float
    turn_id: str
    type: str
    data: Dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        """Return one payload field.

        Args:
            name: Payload field name.
            default: Value when the field is absent.

        Returns:
            The field value or the default.
        """
        return self.data.get(name, default)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the flat on-disk shape.

        Returns:
            Common record fields followed by a deep copy of the payload fields.
        """
        return {
            "seq": self.seq,
            "ts": self.ts,
            "turn_id": self.turn_id,
            "type": self.type,
            **copy.deepcopy(self.data),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "ThreadItem":
        """Parse an on-disk thread item.

        Args:
            record: Decoded mapping with common record fields and type-specific payload fields.

        Returns:
            The validated thread item.

        Raises:
            ThreadItemError: If a common field is invalid or the payload violates its type schema.
        """
        seq = record.get("seq")
        ts = record.get("ts")
        turn_id = record.get("turn_id")
        item_type = record.get("type")
        if not _is_int(seq) or seq < 1:
            raise ThreadItemError("seq must be a positive integer")
        if not _is_number(ts):
            raise ThreadItemError("ts must be a number")
        if not isinstance(turn_id, str) or not turn_id:
            raise ThreadItemError("turn_id must be a non-empty string")
        if not isinstance(item_type, str):
            raise ThreadItemError("type must be a string")
        payload = {k: v for k, v in record.items() if k not in _COMMON_FIELDS}
        return cls(
            seq=seq,
            ts=float(ts),
            turn_id=turn_id,
            type=item_type,
            data=_validate_payload(item_type, payload),
        )

    @classmethod
    def from_line(cls, raw_line: bytes) -> "ThreadItem":
        """Decode and validate a UTF-8 JSON record read from the thread.

        Args:
            raw_line: One UTF-8 encoded JSON line from the conversation log.

        Returns:
            The validated thread item.

        Raises:
            UnicodeDecodeError: If the line is not UTF-8.
            json.JSONDecodeError: If the decoded line is not valid JSON.
            ThreadItemError: If the record is not an object or violates the thread schema.
        """
        record = json.loads(raw_line.decode("utf-8"))
        if not isinstance(record, dict):
            raise ThreadItemError(f"thread line must be a JSON object, got {type(record).__name__}")
        return cls.from_dict(record)
