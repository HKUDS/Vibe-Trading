"""Forward attempt status to IM adapters without releasing unchecked answers."""
from __future__ import annotations

from typing import Any, Callable

from src.channels.bus.events import InboundMessage, OutboundMessage


class AttemptProgress:
    """Poll buffered session events with an attempt-scoped replay cursor."""

    def __init__(self, bus: Any, event_bus: Any, msg: InboundMessage,
                 session_id: str, attempt_id: str,
                 is_visible: Callable[..., bool] | None = None) -> None:
        self.bus = bus
        self.events = event_bus
        self.msg = msg
        self.session_id = session_id
        self.attempt_id = attempt_id
        self.is_visible = is_visible
        self.cursor: str | None = None
        self.streaming = bool(msg.metadata.get("_wants_stream"))
        self.stream_started = False
        self.reasoning_started = False
        self.last_status = ""
        self.reasoning_chars: dict[int, int] = {}

    async def _send(self, content: str, **flags: Any) -> None:
        await self.bus.publish_outbound(OutboundMessage(
            channel=self.msg.channel, chat_id=self.msg.chat_id, content=content,
            metadata={**self.msg.metadata, "_channel_runtime": True,
                      "session_id": self.session_id, "attempt_id": self.attempt_id,
                      "_stream_id": self.attempt_id, **flags},
        ))

    async def poll(self) -> None:
        """Forward status and opt-in reasoning, excluding answer drafts/results."""
        for event in self.events.replay(self.session_id, self.cursor, replay_all=True):
            self.cursor = event.event_id
            data = event.data
            if data.get("attempt_id") != self.attempt_id:
                continue
            kind = event.event_type
            if kind == "reasoning_delta":
                iteration = int(data.get("iter", 0))
                chars = int(data.get("chars", 0))
                seen = self.reasoning_chars.get(iteration, 0)
                self.reasoning_chars[iteration] = max(seen, chars)
                # AgentLoop emits a bounded cumulative tail, not a delta.
                # A missing tail means no text was supplied: show only
                # a status, never reconstruct text from any other payload.
                tail = data.get("tail")
                if isinstance(tail, str) and chars > seen and tail:
                    self.reasoning_started = True
                    await self._send(tail[-min(chars - seen, len(tail)):], _reasoning_delta=True)
                    continue
                if tail is not None or chars <= seen:
                    continue
            if kind in {"tool_call", "attempt.completed", "attempt.failed"}:
                await self._end_reasoning()
            tool = str(data.get("tool") or "tool")
            status = {
                "attempt.created": "Working on your request…",
                "reasoning_delta": "Reasoning…",
                "llm_waiting": "Waiting for the model…",
                "tool_call": f"Using {tool}…",
                "tool_heartbeat": f"Still running {tool}…",
            }.get(kind)
            # Arbitrary progress payloads, tool results and text_delta may
            # be partial. Only these status labels go out.
            hint = kind in {"tool_call", "tool_heartbeat"}
            if not status or status == self.last_status:
                continue
            # A status the channel hides must not become last_status, or the
            # next visible repeat of the previous status is not deduped.
            if self.is_visible is not None and not self.is_visible(tool_hint=hint):
                continue
            self.last_status = status
            flags = {"_progress": True, "_tool_hint": hint}
            if self.streaming:
                flags["_stream_delta"] = True
                self.stream_started = True
            await self._send(status + "\n", **flags)

    async def _end_reasoning(self) -> None:
        if self.reasoning_started:
            await self._send("", _reasoning_end=True)
            self.reasoning_started = False

    async def close(self) -> None:
        """Close transient cards on completion, timeout or cancellation."""
        await self._end_reasoning()
        if self.stream_started:
            await self._send("", _stream_end=True, _resuming=True)
            self.stream_started = False
