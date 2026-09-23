"""API tests for ``GET /markets/kenya/board``.

No network: the loader's price-list functions are patched where the route
imports them (``backtest.loaders.nse_ke_loader``). Loopback ``TestClient``
bypasses dev-mode auth, matching ``test_options_routes.py``.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import api_server
from backtest.loaders import nse_ke_loader
from backtest.loaders.nse_ke_loader import parse_price_list_text
from src.api import markets_routes

TEXT = """\
AGRICULTURAL
440.00 240.00 Kakuzi Plc Ord.5.00 KE0000000281 436.00 405.00 433.00 436.50 443
TELECOMMUNICATION
39.50 25.80 Safaricom Plc Ord 0.05 KE1000001402 36.80 36.35 36.60 36.30 7,340,000
ENERGY & PETROLEUM
5.50 4.10 Kenya Power & Lighting Ltd 4% Pref 20.00 KE0000000356 - - - 5.26 -
BANKING
109.00 54.00 Equity Group Holdings Plc Ord 0.50 KE0000000554 103.00 98.75 98.50 98.50 472,506
"""


def _client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    markets_routes.clear_cache()
    nse_ke_loader.clear_memo()
    yield
    markets_routes.clear_cache()


def _patch_latest(monkeypatch, day=date(2026, 9, 22), text=TEXT, calls=None):
    def fake_latest(*args, **kwargs):
        if calls is not None:
            calls.append(1)
        return day, parse_price_list_text(text)

    monkeypatch.setattr(nse_ke_loader, "latest_price_list", fake_latest)


def test_latest_board_shape(monkeypatch) -> None:
    _patch_latest(monkeypatch)
    resp = _client().get("/markets/kenya/board")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of"] == "2026-09-22"
    assert body["source"] == "nse_ke"
    assert body["source_url"].endswith("/22-SEP-26.pdf")
    rows = {r["code"]: r for r in body["rows"]}
    scom = rows["SCOM"]
    assert scom["close"] == 36.60 and scom["prev"] == 36.30
    assert scom["change"] == pytest.approx(0.30)
    assert scom["change_pct"] == pytest.approx(0.8264, abs=1e-3)
    assert scom["turnover"] == pytest.approx(36.60 * 7_340_000)
    assert scom["sector"] == "Telecommunication"
    assert rows["KUKZ"]["sector"] == "Agricultural"


def test_breadth_counts_only_traded_counters(monkeypatch) -> None:
    _patch_latest(monkeypatch)
    breadth = _client().get("/markets/kenya/board").json()["breadth"]
    assert breadth == {"listed": 4, "traded": 3, "advancers": 1, "decliners": 1, "unchanged": 1}


def test_untraded_counter_carries_previous_close(monkeypatch) -> None:
    _patch_latest(monkeypatch)
    rows = {r["code"]: r for r in _client().get("/markets/kenya/board").json()["rows"]}
    pref = rows["KPLC-P4"]
    assert pref["traded"] is False
    assert pref["close"] == 5.26 and pref["change"] is None and pref["volume"] == 0.0


def test_board_is_cached(monkeypatch) -> None:
    calls: list = []
    _patch_latest(monkeypatch, calls=calls)
    client = _client()
    assert client.get("/markets/kenya/board").status_code == 200
    assert client.get("/markets/kenya/board").status_code == 200
    assert len(calls) == 1


def test_specific_session(monkeypatch) -> None:
    seen: list[date] = []

    def fake_fetch(day):
        seen.append(day)
        return parse_price_list_text(TEXT)

    monkeypatch.setattr(nse_ke_loader, "fetch_price_list", fake_fetch)
    body = _client().get("/markets/kenya/board", params={"date": "2026-09-18"}).json()
    assert seen == [date(2026, 9, 18)] and body["as_of"] == "2026-09-18"


def test_missing_session_is_404(monkeypatch) -> None:
    monkeypatch.setattr(nse_ke_loader, "fetch_price_list", lambda day: None)
    resp = _client().get("/markets/kenya/board", params={"date": "2026-09-19"})
    assert resp.status_code == 404
    assert "holiday" in resp.json()["detail"]


def test_bad_date_is_rejected() -> None:
    assert _client().get("/markets/kenya/board", params={"date": "22-09-2026"}).status_code == 422


def test_missing_extra_is_503(monkeypatch) -> None:
    monkeypatch.setattr(nse_ke_loader.DataLoader, "is_available", lambda self: False)
    resp = _client().get("/markets/kenya/board")
    assert resp.status_code == 503
    assert "nse-ke" in resp.json()["detail"]
