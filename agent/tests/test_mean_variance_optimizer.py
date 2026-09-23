"""Tests for the mean-variance (max Sharpe) optimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.optimizers.mean_variance import MeanVarianceOptimizer


class TestMeanVarianceOptimize:
    """Integration tests for the module-level optimize function."""

    def test_optimize_preserves_sign(self) -> None:
        """Optimizer should preserve signal direction (long/short)."""
        dates = pd.bdate_range("2025-01-01", periods=100)
        codes = ["A", "B"]
        rng = np.random.default_rng(42)
        ret = pd.DataFrame(rng.normal(0, 0.02, (100, 2)), index=dates, columns=codes)
        pos = pd.DataFrame(0.0, index=dates, columns=codes)
        pos.iloc[60:, 0] = 1.0
        pos.iloc[60:, 1] = -1.0

        opt = MeanVarianceOptimizer(lookback=60)
        result = opt.optimize(ret, pos, dates)

        assert (result.iloc[61:, 0] >= 0).all(), "A should remain long"
        assert (result.iloc[61:, 1] <= 0).all(), "B should remain short"

    def test_strong_short_sized_above_weak_short(self) -> None:
        """A short with a strongly negative drift is a better short than one
        with near-zero drift, so it must receive more capital, not less.

        Regression: mu was the raw unsigned asset drift, so a strong short
        (very negative raw mu) scored as a bad "long" in the Sharpe
        objective and was starved of capital relative to a weak short
        (near-zero raw mu) -- sizing was inverted for the short book.
        """
        dates = pd.bdate_range("2025-01-01", periods=140)
        codes = ["WEAK", "STRONG"]
        rng = np.random.default_rng(7)
        weak_ret = rng.normal(-0.0005, 0.01, 140)
        strong_ret = rng.normal(-0.02, 0.01, 140)
        ret = pd.DataFrame({"WEAK": weak_ret, "STRONG": strong_ret}, index=dates)

        pos = pd.DataFrame(0.0, index=dates, columns=codes)
        pos.iloc[120:, 0] = -1.0
        pos.iloc[120:, 1] = -1.0

        opt = MeanVarianceOptimizer(lookback=120)
        result = opt.optimize(ret, pos, dates)
        last = result.iloc[-1]

        assert abs(last["STRONG"]) > abs(last["WEAK"])

    def test_hedged_pair_is_not_starved_by_asset_space_covariance(self) -> None:
        """A long and a short of two positively correlated assets hedge each
        other, so both legs must be funded.

        Regression on the other half of the same bug: signing only ``mu`` left
        the variance term in ASSET space, where the pair still reads +0.92
        correlated and diversification looks worthless. Measured on this
        fixture, the asset-covariance objective put 100% of the book on the
        long and 0% on the short; the position covariance (D Sigma D, off
        diagonal -9.4e-05 instead of +9.4e-05) splits it 0.514 / -0.486.
        """
        rng = np.random.default_rng(11)
        n = 200
        common = rng.normal(0, 0.01, n)
        dates = pd.bdate_range("2025-01-01", periods=n)
        ret = pd.DataFrame(
            {
                "LONG": 0.002 + common + rng.normal(0, 0.003, n),
                "SHORT": -0.0015 + common + rng.normal(0, 0.003, n),
            },
            index=dates,
        )
        assert ret.corr().iloc[0, 1] > 0.9  # the pair really is correlated

        pos = pd.DataFrame(0.0, index=dates, columns=["LONG", "SHORT"])
        pos.iloc[150:, 0] = 1.0
        pos.iloc[150:, 1] = -1.0

        result = MeanVarianceOptimizer(lookback=150).optimize(ret, pos, dates)
        last = result.iloc[-1]

        assert last["LONG"] > 0 and last["SHORT"] < 0
        assert abs(last["SHORT"]) > 0.3, "the hedging short must be funded"
        assert abs(last["LONG"]) > 0.3

    def test_single_asset_unchanged(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=100)
        ret = pd.DataFrame(
            np.random.default_rng(1).normal(0, 0.02, (100, 1)),
            index=dates,
            columns=["A"],
        )
        pos = pd.DataFrame(1.0, index=dates, columns=["A"])

        opt = MeanVarianceOptimizer(lookback=60)
        result = opt.optimize(ret, pos, dates)
        pd.testing.assert_frame_equal(result, pos)

    def test_result_weights_on_simplex(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=100)
        codes = ["A", "B", "C"]
        rng = np.random.default_rng(3)
        ret = pd.DataFrame(rng.normal(0, 0.02, (100, 3)), index=dates, columns=codes)
        pos = pd.DataFrame(1.0, index=dates, columns=codes)

        opt = MeanVarianceOptimizer(lookback=60)
        result = opt.optimize(ret, pos, dates)
        last = result.iloc[-1].values
        assert abs(abs(last).sum() - 1.0) < 1e-6
