"""QVeris must rank minute intervals as intraday, not fall through to daily."""

from __future__ import annotations

from backtest.loaders.qveris_loader import _granularity_tokens, _select_capabilities


def _sample_results() -> list[dict]:
    return [
        {
            "tool_id": "daily-ohlcv",
            "name": "Daily OHLCV historical",
            "description": "end-of-day daily open high low close volume for symbol ticker",
            "stats": {"success_rate": 0.99},
            "expected_cost": 0.01,
        },
        {
            "tool_id": "intraday-1min",
            "name": "1min intraday candles",
            "description": "minute bar ohlcv historical price for symbol ticker",
            "stats": {"success_rate": 0.90},
            "expected_cost": 0.02,
        },
    ]


def test_one_minute_tokens_are_intraday() -> None:
    wanted, unwanted = _granularity_tokens("1m")
    assert "minute" in wanted
    assert "monthly" in unwanted


def test_five_minute_tokens_are_intraday() -> None:
    wanted, _ = _granularity_tokens("5m")
    assert "minute" in wanted


def test_month_token_stays_monthly_not_minute() -> None:
    wanted, unwanted = _granularity_tokens("1M")
    assert "monthly" in wanted
    assert "minute" in unwanted


def test_one_minute_prefers_intraday_capability_over_daily() -> None:
    selected = _select_capabilities(_sample_results(), "1m")
    assert selected
    assert selected[0]["tool_id"] == "intraday-1min"
