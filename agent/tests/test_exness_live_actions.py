"""Exness live-safety tests: real service → real mandate gate → real connector.

Only the HTTP transport is faked. These pin the bring-up checklist claims:
risk-increasing orders pass the mandate gate (instrument class, lot-aware USD
notional, kill switch) and are audited; cancels stay available while halted.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest

from src.live import registry
from src.live import sdk_order_gate as gate
from src.live.classification import ToolClass
from src.live.mandate.model import AssetClass, ConsentMeta, HardCaps, InstrumentType, Mandate, UniverseConstraint
from src.trading import profiles, service
from src.trading.connectors.exness import _client, _market, orders
from src.trading.connectors.exness._client import ExnessClient
from tests.exness_fakes import ACCOUNT, FakeResponse, FakeTransport, discovery_route, make_config

pytestmark = pytest.mark.unit

_CFG_PATH = f"/v1/configuration/accounts/{ACCOUNT}"
_TRADING = f"/v1/trading/accounts/{ACCOUNT}"
_CANDLE = (f"/v1/market-data/accounts/{ACCOUNT}/candles?instrument=EURUSD&timeframe=M1&price_type=both"
           f"&from=2026-11-27T12%3A00%3A00%2B00%3A00&count=-1")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(_client, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(_market, "_utc_now_iso", lambda: "2026-11-27T12:00:00+00:00")
    monkeypatch.setattr(orders, "_sleep", lambda _s: None)
    _client.reset_access_point_cache()
    _market.reset_caches()
    _client.save_config(make_config(profile="live", max_order_notional_usd=50_000))
    yield
    _client.set_client_factory(None)
    _market.reset_caches()


def _mandate(*, max_order_usd: float = 1_000_000.0, instruments=(InstrumentType.FOREX,)) -> Mandate:
    return Mandate(
        schema_version=1,
        hard_caps=HardCaps(
            account_funding_usd=1_000_000.0,
            max_order_notional_usd=max_order_usd,
            max_total_exposure_usd=1_000_000.0,
            max_leverage=2.0,
            allowed_instruments=instruments,
            max_trades_per_day=100,
        ),
        universe=UniverseConstraint(
            asset_classes=(AssetClass.FOREX,),
            min_market_cap_usd=None,
            min_avg_daily_volume_usd=None,
            exclude_symbols=(),
        ),
        consent=ConsentMeta(
            created_at="2026-01-01T00:00:00+00:00",
            consent_token_sha256="deadbeef",
            broker="exness",
            account_ref="acct-1",
            expires_at="2999-01-01T00:00:00+00:00",
        ),
    )


def _patch_gate(monkeypatch: pytest.MonkeyPatch, *, mandate: Mandate | None, halted: bool = False) -> list[Any]:
    audits: list[Any] = []
    monkeypatch.setattr(gate, "load_mandate", lambda broker: mandate)
    monkeypatch.setattr(gate, "halt_flag_set", lambda broker: halted)
    monkeypatch.setattr(gate, "write_live_action", lambda *a, **k: audits.append((a, k)) or {"audited": True})
    monkeypatch.setattr(gate, "read_daily_count", lambda broker: 0)
    monkeypatch.setattr(gate, "increment_daily_count", lambda broker: 1)
    monkeypatch.setattr(gate, "daily_order_lock", lambda broker: nullcontext())
    return audits


def _routes() -> dict[tuple[str, str], Any]:
    return {
        **discovery_route(),
        ("GET", f"{_CFG_PATH}/instruments"): FakeResponse(200, {"instruments": ["EURUSD", "XAUUSD"]}),
        ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): FakeResponse(200, {
            "instrument": "EURUSD", "base_currency": "EUR", "quote_currency": "USD", "contract_size": "100000",
            "volume_min": "0.01", "volume_max": "50", "volume_step": "0.01", "point_digits": 5,
            "trade_mode": "enabled", "exec_mode": "market"}),
        ("GET", _CANDLE): FakeResponse(200, {"candles": [
            {"time": "t", "bid": {"close": 1.1000}, "ask": {"close": 1.1002}, "volume": 1}]}),
        ("GET", f"{_CFG_PATH}/instruments/XAUUSD/conditions"): FakeResponse(200, {
            "instrument": "XAUUSD", "base_currency": "XAU", "quote_currency": "USD", "contract_size": "100",
            "volume_min": "0.01", "volume_max": "50", "volume_step": "0.01", "point_digits": 3,
            "trade_mode": "enabled", "exec_mode": "market"}),
        ("GET", _CANDLE.replace("EURUSD", "XAUUSD")): FakeResponse(200, {"candles": [
            {"time": "t", "bid": {"close": 2650.0}, "ask": {"close": 2650.4}, "volume": 1}]}),
        ("GET", f"{_TRADING}/snapshot"):FakeResponse(200, {
            "orders": [{"order_id": "1001", "order_type": "limit", "state": "placed", "create_time": "t"}],
            "positions": [],
            "account_state": {"balance": "10000", "equity": "10000", "used_margin": "0"}}),
        ("GET", f"{_CFG_PATH}/account"): FakeResponse(200, {"account_id": ACCOUNT, "create_date": "t",
                                                            "settings": {"currency": "USD"}}),
        ("POST", f"{_TRADING}/positions"): FakeResponse(202, {"operation_id": "77", "status": "accepted"}),
        ("DELETE", f"{_TRADING}/orders/1001"): FakeResponse(202, {"operation_id": "78", "status": "accepted"}),
        ("GET", f"{_TRADING}/operations/77"): FakeResponse(200, {"operation_id": "77", "status": "confirmed",
                                                                 "created_at": "t", "updated_at": "t"}),
        ("GET", f"{_TRADING}/operations/78"): FakeResponse(200, {"operation_id": "78", "status": "confirmed",
                                                                 "created_at": "t", "updated_at": "t"}),
    }


def _install() -> FakeTransport:
    transport = FakeTransport(_routes())
    _client.set_client_factory(lambda cfg: ExnessClient(cfg, transport=transport))
    return transport


def test_live_place_blocked_without_mandate(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, mandate=None)
    transport = _install()
    result = service.place_order("EURUSD", "exness-live-api-trade", side="buy", quantity=0.1)
    assert result["status"] == "blocked"
    assert result["reason"] == "no valid mandate on file"
    assert transport.targets("POST") == []


def test_kill_switch_blocks_live_place(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate(), halted=True)
    transport = _install()
    result = service.place_order("EURUSD", "exness-live-api-trade", side="buy", quantity=0.1)
    assert result["status"] == "blocked"
    assert result["reason"] == "live trading halted"
    assert transport.targets("POST") == []


def test_mandate_notional_cap_uses_lot_aware_usd_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    # 0.1 lot EURUSD ≈ $11,001 — a naive quantity × price would be ≈ $0.11 and pass.
    _patch_gate(monkeypatch, mandate=_mandate(max_order_usd=5_000.0))
    transport = _install()
    result = service.place_order("EURUSD", "exness-live-api-trade", side="buy", quantity=0.1)
    assert result["status"] == "blocked"
    assert result["breach"]["limit"] == "max_order_notional_usd"
    assert result["breach"]["attempted_value"] == pytest.approx(0.1 * 100_000 * 1.1001)
    assert transport.targets("POST") == []


def test_metal_cfd_needs_explicit_cfd_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    transport = _install()
    result = service.place_order("XAUUSD", "exness-live-api-trade", side="buy", quantity=0.01)
    assert result["status"] == "blocked"
    assert "could not be priced" not in result["reason"]  # priced fine; refused on instrument class
    assert "instrument" in result["reason"], result["reason"]
    assert transport.targets("POST") == []


def test_mandate_permitted_order_reaches_broker_and_is_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    audits = _patch_gate(monkeypatch, mandate=_mandate())
    transport = _install()
    result = service.place_order("EURUSD", "exness-live-api-trade", side="buy", quantity=0.1)
    assert result["status"] == "ok", result
    assert result["order_state"] == "confirmed"
    assert transport.targets("POST") == [f"{_TRADING}/positions"]
    assert audits, "live order must write an audit event"


def test_readonly_profile_cannot_place(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    transport = _install()
    result = service.place_order("EURUSD", "exness-live-api-readonly", side="buy", quantity=0.1)
    assert result["status"] != "ok"
    assert transport.targets("POST") == []


def test_cancel_stays_available_while_halted(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, mandate=None, halted=True)
    audited: list[Any] = []
    monkeypatch.setattr(service, "_audit_live_cancel", lambda *a, **k: audited.append(a))
    transport = _install()
    result = service.cancel_order("1001", "exness-live-api-trade")
    assert result["status"] == "ok", result
    assert transport.targets("DELETE") == [f"{_TRADING}/orders/1001"]
    assert audited


# --- registration -------------------------------------------------------------------


def test_profiles_registered_live_only_with_mandate_on_trade() -> None:
    exness = {p.id: p for p in profiles.list_profiles() if p.connector == "exness"}
    assert set(exness) == {"exness-live-api-readonly", "exness-live-api-trade"}
    assert all(p.environment == "live" and p.transport == "broker_sdk" for p in exness.values())
    assert exness["exness-live-api-readonly"].readonly is True
    assert "orders.place" not in exness["exness-live-api-trade"].capabilities
    assert "orders.place.requires_mandate" in exness["exness-live-api-trade"].capabilities


def test_curated_map_registered_and_unknown_ops_fail_closed() -> None:
    curated = registry._BROKER_CURATED_MAPS["exness"]
    assert curated["openPosition"] is ToolClass.WRITE
    assert curated["getTradingStateSnapshot"] is ToolClass.READ
    assert "someFutureOperation" not in curated


def test_order_classification_matches_mt5_naming() -> None:
    assert service._order_classification("exness", "EURUSD") == (InstrumentType.FOREX, AssetClass.FOREX)
    assert service._order_classification("exness", "XAUUSD") == (InstrumentType.CFD, None)


def test_service_resolves_exness_sdk_module() -> None:
    module = service._sdk_module("exness")
    assert hasattr(module, "quantity_notional_usd")
    assert service._allowed_override_keys(module) == frozenset({"operation_wait_seconds"})
