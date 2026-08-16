"""Shared invariant: the LLM never sees a system message after index 0.

Anthropic's Messages API accepts only a single leading ``system`` block;
``langchain_anthropic`` raises ``ValueError`` on a mid-conversation system
message. Every mid-conversation steering prompt must therefore be a
``{"role": "user", ...}`` message carrying an inline ``<system>`` tag — the
repo's canonical pattern (``loop.py`` background results and auto-compact).
This helper enforces that invariant over every message list a run handed to
the model.
"""

from __future__ import annotations

from typing import Any


def assert_system_messages_only_lead(history: list[list[dict[str, Any]]]) -> None:
    """Assert no captured message list has a system role after index 0.

    Args:
        history: One message list per LLM call, in call order.
    """
    for call_index, messages in enumerate(history):
        for i, message in enumerate(messages):
            assert message.get("role") != "system" or i == 0, (
                f"mid-conversation system message at index {i} of LLM call "
                f"{call_index}: {message!r}"
            )
