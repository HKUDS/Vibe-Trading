"""Per-response text delivery and progress callbacks for AgentLoop.

A fresh instance is created for each model iteration. Its state deliberately
survives the one provider retry exactly as the former closure state did.
"""
from __future__ import annotations

import time as _time
from typing import Any, Callable


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
        """Deliver a provider's final text, including adapters that do not stream."""
        shown = "".join(self.thinking_chunks)[:self.streamed_chars]
        if not content.startswith(shown):
            # Some adapters return a normalized final message. Replace its own
            # partial stream; never rewrite the provider's final answer.
            self.emit("stream_reset", {"iter": self.iteration, "reason": "provider_final_text"})
            shown = ""
        if len(content) > len(shown):
            self.emit("text_delta", {"delta": content[len(shown):], "iter": self.iteration})

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
