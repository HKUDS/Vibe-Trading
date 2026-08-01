"""Map Vibe-Trading internal events to OpenBB Workspace SSE events.

Vibe-Trading's :class:`AgentLoop` emits fine-grained events through the session
event bus (``text_delta``, ``tool_call``, ``tool_result``, ...). OpenBB
Workspace expects a different, smaller vocabulary of Server-Sent Events built
with the ``openbb_ai`` helper functions (``message_chunk``, ``reasoning_step``,
...).

:class:`SSEEventMapper` translates one Vibe-Trading event into zero or more
``openbb_ai`` SSE objects. Returning an empty list means "swallow this event"
(used for high-frequency progress / bookkeeping events that would only add
noise to the Workspace transcript).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from openbb_ai.helpers import message_chunk, reasoning_step

logger = logging.getLogger("openbb_bridge")

# Vibe-Trading event types that carry the visible answer text.
_TEXT_EVENTS = {"text_delta"}

# Events that are pure progress / telemetry and should not reach Workspace.
_SILENT_EVENTS = {
    "reasoning_delta",
    "thinking_done",
    "tool_progress",
    "tool_heartbeat",
    "llm_usage",
    "stream_start",
    "message.received",
    "attempt.created",
    "session.created",
}


def _clip(value: Any, limit: int = 500) -> str:
    """Return *value* stringified and clipped to *limit* characters."""
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


class SSEEventMapper:
    """Translate Vibe-Trading events into ``openbb_ai`` SSE objects."""

    def map(self, event_type: str, data: Dict[str, Any]) -> List[Any]:
        """Translate one Vibe-Trading event into ``openbb_ai`` SSE objects.

        Args:
            event_type: The session-bus event type.
            data: The event payload; ``None`` is tolerated.

        Returns:
            Zero or more ``openbb_ai`` SSE objects. An empty list means the event
            was deliberately swallowed (progress noise, unknown type, or a
            mapping error).
        """
        data = data or {}
        try:
            if event_type in _TEXT_EVENTS:
                delta = data.get("delta", "")
                return [message_chunk(text=delta)] if delta else []

            if event_type in _SILENT_EVENTS:
                return []

            if event_type == "tool_call":
                tool = data.get("tool", "tool")
                arguments = data.get("arguments")
                details = arguments if isinstance(arguments, dict) else None
                return [
                    reasoning_step(
                        message=f"Calling tool: {tool}",
                        event_type="INFO",
                        details=details,
                    )
                ]

            if event_type == "tool_result":
                tool = data.get("tool", "tool")
                status = data.get("status", "done")
                elapsed = data.get("elapsed_ms")
                preview = data.get("preview")
                suffix = f" ({elapsed}ms)" if elapsed is not None else ""
                level = "ERROR" if str(status).lower() in {"error", "failed"} else "INFO"
                return [
                    reasoning_step(
                        message=f"Tool {tool} -> {status}{suffix}",
                        event_type=level,
                        details=_clip(preview) if preview else None,
                    )
                ]

            if event_type == "compact":
                summary = data.get("summary")
                return [
                    reasoning_step(
                        message="Context compacted to stay within limits.",
                        event_type="INFO",
                        details=_clip(summary) if summary else None,
                    )
                ]

            if event_type == "stream_reset":
                return [
                    reasoning_step(
                        message="Model stream reset, retrying.",
                        event_type="WARNING",
                    )
                ]

            if event_type == "goal.updated":
                goal = data.get("goal") or data.get("summary")
                return [
                    reasoning_step(
                        message="Goal updated.",
                        event_type="INFO",
                        details=_clip(goal) if goal else None,
                    )
                ]

            if event_type == "mcp.warning":
                message = data.get("message", "MCP warning")
                return [reasoning_step(message=_clip(message), event_type="WARNING")]

            if event_type == "attempt.started":
                return [
                    reasoning_step(
                        message="Vibe-Trading agent started.",
                        event_type="INFO",
                    )
                ]

            # Unknown event: swallow it rather than leaking internal noise.
            logger.debug("Unmapped Vibe-Trading event: %s", event_type)
            return []
        except Exception as exc:  # never break the stream on a mapping error
            logger.warning("Failed to map event %s: %s", event_type, exc)
            return []
