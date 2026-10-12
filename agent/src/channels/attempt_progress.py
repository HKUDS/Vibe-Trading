"""Forward attempt status to IM adapters without releasing unchecked answers."""
from __future__ import annotations

from typing import Any

from src.channels.bus.events import InboundMessage, OutboundMessage


class AttemptProgress:
    """Poll buffered session events with an attempt-scoped replay cursor."""

    def __init__(self, bus: Any, event_bus: Any, msg: InboundMessage,
                 session_id: str, attempt_id: str) -> None:
        self.bus = bus
        self.events = event_bus
        self.msg = msg
        self.session_id = session_id
        self.attempt_id = attempt_id
        self.cursor: str | None = None
        self.streaming = bool(msg.metadata.get("_wants_stream"))
        self.stream_started = False
        self.reasoning_started = False
        self.last_status = ""

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
                delta = data.get("delta", "")
                if delta:
                    self.reasoning_started = True
                    await self._send(str(delta), _reasoning_delta=True)
                continue
            if kind in {"tool_call", "grounding_status", "attempt.completed", "attempt.failed"}:
                await self._end_reasoning()
            tool = str(data.get("tool") or "tool")
            status = {
                "attempt.created": "Working on your request…",
                "tool_call": f"Using {tool}…",
                "tool_heartbeat": f"Still running {tool}…",
                "grounding_status": "Checking the figures…",
            }.get(kind)
            # Arbitrary progress payloads, tool results and text_delta may
            # contain unvalidated figures. Only these status labels go out.
            if not status or status == self.last_status:
                continue
            self.last_status = status
            hint = kind in {"tool_call", "tool_heartbeat"}
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
