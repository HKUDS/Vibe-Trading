"""Tests for the opt-in TAP routing of Alpaca order placement.

When TAP is enabled, ``alpaca.sdk.place_order`` must route the order through the
TAP proxy (``tap_forward.forward``) instead of the broker SDK, map the upstream
response into the standard envelope, and fail closed on a denied/timed-out
order. When TAP is disabled, the connector keeps its existing direct-SDK path.

These tests mock ``tap_forward`` so they need no network, no approval, and no
``alpaca-py`` SDK.
"""

from __future__ import annotations

import json

import pytest

from src.trading.connectors.alpaca import sdk as al

pytestmark = pytest.mark.unit


def _paper_cfg() -> "al.AlpacaConfig":
    # No keys needed on the TAP path — placeholders are injected by TAP.
    return al.AlpacaConfig(profile="paper")


def _ok(body: str) -> dict:
    """A TAP forward result for an auto-approved read (GET) — 200 + JSON body."""
    return {"ok": True, "decision": "immediate", "status": 200, "body": body, "error": None}


def test_place_order_routes_through_tap_when_enabled(monkeypatch) -> None:
    captured: dict = {}

    def fake_forward(target, method, body, cred_headers, **_):
        captured["target"] = target
        captured["method"] = method
        captured["body"] = body
        captured["cred_headers"] = dict(cred_headers)
        return {
            "ok": True,
            "decision": "forwarded",
            "status": 200,
            "body": json.dumps({"id": "ord-123", "status": "pending_new", "filled_qty": "0"}),
            "error": None,
        }

    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward", fake_forward)

    result = al.place_order(
        _paper_cfg(),
        symbol="AAPL",
        side="buy",
        quantity=1,
        order_type="limit",
        limit_price=1,
        time_in_force="day",
    )

    # Envelope is mapped from the upstream response, marked as TAP-routed.
    assert result["status"] == "ok"
    assert result["order_id"] == "ord-123"
    assert result["order_status"] == "pending_new"
    assert result["via"] == "tap"

    # The request was aimed at Alpaca's orders endpoint via TAP, with the secret
    # referenced by placeholders (never a raw key) — not an Authorization header.
    assert captured["method"] == "POST"
    assert captured["target"].endswith("/v2/orders")
    assert captured["cred_headers"]["APCA-API-KEY-ID"] == "<CREDENTIAL:alpaca.key_id>"
    assert captured["cred_headers"]["APCA-API-SECRET-KEY"] == "<CREDENTIAL:alpaca.secret_key>"
    sent = json.loads(captured["body"])
    assert sent["symbol"] == "AAPL" and sent["side"] == "buy" and sent["qty"] == "1.0"
    assert sent["type"] == "limit" and sent["limit_price"] == "1.0"
    # Idempotency: the order carries a deterministic client_order_id so an
    # approval-race retry is deduplicated by the broker rather than double-placed.
    assert sent["client_order_id"].startswith("tap-")


def test_denied_order_is_blocked(monkeypatch) -> None:
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(
        al.tap_forward,
        "forward",
        lambda *a, **k: {"ok": False, "decision": "denied", "status": None,
                         "body": None, "error": "denied"},
    )

    result = al.place_order(
        _paper_cfg(), symbol="TSLA", side="buy", notional=10000, order_type="market"
    )

    # Fail closed: a denied order is an error and carries no order_id.
    assert result["status"] == "error"
    assert result["tap_decision"] == "denied"
    assert "order_id" not in result


def test_client_order_id_is_deterministic_for_idempotency(monkeypatch) -> None:
    """Same order content -> same client_order_id (so an approval-race retry is
    deduplicated by the broker); a changed field -> a different id (so a genuine
    second order is not accidentally blocked as a duplicate)."""
    ids: list[str] = []

    def fake_forward(target, method, body, cred_headers, **_):
        ids.append(json.loads(body)["client_order_id"])
        return {"ok": True, "decision": "forwarded", "status": 200,
                "body": json.dumps({"id": "ord", "status": "new"}), "error": None}

    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward", fake_forward)

    kw = dict(symbol="AAPL", side="buy", quantity=1, order_type="limit",
              limit_price=1, time_in_force="day")
    al.place_order(_paper_cfg(), **kw)                       # first submit
    al.place_order(_paper_cfg(), **kw)                       # identical retry
    al.place_order(_paper_cfg(), **{**kw, "quantity": 2})    # genuinely different

    assert ids[0] == ids[1]                       # retry -> broker dedups it
    assert ids[2] != ids[0]                       # different order -> new id
    assert all(i.startswith("tap-") for i in ids)


def test_tap_credential_name_is_overridable(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward",
                        lambda target, method, body, cred_headers, **_: captured.update(
                            cred_headers=dict(cred_headers)) or {
                            "ok": True, "decision": "forwarded", "status": 200,
                            "body": json.dumps({"id": "x", "status": "new"}), "error": None})
    monkeypatch.setenv("TAP_ALPACA_CREDENTIAL", "alpaca-paper")

    al.place_order(_paper_cfg(), symbol="AAPL", side="buy", quantity=1)

    assert captured["cred_headers"]["APCA-API-KEY-ID"] == "<CREDENTIAL:alpaca-paper.key_id>"


def test_tap_disabled_does_not_route_through_tap(monkeypatch) -> None:
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: False)

    def boom(*a, **k):  # forward must never be called when TAP is off
        raise AssertionError("tap_forward.forward called while TAP disabled")

    monkeypatch.setattr(al.tap_forward, "forward", boom)

    # With TAP off and no alpaca-py SDK available, the connector takes its
    # direct-SDK path and reports the missing dependency — never via=tap.
    result = al.place_order(_paper_cfg(), symbol="AAPL", side="buy", quantity=1)

    assert result.get("via") != "tap"


# --------------------------------------------------------------------------- #
# M1b: reads routed through TAP (credential isolation — a read is a GET, which
# TAP auto-approves, so there is no human gate; the process just holds no key).
# Trading reads reuse the SDK field names; the market-data API abbreviates keys,
# so quote/bars are aliased back before mapping.
# --------------------------------------------------------------------------- #


def _enable_tap(monkeypatch, fake_forward) -> None:
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward", fake_forward)


def test_get_account_snapshot_routes_through_tap(monkeypatch) -> None:
    captured: dict = {}

    def fake_forward(target, method, body, cred_headers, **_):
        captured.update(target=target, method=method, cred_headers=dict(cred_headers))
        return _ok(json.dumps({
            "account_number": "PA123", "status": "ACTIVE", "currency": "USD",
            "cash": "1000", "equity": "1500", "buying_power": "3000",
            "portfolio_value": "1500", "pattern_day_trader": False, "trading_blocked": False,
        }))

    _enable_tap(monkeypatch, fake_forward)
    result = al.get_account_snapshot(_paper_cfg())

    assert captured["method"] == "GET"
    assert captured["target"] == "https://paper-api.alpaca.markets/v2/account"
    # Secret referenced by placeholder only — never a raw key on the wire.
    assert captured["cred_headers"]["APCA-API-KEY-ID"] == "<CREDENTIAL:alpaca.key_id>"
    assert captured["cred_headers"]["APCA-API-SECRET-KEY"] == "<CREDENTIAL:alpaca.secret_key>"
    assert result["account"]["account_number"] == "PA123"
    assert result["account"]["equity"] == "1500"


def test_get_positions_routes_through_tap(monkeypatch) -> None:
    captured: dict = {}

    def fake_forward(target, method, body, cred_headers, **_):
        captured.update(target=target, method=method)
        return _ok(json.dumps([{
            "symbol": "AAPL", "side": "long", "qty": "10", "avg_entry_price": "100",
            "market_value": "1100", "current_price": "110", "unrealized_pl": "100",
            "cost_basis": "1000",
        }]))

    _enable_tap(monkeypatch, fake_forward)
    result = al.get_positions(_paper_cfg())

    assert captured["method"] == "GET"
    assert captured["target"] == "https://paper-api.alpaca.markets/v2/positions"
    row = result["positions"][0]
    assert row["symbol"] == "AAPL"
    assert row["quantity"] == "10"          # qty -> quantity
    assert row["unrealized_pnl"] == "100"   # unrealized_pl -> unrealized_pnl


def test_get_open_orders_routes_through_tap(monkeypatch) -> None:
    calls: list = []

    def fake_forward(target, method, body, cred_headers, **_):
        calls.append(target)
        if "status=open" in target:
            return _ok(json.dumps([{
                "id": "o1", "symbol": "AAPL", "side": "buy", "type": "limit",
                "qty": "1", "limit_price": "10", "status": "new", "submitted_at": "t",
            }]))
        return _ok(json.dumps([
            {"id": "o2", "symbol": "TSLA", "side": "sell", "type": "market",
             "qty": "2", "filled_qty": "2", "status": "filled", "submitted_at": "t"},
            {"id": "o3", "symbol": "MSFT", "side": "buy", "type": "market",
             "qty": "1", "filled_qty": None, "status": "canceled", "submitted_at": "t"},
        ]))

    _enable_tap(monkeypatch, fake_forward)
    result = al.get_open_orders(_paper_cfg(), include_executions=True)

    assert all(t.startswith("https://paper-api.alpaca.markets/v2/orders?status=") for t in calls)
    assert any("status=open" in t for t in calls)
    assert any("status=closed" in t for t in calls)
    assert result["open_orders"][0]["order_id"] == "o1"
    # Only filled orders count as executions (o3 has no filled_qty).
    assert [e["order_id"] for e in result["executions"]] == ["o2"]


def test_get_quote_routes_through_tap_and_normalizes_keys(monkeypatch) -> None:
    captured: dict = {}

    def fake_forward(target, method, body, cred_headers, **_):
        captured.update(target=target, method=method)
        # Market-data REST abbreviates: bp/ap/bs/as/t (the SDK exposes full names).
        return _ok(json.dumps({
            "symbol": "AAPL",
            "quote": {"bp": 100.0, "ap": 100.5, "bs": 3, "as": 4, "t": "2026-01-01T00:00:00Z"},
        }))

    _enable_tap(monkeypatch, fake_forward)
    result = al.get_quote("aapl", config=_paper_cfg())

    assert captured["method"] == "GET"
    assert captured["target"].startswith("https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest")
    assert "feed=iex" in captured["target"]
    q = result["quote"]
    assert q["bid"] == 100.0    # bp -> bid_price -> bid
    assert q["ask"] == 100.5    # ap -> ask_price -> ask
    assert q["bid_size"] == 3
    assert q["ask_size"] == 4


def test_get_historical_bars_routes_through_tap_and_normalizes_keys(monkeypatch) -> None:
    captured: dict = {}

    def fake_forward(target, method, body, cred_headers, **_):
        captured.update(target=target, method=method)
        return _ok(json.dumps({
            "symbol": "AAPL",
            "bars": [{"t": "2026-01-01T00:00:00Z", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 1000}],
        }))

    _enable_tap(monkeypatch, fake_forward)
    result = al.get_historical_bars("aapl", config=_paper_cfg(), period="1d", limit=5)

    assert captured["target"].startswith("https://data.alpaca.markets/v2/stocks/AAPL/bars")
    assert "timeframe=1Day" in captured["target"]
    assert "limit=5" in captured["target"]
    bar = result["bars"][0]
    assert bar["open"] == 1.0     # o -> open
    assert bar["high"] == 2.0
    assert bar["low"] == 0.5
    assert bar["close"] == 1.5    # c -> close
    assert bar["volume"] == 1000  # v -> volume


def test_read_fails_closed_when_tap_errors(monkeypatch) -> None:
    # A host-pin rejection / TAP error must not silently yield empty data — the
    # read raises, mirroring the SDK path raising on an API error.
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(
        al.tap_forward, "forward",
        lambda *a, **k: {"ok": False, "decision": "error", "status": 403,
                         "body": None, "error": "host not allowed"},
    )
    with pytest.raises(RuntimeError):
        al.get_positions(_paper_cfg())


def test_reads_do_not_route_through_tap_when_disabled(monkeypatch) -> None:
    # TAP off: the read must take the direct-SDK path and never call forward.
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: False)

    def boom(*a, **k):
        raise AssertionError("tap_forward.forward called while TAP disabled")

    monkeypatch.setattr(al.tap_forward, "forward", boom)

    class _FakeClient:
        def get_all_positions(self):
            return [{"symbol": "NVDA", "side": "long", "qty": "1", "avg_entry_price": "1",
                     "market_value": "1", "current_price": "1", "unrealized_pl": "0", "cost_basis": "1"}]

    monkeypatch.setattr(al, "_trading_client", lambda cfg: _FakeClient())
    result = al.get_positions(_paper_cfg())

    assert result["positions"][0]["symbol"] == "NVDA"   # came from the SDK path


# --------------------------------------------------------------------------- #
# M1b: cancel routed through TAP (a write — human-approved, not auto-approved).
# --------------------------------------------------------------------------- #


def test_cancel_order_routes_through_tap(monkeypatch) -> None:
    captured: dict = {}

    def fake_forward(target, method, body, cred_headers, **_):
        captured.update(target=target, method=method, cred_headers=dict(cred_headers))
        # A cancel is a write: TAP forwards after approval; Alpaca returns 204.
        return {"ok": True, "decision": "forwarded", "status": 204, "body": None, "error": None}

    _enable_tap(monkeypatch, fake_forward)
    result = al.cancel_order(_paper_cfg(), order_id="ord-1", symbol="aapl")

    assert captured["method"] == "DELETE"
    assert captured["target"] == "https://paper-api.alpaca.markets/v2/orders/ord-1"
    assert captured["cred_headers"]["APCA-API-SECRET-KEY"] == "<CREDENTIAL:alpaca.secret_key>"
    assert result["status"] == "ok"
    assert result["cancelled"] is True
    assert result["via"] == "tap"
    assert result["symbol"] == "AAPL"


def test_denied_cancel_is_blocked(monkeypatch) -> None:
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(
        al.tap_forward, "forward",
        lambda *a, **k: {"ok": False, "decision": "denied", "status": None,
                         "body": None, "error": None},
    )
    result = al.cancel_order(_paper_cfg(), order_id="ord-1")

    # Fail closed: a denied cancel is an error and did not cancel anything.
    assert result["status"] == "error"
    assert result["tap_decision"] == "denied"
    assert result.get("cancelled") is not True


# --------------------------------------------------------------------------- #
# Red line: the live mandate gate strictly precedes TAP. TAP is transport under
# `connector.place_order`; a mandate DENY must block the order with
# `tap_forward.forward` never called, and an ALLOW must route it through TAP.
# These run the REAL alpaca connector module through the REAL gate.
# --------------------------------------------------------------------------- #

from src.live import sdk_order_gate as gate  # noqa: E402
from tests.test_sdk_order_gate import _intent, _mandate, _patch_gate  # noqa: E402


def test_live_mandate_deny_blocks_before_any_tap_call(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward",
                        lambda *a, **k: calls.append(a) or {"ok": False})
    _patch_gate(monkeypatch, mandate=None)  # no valid mandate on file → DENY

    out = gate.execute_live_order(
        broker="alpaca",
        connector_module=al,
        config=al.AlpacaConfig(profile="live"),
        intent=_intent(notional=500.0),
        place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0,
                      "order_type": "market"},
    )

    assert out["status"] == "blocked" and out["decision"] == "deny"
    assert calls == []  # nothing — not even a read — reached TAP


def test_live_mandate_halt_blocks_before_any_tap_call(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward",
                        lambda *a, **k: calls.append(a) or {"ok": False})
    _patch_gate(monkeypatch, mandate=_mandate(), halted=True)  # kill switch tripped

    out = gate.execute_live_order(
        broker="alpaca",
        connector_module=al,
        config=al.AlpacaConfig(profile="live"),
        intent=_intent(notional=500.0),
        place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0,
                      "order_type": "market"},
    )

    assert out["status"] == "blocked"
    assert calls == []


def test_live_mandate_allow_routes_order_through_tap(monkeypatch) -> None:
    order_posts: list[str] = []

    def fake_forward(target, method, body, cred_headers, **_):
        if method == "GET" and target.endswith("/v2/positions"):
            return _ok(json.dumps([]))
        if method == "GET" and target.endswith("/v2/account"):
            return _ok(json.dumps({
                "account_number": "LA123", "status": "ACTIVE", "currency": "USD",
                "cash": "100000", "equity": "100000", "buying_power": "200000",
                "portfolio_value": "100000", "pattern_day_trader": False,
                "trading_blocked": False,
            }))
        assert method == "POST" and target.endswith("/v2/orders")
        order_posts.append(target)
        return {"ok": True, "decision": "forwarded", "status": 200,
                "body": json.dumps({"id": "ord-live-1", "status": "accepted"}),
                "error": None}

    monkeypatch.setattr(al.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(al.tap_forward, "forward", fake_forward)
    _patch_gate(monkeypatch, mandate=_mandate())  # in-bounds → ALLOW

    out = gate.execute_live_order(
        broker="alpaca",
        connector_module=al,
        config=al.AlpacaConfig(profile="live"),
        intent=_intent(notional=500.0),
        place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0,
                      "order_type": "market"},
    )

    # Same gate, same ordering — the ALLOW went out through TAP, to the live host.
    assert out["status"] == "ok"
    assert out["via"] == "tap"
    assert out["order_id"] == "ord-live-1"
    assert "live_action" in out  # the gate audited the allowed order
    assert order_posts == ["https://api.alpaca.markets/v2/orders"]
