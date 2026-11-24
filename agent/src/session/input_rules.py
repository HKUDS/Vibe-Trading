"""Share session input limits across HTTP and SDK entry points."""

from __future__ import annotations

import re

#: Longest user message a session accepts, in characters.
MAX_MESSAGE_CHARS = 100_000
#: Shape of an id that is safe to join under a storage directory.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def check_session_id(value: object) -> str:
    """Return ``value`` when it is a safe session id.

    Args:
        value: Candidate ID to validate against SAFE_ID_RE.

    Returns:
        The validated session ID.

    Raises:
        ValueError: If the value is not a string matching SAFE_ID_RE.
    """
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ValueError("invalid session_id")
    return value


def check_message_text(text: object) -> str:
    """Return ``text`` when it is a sendable user message.

    Args:
        text: Candidate user message, limited to MAX_MESSAGE_CHARS characters.

    Returns:
        The validated message text.

    Raises:
        ValueError: If the message is not a nonempty string or exceeds the character limit.
    """
    if not isinstance(text, str) or not text:
        raise ValueError("Message must contain at least 1 character")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(
            f"Message must contain at most {MAX_MESSAGE_CHARS} characters. Shorten it before sending."
        )
    return text
