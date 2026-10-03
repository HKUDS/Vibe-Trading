"""Public portfolio risk tool annualizes weekly/monthly bars by their frequency."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from src.tools.portfolio_risk_tool import PortfolioRiskXrayTool


@pytest.mark.parametrize(
    "interval,frequency,annual_bars",
    [
        ("1W", "W-FRI", 52),
        ("1w", "W-FRI", 52),
        ("1M", "MS", 12),
        ("1D", "B", 252),
        ("1m", "min", 252),
    ],
)
def test_public_tool_annualizes_calendar_bars(
    interval: str, frequency: str, annual_bars: int
) -> None:
    closes = 100 * np.cumprod(1 + np.tile([0.02, -0.01, 0.005, -0.015], 15))
    dates = pd.date_range("2020-01-01", periods=len(closes), freq=frequency)
    records = [
        {"date": date.isoformat(), "close": float(close)}
        for date, close in zip(dates, closes)
    ]
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return {"AAA": records}

    result = json.loads(
        PortfolioRiskXrayTool(data_fetcher=fetch).execute(
            symbols=["AAA"],
            interval=interval,
            start_date="2020-01-01",
            end_date="2026-01-01",
        )
    )
    assert result["status"] == "ok"
    assert calls[0]["interval"] == interval
    vol = result["data"]["volatility"]
    assert vol["daily_vol"] > 0
    observed_vol = pd.Series(closes).pct_change(fill_method=None).dropna().std(ddof=1)
    assert vol["annualized_vol"] == pytest.approx(observed_vol * math.sqrt(annual_bars))
