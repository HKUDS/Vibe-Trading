"""Tests for yfinance interval mapping (month vs minute case)."""

from __future__ import annotations

from backtest.loaders.yfinance_loader import _to_yfinance_interval


def test_month_token_maps_to_1mo_not_1m() -> None:
    assert _to_yfinance_interval("1M") == "1mo"
    assert _to_yfinance_interval("1m") == "1m"


def test_week_token_maps_to_1wk() -> None:
    assert _to_yfinance_interval("1W") == "1wk"


def test_daily_and_hour_unchanged() -> None:
    assert _to_yfinance_interval("1D") == "1d"
    assert _to_yfinance_interval("1H") == "1h"
    assert _to_yfinance_interval("4H") == "1h"
