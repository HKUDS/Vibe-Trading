"""Tests for Alpaca period → timeframe mapping."""

from __future__ import annotations

from src.trading.connectors.alpaca.sdk import _rest_timeframe


def test_project_hour_tokens_map_to_hour_not_day() -> None:
    assert _rest_timeframe("1H") == "1Hour"
    assert _rest_timeframe("4H") == "4Hour"
    assert _rest_timeframe("1h") == "1Hour"
    assert _rest_timeframe("4h") == "4Hour"


def test_minute_month_case_still_distinct() -> None:
    assert _rest_timeframe("1m") == "1Min"
    assert _rest_timeframe("1M") == "1Month"
