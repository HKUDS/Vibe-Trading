"""Exness connector order-path tests: validation, sizing, guards, async status."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.trading.connectors.exness import _client, _market, orders
from src.trading.connectors.exness import sdk as exness_sdk
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
    yield
    _client.set_client_factory(None)
    _market.reset_caches()


def _trade_cfg(**overrides: Any):
    # 0.1 lot EURUSD ≈ $11k, above the $10k default guard; widen it for flow tests.
    return make_config(**{"profile": "live", "max_order_notional_usd": 50_000, **overrides})


def _conditions(**overrides: Any) -> FakeResponse:
    body = {"instrument": "EURUSD", "base_currency": "EUR", "quote_currency": "USD", "contract_size": "100000",
            "volume_min": "0.01", "volume_max": "50", "volume_step": "0.01", "point_digits": 5,
            "trade_mode": "enabled", "exec_mode": "market"}
    body.update(overrides)
    return FakeResponse(200, body)


def _base_routes(**cond: Any) -> dict[tuple[str, str], Any]:
    return {
        **discovery_route(),
        ("GET", f"{_CFG_PATH}/instruments"): FakeResponse(200, {"instruments": ["EURUSD", "XAUUSD"]}),
        ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions(**cond),
        ("GET", _CANDLE): FakeResponse(200, {"candles": [
            {"time": "t", "bid": {"close": 1.1000}, "ask": {"close": 1.1002}, "volume": 1}]}),
    }


def _install(routes: dict[tuple[str, str], Any]) -> FakeTransport:
    transport = FakeTransport(routes)
    _client.set_client_factory(lambda cfg: ExnessClient(cfg, transport=transport))
    return transport


def _accepted(op: str = "77") -> FakeResponse:
    return FakeResponse(202, {"operation_id": op, "client_request_id": "x", "status": "accepted"})


def _op(status: str, **extra: Any) -> FakeResponse:
    return FakeResponse(200, {"operation_id": "77", "status": status, "created_at": "t", "updated_at": "t", **extra})


# --- validation (no network) -------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"side": "hold", "quantity": 0.1}, "side"),
        ({"side": "buy", "quantity": 0.1, "order_type": "stop"}, "order_type"),
        ({"side": "buy"}, "exactly one"),
        ({"side": "buy", "quantity": 0.1, "notional": 100}, "exactly one"),
        ({"side": "buy", "quantity": 0.1, "order_type": "limit"}, "limit_price"),
        ({"side": "buy", "quantity": 0.1, "order_type": "limit", "limit_price": 1.1}, "gtc"),
        ({"side": "buy", "quantity": -1}, "positive"),
        ({"side": "buy", "quantity": float("nan")}, "positive"),
    ],
)
def test_invalid_orders_fail_closed_before_any_request(kwargs: dict[str, Any], message: str) -> None:
    transport = _install({})
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", **kwargs)
    assert result["status"] == "error"
    assert message in result["error"]
    assert transport.calls == []


def test_readonly_profile_refuses_orders_without_network() -> None:
    transport = _install({})
    result = orders.place_order(make_config(profile="live-readonly"), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "error"
    assert "read-only" in result["error"]
    assert orders.cancel_order(make_config(profile="live-readonly"), "1")["status"] == "error"
    assert transport.calls == []


# --- market orders + async status --------------------------------------------------------


def test_market_order_posts_position_and_confirms() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/positions")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("confirmed")
    transport = _install(routes)
    result = orders.place_order(_trade_cfg(), symbol="EUR/USD", side="buy", quantity=0.1)
    assert result["status"] == "ok", result
    assert result["order_state"] == "confirmed"
    assert result["operation_id"] == "77"
    assert result["resolved_symbol"] == "EURUSD"
    post = next(c for c in transport.calls if c["method"] == "POST")
    assert json.loads(post["data"]) == {"instrument": "EURUSD", "side": "buy", "volume": "0.1",
                                        "comment": "vibe-trading"}
    assert post["headers"]["EXN-IDEMPOTENCY-KEY"] == result["client_order_id"]
    assert result["client_order_id"].startswith("vt-")


def test_rejected_operation_is_an_error_with_broker_reason() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/positions")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op(
        "rejected", error_code=5006, error_message="TRADING_RULE_INSUFFICIENT_MARGIN")
    result = (_install(routes), orders.place_order(_trade_cfg(), symbol="EURUSD", side="sell", quantity=0.1))[1]
    assert result["status"] == "error"
    assert "TRADING_RULE_INSUFFICIENT_MARGIN" in result["error"]
    assert result["operation_id"] == "77"


def test_unconfirmed_operation_is_ok_pending_never_resubmitted() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/positions")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("pending")
    transport = _install(routes)
    result = orders.place_order(_trade_cfg(operation_wait_seconds=1), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "ok"
    assert result["order_state"] == "pending"
    assert "operation_id" in result["warning"]
    assert len(transport.targets("POST")) == 1


def test_post_failure_is_error_and_never_retried() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/positions")] = FakeResponse(
        503, {"code": 2, "error_message": "SYSTEM_TEMPORARY_UNAVAILABLE"})
    transport = _install(routes)
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "error"
    assert len(transport.targets("POST")) == 1
    assert result["client_order_id"].startswith("vt-")


# --- instant execution ----------------------------------------------------------------------


def _instant_routes(candle_time: str = "2026-11-27T11:59:00+00:00", candles: list | None = None,
                    bid: float = 1.0971700000000002, ask: float = 1.0973800000000002) -> dict:
    routes = _base_routes(exec_mode="instant")
    body = {"candles": candles if candles is not None else [
        {"time": candle_time, "bid": {"close": bid}, "ask": {"close": ask}, "volume": 1}]}
    routes[("GET", _CANDLE)] = FakeResponse(200, body)
    routes[("POST", f"{_TRADING}/positions")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("confirmed")
    return routes


def _posted(transport: FakeTransport) -> dict[str, Any]:
    return json.loads(next(c for c in transport.calls if c["method"] == "POST")["data"])


def test_instant_buy_requests_latest_ask_with_configured_deviation() -> None:
    transport = _install(_instant_routes())
    result = orders.place_order(_trade_cfg(deviation_points=15), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "ok", result
    assert _posted(transport) == {"instrument": "EURUSD", "side": "buy", "volume": "0.1", "price": "1.09738",
                                  "deviation": "15", "comment": "vibe-trading"}
    assert result["requested_price"] == 1.09738
    assert result["deviation_points"] == 15


def test_instant_sell_requests_latest_bid_with_default_deviation() -> None:
    transport = _install(_instant_routes())
    orders.place_order(_trade_cfg(), symbol="EURUSD", side="sell", quantity=0.1)
    body = _posted(transport)
    assert body["price"] == "1.09717"
    assert body["deviation"] == "10"


@pytest.mark.parametrize("candles", [[], None])
def test_instant_order_without_a_quote_is_refused(candles: list | None) -> None:
    routes = _instant_routes(candles=[] if candles == [] else [
        {"time": "2026-11-27T11:59:00+00:00", "bid": {}, "ask": {}, "volume": 1}])
    transport = _install(routes)
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "error"
    assert transport.targets("POST") == []


def test_instant_order_on_a_stale_quote_is_refused() -> None:
    transport = _install(_instant_routes(candle_time="2026-11-27T11:50:00+00:00"))
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "error"
    assert "stale" in result["error"]
    assert transport.targets("POST") == []


def test_requote_rejection_explains_deviation() -> None:
    routes = _instant_routes()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("rejected", error_code=6000, error_message="EXECUTION_REQUOTE")
    _install(routes)
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "error"
    assert "deviation_points" in result["error"]


@pytest.mark.parametrize("bad", [0, -1, 5000, "abc"])
def test_deviation_points_must_be_sane(bad: Any) -> None:
    from src.trading.connectors.exness._client import ExnessConfigError

    with pytest.raises(ExnessConfigError, match="deviation_points"):
        make_config(deviation_points=bad)


def test_market_execution_orders_do_not_send_price() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/positions")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("confirmed")
    transport = _install(routes)
    orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.1)
    assert "price" not in _posted(transport) and "deviation" not in _posted(transport)


# --- limit orders -------------------------------------------------------------------------


def test_limit_order_posts_pending_order_with_point_digits() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/orders")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("confirmed")
    transport = _install(routes)
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.2, order_type="limit",
                                limit_price=1.095, time_in_force="gtc")
    assert result["status"] == "ok"
    body = json.loads(next(c for c in transport.calls if c["method"] == "POST")["data"])
    assert body == {"instrument": "EURUSD", "side": "buy", "type": "limit", "volume": "0.2", "price": "1.095",
                    "comment": "vibe-trading"}


def test_limit_price_with_too_many_decimals_is_refused() -> None:
    transport = _install(_base_routes())
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", quantity=0.1, order_type="limit",
                                limit_price=1.0950001, time_in_force="gtc")
    assert result["status"] == "error"
    assert "decimal" in result["error"]
    assert transport.targets("POST") == []


# --- sizing + guards --------------------------------------------------------------------------


@pytest.mark.parametrize("qty, message", [(0.005, "minimum"), (60, "maximum"), (0.015, "step")])
def test_volume_rules_from_conditions(qty: float, message: str) -> None:
    transport = _install(_base_routes())
    result = orders.place_order(_trade_cfg(max_order_volume=100), symbol="EURUSD", side="buy", quantity=qty)
    assert result["status"] == "error"
    assert message in result["error"]
    assert transport.targets("POST") == []


def test_connector_volume_guard() -> None:
    _install(_base_routes())
    result = orders.place_order(_trade_cfg(max_order_volume=0.05), symbol="EURUSD", side="buy", quantity=0.1)
    assert result["status"] == "error"
    assert "max_order_volume" in result["error"]


def test_connector_notional_guard() -> None:
    _install(_base_routes())
    result = orders.place_order(_trade_cfg(max_order_notional_usd=5000), symbol="EURUSD", side="buy",
                                quantity=0.1)
    assert result["status"] == "error"
    assert "max_order_notional_usd" in result["error"]


def test_notional_sizing_floors_to_volume_step() -> None:
    routes = _base_routes()
    routes[("POST", f"{_TRADING}/positions")] = _accepted()
    routes[("GET", f"{_TRADING}/operations/77")] = _op("confirmed")
    transport = _install(routes)
    # 1 lot ≈ $110,010 → $5,000 ≈ 0.04545 lots → floored to 0.04.
    result = orders.place_order(_trade_cfg(), symbol="EURUSD", side="buy", notional=5000)
    assert result["status"] == "ok"
    body = json.loads(next(c for c in transport.calls if c["method"] == "POST")["data"])
    assert body["volume"] == "0.04"


def test_quantity_notional_usd_hook_prices_lots() -> None:
    _install(_base_routes())
    value = exness_sdk.quantity_notional_usd(_trade_cfg(), "EURUSD", 0.5)
    assert value == pytest.approx(0.5 * 100000 * 1.1001)


def test_quantity_notional_usd_hook_fails_closed_to_none() -> None:
    _install({**discovery_route(), ("GET", f"{_CFG_PATH}/instruments"): FakeResponse(500, {"code": 3})})
    assert exness_sdk.quantity_notional_usd(_trade_cfg(), "EURUSD", 0.5) is None


# --- cancel / close -------------------------------------------------------------------------------


def _snapshot(orders_: list[dict[str, Any]], positions: list[dict[str, Any]]) -> FakeResponse:
    return FakeResponse(200, {"orders": orders_, "positions": positions,
                              "account_state": {"balance": "1", "equity": "1", "used_margin": "0"}})


def test_cancel_pending_order_deletes_order() -> None:
    routes = {**discovery_route(),
              ("GET", f"{_TRADING}/snapshot"): _snapshot([{"order_id": "1001", "order_type": "limit",
                                                          "state": "placed", "create_time": "t"}], []),
              ("DELETE", f"{_TRADING}/orders/1001"): _accepted(),
              ("GET", f"{_TRADING}/operations/77"): _op("confirmed")}
    transport = _install(routes)
    result = orders.cancel_order(_trade_cfg(), "1001")
    assert result["status"] == "ok"
    assert result["action"] == "order_cancelled"
    assert transport.calls[-2]["headers"]["EXN-IDEMPOTENCY-KEY"].startswith("vt-")


def test_cancel_with_position_id_closes_that_position_only() -> None:
    position = {"position_id": "2001", "direction": "buy", "instrument": "EURUSD", "volume": "0.10",
                "state": "open", "create_time": "t"}
    routes = {**discovery_route(),
              ("GET", f"{_TRADING}/snapshot"): _snapshot([], [position]),
              ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions(),
              ("DELETE", f"{_TRADING}/positions/2001"): _accepted(),
              ("GET", f"{_TRADING}/operations/77"): _op("confirmed")}
    transport = _install(routes)
    result = orders.cancel_order(_trade_cfg(), "2001")
    assert result["status"] == "ok"
    assert result["action"] == "position_closed"
    assert transport.targets("POST") == []


def test_cancel_unknown_id_is_error() -> None:
    _install({**discovery_route(), ("GET", f"{_TRADING}/snapshot"): _snapshot([], [])})
    assert orders.cancel_order(_trade_cfg(), "999")["status"] == "error"


def test_cancel_requires_numeric_id() -> None:
    transport = _install({})
    assert orders.cancel_order(_trade_cfg(), "../1")["status"] == "error"
    assert transport.calls == []


def test_partial_close_sends_volume_and_rejects_oversize() -> None:
    position = {"position_id": "2001", "direction": "buy", "instrument": "EURUSD", "volume": "0.10",
                "state": "open", "create_time": "t"}
    routes = {**discovery_route(),
              ("GET", f"{_TRADING}/snapshot"): _snapshot([], [position]),
              ("GET", f"{_CFG_PATH}/instruments/EURUSD/conditions"): _conditions(),
              ("DELETE", f"{_TRADING}/positions/2001?volume=0.05"): _accepted(),
              ("GET", f"{_TRADING}/operations/77"): _op("confirmed")}
    _install(routes)
    assert orders.close_position(_trade_cfg(), "2001", volume=0.05)["status"] == "ok"
    oversize = orders.close_position(_trade_cfg(), "2001", volume=0.5)
    assert oversize["status"] == "error"
    assert "exceeds" in oversize["error"]


def test_instant_close_sends_bid_for_a_buy_position_with_deviation() -> None:
    position = {"position_id": "2001", "direction": "buy", "instrument": "EURUSD", "volume": "0.10",
                "state": "open", "create_time": "t"}
    target = f"{_TRADING}/positions/2001?volume=0.05&price=1.09717&deviation=10"
    routes = {**_instant_routes(), ("GET", f"{_TRADING}/snapshot"): _snapshot([], [position]),
              ("DELETE", target): _accepted()}
    transport = _install(routes)
    assert orders.close_position(_trade_cfg(), "2001", volume=0.05)["status"] == "ok"
    assert transport.targets("DELETE") == [target]


def test_instant_close_without_fresh_quote_still_attempts_close() -> None:
    position = {"position_id": "2001", "direction": "sell", "instrument": "EURUSD", "volume": "0.10",
                "state": "open", "create_time": "t"}
    routes = {**_instant_routes(candle_time="2026-11-27T10:00:00+00:00"),
              ("GET", f"{_TRADING}/snapshot"): _snapshot([], [position]),
              ("DELETE", f"{_TRADING}/positions/2001"): _accepted()}
    transport = _install(routes)
    result = orders.cancel_order(_trade_cfg(), "2001")
    assert result["status"] == "ok"
    assert transport.targets("DELETE") == [f"{_TRADING}/positions/2001"]
