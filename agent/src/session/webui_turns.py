"""In-process WebUI turn timing helpers for channel adapters."""

from __future__ import annotations

import time


_TURN_STARTED_AT: dict[str, float] = {}


def mark_websocket_turn_started(chat_id: str, started_at: float | None = None) -> float:
    """Record that a WebSocket chat turn started and return its timestamp."""
    value = float(started_at if started_at is not None else time.time())
    _TURN_STARTED_AT[str(chat_id)] = value
    return value


def clear_websocket_turn_started(chat_id: str) -> None:
    """Clear a recorded WebSocket turn start timestamp."""
    _TURN_STARTED_AT.pop(str(chat_id), None)


def websocket_turn_wall_started_at(chat_id: str | None = None) -> float | None:
    """Return the wall-clock time when the current turn started, or None."""
    if chat_id is None:
        return None
    return _TURN_STARTED_AT.get(str(chat_id))
