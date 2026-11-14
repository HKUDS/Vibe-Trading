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


def test_normalization_keeps_observed_timezone_after_removing_index_zone() -> None:
    import pandas as pd
    from backtest.loaders.yfinance_loader import _normalize_frame

    frame = pd.DataFrame(
        {"Open": [10], "High": [11], "Low": [9], "Close": [10], "Volume": [100]},
        index=pd.DatetimeIndex(["2026-11-12 09:30"], tz="America/New_York"),
    )
    minute = _normalize_frame(frame, "1m")
    assert minute.index.tz is None
    assert minute.attrs["timezone"] == "America/New_York"
    assert minute.attrs["timestamp_basis"] == "bar_open"
    month = _normalize_frame(frame, "1M")
    assert month.attrs["timestamp_basis"] == "session_date"
    unknown = _normalize_frame(frame.tz_localize(None), "1m")
    assert "timezone" not in unknown.attrs
