"""Per-response text delivery and progress callbacks for AgentRuntime."""
from __future__ import annotations

import time as _time
import uuid
from typing import Any, Callable

from src.kernel import events as vocabulary
from src.kernel.events import EventSink


class TurnStream:
    """Stream model text unchanged and throttle progress events.

    Args:
        emit: Sink for live assistant events.
        iteration: Host iteration number carried by emitted events.
        heartbeat_interval: Callback returning the minimum gap between waiting events in seconds.
        reasoning_interval: Callback returning the minimum gap between reasoning events in seconds.
    """

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
        self.last_waiting_emit: float | None = None

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a stream event, starting the live assistant item on its first delta.

        Args:
            event_type: Event type passed to the sink.
            data: Payload whose kind determines whether to attach the live assistant ID.
        """
        if data.get("kind") in {vocabulary.TEXT_DELTA, vocabulary.TEXT_RESET, vocabulary.REASONING_DELTA}:
            if not self.started:
                self.started = True
                self._emit(vocabulary.ITEM_STARTED, {"kind": vocabulary.ITEM_STARTED, "live_id": self.live_id,
                                             "item": {"type": "assistant"}, "iter": self.iteration})
            data = {**data, "live_id": self.live_id}
        self._emit(event_type, data)

    def on_text(self, delta: str) -> None:
        """Buffer and emit the next text fragment.

        Args:
            delta: Provider text fragment to add to the assistant stream.
        """
        self.thinking_chunks.append(delta)
        self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_DELTA, "delta": delta, "iter": self.iteration})
        self.streamed_chars += len(delta)

    def finish(self, content: str) -> None:
        """Deliver a provider's final text, including adapters that do not stream.

        Any remaining text is emitted with the final phase.

        Args:
            content: Complete provider text. A changed prefix resets the live text.
        """
        shown = "".join(self.thinking_chunks)[:self.streamed_chars]
        if not content.startswith(shown):
            # Some adapters normalize final text, requiring a reset of the partial stream.
            self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_RESET, "iter": self.iteration, "reason": "provider_final_text"})
            shown = ""
        if len(content) > len(shown):
            self.emit(
                vocabulary.ITEM_DELTA,
                {"kind": vocabulary.TEXT_DELTA, "delta": content[len(shown):], "iter": self.iteration, "phase": "final"},
            )

    def on_waiting(self) -> None:
        """Emit a waiting heartbeat when the configured interval allows it."""
        now = _time.monotonic()
        if self.last_waiting_emit is None or now - self.last_waiting_emit >= self.heartbeat_interval():
            self.last_waiting_emit = now
            self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_WAITING, "iter": self.iteration})

    def on_reasoning(self, delta: str) -> None:
        # Throttle reasoning to preserve text and tool events in the SSE replay buffer.
        """Track reasoning and emit the latest tail at the configured interval.

        Args:
            delta: Provider reasoning fragment used to update the character count and tail.
        """
        self.reasoning_chars += len(delta)
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
        self.reasoning_chars = 0
        self.last_reasoning_emit = None
