"""Pure provider message projection and positional tool-call pairing.

Request repair and canonical session replay share this implementation. Repair
never changes persisted history or grants tool or instrument authorization.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Mapping, Optional

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
) -> Dict[str, Any]:
    """Rebuild the assistant message the loop sent, in the loop's key order.

    Mirrors ``ContextBuilder.format_assistant_tool_calls`` for a tool-call
    response and the loop's plain ``{"role", "content"}`` for a final answer.
    """
    message: Dict[str, Any] = {"role": "assistant", "content": copy.deepcopy(item.get("llm_content") if item.get("llm_content") is not None else item.get("content"))}
    tool_calls = item.get("tool_calls") or []
    if tool_calls:
        message["tool_calls"] = copy.deepcopy(tool_calls)
        if any(call.get("extra_content") for call in tool_calls):
            message["additional_kwargs"] = {"tool_calls": copy.deepcopy(tool_calls)}
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

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self._pending: Dict[str, str] = {}
        self._answered: set = set()
        self._held: List[Dict[str, Any]] = []

    def assistant(self, item: Mapping[str, Any]) -> None:
        self.close_block()
        message = assistant_message(item)
        self.assistant_message(message)

    def assistant_message(self, message: Dict[str, Any]) -> None:
        """Append an already reconstructed assistant message."""
        self.close_block()
        self.messages.append(message)
        for call in message.get("tool_calls", []):
            self._pending[call["id"]] = call["function"]["name"]

    def tool_result(self, item: Mapping[str, Any]) -> None:
        self.tool_result_message({
            "role": "tool",
            "tool_call_id": item.get("tool_call_id"),
            "name": item.get("name"),
            "content": item.get("content"),
        })

    def tool_result_message(self, message: Dict[str, Any]) -> None:
        """Append an already reconstructed tool result."""
        call_id = message.get("tool_call_id")
        if call_id not in self._pending or call_id in self._answered:
            logger.debug("Replay dropped a tool result without an open call: %s", call_id)
            return
        self._answered.add(call_id)
        self.messages.append(copy.deepcopy(message))

    def other(self, message: Dict[str, Any]) -> None:
        if self._pending:
            self._held.append(message)
        else:
            self.messages.append(message)

    def close_block(self) -> None:
        for call_id, name in self._pending.items():
            if call_id not in self._answered:
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": INTERRUPTED_RESULT_CONTENT,
                    }
                )
        self._pending = {}
        self._answered = set()
        self.messages.extend(self._held)
        self._held = []



class _MessageItem(dict):
    """Minimal thread-item adapter used by the shared pairing replayer."""

    def __init__(self, item_type: str, message: dict[str, Any]) -> None:
        super().__init__(copy.deepcopy(message))
        self.type = item_type
        self.seq = 0


def repair_provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair tool blocks for one provider request without changing history.

    The session thread's positional replayer is the single pairing
    implementation. A fresh replayer output supplies one interrupted result
    for an unanswered call and drops orphan results. The caller's message list
    is never mutated, so the repair remains request-local.

    Args:
        messages: Messages about to be sent to a provider.

    Returns:
        A repaired, independent message list.
    """
    replayer = MessagePairing()
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            replayer.assistant(_MessageItem("assistant", message))
        elif role == "tool":
            replayer.tool_result(_MessageItem("tool_result", message))
        elif role == "assistant":
            replayer.close_block()
            replayer.messages.append(copy.deepcopy(message))
        else:
            replayer.other(copy.deepcopy(message))
    replayer.close_block()
    return replayer.messages


