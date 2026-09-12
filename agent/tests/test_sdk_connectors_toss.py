"""Tests for the Toss Securities (토스증권) direct-SDK trading connector.

Mirrors ``test_sdk_connectors.py``: exercises profile registration, the
fully-read-only guard (Toss documents no verifiable sandbox, following the
Trading 212 precedent), config resolution, read/write classification, secret
redaction, and service dispatch degrading cleanly when nothing is configured
— no live credentials or network access required.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.live.classification import ToolClass
from src.trading import profiles, service
from src.trading.connectors.toss import sdk as toss
from src.trading.connectors.toss.classification import TOSS_TOOL_CLASS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Profile registration
# --------------------------------------------------------------------------- #


def test_toss_sdk_profile_registered() -> None:
    ids = {p.id for p in profiles.list_profiles()}
    assert "toss-live-sdk-readonly" in ids


def test_toss_exposes_no_paper_or_live_trade_profile() -> None:
    """Toss documents no verifiable sandbox — every profile is read-only,
    mirroring the Trading 212 precedent (never even a paper-trade profile)."""
    toss_profiles = [p for p in profiles.list_profiles() if p.connector == "toss"]
    assert toss_profiles
    for profile in toss_profiles:
        assert profile.readonly is True
        assert not any(".place" in cap for cap in profile.capabilities)


# --------------------------------------------------------------------------- #
# Order refusal (fully read-only, like Trading 212)
# --------------------------------------------------------------------------- #


def test_toss_place_order_always_refused() -> None:
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1", profile="live-readonly")
    result = toss.place_order(cfg, symbol="005930", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "read-only" in result["error"]
    assert result["paper_guard"] == "read_only_no_runtime_discriminator"


def test_toss_cancel_order_always_refused() -> None:
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.cancel_order(cfg, "ORD1")
    assert result["status"] == "error"
    assert "read-only" in result["error"]


def test_toss_place_order_refused_even_when_declared_paper() -> None:
    """No verified sandbox exists, so even a 'paper'-declared profile refuses —
    unlike Dhan/Upbit, there is no honest local simulation to fall back to."""
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1", profile="paper")
    result = toss.place_order(cfg, symbol="005930", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "disabled" in result["error"]


def test_toss_invalid_profile_rejected() -> None:
    with pytest.raises(toss.TossConfigError):
        toss.TossConfig.from_mapping({"profile": "go-live"})


# --------------------------------------------------------------------------- #
# Read paths (spec-shaped payloads: every Toss response is {"result": ...})
# --------------------------------------------------------------------------- #


#: A single holdings item shaped exactly like GET /api/v1/holdings per the
#: openapi.json v1.2.15 spec (confirmed by review on #1409).
_HOLDINGS_PAYLOAD = {
    "result": {
        "totalPurchaseAmount": {"krw": 700000, "usd": None},
        "marketValue": {"amount": {"krw": 715000, "usd": None}, "amountAfterCost": {"krw": 714000, "usd": None}},
        "profitLoss": {
            "amount": {"krw": 15000, "usd": None},
            "amountAfterCost": {"krw": 14000, "usd": None},
            "rate": 2.14,
            "rateAfterCost": 2.0,
        },
        "dailyProfitLoss": {"krw": 1500, "usd": None},
        "items": [
            {
                "symbol": "005930",
                "name": "Samsung Electronics",
                "marketCountry": "KR",
                "currency": "KRW",
                "quantity": 10,
                "lastPrice": "71500",
                "averagePurchasePrice": "70000",
                "marketValue": {"purchaseAmount": "700000", "amount": "715000", "amountAfterCost": "714000"},
                "profitLoss": {"amount": "15000", "amountAfterCost": "14000", "rate": "2.14", "rateAfterCost": "2.0"},
                "dailyProfitLoss": "1500",
                "cost": "1000",
            }
        ],
    }
}


def test_toss_positions_reads_holdings_and_unwraps_nested_items(monkeypatch) -> None:
    def fake_get(cfg, path, *, authed, account_scoped, params=None):
        assert path == "/api/v1/holdings"
        assert authed is True
        assert account_scoped is True
        return _HOLDINGS_PAYLOAD

    monkeypatch.setattr(toss, "_get", fake_get)
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_positions(cfg)

    assert result["status"] == "ok"
    assert result["positions"] == [
        {
            "symbol": "005930",
            "name": "Samsung Electronics",
            "quantity": 10,
            "average_price": "70000",
            "current_price": "71500",
            "pnl": "15000",
            "currency": "KRW",
            "market": "KR",
        }
    ]


def test_toss_account_snapshot_reads_holdings_totals_without_flattening_currency(monkeypatch) -> None:
    monkeypatch.setattr(toss, "_get", lambda *a, **k: _HOLDINGS_PAYLOAD)
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_account_snapshot(cfg)

    assert result["status"] == "ok"
    assert result["account"]["total_purchase_amount"] == {"krw": 700000, "usd": None}
    assert result["account"]["market_value"]["amount"] == {"krw": 715000, "usd": None}
    assert result["account"]["profit_loss"]["rate"] == 2.14


def test_toss_open_orders_calls_status_open_and_closed_separately(monkeypatch) -> None:
    """status is a required query param on /api/v1/orders, not something to
    derive by inspecting each row -- two calls, matching the spec."""
    calls = []

    def fake_get(cfg, path, *, authed, account_scoped, params=None):
        calls.append(params)
        assert path == "/api/v1/orders"
        if params == {"status": "OPEN"}:
            return {
                "result": {
                    "orders": [
                        {
                            "orderId": "1",
                            "symbol": "005930",
                            "side": "BUY",
                            "orderType": "LIMIT",
                            "status": "PARTIAL_FILLED",
                            "price": "70000",
                            "quantity": 5,
                            "currency": "KRW",
                            "orderedAt": "t1",
                            "execution": {"filledQuantity": 2, "averageFilledPrice": "70000"},
                        }
                    ],
                    "hasNext": False,
                    "nextCursor": None,
                }
            }
        return {"result": {"orders": [], "hasNext": False, "nextCursor": None}}

    monkeypatch.setattr(toss, "_get", fake_get)
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_open_orders(cfg, include_executions=True)

    assert calls == [{"status": "OPEN"}, {"status": "CLOSED"}]
    assert result["open_orders"] == [
        {
            "order_id": "1",
            "symbol": "005930",
            "side": "BUY",
            "order_type": "LIMIT",
            "status": "PARTIAL_FILLED",
            "quantity": 5,
            "filled_quantity": 2,
            "price": "70000",
            "currency": "KRW",
            "created_at": "t1",
        }
    ]
    assert result["executions"] == []


def test_toss_get_quote_unwraps_result_list(monkeypatch) -> None:
    def fake_get(cfg, path, *, authed, account_scoped, params=None):
        assert path == "/api/v1/prices"
        assert params == {"symbols": "005930"}
        return {"result": [{"symbol": "005930", "lastPrice": "71500", "currency": "KRW", "timestamp": "t"}]}

    monkeypatch.setattr(toss, "_get", fake_get)
    result = toss.get_quote("005930", config=toss.TossConfig(client_id="c", client_secret="s", account_seq="1"))

    assert result["status"] == "ok"
    assert result["quote"]["last"] == "71500"


def test_toss_get_quote_errors_on_an_unpriced_result_instead_of_returning_ok_with_nulls(monkeypatch) -> None:
    monkeypatch.setattr(toss, "_get", lambda *a, **k: {"result": [{"symbol": "005930"}]})
    result = toss.get_quote("005930", config=toss.TossConfig(client_id="c", client_secret="s", account_seq="1"))
    assert result["status"] == "error"


def test_toss_get_historical_bars_uses_count_not_limit_and_unwraps_nested_result(monkeypatch) -> None:
    def fake_get(cfg, path, *, authed, account_scoped, params=None):
        assert path == "/api/v1/candles"
        assert params["count"] == 5
        assert "limit" not in params
        return {
            "result": {
                "candles": [
                    {"timestamp": "t1", "openPrice": "1", "highPrice": "2", "lowPrice": "1", "closePrice": "1.5"},
                ],
                "nextBefore": None,
            }
        }

    monkeypatch.setattr(toss, "_get", fake_get)
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_historical_bars("005930", config=cfg, limit=5)

    assert result["status"] == "ok"
    assert result["bars"] == [{"time": "t1", "open": "1", "high": "2", "low": "1", "close": "1.5", "volume": None}]


def test_toss_get_historical_bars_errors_on_a_bar_with_no_close_price(monkeypatch) -> None:
    """A missing close is a data problem -- silently dropping it would leave a
    gap in the series with no signal that anything was wrong."""
    monkeypatch.setattr(
        toss,
        "_get",
        lambda *a, **k: {"result": {"candles": [{"timestamp": "t1"}], "nextBefore": None}},
    )
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_historical_bars("005930", config=cfg)
    assert result["status"] == "error"


# --------------------------------------------------------------------------- #
# Auth header shape / error surfacing (requests-level, no mocked _get)
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, status_code: int, json_body: Any, content: bytes = b"{}"):
        self.status_code = status_code
        self._json = json_body
        self.content = content
        self.text = "" if not content else str(content)
        self.reason = "OK" if status_code < 400 else "Unauthorized"

    def json(self):
        return self._json


def test_toss_request_sends_bearer_and_account_headers(monkeypatch) -> None:
    seen = {}

    def fake_get(url, *, headers, params, timeout):
        seen.update({"url": url, "headers": headers})
        return _FakeResponse(200, {"result": []})

    monkeypatch.setattr(toss.requests, "get", fake_get)
    monkeypatch.setattr(toss, "_access_token", lambda cfg: "tok")

    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="acct-1")
    toss._get(cfg, "/api/v1/holdings", authed=True, account_scoped=True)

    assert seen["url"] == "https://openapi.tossinvest.com/api/v1/holdings"
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert seen["headers"]["X-Tossinvest-Account"] == "acct-1"


def test_toss_check_connection_surfaces_a_clean_error_on_a_bad_key(monkeypatch) -> None:
    monkeypatch.setattr(toss.requests, "get", lambda *a, **k: _FakeResponse(401, {"message": "invalid token"}))
    monkeypatch.setattr(toss, "_access_token", lambda cfg: "bad-tok")

    result = toss.check_status(toss.TossConfig(client_id="c", client_secret="s", account_seq="1"))
    assert result["status"] == "error"
    assert "authentication failed" in result["error"]


# --------------------------------------------------------------------------- #
# Redaction / service dispatch / classification
# --------------------------------------------------------------------------- #


def test_toss_redacts_client_secret() -> None:
    cfg = toss.TossConfig(client_id="client-1234", client_secret="super-secret", account_seq="1")
    pub = toss._public_config(cfg)
    assert "super-secret" not in str(pub)
    assert pub["client_id"].endswith("***")
    assert pub["client_secret"] == "***redacted***"


def test_toss_service_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(toss, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("toss-live-sdk-readonly")
    assert result["status"] == "error"
    assert result["connector"] == "toss"
    assert result["transport"] == "broker_sdk"


def test_toss_order_ops_classified_write() -> None:
    for name in ("place_order", "cancel_order"):
        assert TOSS_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("get_positions", "get_account_snapshot"):
        assert TOSS_TOOL_CLASS[name] is ToolClass.READ
