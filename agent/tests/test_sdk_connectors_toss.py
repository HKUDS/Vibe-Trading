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


def test_toss_positions_reads_holdings_and_unwraps_result(monkeypatch) -> None:
    def fake_get(cfg, path, *, authed, account_scoped, params=None):
        assert path == "/api/v1/holdings"
        assert authed is True
        assert account_scoped is True
        return {
            "result": [
                {"symbol": "005930", "quantity": 10, "averagePrice": 70000, "currentPrice": 71500, "currency": "KRW"}
            ]
        }

    monkeypatch.setattr(toss, "_get", fake_get)
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_positions(cfg)

    assert result["status"] == "ok"
    assert result["positions"] == [
        {
            "symbol": "005930",
            "name": None,
            "quantity": 10,
            "average_price": 70000,
            "current_price": 71500,
            "pnl": None,
            "currency": "KRW",
            "market": None,
        }
    ]


def test_toss_open_orders_splits_on_status_from_a_single_endpoint(monkeypatch) -> None:
    def fake_get(cfg, path, *, authed, account_scoped, params=None):
        assert path == "/api/v1/orders"
        return {
            "result": [
                {"orderId": "1", "symbol": "005930", "status": "OPEN", "side": "buy", "quantity": 5},
                {"orderId": "2", "symbol": "005930", "status": "FILLED", "side": "sell", "quantity": 3},
            ]
        }

    monkeypatch.setattr(toss, "_get", fake_get)
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_open_orders(cfg, include_executions=True)

    assert [row["order_id"] for row in result["open_orders"]] == ["1"]
    assert [row["order_id"] for row in result["executions"]] == ["2"]


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


def test_toss_get_historical_bars_drops_bars_with_no_close_price(monkeypatch) -> None:
    monkeypatch.setattr(
        toss,
        "_get",
        lambda *a, **k: {"result": {"candles": [{"timestamp": "t1"}], "nextBefore": None}},
    )
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.get_historical_bars("005930", config=cfg)
    assert result["bars"] == []


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
