"""Regression tests for merging the two live A-share content sources."""

from __future__ import annotations

from src.api import market_routes


def test_reports_merge_iwencai_and_a_stock_data(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "iwencai_stock_reports",
        lambda code, limit: [
            {"title": "Shared report", "publishDate": "2026-08-17", "url": "https://iwencai.test/shared", "source": "Iwencai"},
            {"title": "Iwencai only", "publishDate": "2026-08-16", "url": "https://iwencai.test/only"},
        ],
    )
    monkeypatch.setattr(
        market_routes,
        "eastmoney_reports",
        lambda code, limit: [
            {"title": "Shared report", "publishDate": "2026-08-17", "infoCode": "em1"},
            {"title": "a-stock-data only", "publishDate": "2026-08-15", "infoCode": "em2"},
        ],
    )

    rows = market_routes._fetch_stock_reports("600519.SH", limit=20)

    assert [row["title"] for row in rows] == ["Shared report", "Iwencai only", "a-stock-data only"]
    assert rows[0]["source"] == "Iwencai"
    assert rows[0]["infoCode"] == "em1"


def test_news_merge_keeps_both_sources_and_removes_same_story(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "iwencai_stock_news",
        lambda code, page, page_size: [
            {"title": "Shared news", "time": "2026-08-17", "url": "https://iwencai.test/shared", "source": "Iwencai"},
            {"title": "Iwencai only", "time": "2026-08-16", "url": "https://iwencai.test/only"},
        ],
    )
    monkeypatch.setattr(
        market_routes,
        "eastmoney_stock_news",
        lambda code, limit, page=1: [
            {"title": "Shared news", "time": "2026-08-17", "url": "https://eastmoney.test/shared"},
            {"title": "a-stock-data only", "time": "2026-08-15", "url": "https://eastmoney.test/only"},
        ],
    )

    rows = market_routes._fetch_stock_news("600519.SH", "a_share", 1, 20)

    assert [row["title"] for row in rows] == ["Shared news", "Iwencai only", "a-stock-data only"]
    assert rows[0]["source"] == "Iwencai"
