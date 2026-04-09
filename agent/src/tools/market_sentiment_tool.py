"""Optional Adanos market sentiment tool for structured US-stock sentiment snapshots."""

from __future__ import annotations

import json
import os
from statistics import mean
from typing import Any

import requests

from src.agent.tools import BaseTool

_API_BASE = "https://api.adanos.org"
_TIMEOUT_SECONDS = 20
_MAX_TICKERS = 10
_SUPPORTED_SOURCES = ("reddit", "x", "news", "polymarket")
_COMPARE_PATHS = {
    "reddit": "/reddit/stocks/v1/compare",
    "x": "/x/stocks/v1/compare",
    "news": "/news/stocks/v1/compare",
    "polymarket": "/polymarket/stocks/v1/compare",
}
_TRENDING_PATHS = {
    "reddit": "/reddit/stocks/v1/trending",
    "x": "/x/stocks/v1/trending",
    "news": "/news/stocks/v1/trending",
    "polymarket": "/polymarket/stocks/v1/trending",
}


def _get_api_key() -> str:
    return os.getenv("ADANOS_API_KEY", "").strip()


def _normalize_source(source: Any) -> str:
    normalized = str(source or "all").strip().lower()
    if normalized in {"", "all"}:
        return "all"
    if normalized not in _SUPPORTED_SOURCES:
        raise ValueError(
            f"Unsupported source '{normalized}'. Use one of: all, {', '.join(_SUPPORTED_SOURCES)}"
        )
    return normalized


def _normalize_tickers(tickers: Any) -> list[str]:
    if tickers is None:
        return []

    if isinstance(tickers, str):
        raw_values = tickers.split(",")
    elif isinstance(tickers, (list, tuple, set)):
        raw_values = list(tickers)
    else:
        raise ValueError("tickers must be a comma-separated string or a list of ticker symbols")

    seen: set[str] = set()
    normalized: list[str] = []
    for value in raw_values:
        ticker = str(value).strip().upper().replace("$", "")
        if ticker and ticker not in seen:
            seen.add(ticker)
            normalized.append(ticker)

    if len(normalized) > _MAX_TICKERS:
        raise ValueError(f"Maximum {_MAX_TICKERS} tickers allowed")
    return normalized


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("stocks", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _request_json(path: str, params: dict[str, Any], api_key: str, *, allow_404: bool = False) -> Any:
    response = requests.get(
        f"{_API_BASE}{path}",
        params=params,
        headers={"X-API-Key": api_key},
        timeout=_TIMEOUT_SECONDS,
    )
    if allow_404 and response.status_code == 404:
        return []
    if response.status_code != 200:
        raise RuntimeError(f"{path} returned {response.status_code}: {response.text[:300]}")
    return response.json()


def _extract_activity(row: dict[str, Any]) -> tuple[str | None, int | float | None]:
    for key in ("mentions", "unique_tweets", "trade_count", "unique_posts", "source_count", "unique_traders"):
        value = row.get(key)
        if value is not None:
            return key, value
    return None, None


def _normalize_compare_row(source: str, row: dict[str, Any]) -> dict[str, Any]:
    activity_key, activity_value = _extract_activity(row)
    return {
        "ticker": row.get("ticker"),
        "company_name": row.get("company_name"),
        "buzz_score": row.get("buzz_score"),
        "sentiment_score": row.get("sentiment_score"),
        "bullish_pct": row.get("bullish_pct"),
        "bearish_pct": row.get("bearish_pct"),
        "trend": row.get("trend"),
        "activity_label": activity_key,
        "activity": activity_value,
        "source": source,
    }


def _normalize_trending_row(source: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_compare_row(source, row)
    normalized["rank"] = row.get("rank")
    return normalized


def _has_signal(row: dict[str, Any]) -> bool:
    for key in ("buzz_score", "sentiment_score", "bullish_pct", "activity"):
        value = row.get(key)
        if value is None:
            continue
        try:
            if float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _classify_alignment(bullish_values: list[float]) -> str:
    if not bullish_values:
        return "no_signal"
    if len(bullish_values) == 1:
        return "single_source"

    bullish_sources = sum(value >= 55 for value in bullish_values)
    bearish_sources = sum(value <= 45 for value in bullish_values)

    if bullish_sources == len(bullish_values) or bearish_sources == len(bullish_values):
        return "aligned"
    if bullish_sources and bearish_sources:
        return "divergent"
    return "mixed"


def _aggregate_snapshot(tickers: list[str], per_source_rows: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    aggregated: list[dict[str, Any]] = []
    for ticker in tickers:
        source_rows = {
            source: rows[ticker]
            for source, rows in per_source_rows.items()
            if ticker in rows
        }
        signal_rows = [row for row in source_rows.values() if _has_signal(row)]
        buzz_values = [
            float(row["buzz_score"])
            for row in signal_rows
            if row.get("buzz_score") is not None
        ]
        bullish_values = [
            float(row["bullish_pct"])
            for row in signal_rows
            if row.get("bullish_pct") is not None
        ]
        sentiment_values = [
            float(row["sentiment_score"])
            for row in signal_rows
            if row.get("sentiment_score") is not None
        ]

        company_name = next(
            (row.get("company_name") for row in source_rows.values() if row.get("company_name")),
            None,
        )
        aggregated.append(
            {
                "ticker": ticker,
                "company_name": company_name,
                "average_buzz": round(mean(buzz_values), 2) if buzz_values else 0.0,
                "average_bullish_pct": round(mean(bullish_values), 1) if bullish_values else None,
                "average_sentiment_score": round(mean(sentiment_values), 3) if sentiment_values else None,
                "coverage": len(signal_rows),
                "source_alignment": _classify_alignment(bullish_values),
                "sources": source_rows,
            }
        )

    aggregated.sort(key=lambda item: item["average_buzz"], reverse=True)
    return aggregated


def run_market_sentiment(
    *,
    mode: str = "snapshot",
    tickers: Any = None,
    source: str = "all",
    days: int = 7,
    limit: int = 10,
) -> str:
    """Run optional Adanos market sentiment lookup.

    Args:
        mode: snapshot or trending.
        tickers: Comma-separated string or list of tickers for snapshot mode.
        source: all, reddit, x, news, or polymarket.
        days: Lookback window in days.
        limit: Max trending rows per source.

    Returns:
        JSON-formatted result.
    """
    api_key = _get_api_key()
    if not api_key:
        return json.dumps(
            {
                "status": "not_configured",
                "message": "Set ADANOS_API_KEY to enable structured market sentiment snapshots and trending tickers.",
            },
            ensure_ascii=False,
        )

    mode_normalized = str(mode or "snapshot").strip().lower()
    if mode_normalized not in {"snapshot", "trending"}:
        return json.dumps(
            {"status": "error", "error": "mode must be 'snapshot' or 'trending'"},
            ensure_ascii=False,
        )

    try:
        days_value = int(days)
        limit_value = int(limit)
        if days_value < 1 or days_value > 90:
            raise ValueError("days must be between 1 and 90")
        if limit_value < 1 or limit_value > 25:
            raise ValueError("limit must be between 1 and 25")
        source_value = _normalize_source(source)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    selected_sources = list(_SUPPORTED_SOURCES) if source_value == "all" else [source_value]

    if mode_normalized == "snapshot":
        try:
            ticker_list = _normalize_tickers(tickers)
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        if not ticker_list:
            return json.dumps(
                {"status": "error", "error": "tickers is required for snapshot mode"},
                ensure_ascii=False,
            )

        per_source_rows: dict[str, dict[str, dict[str, Any]]] = {}
        errors: dict[str, str] = {}
        for source_name in selected_sources:
            try:
                payload = _request_json(
                    _COMPARE_PATHS[source_name],
                    {"tickers": ",".join(ticker_list), "days": days_value},
                    api_key,
                )
                rows = {
                    str(row.get("ticker", "")).upper(): _normalize_compare_row(source_name, row)
                    for row in _extract_rows(payload)
                    if row.get("ticker")
                }
                per_source_rows[source_name] = rows
            except Exception as exc:  # pragma: no cover - covered via error contract tests
                errors[source_name] = str(exc)

        if not per_source_rows:
            return json.dumps(
                {"status": "error", "error": "All Adanos sentiment requests failed", "errors": errors},
                ensure_ascii=False,
            )

        status = "ok" if not errors else "partial"
        return json.dumps(
            {
                "status": status,
                "mode": "snapshot",
                "period_days": days_value,
                "sources_requested": selected_sources,
                "tickers": _aggregate_snapshot(ticker_list, per_source_rows),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )

    trending_results: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for source_name in selected_sources:
        try:
            payload = _request_json(
                _TRENDING_PATHS[source_name],
                {"days": days_value, "limit": limit_value},
                api_key,
                allow_404=True,
            )
            rows = [
                _normalize_trending_row(source_name, row)
                for row in _extract_rows(payload if isinstance(payload, dict) else payload)
            ]
            trending_results[source_name] = rows[:limit_value]
        except Exception as exc:  # pragma: no cover - covered via error contract tests
            errors[source_name] = str(exc)

    if not trending_results:
        return json.dumps(
            {"status": "error", "error": "All Adanos sentiment requests failed", "errors": errors},
            ensure_ascii=False,
        )

    payload: dict[str, Any] = {
        "status": "ok" if not errors else "partial",
        "mode": "trending",
        "period_days": days_value,
        "sources_requested": selected_sources,
        "errors": errors,
    }
    if source_value == "all":
        payload["results"] = trending_results
    else:
        payload["results"] = trending_results[selected_sources[0]]
    return json.dumps(payload, ensure_ascii=False, indent=2)


class MarketSentimentTool(BaseTool):
    """Optional structured market sentiment tool powered by Adanos."""

    name = "market_sentiment"
    description = (
        "Fetch structured stock market sentiment from an optional Adanos API integration. "
        "Use snapshot mode for ticker comparisons or trending mode for source-ranked hot names. "
        "Returns status=not_configured when ADANOS_API_KEY is missing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "Mode: snapshot or trending",
                "default": "snapshot",
            },
            "tickers": {
                "type": ["string", "array"],
                "description": "Comma-separated tickers or a ticker list for snapshot mode (max 10)",
            },
            "source": {
                "type": "string",
                "description": "Sentiment source: all, reddit, x, news, or polymarket",
                "default": "all",
            },
            "days": {
                "type": "integer",
                "description": "Lookback window in days (1-90, depending on account)",
                "default": 7,
            },
            "limit": {
                "type": "integer",
                "description": "Trending result limit per source (1-25)",
                "default": 10,
            },
        },
        "required": ["mode"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Execute market sentiment lookup."""
        return run_market_sentiment(
            mode=kwargs.get("mode", "snapshot"),
            tickers=kwargs.get("tickers"),
            source=kwargs.get("source", "all"),
            days=kwargs.get("days", 7),
            limit=kwargs.get("limit", 10),
        )
