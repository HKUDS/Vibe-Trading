"""Benchmark performance must use the same dates as the portfolio."""

import pandas as pd
import pytest

from backtest.metrics import calc_metrics


def test_benchmark_return_excludes_observations_outside_equity_window():
    dates = pd.date_range("2025-01-02", periods=2)
    equity = pd.Series([110.0, 121.0], index=dates)
    benchmark = pd.Series(
        [0.50, 0.10, 0.10, -0.50],
        index=pd.date_range("2025-01-01", periods=4),
    )

    metrics = calc_metrics(equity, [], 100.0, bench_ret=benchmark)

    assert metrics["benchmark_return"] == pytest.approx(0.21)
    assert metrics["excess_return"] == pytest.approx(0.0)
    assert metrics["tracking_error"] == pytest.approx(0.0)
