"""Per-response text delivery and progress callbacks for AgentRuntime.

A fresh instance is created for each model iteration. Its state deliberately
survives the one provider retry exactly as the former closure state did.
"""
from __future__ import annotations

import time as _time
import uuid
from typing import Any, Callable

from src.kernel import events as vocabulary
from src.kernel.events import EventSink


class TurnStream:
    """Stream model text unchanged and throttle progress events."""

    def __init__(
        self, *, emit: EventSink,
        iteration: int, heartbeat_interval: Callable[[], float], reasoning_interval: Callable[[], float],
    ) -> None:
        self._emit = emit
        self.live_id = f"assistant:{uuid.uuid4().hex}"
        self.started = False
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

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit one response lifecycle directly from the streaming owner."""
        if data.get("kind") in {vocabulary.TEXT_DELTA, vocabulary.TEXT_RESET, vocabulary.REASONING_DELTA}:
            if not self.started:
                self.started = True
                self._emit(vocabulary.ITEM_STARTED, {"kind": vocabulary.ITEM_STARTED, "live_id": self.live_id,
                                             "item": {"type": "assistant"}, "iter": self.iteration})
            data = {**data, "live_id": self.live_id}
        self._emit(event_type, data)

    def on_text(self, delta: str) -> None:
        self.thinking_chunks.append(delta)
        self.stream_total += len(delta)
        self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_DELTA, "delta": delta, "iter": self.iteration})
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
            self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_RESET, "iter": self.iteration, "reason": "provider_final_text"})
            shown = ""
        if len(content) > len(shown):
            self.emit(
                vocabulary.ITEM_DELTA,
                {"kind": vocabulary.TEXT_DELTA, "delta": content[len(shown):], "iter": self.iteration, "phase": "final"},
            )

    def on_waiting(self) -> None:
        now = _time.monotonic()
        if self.last_waiting_emit is None or now - self.last_waiting_emit >= self.heartbeat_interval():
            self.last_waiting_emit = now
            self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_WAITING, "iter": self.iteration})

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
        reasoning_event["kind"] = vocabulary.REASONING_DELTA
        self.emit(vocabulary.ITEM_DELTA, reasoning_event)

    def reset_for_retry(self) -> None:
        """Discard the failed text attempt with the existing retry semantics."""
        self.thinking_chunks.clear()
        self.streamed_chars = 0
        self.stream_total = 0
        self.reasoning_chars = 0
        self.last_reasoning_emit = None
