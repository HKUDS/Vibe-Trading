"""Tests for the turnover-aware optimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.optimizers.turnover_aware import TurnoverAwareOptimizer, optimize


def _sample_data(n_days: int = 200, n_assets: int = 4, seed: int = 0):
    """Return (ret, pos, dates) for a small long-only universe."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    codes = [f"A{i}" for i in range(n_assets)]
    ret = pd.DataFrame(
        rng.normal(0.001, 0.02, (n_days, n_assets)), index=dates, columns=codes
    )
    pos = pd.DataFrame(1.0, index=dates, columns=codes)
    return ret, pos, dates


class TestTurnoverAwareCalcWeights:
    """Unit tests for the core weight calculation."""

    def test_weights_sum_to_one(self) -> None:
        rng = np.random.default_rng(42)
        n = 5
        A = rng.standard_normal((120, n))
        ctx = {"cov": np.cov(A.T), "mu": A.mean(axis=0), "active": [f"A{i}" for i in range(n)]}
        opt = TurnoverAwareOptimizer(turnover_penalty=0.5)
        w = opt._calc_weights(ctx)
        assert abs(w.sum() - 1.0) < 1e-8

    def test_weights_nonnegative(self) -> None:
        rng = np.random.default_rng(7)
        n = 4
        A = rng.standard_normal((120, n))
        ctx = {"cov": np.cov(A.T), "mu": A.mean(axis=0), "active": [f"A{i}" for i in range(n)]}
        opt = TurnoverAwareOptimizer(turnover_penalty=0.5)
        w = opt._calc_weights(ctx)
        assert np.all(w >= -1e-9)

    def test_zero_penalty_is_path_independent(self) -> None:
        """With gamma=0 the prior weights must not affect the solution."""
        rng = np.random.default_rng(3)
        n = 4
        A = rng.standard_normal((120, n))
        codes = [f"A{i}" for i in range(n)]
        ctx = {"cov": np.cov(A.T), "mu": A.mean(axis=0), "active": codes}

        fresh = TurnoverAwareOptimizer(turnover_penalty=0.0)
        w_fresh = fresh._calc_weights(dict(ctx))

        seeded = TurnoverAwareOptimizer(turnover_penalty=0.0)
        seeded._prev = {codes[0]: 1.0}  # arbitrary prior concentration
        w_seeded = seeded._calc_weights(dict(ctx))

        np.testing.assert_allclose(w_fresh, w_seeded, atol=1e-4)

    def test_empty_active_set(self) -> None:
        opt = TurnoverAwareOptimizer()
        w = opt._calc_weights({"cov": np.empty((0, 0)), "mu": np.array([]), "active": []})
        assert len(w) == 0


class TestTurnoverAwareOptimize:
    """Integration tests through the module-level optimize()."""

    def test_higher_penalty_lowers_turnover(self) -> None:
        ret, pos, dates = _sample_data()

        low = TurnoverAwareOptimizer(lookback=60, risk_aversion=5.0, turnover_penalty=0.0)
        low.optimize(ret, pos, dates)

        high = TurnoverAwareOptimizer(lookback=60, risk_aversion=5.0, turnover_penalty=2.0)
        high.optimize(ret, pos, dates)

        assert sum(high.realized_turnover) <= sum(low.realized_turnover) + 1e-9

    def test_turnover_monotone_non_increasing_in_penalty(self) -> None:
        """Realized turnover must not rise as the penalty grows."""
        ret, pos, dates = _sample_data()
        totals = []
        for gamma in (0.0, 0.5, 1.0, 2.0, 5.0):
            opt = TurnoverAwareOptimizer(
                lookback=60, risk_aversion=5.0, turnover_penalty=gamma
            )
            opt.optimize(ret, pos, dates)
            totals.append(sum(opt.realized_turnover))
        assert all(totals[i] >= totals[i + 1] - 1e-9 for i in range(len(totals) - 1))

    def test_all_nan_column_does_not_raise(self) -> None:
        """A fully NaN asset column must not crash the optimizer."""
        ret, pos, dates = _sample_data()
        ret["A0"] = np.nan
        opt = TurnoverAwareOptimizer(lookback=60, turnover_penalty=0.5)
        result = opt.optimize(ret, pos, dates)
        assert result.shape == pos.shape

    def test_result_weights_on_simplex(self) -> None:
        ret, pos, dates = _sample_data()
        opt = TurnoverAwareOptimizer(lookback=60, risk_aversion=5.0, turnover_penalty=0.5)
        result = opt.optimize(ret, pos, dates)
        last = result.iloc[-1].values
        assert abs(last.sum() - 1.0) < 1e-6
        assert (last >= -1e-9).all()

    def test_preserves_sign(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=120)
        codes = ["A", "B"]
        rng = np.random.default_rng(11)
        ret = pd.DataFrame(rng.normal(0, 0.02, (120, 2)), index=dates, columns=codes)
        pos = pd.DataFrame(0.0, index=dates, columns=codes)
        pos.iloc[60:, 0] = 1.0
        pos.iloc[60:, 1] = -1.0

        result = optimize(ret, pos, dates, lookback=60, turnover_penalty=0.5)
        assert (result.iloc[61:, 0] >= 0).all()
        assert (result.iloc[61:, 1] <= 0).all()

    def test_short_window_and_nan_do_not_raise(self) -> None:
        ret, pos, dates = _sample_data(n_days=80)
        ret.iloc[10:20, 0] = np.nan
        opt = TurnoverAwareOptimizer(lookback=60, turnover_penalty=0.5)
        result = opt.optimize(ret, pos, dates)
        assert result.shape == pos.shape

    def test_turnover_recorded(self) -> None:
        ret, pos, dates = _sample_data()
        opt = TurnoverAwareOptimizer(lookback=60, turnover_penalty=0.5)
        opt.optimize(ret, pos, dates)
        assert len(opt.realized_turnover) > 0
        assert all(t >= 0.0 for t in opt.realized_turnover)

    def test_single_asset_unchanged(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=100)
        ret = pd.DataFrame(
            np.random.default_rng(1).normal(0, 0.02, (100, 1)), index=dates, columns=["A"]
        )
        pos = pd.DataFrame(1.0, index=dates, columns=["A"])
        result = optimize(ret, pos, dates, lookback=60)
        pd.testing.assert_frame_equal(result, pos)
