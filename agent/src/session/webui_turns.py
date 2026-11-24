"""In-process WebUI turn timing helpers for channel adapters."""

from __future__ import annotations

import time


_TURN_STARTED_AT: dict[str, float] = {}


def mark_websocket_turn_started(chat_id: str, started_at: float | None = None) -> float:
    """Record the start time of a WebSocket chat turn.

    Args:
        chat_id: Chat ID used to index the current turn.
        started_at: Unix timestamp in seconds, defaulting to the current wall-clock time.

    Returns:
        The stored timestamp.
    """
    value = float(started_at if started_at is not None else time.time())
    _TURN_STARTED_AT[str(chat_id)] = value
    return value


def clear_websocket_turn_started(chat_id: str) -> None:
    """Clear a recorded WebSocket turn start timestamp.

    Args:
        chat_id: Chat ID whose current turn timestamp should be cleared.
    """
    _TURN_STARTED_AT.pop(str(chat_id), None)


def websocket_turn_wall_started_at(chat_id: str | None = None) -> float | None:
    """Read the recorded start time of a WebSocket chat turn.

    Args:
        chat_id: Chat ID to look up, or None when no chat is selected.

    Returns:
        The stored Unix timestamp in seconds, or None if unavailable.
    """
    if chat_id is None:
        return None
    return _TURN_STARTED_AT.get(str(chat_id))
