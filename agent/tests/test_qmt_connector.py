"""Unit tests for the generic QMT/XtQuant connector."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.trading import profiles, service
from src.trading.connectors.qmt import sdk as qmt

pytestmark = pytest.mark.unit


class _FakeTrader:
    def __init__(self, path, session_id):
        self.path = path
        self.session_id = session_id
        self.calls = []

    def start(self):
        self.calls.append("start")
        return 0

    def connect(self):
        self.calls.append("connect")
        return 0

    def subscribe(self, account):
        self.calls.append(("subscribe", account.account_id, account.account_type))
        return 0

    def stop(self):
        self.calls.append("stop")

    def query_stock_asset(self, account):
        return SimpleNamespace(
            account_id=account.account_id,
            account_type=account.account_type,
            cash=1234.5,
            total_asset=2345.6,
        )

    def query_stock_positions(self, account):
        return [SimpleNamespace(stock_code="600000.SH", volume=100)]

    def query_stock_orders(self, account):
        return [SimpleNamespace(order_id=7, stock_code="600000.SH")]

    def query_stock_trades(self, account):
        return [SimpleNamespace(traded_volume=100, traded_price=10.5)]

    def order_stock(self, *args):
        self.calls.append(("order_stock", args))
        return 19

    def cancel_order_stock(self, *args):
        self.calls.append(("cancel_order_stock", args))
        return 0


class _FakeAccount:
    def __init__(self, account_id, account_type="STOCK"):
        self.account_id = account_id
        self.account_type = account_type


@pytest.fixture
def fake_xtquant(monkeypatch, tmp_path):
    trader_holder = {}

    def make_trader(path, session_id):
        trader = _FakeTrader(path, session_id)
        trader_holder["trader"] = trader
        return trader

    deps = SimpleNamespace(
        XtQuantTrader=make_trader,
        StockAccount=_FakeAccount,
        xtconstant=SimpleNamespace(STOCK_BUY=1, STOCK_SELL=2, FIX_PRICE=3, LATEST_PRICE=4),
        xtdata=SimpleNamespace(
            get_full_tick=lambda symbols: {symbols[0]: {"lastPrice": 10.5}},
            download_history_data=lambda *args: None,
            get_market_data_ex=lambda *args, **kwargs: {
                "600000.SH": [{"time": 1, "close": 10.5}]
            },
        ),
    )
    monkeypatch.setattr(qmt, "_require_xtquant", lambda: deps)
    cfg = qmt.QMTConfig(userdata_mini=str(tmp_path), account_id="123456", profile="paper", readonly=False)
    return cfg, trader_holder


def test_qmt_profiles_registered_and_only_paper_trade_is_writable():
    qmt_profiles = [profile for profile in profiles.list_profiles() if profile.connector == "qmt"]
    assert {profile.id for profile in qmt_profiles} == {
        "qmt-paper-sdk",
        "qmt-paper-trade",
        "qmt-live-sdk-readonly",
    }
    assert profiles.profile_by_id("qmt-paper-trade").readonly is False
    assert profiles.profile_by_id("qmt-live-sdk-readonly").readonly is True
    assert "qmt" in service._SDK_CONNECTOR_MODULES


def test_qmt_config_builds_from_profile_and_overrides(tmp_path):
    cfg = qmt.build_config(
        {"profile": "paper", "account_type": "STOCK"},
        {"userdata_mini": str(tmp_path), "account_id": "abc", "session_id": "88"},
    )
    assert cfg.userdata_mini == str(tmp_path)
    assert cfg.account_id == "abc"
    assert cfg.session_id == 88
    assert cfg.environment == "paper"


def test_qmt_reads_use_account_identity_and_cleanup(fake_xtquant):
    cfg, holder = fake_xtquant
    result = qmt.get_account_snapshot(cfg)
    assert result["status"] == "ok"
    assert result["account"]["account_id"] == "123456"
    assert holder["trader"].calls[-1] == "stop"


def test_qmt_rejects_account_identity_mismatch(fake_xtquant):
    cfg, holder = fake_xtquant

    class WrongAccountTrader(_FakeTrader):
        def query_stock_asset(self, account):
            return SimpleNamespace(account_id="different", account_type="STOCK")

    def wrong_trader(path, session_id):
        trader = WrongAccountTrader(path, session_id)
        holder["trader"] = trader
        return trader

    deps = qmt._require_xtquant()
    deps.XtQuantTrader = wrong_trader
    result = qmt.get_positions(cfg)
    assert result["status"] == "error"
    assert "mismatch" in result["error"]


def test_qmt_paper_order_maps_xtquant_constants(fake_xtquant):
    cfg, holder = fake_xtquant
    result = qmt.place_order(cfg, symbol="600000.SH", side="buy", quantity=200, order_type="limit", limit_price=10.5)
    assert result["status"] == "ok"
    assert result["order_id"] == 19
    call = next(call for call in holder["trader"].calls if call[0] == "order_stock")
    assert call[1][1:] == ("600000.SH", 1, 200, 3, 10.5, "vibe-trading", "vibe-trading")


def test_qmt_readonly_profile_refuses_paper_order_before_session(tmp_path):
    cfg = qmt.QMTConfig(userdata_mini=str(tmp_path), account_id="abc", profile="paper", readonly=True)
    result = qmt.place_order(cfg, symbol="600000.SH", side="buy", quantity=100)
    assert result["status"] == "error"
    assert "read-only" in result["error"]


def test_qmt_live_order_refuses_before_session(tmp_path):
    cfg = qmt.QMTConfig(userdata_mini=str(tmp_path), account_id="abc", profile="live-readonly", readonly=True)
    result = qmt.place_order(cfg, symbol="600000.SH", side="buy", quantity=100)
    assert result["status"] == "error"
    assert "disabled" in result["error"]


def test_qmt_symbol_normalization():
    assert qmt._normalize_symbol("SH.600000") == "600000.SH"
    assert qmt._normalize_symbol("600000") == "600000.SH"
    assert qmt._normalize_symbol("000001") == "000001.SZ"
