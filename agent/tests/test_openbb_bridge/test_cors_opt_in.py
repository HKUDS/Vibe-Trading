"""CORS regressions for the additive VIBE_TRADING_EXTRA_CORS_ORIGINS opt-in.

The OpenBB Workspace bridge needs a browser origin the loopback defaults do not
cover. It must be opt-in: CORS is installed globally with credentials, and in
keyless dev mode safe GETs are admitted by local peer address, so an origin
trusted here can read every other endpoint too.
"""

from __future__ import annotations

import pytest

import api_server
from src.api import security


def test_openbb_origin_is_not_trusted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("VIBE_TRADING_EXTRA_CORS_ORIGINS", raising=False)

    assert "https://pro.openbb.co" not in security._get_cors_origins()


def test_extra_origins_are_appended_to_the_loopback_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("VIBE_TRADING_EXTRA_CORS_ORIGINS", "https://pro.openbb.co")

    origins = security._get_cors_origins()

    # Additive, not replacing: the bundled Web UI origins survive.
    assert set(api_server._DEFAULT_CORS_ORIGINS).issubset(origins)
    assert origins[-1] == "https://pro.openbb.co"


def test_extra_origins_are_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://pro.openbb.co")
    monkeypatch.setenv("VIBE_TRADING_EXTRA_CORS_ORIGINS", "https://pro.openbb.co")

    assert security._get_cors_origins() == ["https://pro.openbb.co"]


def test_extra_origins_reject_credentialed_wildcard() -> None:
    with pytest.raises(RuntimeError, match="VIBE_TRADING_EXTRA_CORS_ORIGINS"):
        api_server._parse_extra_cors_origins("https://pro.openbb.co,*")


def test_extra_origins_parse_blank_input_as_empty() -> None:
    assert api_server._parse_extra_cors_origins(None) == []
    assert api_server._parse_extra_cors_origins("  ,  ") == []
