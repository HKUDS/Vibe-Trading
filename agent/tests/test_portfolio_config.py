from __future__ import annotations

import json
import os

import pytest

from src.portfolio.config import (
    PortfolioSettingsStore,
    eligible_profiles,
    parse_settings,
    source_catalog,
)
from src.trading.connections import ConnectionStore
from src.trading.profiles import profile_by_id
from src.trading.types import TradingProfile


def test_portfolio_settings_round_trip_without_credentials(tmp_path):
    store = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings = store.save(
        {
            "display_currency": "CNY",
            "sources": [
                {
                    "id": "main-stocks",
                    "profile_id": "alpaca-live-sdk-readonly",
                    "label": "Main stocks",
                    "enabled": True,
                    "order": 0,
                    "include_cash": True,
                }
            ],
        }
    )

    assert store.load() == settings
    if os.name == "posix":
        assert (tmp_path / "portfolio.json").stat().st_mode & 0o777 == 0o600
    payload = json.loads((tmp_path / "portfolio.json").read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(payload)
    assert "profile_id" not in json.dumps(payload)
    assert source_catalog(settings, store.connection_store)[0].keys() >= {
        "connection_id",
        "readonly",
        "selected",
    }


def test_portfolio_settings_reject_trade_profiles():
    connections = ConnectionStore()
    with pytest.raises(ValueError, match="eligible for read-only"):
        parse_settings(
            {
                "display_currency": "USD",
                "sources": [
                    {
                        "id": "unsafe",
                        "profile_id": "binance-live-trade",
                        "label": "Unsafe",
                    }
                ],
            },
            connections,
        )


def test_new_install_starts_with_no_selected_sources(tmp_path):
    store = PortfolioSettingsStore(tmp_path / "portfolio.json")
    assert store.load().sources == ()


def test_a_discovery_only_profile_cannot_back_a_portfolio_source(
    monkeypatch, tmp_path
):
    """Tool discovery is not a holdings read, so such a profile is not eligible.

    A remote profile can be read-only yet expose discovery and no holdings
    reads. Accepting it would create a source that fails on every refresh.
    """
    profile = TradingProfile(
        id="discovery-only-test",
        connector="test",
        label="Discovery only",
        environment="live",
        transport="remote_mcp",
        capabilities=("mcp.read.discovery",),
        readonly=True,
        config={"server": "test"},
    )
    original_profile_by_id = profile_by_id

    def lookup(profile_id):
        return profile if profile_id == profile.id else original_profile_by_id(profile_id)

    monkeypatch.setattr("src.portfolio.config.profile_by_id", lookup)
    monkeypatch.setattr("src.trading.connections.profile_by_id", lookup)
    assert profile.readonly is True
    assert profile.capabilities == ("mcp.read.discovery",)
    assert profile not in eligible_profiles()
    assert all(
        {"account.read", "positions.read"}.issubset(item.capabilities)
        and item.readonly
        for item in eligible_profiles()
    )

    with pytest.raises(ValueError, match="not eligible for read-only"):
        parse_settings(
            {
                "display_currency": "USD",
                "sources": [
                    {
                        "id": "discovery-only",
                        "profile_id": profile.id,
                        "label": "Discovery only",
                    }
                ],
            },
            ConnectionStore(tmp_path / "connections.json"),
        )
