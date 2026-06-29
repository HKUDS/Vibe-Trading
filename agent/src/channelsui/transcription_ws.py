"""Transcription WebSocket compatibility helpers."""

from __future__ import annotations

from typing import Any


async def webui_transcription_event(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
    """Return a structured response when transcription is not configured."""
    del args, kwargs
    return "error", {"detail": "audio transcription is not configured"}
