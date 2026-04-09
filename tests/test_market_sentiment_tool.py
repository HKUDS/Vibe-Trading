from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from src.tools import build_registry
from src.tools.market_sentiment_tool import run_market_sentiment


class DummyResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_market_sentiment_returns_not_configured_without_api_key(monkeypatch):
    monkeypatch.delenv("ADANOS_API_KEY", raising=False)

    payload = json.loads(run_market_sentiment(mode="snapshot", tickers="AAPL,NVDA"))

    assert payload["status"] == "not_configured"
    assert "ADANOS_API_KEY" in payload["message"]


def test_market_sentiment_snapshot_aggregates_sources(monkeypatch):
    monkeypatch.setenv("ADANOS_API_KEY", "demo-key")

    calls: list[str] = []

    def fake_get(url, *, params, headers, timeout):
        calls.append(url)
        assert headers["X-API-Key"] == "demo-key"
        assert timeout == 20
        assert params["tickers"] == "AAPL,NVDA"
        if url.endswith("/reddit/stocks/v1/compare"):
            return DummyResponse(
                200,
                {
                    "period_days": 7,
                    "stocks": [
                        {"ticker": "AAPL", "company_name": "Apple Inc.", "buzz_score": 60.0, "bullish_pct": 65, "sentiment_score": 0.42, "mentions": 120, "trend": "rising"},
                        {"ticker": "NVDA", "company_name": "NVIDIA", "buzz_score": 75.0, "bullish_pct": 70, "sentiment_score": 0.55, "mentions": 180, "trend": "rising"},
                    ],
                },
            )
        if url.endswith("/x/stocks/v1/compare"):
            return DummyResponse(
                200,
                {
                    "period_days": 7,
                    "stocks": [
                        {"ticker": "AAPL", "company_name": "Apple Inc.", "buzz_score": 40.0, "bullish_pct": 35, "sentiment_score": -0.12, "unique_tweets": 88, "trend": "stable"},
                        {"ticker": "NVDA", "company_name": "NVIDIA", "buzz_score": 55.0, "bullish_pct": 67, "sentiment_score": 0.31, "unique_tweets": 96, "trend": "stable"},
                    ],
                },
            )
        if url.endswith("/news/stocks/v1/compare"):
            return DummyResponse(
                200,
                {
                    "period_days": 7,
                    "stocks": [
                        {"ticker": "AAPL", "company_name": "Apple Inc.", "buzz_score": 30.0, "bullish_pct": 58, "sentiment_score": 0.19, "mentions": 12, "trend": "stable"},
                    ],
                },
            )
        if url.endswith("/polymarket/stocks/v1/compare"):
            return DummyResponse(
                200,
                {
                    "period_days": 7,
                    "stocks": [
                        {"ticker": "AAPL", "company_name": "Apple Inc.", "buzz_score": 50.0, "bullish_pct": 62, "sentiment_score": 0.27, "trade_count": 250, "trend": "stable"},
                    ],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("src.tools.market_sentiment_tool.requests.get", fake_get)

    payload = json.loads(run_market_sentiment(mode="snapshot", tickers=["AAPL", "NVDA"], days=7))

    assert payload["status"] == "ok"
    assert payload["mode"] == "snapshot"
    assert len(calls) == 4
    assert payload["tickers"][0]["ticker"] == "NVDA"
    assert payload["tickers"][0]["coverage"] == 2
    assert payload["tickers"][0]["source_alignment"] == "aligned"

    aapl = next(item for item in payload["tickers"] if item["ticker"] == "AAPL")
    assert aapl["coverage"] == 4
    assert aapl["average_buzz"] == 45.0
    assert aapl["average_bullish_pct"] == 55.0
    assert aapl["source_alignment"] == "divergent"
    assert aapl["sources"]["polymarket"]["activity"] == 250
    assert aapl["sources"]["x"]["activity_label"] == "unique_tweets"


def test_market_sentiment_snapshot_excludes_zero_placeholders_from_coverage(monkeypatch):
    monkeypatch.setenv("ADANOS_API_KEY", "demo-key")

    def fake_get(url, *, params, headers, timeout):
        return DummyResponse(
            200,
            {
                "period_days": 7,
                "stocks": [
                    {"ticker": "PLTR", "company_name": "Palantir", "buzz_score": 0.0, "bullish_pct": None, "sentiment_score": None, "mentions": 0, "trend": None},
                ],
            },
        )

    monkeypatch.setattr("src.tools.market_sentiment_tool.requests.get", fake_get)

    payload = json.loads(run_market_sentiment(mode="snapshot", tickers="PLTR", source="all", days=7))

    assert payload["status"] == "ok"
    assert payload["tickers"][0]["ticker"] == "PLTR"
    assert payload["tickers"][0]["coverage"] == 0
    assert payload["tickers"][0]["average_buzz"] == 0.0
    assert payload["tickers"][0]["source_alignment"] == "no_signal"


def test_market_sentiment_trending_allows_partial_source_failures(monkeypatch):
    monkeypatch.setenv("ADANOS_API_KEY", "demo-key")

    def fake_get(url, *, params, headers, timeout):
        if url.endswith("/reddit/stocks/v1/trending"):
            return DummyResponse(200, [{"ticker": "TSLA", "buzz_score": 81.0, "bullish_pct": 63, "mentions": 210, "trend": "rising"}])
        if url.endswith("/x/stocks/v1/trending"):
            return DummyResponse(404, {"detail": "No trending stocks found"})
        if url.endswith("/news/stocks/v1/trending"):
            return DummyResponse(200, [{"ticker": "NVDA", "buzz_score": 54.0, "bullish_pct": 59, "mentions": 24, "trend": "stable"}])
        if url.endswith("/polymarket/stocks/v1/trending"):
            return DummyResponse(500, {"detail": "upstream error"})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("src.tools.market_sentiment_tool.requests.get", fake_get)

    payload = json.loads(run_market_sentiment(mode="trending", source="all", days=3, limit=5))

    assert payload["status"] == "partial"
    assert set(payload["results"]) == {"reddit", "x", "news"}
    assert payload["results"]["x"] == []
    assert "polymarket" in payload["errors"]


def test_registry_includes_market_sentiment_tool():
    registry = build_registry()
    tool = registry.get("market_sentiment")
    assert tool is not None
    assert tool.name == "market_sentiment"
