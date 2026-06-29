"""WebUI fork-chat compatibility for the WebSocket channel."""

from __future__ import annotations

from typing import Any


_HANDLE_WEBUI_FORK_CHAT = None


async def handle_webui_fork_chat(*args: Any, **kwargs: Any) -> None:
    """Return a structured unsupported response for fork-chat requests."""
    del kwargs
    if len(args) >= 2:
        channel, connection = args[0], args[1]
        send_event = getattr(channel, "_send_event", None)
        if callable(send_event):
            await send_event(
                connection,
                "error",
                detail="fork_chat is not available in this runtime",
            )
    return
