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
