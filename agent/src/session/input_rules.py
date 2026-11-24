"""Limits on what a caller may hand the session layer.

One definition for every entry point that accepts a session id or a user
message from outside the kernel: the HTTP routes (``SendMessageRequest`` and
``_validate_path_param``) and the embeddable ``vibe_trading.Client``.
"""

from __future__ import annotations

import re

#: Longest user message a session accepts, in characters.
MAX_MESSAGE_CHARS = 100_000
#: Shape of an id that is safe to join under a storage directory.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def check_session_id(value: object) -> str:
    """Return ``value`` when it is a safe session id."""
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ValueError("invalid session_id")
    return value


def check_message_text(text: object) -> str:
    """Return ``text`` when it is a sendable user message."""
    if not isinstance(text, str) or not text:
        raise ValueError("Message must contain at least 1 character")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(
            f"Message must contain at most {MAX_MESSAGE_CHARS} characters. Shorten it before sending."
        )
    return text
