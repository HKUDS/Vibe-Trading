"""Regression tests for database-first overview loading."""

from __future__ import annotations

from src.api import market_routes
from src.market_overview_store import MarketOverviewStore


def test_overview_store_round_trips_payload(tmp_path) -> None:
    store = MarketOverviewStore(tmp_path / "overview.db")
    payload = {"items": [{"symbol": "000001.SH", "price": 3000.0}], "updated_at": "now"}

    store.save("indices:a_share", payload)

    assert store.get("indices:a_share") == payload
    assert store.age_seconds("indices:a_share") is not None


def test_cached_overview_returns_immediately_and_schedules_refresh(monkeypatch, tmp_path) -> None:
    store = MarketOverviewStore(tmp_path / "overview.db")
    scheduled: list[str] = []
    monkeypatch.setattr(market_routes, "MarketOverviewStore", lambda: store)
    monkeypatch.setattr(
        market_routes,
        "_schedule_overview_refresh",
        lambda cache_key, fetcher: scheduled.append(cache_key) or True,
    )

    payload = market_routes._cached_overview(
        "indices:us",
        lambda: {"items": [], "updated_at": None},
        lambda: {"items": [{"symbol": "^DJI"}], "updated_at": "fresh"},
    )

    assert payload["items"] == []
    assert payload["from_cache"] is False
    assert payload["cache_status"] == "refreshing"
    assert scheduled == ["indices:us"]
