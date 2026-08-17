"""Tests for the daily stock-detail SQLite cache boundary."""

from __future__ import annotations

import sqlite3

from src.api import market_routes
from src.stock_detail_store import StockDetailStore


def test_a_share_detail_reuses_static_data_and_same_day_daily_bars(monkeypatch, tmp_path) -> None:
    store = StockDetailStore(tmp_path / "stock-details.db")
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(
        market_routes,
        "iwencai_stock_reports",
        lambda *args, **kwargs: (_ for _ in ()).throw(market_routes.IwencaiSkillError("test fallback")),
    )
    monkeypatch.setattr(
        market_routes,
        "iwencai_stock_news",
        lambda *args, **kwargs: (_ for _ in ()).throw(market_routes.IwencaiSkillError("test fallback")),
    )
    calls = {"quote": 0, "profile": 0, "financials": 0, "reports": 0, "boards": 0, "bars": 0, "news": 0}

    def fake_quote(codes):
        calls["quote"] += 1
        return {codes[0]: {"name": "贵州茅台", "price": 1500.0}}

    def fake_bars(code, start, end, period="1d"):
        calls["bars"] += 1
        return [{"trade_date": "2026-08-17", "open": 1490, "high": 1510, "low": 1480, "close": 1500, "volume": 100}]

    monkeypatch.setattr(market_routes, "tencent_quote", fake_quote)
    monkeypatch.setattr(market_routes, "eastmoney_stock_info", lambda code: calls.__setitem__("profile", calls["profile"] + 1) or {"industry": "白酒"})
    monkeypatch.setattr(market_routes, "_a_share_financials", lambda code: calls.__setitem__("financials", calls["financials"] + 1) or {"eps": 1.0})
    monkeypatch.setattr(market_routes, "eastmoney_reports", lambda code, limit: calls.__setitem__("reports", calls["reports"] + 1) or [{"title": "研报"}])
    monkeypatch.setattr(market_routes, "eastmoney_stock_boards", lambda code: calls.__setitem__("boards", calls["boards"] + 1) or [{"board_name": "白酒"}])
    monkeypatch.setattr(market_routes, "tencent_bars", fake_bars)
    monkeypatch.setattr(market_routes, "eastmoney_stock_news", lambda code, limit: calls.__setitem__("news", calls["news"] + 1) or [{"title": "新闻"}])

    first = market_routes._stock_detail_a_share("600519.SH", "1d")
    second = market_routes._stock_detail_a_share("600519.SH", "1d")

    assert first["bars"] == second["bars"]
    assert calls == {"quote": 1, "profile": 1, "financials": 1, "reports": 2, "boards": 1, "bars": 1, "news": 2}

    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE stock_detail_bars_cache SET refreshed_date = '2000-01-01' WHERE symbol = ? AND period = ?",
            ("600519.SH", "1d"),
        )

    market_routes._stock_detail_a_share("600519.SH", "1d")

    assert calls["bars"] == 2
    assert calls["quote"] == 1
