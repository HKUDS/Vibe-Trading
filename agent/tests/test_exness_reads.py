"""Exness connector read-path tests (synthetic fixtures, injected transport)."""

from __future__ import annotations

from typing import Any

import pytest

from src.trading.connectors.exness import _client, _market
from src.trading.connectors.exness import sdk as exness_sdk
from src.trading.connectors.exness._client import ExnessClient
from tests.exness_fakes import ACCOUNT, FakeResponse, FakeTransport, discovery_route, make_config

pytestmark = pytest.mark.unit

_CFG_PATH = f"/v1/configuration/accounts/{ACCOUNT}"
_SNAPSHOT = f"/v1/trading/accounts/{ACCOUNT}/snapshot"
_CANDLES = f"/v1/market-data/accounts/{ACCOUNT}/candles"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(_client, "get_runtime_root", lambda: tmp_path)
    _client.reset_access_point_cache()
    _market.reset_caches()
    monkeypatch.setattr(_market, "_utc_now_iso", lambda: "2026-11-27T12:00:00+00:00")
    yield
    _client.set_client_factory(None)
    _market.reset_caches()


def _install(routes: dict[tuple[str, str], Any]) -> FakeTransport:
    transport = FakeTransport({**discovery_route(), **routes})
    _client.set_client_factory(lambda cfg: ExnessClient(cfg, transport=transport))
    return transport


def _conditions(name: str, base: str, quote: str, contract: str = "100000") -> FakeResponse:
    return FakeResponse(200, {
        "instrument": name, "base_currency": base, "quote_currency": quote, "contract_size": contract,
        "volume_min": "0.01", "volume_max": "200", "volume_step": "0.01", "point_digits": 5,
        "trade_mode": "enabled", "exec_mode": "market",
    })


def _last_candle(name: str, bid: float, ask: float) -> tuple[tuple[str, str], FakeResponse]:
    target = (f"{_CANDLES}?instrument={name}&timeframe=M1&price_type=both"
              f"&from=2026-11-27T12%3A00%3A00%2B00%3A00&count=-1")
    body = {"candles": [{"time": "2026-11-27T11:59:00+00:00", "bid": {"close": bid}, "ask": {"close": ask},
                         "volume": 10}]}
    return ("GET", target), FakeResponse(200, body)


_INSTRUMENTS = FakeResponse(200, {"instruments": ["EURUSD", "USDJPY", "XAUUSD", "EURGBP", "GBPUSD"]})


def _account_route() -> dict[tuple[str, str], FakeResponse]:
    return {("GET", f"{_CFG_PATH}/account"): FakeResponse(200, {
        "account_id": ACCOUNT, "account_name": "Standard", "create_date": "2024-03-14T11:46:30+00:00",
        "settings": {"currency": "USD", "leverage": "1:200", "trade_mode": "enabled",
                     "account_status": "active", "execution_mode": "market"},
    })}


# --- check_status -----------------------------------------------------------------


def test_check_status_reports_connected_account_without_secrets() -> None:
    _install(_account_route())
    report = exness_sdk.check_status(make_config())
    assert report["status"] == "ok"
    assert report["connection_state"] == "connected"
    assert report["account"]["currency"] == "USD"
    assert report["account"]["trade_mode"] == "enabled"
    assert report["environment"] == "live"
    assert "exnsk-synthetic-example" not in repr(report)


def test_check_status_missing_credentials_makes_no_request() -> None:
    transport = _install({})
    report = exness_sdk.check_status(make_config(api_key="", private_key="", account_id="", gateway_url=""))
    assert report["status"] == "error"
    assert report["error_code"] == "credentials_missing"
    assert transport.calls == []


def test_check_status_maps_permission_denied() -> None:
    _install({("GET", f"{_CFG_PATH}/account"): FakeResponse(
        403, {"code": 1002, "error_message": "AUTH_PERMISSION_DENIED"})})
    report = exness_sdk.check_status(make_config())
    assert report["status"] == "error"
    assert report["error_code"] == "auth_permission_denied"


def test_check_status_invalid_signature_maps_to_auth_failed() -> None:
    _install({("GET", f"{_CFG_PATH}/account"): FakeResponse(
        401, {"code": 1001, "error_message": "AUTH_INVALID_SIGNATURE"})})
    assert exness_sdk.check_status(make_config())["error_code"] == "auth_failed"


# --- account / positions / orders -----------------------------------------------------


def _snapshot(positions: list[dict[str, Any]], orders: list[dict[str, Any]] | None = None) -> FakeResponse:
    return FakeResponse(200, {
        "orders": orders or [],
        "positions": positions,
        "account_state": {"balance": "10000.00", "equity": "10050.00", "used_margin": "100.00"},
    })


def test_account_snapshot_parses_decimal_strings_and_currency() -> None:
    _install({("GET", _SNAPSHOT): _snapshot([]), **_account_route()})
    result = exness_sdk.get_account_snapshot(make_config())
    account = result["account"]
    assert result["status"] == "ok"
    assert account["equity"] == 10050.0
    assert account["margin_free"] == 9950.0
    assert account["currency"] == "USD"


def test_positions_carry_usd_market_value_for_quote_usd_pair() -> None:
    position = {"position_id": "2001", "direction": "buy", "instrument": "EURUSD", "volume": "0.10",
                "open_price": "1.0800", "state": "open", "create_time": "2026-11-27T10:00:00+00:00"}
    key, candle = _last_candle("EURUSD", 1.1000, 1.1002)
    _install({("GET", _SNAPSHOT): _snapshot([position]),
              ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions("EURUSD", "EUR", "USD"),
              key: candle})
    rows = exness_sdk.get_positions(make_config())["positions"]
    assert rows[0]["symbol"] == "EURUSD"
    assert rows[0]["side"] == "buy"
    assert rows[0]["quantity"] == 0.10
    assert rows[0]["position_id"] == "2001"
    assert rows[0]["market_value"] == pytest.approx(0.10 * 100000 * 1.1001)


def test_positions_base_usd_pair_is_exact_without_quote() -> None:
    position = {"position_id": "1", "direction": "sell", "instrument": "USDJPY", "volume": "1",
                "state": "open", "create_time": "x"}
    _install({("GET", _SNAPSHOT): _snapshot([position]),
              ("GET", f"{_CFG_PATH}/instruments/USDJPY/conditions"): _conditions("USDJPY", "USD", "JPY")})
    row = exness_sdk.get_positions(make_config())["positions"][0]
    assert row["side"] == "sell"
    assert row["market_value"] == pytest.approx(100000.0)


def test_unpriceable_position_reports_none_market_value() -> None:
    position = {"position_id": "1", "direction": "buy", "instrument": "EURGBP", "volume": "1",
                "state": "open", "create_time": "x"}
    _install({("GET", _SNAPSHOT): _snapshot([position]),
              ("GET", f"{_CFG_PATH}/instruments/EURGBP/conditions"): _conditions("EURGBP", "EUR", "GBP"),
              ("GET", f"{_CFG_PATH}/instruments"): FakeResponse(200, {"instruments": ["EURGBP"]})})
    assert exness_sdk.get_positions(make_config())["positions"][0]["market_value"] is None


def test_open_orders_lists_pending_orders() -> None:
    order = {"order_id": "1001", "order_type": "limit", "state": "placed", "direction": "buy",
             "instrument": "EURUSD", "price": "1.0800", "volume": "1.0", "create_time": "t"}
    _install({("GET", _SNAPSHOT): _snapshot([], [order])})
    result = exness_sdk.get_open_orders(make_config())
    assert result["open_orders"][0]["order_id"] == "1001"
    assert result["open_orders"][0]["side"] == "buy"
    assert result["open_orders"][0]["limit_price"] == 1.08
    assert "executions" not in result


def test_open_orders_with_executions_follows_deal_cursors() -> None:
    deals = f"/v1/history/accounts/{ACCOUNT}/deals"
    first = (f"{deals}?from=2026-11-20T12%3A00%3A00%2B00%3A00&limit=200")
    second = f"{deals}?cursor=abc&limit=200"
    deal = {"deal_id": "1", "order_id": "2", "position_id": "3", "type": "open", "direction": "buy",
            "instrument": "EURUSD", "volume": "0.1", "price": "1.1", "create_time": "t",
            "profit": {"amount": "0", "currency": "USD"}}
    _install({("GET", _SNAPSHOT): _snapshot([]),
              ("GET", first): FakeResponse(200, {"items": [{"event_time": "t", "deal": deal}],
                                                 "next_cursor": "abc", "has_more": True}),
              ("GET", second): FakeResponse(200, {"items": [{"event_time": "t", "deal": {**deal, "deal_id": "4"}}],
                                                  "has_more": False})})
    result = exness_sdk.get_open_orders(make_config(), include_executions=True)
    assert [e["deal_id"] for e in result["executions"]] == ["1", "4"]


# --- quotes / bars / search ----------------------------------------------------------------


def test_quote_is_rounded_to_instrument_point_digits() -> None:
    # Exness serializes some prices with binary-float noise (seen live: 1.0971700000000002).
    key, candle = _last_candle("EURUSD", 1.0971700000000002, 1.0973800000000002)
    _install({("GET", f"{_CFG_PATH}/instruments"): _INSTRUMENTS, key: candle,
              ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions("EURUSD", "EUR", "USD")})
    quote = exness_sdk.get_quote("EURUSD", config=make_config())["quote"]
    assert quote["bid"] == 1.09717
    assert quote["ask"] == 1.09738
    assert repr(quote["bid"]) == "1.09717"


def test_quote_comes_from_latest_bid_ask_candle_and_is_labelled() -> None:
    key, candle = _last_candle("EURUSD", 1.1000, 1.1002)
    _install({("GET", f"{_CFG_PATH}/instruments"): _INSTRUMENTS, key: candle,
              ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions("EURUSD", "EUR", "USD")})
    result = exness_sdk.get_quote("EUR/USD", config=make_config())
    assert result["status"] == "ok"
    assert result["resolved_symbol"] == "EURUSD"
    assert result["quote"]["bid"] == 1.1 and result["quote"]["ask"] == 1.1002
    assert result["quote"]["quote_source"] == "candle"
    assert "last" not in result["quote"]


def test_latest_quote_is_reused_briefly_to_respect_the_candle_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    key, candle = _last_candle("EURUSD", 1.1000, 1.1002)
    transport = _install({key: candle})
    clock = [100.0]
    monkeypatch.setattr(_market.time, "monotonic", lambda: clock[0])
    client = _client.make_client(make_config())
    first = _market.latest_bid_ask(client, "EURUSD")
    clock[0] += 1.0
    assert _market.latest_bid_ask(client, "EURUSD") == first
    assert transport.targets().count(key[1]) == 1
    clock[0] += _market.QUOTE_CACHE_SECONDS + 0.1
    _market.latest_bid_ask(client, "EURUSD")
    assert transport.targets().count(key[1]) == 2


def test_unknown_symbol_is_an_error_not_a_guess() -> None:
    _install({("GET", f"{_CFG_PATH}/instruments"): _INSTRUMENTS})
    result = exness_sdk.get_quote("AAPL", config=make_config())
    assert result["status"] == "error"
    assert "AAPL" in result["error"]


def test_historical_bars_page_backwards_within_candle_limit() -> None:
    limits = FakeResponse(200, {"limits": {"rest": {"global_account_rate": {}, "methods": [
        {"api_operation_id": "getCandleHistory", "http_method": "GET", "path": "x",
         "rate_limit": {"limit": 10, "window_seconds": 1}, "limits": {"max_candles_per_request": 2}}]},
        "websocket": {}}})
    base = f"{_CANDLES}?instrument=EURUSD&timeframe=D1&price_type=bid"
    page1 = f"{base}&from=2026-11-27T12%3A00%3A00%2B00%3A00&count=-2"
    page2 = f"{base}&from=2026-11-25T00%3A00%3A00%2B00%3A00&count=-1"
    _install({
        ("GET", f"{_CFG_PATH}/instruments"): _INSTRUMENTS,
        ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions("EURUSD", "EUR", "USD"),
        ("GET", f"{_CFG_PATH}/limits"): limits,
        ("GET", page1): FakeResponse(200, {"candles": [
            {"time": "2026-11-25T00:00:00+00:00", "open": 1.0000000000000002, "high": 2, "low": 0.5, "close": 1.5,
             "volume": 3},
            {"time": "2026-11-26T00:00:00+00:00", "open": 1.5, "high": 2, "low": 1, "close": 1.8, "volume": 4}]}),
        ("GET", page2): FakeResponse(200, {"candles": [
            {"time": "2026-11-24T00:00:00+00:00", "open": 0.9, "high": 1.1, "low": 0.8, "close": 1, "volume": 2}]}),
    })
    result = exness_sdk.get_historical_bars("EURUSD", config=make_config(), period="1d", limit=3)
    assert result["status"] == "ok"
    assert [b["time"] for b in result["bars"]] == [
        "2026-11-24T00:00:00+00:00", "2026-11-25T00:00:00+00:00", "2026-11-26T00:00:00+00:00"]
    assert result["bars"][0] == {"time": "2026-11-24T00:00:00+00:00", "open": 0.9, "high": 1.1, "low": 0.8,
                                 "close": 1.0, "volume": 2.0}
    assert result["timeframe"] == "D1"
    assert result["bars"][1]["open"] == 1.0  # float noise rounded away at point_digits


def test_unknown_point_digits_leave_prices_unrounded() -> None:
    key, candle = _last_candle("EURUSD", 1.0971700000000002, 1.0973800000000002)
    _install({("GET", f"{_CFG_PATH}/instruments"): _INSTRUMENTS, key: candle,
              ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): FakeResponse(200, {"instrument": "EURUSD"})})
    assert exness_sdk.get_quote("EURUSD", config=make_config())["quote"]["bid"] == 1.0971700000000002


def test_unsupported_period_is_refused() -> None:
    _install({})
    result = exness_sdk.get_historical_bars("EURUSD", config=make_config(), period="7m")
    assert result["status"] == "error"


def test_search_instruments_filters_catalog() -> None:
    _install({("GET", f"{_CFG_PATH}/instruments"): _INSTRUMENTS})
    result = exness_sdk.search_instruments("usd", config=make_config(), limit=2)
    assert result["status"] == "ok"
    assert len(result["instruments"]) == 2
    first = result["instruments"][0]
    assert first["native_symbol"] in {"EURUSD", "USDJPY", "XAUUSD", "GBPUSD"}
    assert first["exchange"] == "Exness"
