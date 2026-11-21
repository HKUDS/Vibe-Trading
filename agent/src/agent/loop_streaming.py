"""Per-response text delivery and progress callbacks for AgentLoop.

A fresh instance is created for each model iteration. Its state deliberately
survives the one provider retry exactly as the former closure state did.
"""
from __future__ import annotations

import copy
import time as _time
from typing import Any, Callable

from src.session.thread import _Replayer


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
    replayer = _Replayer()
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


class TurnStream:
    """Stream model text unchanged and throttle progress events."""

    def __init__(
        self, *, emit: Callable[[str, dict[str, Any]], None],
        iteration: int, heartbeat_interval: Callable[[], float], reasoning_interval: Callable[[], float],
    ) -> None:
        self.emit = emit
        self.iteration = iteration
        self.heartbeat_interval = heartbeat_interval
        self.reasoning_interval = reasoning_interval
        self.thinking_chunks: list[str] = []
        self.reasoning_chars = 0
        self.reasoning_tail = ""
        self.last_reasoning_emit: float | None = None
        self.streamed_chars = 0
        self.stream_total = 0
        self.last_waiting_emit: float | None = None

    def on_text(self, delta: str) -> None:
        self.thinking_chunks.append(delta)
        self.stream_total += len(delta)
        self.emit("text_delta", {"delta": delta, "iter": self.iteration})
        self.streamed_chars = self.stream_total

    def finish(self, content: str) -> None:
        """Deliver a provider's final text, including adapters that do not stream.

        Text delivered here is the turn's answer, so its delta carries
        ``phase: final``. Deltas streamed earlier left before the response said
        whether tool calls follow and carry no phase.
        """
        shown = "".join(self.thinking_chunks)[:self.streamed_chars]
        if not content.startswith(shown):
            # Some adapters return a normalized final message. Replace its own
            # partial stream; never rewrite the provider's final answer.
            self.emit("stream_reset", {"iter": self.iteration, "reason": "provider_final_text"})
            shown = ""
        if len(content) > len(shown):
            self.emit(
                "text_delta",
                {"delta": content[len(shown):], "iter": self.iteration, "phase": "final"},
            )

    def on_waiting(self) -> None:
        now = _time.monotonic()
        if self.last_waiting_emit is None or now - self.last_waiting_emit >= self.heartbeat_interval():
            self.last_waiting_emit = now
            self.emit("llm_waiting", {"iter": self.iteration})

    def on_reasoning(self, delta: str) -> None:
        # Throttled: long reasoning streams produce hundreds of
        # chunks; emitting each one floods the SSE replay buffer
        # and evicts tool_call/text_delta events. The first chunk
        # of each iteration always emits immediately so the UI
        # flips to "Reasoning…" without delay.
        self.reasoning_chars += len(delta)
        # Rolling tail rides the already-throttled emit so the UI
        # can whisper the current thought; a bounded window keeps
        # replay-buffer pressure flat regardless of trace length.
        self.reasoning_tail = (self.reasoning_tail + delta)[-600:]
        now = _time.monotonic()
        if (
            self.last_reasoning_emit is not None
            and now - self.last_reasoning_emit < self.reasoning_interval()
        ):
            return
        self.last_reasoning_emit = now
        reasoning_event = {
            "iter": self.iteration,
            "chars": self.reasoning_chars,
        }
        reasoning_event["tail"] = self.reasoning_tail
        self.emit("reasoning_delta", reasoning_event)

    def reset_for_retry(self) -> None:
        """Discard the failed text attempt with the existing retry semantics."""
        self.thinking_chunks.clear()
        self.streamed_chars = 0
        self.stream_total = 0
        self.reasoning_chars = 0
        self.last_reasoning_emit = None
