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


@pytest.fixture
def local_price_file(tmp_path, monkeypatch):
    from backtest.loaders import base, local_loader
    from src.market_data import fetch_market_data

    dates = pd.bdate_range("2020-01-01", "2026-01-31")
    close = 100 * np.cumprod(1 + np.resize([0.002, -0.001, 0.0005, -0.0015], len(dates)))
    path = tmp_path / "calendar-prices.csv"
    pd.DataFrame(
        {"date": dates, "open": close, "high": close, "low": close,
         "close": close, "volume": 100}
    ).to_csv(path, index=False)
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: False)
    monkeypatch.setattr(
        local_loader, "_load_config",
        lambda: {"sources": [{"symbol": "AAA.US", "type": "csv", "path": str(path)}]},
    )

    def fetch(**kwargs):
        # Exercise real CSV filtering, the shared market-data resampler and
        # public tool shaping while keeping all data local to the fixture.
        return fetch_market_data(
            **kwargs, loader_resolver=lambda source: local_loader.DataLoader
        )

    return PortfolioRiskXrayTool(data_fetcher=fetch)


@pytest.mark.parametrize("end_date", ["2024-02-29", "2025-01-15", "2025-01-31"])
def test_monthly_default_range_supplies_enough_real_resampled_bars(
    local_price_file, end_date: str
) -> None:
    result = json.loads(local_price_file.execute(
        symbols=["AAA.US"], source="local", interval="1M", end_date=end_date
    ))
    assert result["status"] == "ok", result
    assert result["data"]["inputs"]["aligned_days"] >= 30
    assert result["data"]["volatility"]["annualized_vol"] == pytest.approx(
        result["data"]["volatility"]["daily_vol"] * math.sqrt(12)
    )
    # Calendar arithmetic preserves the day where possible, including leap day.
    assert result["meta"]["start_date"] == (
        pd.Timestamp(end_date) - pd.DateOffset(months=31)
    ).date().isoformat()


def test_explicit_short_monthly_range_still_fails_history_gate(local_price_file) -> None:
    result = json.loads(local_price_file.execute(
        symbols=["AAA.US"], source="local", interval="1M",
        start_date="2025-01-01", end_date="2026-01-01",
    ))
    assert result["status"] == "error"
    assert "at least 30 valid bars" in result["error"]


@pytest.mark.parametrize("interval", ["1D", "1W", "1m"])
def test_nonmonthly_default_range_keeps_one_year(interval: str) -> None:
    assert PortfolioRiskXrayTool._parse_dates(None, "2026-01-01", interval) == (
        "2025-01-01", "2026-01-01"
    )
