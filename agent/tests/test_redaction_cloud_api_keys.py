"""Bare Stripe, Google and AWS temporary keys are scrubbed from free-form text."""

from __future__ import annotations

import pytest

from src.tools.redaction import redact_text

_KEYS = [
    "sk_live_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "sk_test_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "rk_live_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "AIza" + "Sy" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
    "ASIA" + "IOSFODNN7EXAMPLE",
]


@pytest.mark.parametrize("key", _KEYS)
def test_bare_key_is_redacted(key: str) -> None:
    out = redact_text(f"request failed with {key} in the header")
    assert key not in out
    assert out == "request failed with [redacted] in the header"
    assert redact_text(out) == out


def test_lookalikes_are_left_alone() -> None:
    text = "pk_live_publishableKey123456 sk_live_short AIzaShort ASIA123 task_test_" + "x" * 20
    assert redact_text(text) == text
