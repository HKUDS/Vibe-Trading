"""Bare developer-platform tokens are scrubbed from free-form text."""

from __future__ import annotations

import pytest

from src.tools.redaction import redact_text

_TOKENS = [
    "github_pat_11ABCDEFG0" + "a1B2c3D4e5F6g7H8i9J0_" + "k" * 40,
    "glpat-" + "a1B2c3D4e5F6g7H8i9J0",
    "npm_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "hf_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6",
]


@pytest.mark.parametrize("token", _TOKENS)
def test_bare_platform_token_is_redacted(token: str) -> None:
    out = redact_text(f"cloning with {token} failed")
    assert token not in out
    assert out == "cloning with [redacted] failed"
    assert redact_text(out) == out


@pytest.mark.parametrize("token", _TOKENS)
def test_platform_token_inside_url_userinfo_is_redacted(token: str) -> None:
    out = redact_text(f"fatal: https://{token}@host/org/repo.git")
    assert token not in out


def test_lookalike_identifiers_are_left_alone() -> None:
    text = "npm_config_registry hf_home github_pat_ glpat-short npm_short hf_x"
    assert redact_text(text) == text
