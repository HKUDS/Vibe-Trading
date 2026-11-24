"""Pure provider message projection and positional tool-call pairing."""
from __future__ import annotations

import copy
import json
import logging
from typing import Any, Mapping, Optional

from src.kernel.contracts import ModelMessage

logger = logging.getLogger(__name__)

INTERRUPTED_RESULT_CONTENT = json.dumps(
    {
        "status": "error",
        "error": (
            "interrupted: this tool call did not finish and no result was "
            "recorded. It may have partly run."
        ),
    },
    ensure_ascii=False,
)


def message_value(message: Any, key: str, default: Any = None) -> Any:
    """Read a field from a message mapping or SDK object."""
    return message.get(key, default) if isinstance(message, dict) else getattr(message, key, default)


def assistant_message(
    item: Mapping[str, Any],
    *,
    target_provider: Optional[str] = None,
    target_model: Optional[str] = None,
) -> ModelMessage:
    """Rebuild the assistant message the loop sent, in the loop's key order."""
    source_provider = item.get("provider")
    source_model = item.get("model")
    same_runtime = (
        target_provider is None and target_model is None
    ) or (
        isinstance(source_provider, str)
        and isinstance(source_model, str)
        and source_provider == target_provider
        and source_model == target_model
    )
    content = item.get("llm_content")
    message = {"role": "assistant", "content": copy.deepcopy(item.get("content") if content is None else content)}
    tool_calls = copy.deepcopy(item.get("tool_calls") or [])
    if tool_calls:
        if not same_runtime:
            for call in tool_calls:
                extra = call.get("extra_content")
                if not isinstance(extra, dict):
                    continue
                for metadata in (extra, extra.get("google")):
                    if isinstance(metadata, dict):
                        metadata.pop("thought_signature", None)
                        metadata.pop("thoughtSignature", None)
                if extra.get("google") == {}:
                    extra.pop("google")
                if not extra:
                    call.pop("extra_content")
        message["tool_calls"] = tool_calls
        if any(call.get("extra_content") for call in tool_calls):
            message["additional_kwargs"] = {"tool_calls": copy.deepcopy(tool_calls)}
    if same_runtime and item.get("reasoning_content") is not None:
        message["reasoning_content"] = item.get("reasoning_content")
    if same_runtime and item.get("provider_items"):
        message["provider_items"] = copy.deepcopy(item.get("provider_items"))
    return message


class MessagePairing:
    """Keep results next to their assistant call block and fill missing results."""

    def __init__(
        self, missing_result: str = INTERRUPTED_RESULT_CONTENT, *, missing_first: bool = False,
    ) -> None:
        self._missing_result = missing_result
        self._missing_first = missing_first
        self._result_start = 0
        self.messages: list[ModelMessage] = []
        self._pending: dict[str, str] = {}
        self._answered: set[str] = set()
        self._held: list[ModelMessage] = []

    def add(self, message: ModelMessage) -> None:
        """Consume an independently owned message, preserving its identity."""
        role = message.get("role")
        if role == "assistant":
            self.close_block()
            self.messages.append(message)
            self._result_start = len(self.messages)
            self._pending = {
                call["id"]: call["function"]["name"] for call in message.get("tool_calls", [])
            }
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in self._pending or call_id in self._answered:
                logger.debug("Dropped a tool result without an open call: %s", call_id)
                return
            self._answered.add(call_id)
            self.messages.append(message)
        elif self._pending:
            self._held.append(message)
        else:
            self.messages.append(message)

    def close_block(self) -> None:
        stubs = [
            {"role": "tool", "tool_call_id": call_id, "name": name, "content": self._missing_result}
            for call_id, name in self._pending.items() if call_id not in self._answered
        ]
        position = self._result_start if self._missing_first else len(self.messages)
        self.messages[position:position] = stubs
        self._pending.clear()
        self._answered.clear()
        self.messages.extend(self._held)
        self._held.clear()


def repair_provider_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Repair tool blocks for one provider request without changing history."""
    replayer = MessagePairing()
    for message in messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            replayer.add(assistant_message(message))
        else:
            replayer.add(copy.deepcopy(message))
    replayer.close_block()
    return replayer.messages


def attach_tool_call_thought_signatures(message: dict[str, Any], tool_calls: list) -> dict[str, Any]:
    """Attach Gemini thought signatures to assistant replay tool calls."""
    outbound_tool_calls = message.get("tool_calls")
    if not isinstance(outbound_tool_calls, list):
        return message

    signatures_by_id: dict[str, str] = {}
    signatures_by_index: dict[int, str] = {}
    for index, tc in enumerate(tool_calls):
        extra_content = getattr(tc, "extra_content", None)
        signature = None
        if isinstance(extra_content, dict):
            signature = extra_content.get("thought_signature")
            google_extra = extra_content.get("google")
            if not signature and isinstance(google_extra, dict):
                signature = google_extra.get("thought_signature") or google_extra.get(
                    "thoughtSignature"
                )
        signature = signature or getattr(tc, "thought_signature", None)
        if not signature:
            continue
        tc_id = getattr(tc, "id", None)
        if tc_id:
            signatures_by_id[str(tc_id)] = signature
        signatures_by_index[index] = signature

    if not signatures_by_id and not signatures_by_index:
        return message

    def attach(raw_tool_call: Any, index: int) -> None:
        if not isinstance(raw_tool_call, dict):
            return
        signature = signatures_by_id.get(str(raw_tool_call.get("id"))) or signatures_by_index.get(index)
        if not signature:
            return
        extra_content = raw_tool_call.setdefault("extra_content", {})
        if not isinstance(extra_content, dict):
            extra_content = {}
            raw_tool_call["extra_content"] = extra_content
        extra_content["thought_signature"] = signature
        google = extra_content.setdefault("google", {})
        if not isinstance(google, dict):
            google = {}
            extra_content["google"] = google
        google["thought_signature"] = signature

    for index, raw_tool_call in enumerate(outbound_tool_calls):
        attach(raw_tool_call, index)

    additional_kwargs = message.setdefault("additional_kwargs", {})
    raw_tool_calls = additional_kwargs.setdefault(
        "tool_calls",
        copy.deepcopy(outbound_tool_calls),
    )
    if isinstance(raw_tool_calls, list):
        for index, raw_tool_call in enumerate(raw_tool_calls):
            attach(raw_tool_call, index)

    return message


def _tool_call_thought_signature_maps(ai_message: Any) -> tuple[dict[str, str], dict[int, str]]:
    """Return Gemini thought signatures captured by ``ChatOpenAIWithReasoning``."""
    by_id: dict[str, str] = {}
    by_index: dict[int, str] = {}
    additional_kwargs = getattr(ai_message, "additional_kwargs", {})
    entries = additional_kwargs.get("tool_call_thought_signatures", [])

    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return by_id, by_index

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        signature = entry.get("thought_signature")
        if not signature:
            continue
        if entry.get("id"):
            by_id[str(entry["id"])] = signature
        index = entry.get("index")
        if isinstance(index, int):
            by_index[index] = signature
    return by_id, by_index


def _extract_tool_call_extra_content(raw_tool_call: Any) -> dict[str, Any]:
    """Extract provider-specific tool-call metadata LangChain would drop."""
    if not isinstance(raw_tool_call, dict):
        return {}

    extra_content: dict[str, Any] = {}
    raw_extra = raw_tool_call.get("extra_content")
    if isinstance(raw_extra, dict):
        extra_content.update(raw_extra)
        google_extra = raw_extra.get("google")
        if isinstance(google_extra, dict):
            signature = google_extra.get("thought_signature") or google_extra.get(
                "thoughtSignature"
            )
            if signature:
                extra_content["thought_signature"] = signature

    function = raw_tool_call.get("function")
    if isinstance(function, dict):
        function_extra = function.get("extra_content")
        if isinstance(function_extra, dict):
            extra_content.update(function_extra)
        if function.get("thought_signature"):
            extra_content["thought_signature"] = function["thought_signature"]

    if raw_tool_call.get("thought_signature"):
        extra_content["thought_signature"] = raw_tool_call["thought_signature"]

    return extra_content


def _merge_tool_call_extra_content(*raw_tool_calls: Any) -> dict[str, Any]:
    """Merge provider metadata from standardized and raw tool-call shapes."""
    extra_content: dict[str, Any] = {}
    for raw_tool_call in raw_tool_calls:
        extra_content.update(_extract_tool_call_extra_content(raw_tool_call))
    return extra_content
