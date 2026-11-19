"""Tail and distribution-shape metrics for the backtest summary.

``calc_metrics`` already reports Sharpe/Sortino/Calmar and trade statistics but
nothing about the shape of the return distribution. Options and tail-sensitive
research need the Omega ratio (gain/loss mass around a threshold) and the tail
ratio (right tail versus left tail), plus the return skew and kurtosis that
govern option-seller risk. This module pins those numbers and their numerical
boundaries: no downside mass, zero-variance samples, and non-finite equity.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import calc_metrics

_DATES = pd.bdate_range("2025-01-01", periods=8)


def _equity(returns):
    """Turn a per-bar return path into an equity curve on ``_DATES``.

    ``calc_metrics`` rebuilds returns with ``pct_change().fillna(0)``, so the
    first bar always reads back as 0. The fixtures below therefore lead with 0
    so the recovered series matches the intended arithmetic exactly.
    """
    return (1.0 + pd.Series(returns, index=_DATES)).cumprod() * 100_000.0


def _metrics(returns):
    return calc_metrics(_equity(returns), [], 100_000.0)


class TestOmegaRatio:
    def test_omega_is_gain_mass_over_loss_mass_at_zero_threshold(self):
        # Gains: 0.1 + 0.2 = 0.3. Losses: |-0.05| + |-0.1| = 0.15. Omega = 2.0.
        metrics = _metrics([0.0, 0.1, -0.05, 0.2, -0.1, 0.0, 0.0, 0.0])
        assert metrics["omega_ratio"] == pytest.approx(2.0)

    def test_omega_ignores_the_zero_threshold_bar_itself(self):
        # A flat bar (0.0) is neither gain nor loss mass. Where it sits in the
        # path must not change Omega.
        gain_then_loss = [0.0, 0.1, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0]
        zeros_first = [0.0, 0.0, 0.1, -0.1, 0.0, 0.0, 0.0, 0.0]
        assert _metrics(gain_then_loss)["omega_ratio"] == pytest.approx(1.0)
        assert _metrics(zeros_first)["omega_ratio"] == pytest.approx(1.0)

    def test_omega_is_none_when_no_return_falls_below_the_threshold(self):
        metrics = _metrics([0.0, 0.1, 0.2, 0.05, 0.0, 0.0, 0.0, 0.0])
        assert metrics["omega_ratio"] is None


class TestTailRatio:
    def test_tail_ratio_is_right_tail_over_left_tail_magnitude(self):
        returns = np.array([0.0, 0.3, -0.2, 0.1, -0.05, 0.02, -0.01, 0.0])
        metrics = _metrics(list(returns))
        expected = abs(np.percentile(returns, 95)) / abs(np.percentile(returns, 5))
        assert metrics["tail_ratio"] == pytest.approx(expected)

    def test_tail_ratio_is_none_when_the_left_tail_is_empty(self):
        # Every return is >= 0 so the 5th-percentile magnitude is zero.
        metrics = _metrics([0.0, 0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 0.0])
        assert metrics["tail_ratio"] is None


class TestReturnShape:
    def test_return_skew_and_kurtosis_match_the_sample_moments(self):
        returns = np.array([0.0, 0.2, -0.1, 0.05, -0.3, 0.1, -0.02, 0.04])
        metrics = _metrics(list(returns))
        expected = pd.Series(returns)
        assert metrics["return_skew"] == pytest.approx(float(expected.skew()))
        # pandas ``kurt`` is excess kurtosis (normal == 0).
        assert metrics["return_kurtosis"] == pytest.approx(float(expected.kurt()))

    def test_shape_moments_default_to_zero_on_a_flat_series(self):
        # Zero variance -> skew and excess kurtosis are undefined; report 0.0.
        metrics = _metrics([0.0] * 8)
        assert metrics["return_skew"] == 0.0
        assert metrics["return_kurtosis"] == 0.0

    def test_shape_moments_default_to_zero_on_a_tiny_sample(self):
        # Fewer than three observations cannot support a sample skew. Build a
        # two-bar equity curve directly so the recovered series is that short.
        equity = pd.Series([100_000.0, 110_000.0], index=_DATES[:2])
        metrics = calc_metrics(equity, [], 100_000.0)
        assert metrics["return_skew"] == 0.0
        assert metrics["return_kurtosis"] == 0.0


class TestEmptyShape:
    def test_empty_equity_still_reports_the_tail_shape_keys(self):
        # The no-data summary keeps a stable shape so consumers never KeyError.
        metrics = calc_metrics(pd.Series(dtype=float), [], 100_000.0)
        for key in ("omega_ratio", "tail_ratio", "return_skew", "return_kurtosis"):
            assert key in metrics


class TestNonFiniteGuard:
    def test_tail_shape_metrics_are_neutral_when_equity_touches_zero(self):
        # 100 -> 0 -> 50 makes pct_change emit inf/NaN; the risk ratios must not
        # leak a non-finite number into the summary.
        equity = pd.Series([100_000.0, 0.0, 50_000.0], index=_DATES[:3])
        metrics = calc_metrics(equity, [], 100_000.0)
        for key in ("omega_ratio", "tail_ratio", "return_skew", "return_kurtosis"):
            value = metrics[key]
            if value is not None:
                assert np.isfinite(value), f"{key} leaked non-finite {value}"
