"""Tests for the KIS (한국투자증권) direct-SDK trading connector.

Mirrors ``test_sdk_connectors.py``: exercises profile registration, the
genuine structural paper/live host separation, config resolution, read/write
classification, secret redaction, and service dispatch degrading cleanly when
nothing is configured — no live credentials or network access required.
"""

from __future__ import annotations

import pytest

from src.live.classification import ToolClass
from src.trading import profiles, service
from src.trading.connectors.kis import sdk as kis
from src.trading.connectors.kis.classification import KIS_TOOL_CLASS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Profile registration
# --------------------------------------------------------------------------- #


def test_kis_sdk_profiles_registered() -> None:
    ids = {p.id for p in profiles.list_profiles()}
    assert {"kis-paper-sdk", "kis-paper-trade", "kis-live-sdk-readonly"} <= ids


def test_kis_live_profile_is_readonly_broker_sdk() -> None:
    profile = profiles.profile_by_id("kis-live-sdk-readonly")
    assert profile.connector == "kis"
    assert profile.environment == "live"
    assert profile.transport == "broker_sdk"
    assert profile.readonly is True
    assert not any(".place" in cap or "requires_mandate" in cap for cap in profile.capabilities)


def test_kis_paper_trade_profile_allows_order_placement() -> None:
    profile = profiles.profile_by_id("kis-paper-trade")
    assert profile.environment == "paper"
    assert profile.readonly is False
    assert "orders.place" in profile.capabilities


# --------------------------------------------------------------------------- #
# Genuine structural paper/live host separation
# --------------------------------------------------------------------------- #


def test_kis_base_url_differs_by_environment() -> None:
    paper = kis.KISConfig(profile="paper")
    live = kis.KISConfig(profile="live-readonly")
    assert paper.base_url != live.base_url
    assert "vts" in paper.base_url  # 모의투자 (paper) host
    assert paper.base_url.endswith(":29443")
    assert live.base_url.endswith(":9443")


def test_kis_order_tr_id_differs_by_environment_and_side() -> None:
    assert kis._TR_ORDER_BUY["paper"] != kis._TR_ORDER_BUY["live"]
    assert kis._TR_ORDER_BUY["paper"] != kis._TR_ORDER_SELL["paper"]


def test_kis_invalid_profile_rejected() -> None:
    with pytest.raises(kis.KISConfigError):
        kis.KISConfig.from_mapping({"profile": "live"})  # only paper/live-readonly


# --------------------------------------------------------------------------- #
# Order validation
# --------------------------------------------------------------------------- #


def test_kis_place_order_validates_before_any_request() -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    missing_qty = kis.place_order(cfg, symbol="005930", side="buy")
    bad_side = kis.place_order(cfg, symbol="005930", side="hold", quantity=10)
    missing_limit_price = kis.place_order(cfg, symbol="005930", side="buy", quantity=10, order_type="limit")
    notional_rejected = kis.place_order(cfg, symbol="005930", side="buy", notional=100_000)
    assert missing_qty["status"] == "error"
    assert bad_side["status"] == "error"
    assert missing_limit_price["status"] == "error"
    assert notional_rejected["status"] == "error"
    assert "notional" in notional_rejected["error"]


def test_kis_cancel_order_rejects_fractional_sub_share_quantity() -> None:
    """0.5 must not silently truncate to 0 and flip into a full-quantity cancel."""
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    result = kis.cancel_order(cfg, "ORD1", order_branch="00001", quantity=0.5)
    assert result["status"] == "error"


def test_kis_get_historical_bars_limit_zero_returns_no_bars(monkeypatch) -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    monkeypatch.setattr(
        kis,
        "_get",
        lambda *a, **k: {"output2": [{"stck_bsop_date": "20260101", "stck_clpr": "100"}]},
    )
    result = kis.get_historical_bars("005930", config=cfg, limit=0)
    assert result["bars"] == []


# --------------------------------------------------------------------------- #
# Redaction / service dispatch / classification
# --------------------------------------------------------------------------- #


def test_kis_redacts_app_secret() -> None:
    cfg = kis.KISConfig(app_key="APPKEY123456", app_secret="topsecret", account_no="12345678")
    pub = kis._public_config(cfg)
    assert "topsecret" not in str(pub)
    assert pub["app_key"].endswith("***")
    assert pub["app_secret"] == "***redacted***"


def test_kis_service_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(kis, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("kis-paper-sdk")
    assert result["status"] == "error"
    assert result["connector"] == "kis"
    assert result["transport"] == "broker_sdk"


def test_kis_order_ops_classified_write() -> None:
    for name in ("place_order", "cancel_order"):
        assert KIS_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("get_positions", "get_account_snapshot"):
        assert KIS_TOOL_CLASS[name] is ToolClass.READ
