"""Regression tests for persistent overview watchlists."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import market_routes
from src.api.security import require_auth
from src.session.models import AuthMethod, Principal
from src.watchlist_store import WatchlistStore


def test_watchlist_store_round_trip_preserves_market_order(tmp_path) -> None:
    store = WatchlistStore(tmp_path / "watchlists.db")
    payload = {
        "a_share": [
            {"symbol": "600519.SH", "name": "贵州茅台"},
            {"symbol": "000001.SZ", "name": "平安银行"},
        ],
        "us": [{"symbol": "AAPL.US", "name": "Apple"}],
    }

    assert store.save("shared-key-holder", payload) == payload
    assert store.load("shared-key-holder") == payload


def test_watchlist_store_replaces_old_entries_and_isolates_scopes(tmp_path) -> None:
    store = WatchlistStore(tmp_path / "watchlists.db")
    store.save(
        "scope-a",
        {"a_share": [{"symbol": "600519.SH", "name": "贵州茅台"}], "us": []},
    )
    store.save(
        "scope-a",
        {"a_share": [], "us": [{"symbol": "MSFT.US", "name": "Microsoft"}]},
    )
    store.save(
        "scope-b",
        {"a_share": [{"symbol": "000001.SZ", "name": "平安银行"}], "us": []},
    )

    assert store.load("scope-a") == {
        "a_share": [],
        "us": [{"symbol": "MSFT.US", "name": "Microsoft"}],
    }
    assert store.load("scope-b") == {
        "a_share": [{"symbol": "000001.SZ", "name": "平安银行"}],
        "us": [],
    }


def test_market_watchlist_api_reads_and_writes_sqlite_store(monkeypatch, tmp_path) -> None:
    store = WatchlistStore(tmp_path / "watchlists.db")
    monkeypatch.setattr(market_routes, "_get_watchlist_store", lambda: store)

    app = FastAPI()
    market_routes.register_market_routes(app)
    app.dependency_overrides[require_auth] = lambda: Principal(
        subject="shared-key-holder", auth_method=AuthMethod.SHARED_KEY
    )
    client = TestClient(app)
    payload = {
        "a_share": [{"symbol": "600519.SH", "name": "贵州茅台"}],
        "us": [],
    }

    response = client.put("/market/watchlists", json=payload)
    assert response.status_code == 200
    assert response.json() == payload
    assert client.get("/market/watchlists").json() == payload
