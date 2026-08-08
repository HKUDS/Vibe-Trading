"""Regression: the information ratio's denominator must be reported.

``calc_metrics`` computed the annualised active-return standard deviation to
form the information ratio and then discarded it, so the 18-key return carried
no tracking error and no benchmark beta — the two numbers a benchmark-relative
mandate is written around.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import calc_metrics

_DATES = pd.bdate_range("2025-01-01", periods=60)


def _series(values):
    return pd.Series(values, index=_DATES)


def _equity(returns):
    return (1.0 + _series(returns)).cumprod() * 100_000.0


def _metrics(port_returns, bench_returns):
    # calc_metrics derives portfolio returns with pct_change().fillna(0), so the
    # first bar is always zero. Zero the benchmark's first bar too, or the two
    # series are off by one observation and every comparison is contaminated.
    port = np.asarray(port_returns, dtype=float).copy()
    bench = np.asarray(bench_returns, dtype=float).copy()
    port[0] = 0.0
    bench[0] = 0.0
    return calc_metrics(_equity(port), [], 100_000.0, bench_ret=_series(bench))


class TestTrackingError:
    def test_a_portfolio_that_tracks_exactly_has_no_tracking_error(self):
        rng = np.random.default_rng(7)
        bench = rng.normal(0.0005, 0.01, len(_DATES))

        metrics = _metrics(bench, bench)

        assert metrics["tracking_error"] == pytest.approx(0.0, abs=1e-9)

    def test_tracking_error_is_annualised(self):
        rng = np.random.default_rng(11)
        bench = rng.normal(0.0005, 0.01, len(_DATES))
        active = rng.normal(0.0, 0.004, len(_DATES))

        metrics = _metrics(bench + active, bench)
        expected = float(pd.Series(active).std()) * np.sqrt(252)

        assert metrics["tracking_error"] == pytest.approx(expected, rel=0.05)

    def test_it_is_present_even_with_no_benchmark(self):
        metrics = calc_metrics(_equity(np.zeros(len(_DATES))), [], 100_000.0)

        assert metrics["tracking_error"] == 0.0
        assert metrics["benchmark_beta"] == 0.0


class TestBenchmarkBeta:
    def test_a_portfolio_identical_to_the_benchmark_has_beta_one(self):
        rng = np.random.default_rng(3)
        bench = rng.normal(0.0005, 0.01, len(_DATES))

        metrics = _metrics(bench, bench)

        assert metrics["benchmark_beta"] == pytest.approx(1.0, abs=1e-6)

    def test_a_double_exposure_portfolio_has_beta_two(self):
        rng = np.random.default_rng(5)
        bench = rng.normal(0.0005, 0.01, len(_DATES))

        metrics = _metrics(bench * 2.0, bench)

        assert metrics["benchmark_beta"] == pytest.approx(2.0, rel=0.02)

    def test_a_flat_benchmark_yields_zero_rather_than_a_division_blowup(self):
        rng = np.random.default_rng(13)

        metrics = _metrics(rng.normal(0.0, 0.01, len(_DATES)), np.zeros(len(_DATES)))

        assert metrics["benchmark_beta"] == 0.0
