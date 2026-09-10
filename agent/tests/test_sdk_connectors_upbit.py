"""Tests for the Upbit direct-SDK trading connector.

Mirrors ``test_sdk_connectors.py``: exercises profile registration, the
structural paper-only guard (Upbit has no runtime paper/live discriminator),
config resolution, read/write classification, secret redaction, and service
dispatch degrading cleanly when nothing is configured — no live credentials
or network access required.
"""

from __future__ import annotations

import pytest

from src.live.classification import ToolClass
from src.trading import profiles, service
from src.trading.connectors.upbit import sdk as up
from src.trading.connectors.upbit.classification import UPBIT_TOOL_CLASS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Profile registration
# --------------------------------------------------------------------------- #


def test_upbit_sdk_profiles_registered() -> None:
    ids = {p.id for p in profiles.list_profiles()}
    assert {"upbit-paper-sdk", "upbit-paper-trade", "upbit-live-sdk-readonly"} <= ids


def test_upbit_live_profile_is_readonly_broker_sdk() -> None:
    profile = profiles.profile_by_id("upbit-live-sdk-readonly")
    assert profile.connector == "upbit"
    assert profile.environment == "live"
    assert profile.transport == "broker_sdk"
    assert profile.readonly is True
    assert not any(".place" in cap or "requires_mandate" in cap for cap in profile.capabilities)


def test_upbit_exposes_no_live_trade_profile() -> None:
    """No runtime discriminator -> no *-live-trade profile, ever (Longbridge precedent)."""
    ids = {p.id for p in profiles.list_profiles()}
    assert "upbit-live-trade" not in ids
    for profile in profiles.list_profiles():
        if profile.connector == "upbit" and profile.environment == "live":
            assert not any(".place" in cap or "requires_mandate" in cap for cap in profile.capabilities)


# --------------------------------------------------------------------------- #
# Structural paper-only guard (no runtime discriminator)
# --------------------------------------------------------------------------- #


def test_upbit_paper_place_order_simulated_locally() -> None:
    cfg = up.UpbitConfig(access_key="ak", secret_key="sk", profile="paper")
    result = up.place_order(cfg, symbol="KRW-BTC", side="buy", quantity=0.01, limit_price=50_000_000)
    assert result["status"] == "ok"
    assert result["is_paper"] is True
    assert result["order_status"] == "simulated_fill"
    assert result["paper_guard"] == "simulated_locally"
    assert result["fill_price"] == 50_000_000


def test_upbit_paper_cancel_order_simulated() -> None:
    cfg = up.UpbitConfig(access_key="ak", secret_key="sk", profile="paper")
    result = up.cancel_order(cfg, "ORD1")
    assert result["status"] == "ok"
    assert result["cancelled"] is True
    assert result["is_paper"] is True


def test_upbit_live_order_hard_refused() -> None:
    """The guard must be structurally impossible to bypass, not a checked flag:
    it runs as the first statement in place_order/cancel_order, before any
    network call — see test_paper_capped_connectors_refuse_live.py."""
    cfg = up.UpbitConfig(access_key="ak", secret_key="sk", profile="live-readonly")
    result = up.place_order(cfg, symbol="KRW-BTC", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "paper-only" in result["error"]

    cancel_result = up.cancel_order(cfg, "ORD1")
    assert cancel_result["status"] == "error"
    assert "paper-only" in cancel_result["error"]


def test_upbit_notional_order_fails_closed_when_quote_unavailable(monkeypatch) -> None:
    """A failed live-quote lookup must not fabricate a null-priced 'ok' fill."""
    cfg = up.UpbitConfig(access_key="ak", secret_key="sk", profile="paper")
    monkeypatch.setattr(up, "get_quote", lambda *a, **k: {"status": "error", "error": "network"})
    result = up.place_order(cfg, symbol="KRW-BTC", side="buy", notional=100_000)
    assert result["status"] == "error"


def test_upbit_place_order_requires_exactly_one_of_quantity_or_notional() -> None:
    cfg = up.UpbitConfig(access_key="ak", secret_key="sk", profile="paper")
    both = up.place_order(cfg, symbol="KRW-BTC", side="buy", quantity=1, notional=1000)
    neither = up.place_order(cfg, symbol="KRW-BTC", side="buy")
    assert both["status"] == "error"
    assert neither["status"] == "error"


def test_upbit_normalizes_market_symbol() -> None:
    assert up._normalize_market("krw/btc") == "KRW-BTC"
    assert up._normalize_market(" KRW-eth ") == "KRW-ETH"


def test_upbit_invalid_profile_rejected() -> None:
    with pytest.raises(up.UpbitConfigError):
        up.UpbitConfig.from_mapping({"profile": "live"})  # only paper/live-readonly


# --------------------------------------------------------------------------- #
# Redaction / service dispatch / classification
# --------------------------------------------------------------------------- #


def test_upbit_redacts_secret_key() -> None:
    cfg = up.UpbitConfig(access_key="access-1234", secret_key="super-secret")
    pub = up._public_config(cfg)
    assert "super-secret" not in str(pub)
    assert pub["access_key"].endswith("***")
    assert pub["secret_key"] == "***redacted***"


def test_upbit_service_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(up, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("upbit-paper-sdk")
    assert result["status"] == "error"
    assert result["connector"] == "upbit"
    assert result["transport"] == "broker_sdk"


def test_upbit_order_ops_classified_write() -> None:
    for name in ("place_order", "cancel_order"):
        assert UPBIT_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("get_positions", "get_account_snapshot"):
        assert UPBIT_TOOL_CLASS[name] is ToolClass.READ
