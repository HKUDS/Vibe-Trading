"""Pure provider message projection and positional tool-call pairing.

Request repair and canonical session replay share this implementation. Repair
never changes persisted history or grants tool or instrument authorization.
"""
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


def assistant_message(
    item: Mapping[str, Any],
    *,
    target_provider: Optional[str] = None,
    target_model: Optional[str] = None,
) -> ModelMessage:
    """Rebuild the assistant message the loop sent, in the loop's key order.

    Mirrors ``ContextBuilder.format_assistant_tool_calls`` for a tool-call
    response and the loop's plain ``{"role", "content"}`` for a final answer.
    """
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
    """Single pass over thread items that keeps every tool block well-formed.

    A tool block is an assistant message with tool calls plus the results that
    must follow it directly. While a block is open, results for its calls are
    appended and anything else is held back; the block closes at the next
    assistant message, turn boundary or end of input, where calls without a
    result get :data:`INTERRUPTED_RESULT_CONTENT` and the held messages follow.
    A result for a call outside the open block is dropped.

    Pairing is positional, not by a session-wide id set: providers that derive
    call ids from a per-response counter reuse them across turns.
    """

    def __init__(
        self, missing_result: str = INTERRUPTED_RESULT_CONTENT, *, missing_first: bool = False,
    ) -> None:
        self._missing_result = missing_result
        self._missing_first = missing_first
        self._result_start = 0
        self.messages: list[ModelMessage] = []
        self._pending: dict[str, str] = {}
        self._answered: set = set()
        self._held: list[ModelMessage] = []

    def add(self, message: ModelMessage) -> None:
        """Consume an independently owned message, preserving its identity."""
        role = message.get("role")
        if role == "assistant":
            self.close_block()
            self.messages.append(message)
            self._result_start = len(self.messages)
            for call in message.get("tool_calls", []):
                self._pending[call["id"]] = call["function"]["name"]
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
        self._pending = {}
        self._answered = set()
        self.messages.extend(self._held)
        self._held = []


def repair_provider_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Repair tool blocks for one provider request without changing history.

    A new positional pairing supplies one interrupted result
    for an unanswered call and drops orphan results. The caller's message list
    is never mutated, so the repair remains request-local.

    Args:
        messages: Messages about to be sent to a provider.

    Returns:
        A repaired, independent message list.
    """
    replayer = MessagePairing()
    for message in messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            replayer.add(assistant_message(message))
        else:
            replayer.add(copy.deepcopy(message))
    replayer.close_block()
    return replayer.messages


def attach_tool_call_thought_signatures(message: dict[str, Any], tool_calls: list) -> dict[str, Any]:
    """Attach Gemini thought signatures to assistant replay tool calls.

    The replay message is later converted back into LangChain messages from a
    plain dict history. Keep signatures in both the provider-neutral
    ``extra_content.thought_signature`` slot and Gemini's OpenAI-compatible
    ``extra_content.google.thought_signature`` slot so both local replay tests
    and the Gemini request injector can recover the value.
    """
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
