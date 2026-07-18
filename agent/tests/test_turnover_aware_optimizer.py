"""Tests for the turnover-aware optimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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


# ---------------------------------------------------------------------------
# Exposure caps
# ---------------------------------------------------------------------------


class TestExposureCaps:
    def _ctx(self, n_assets: int = 5, seed: int = 42) -> dict:
        rng = np.random.default_rng(seed)
        mu = rng.normal(0.001, 0.02, n_assets)
        A = rng.standard_normal((120, n_assets))
        cov = np.cov(A.T)
        return {"cov": cov, "mu": mu, "active": [f"A{i}" for i in range(n_assets)]}

    # — per-name caps —

    def test_per_name_cap_enforced(self) -> None:
        opt = TurnoverAwareOptimizer(max_per_name=0.3)
        w = opt._calc_weights(self._ctx())
        assert w.max() <= 0.3 + 1e-6

    def test_per_name_cap_none_behaves_like_uncapped(self) -> None:
        ctx = self._ctx()
        w_capped = TurnoverAwareOptimizer(max_per_name=0.3)._calc_weights(ctx)
        w_free = TurnoverAwareOptimizer()._calc_weights(ctx)
        assert (w_capped <= 0.3 + 1e-6).all()
        assert (w_free <= 1.0 + 1e-6).all()

    def test_uncapped_second_rebalance_starts_from_previous_weights(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from scipy import optimize as scipy_optimize

        real_minimize = scipy_optimize.minimize
        initial_weights: list[np.ndarray] = []

        def capture_initial_weights(fun, x0, *args, **kwargs):
            initial_weights.append(np.asarray(x0, dtype=float).copy())
            return real_minimize(fun, x0, *args, **kwargs)

        monkeypatch.setattr(scipy_optimize, "minimize", capture_initial_weights)
        optimizer = TurnoverAwareOptimizer(turnover_penalty=0.5)
        first_weights = optimizer._calc_weights(self._ctx())
        optimizer._calc_weights(self._ctx())

        np.testing.assert_array_equal(initial_weights[-1], first_weights)

    def test_tight_per_name_cap_spreads_weights(self) -> None:
        n = 10
        ctx = self._ctx(n_assets=n)
        w = TurnoverAwareOptimizer(max_per_name=0.12)._calc_weights(ctx)  # 10*0.12=1.2 feasible
        assert w.max() <= 0.12 + 1e-6
        assert w.sum() == pytest.approx(1.0)

    # — per-group caps —

    def test_per_group_cap_enforced(self) -> None:
        ctx = self._ctx()
        groups = {"A0": "tech", "A1": "tech", "A2": "finance", "A3": "finance", "A4": "other"}
        opt = TurnoverAwareOptimizer(
            groups=groups, max_per_group={"tech": 0.4, "finance": 0.35}
        )
        w = opt._calc_weights(ctx)
        active = ctx["active"]
        tech_sum = sum(w[i] for i, c in enumerate(active) if groups.get(c) == "tech")
        fin_sum = sum(w[i] for i, c in enumerate(active) if groups.get(c) == "finance")
        assert tech_sum <= 0.4 + 1e-6
        assert fin_sum <= 0.35 + 1e-6
        assert w.sum() == pytest.approx(1.0)

    def test_unmapped_assets_not_constrained(self) -> None:
        ctx = self._ctx()
        groups = {"A0": "tech"}  # only A0 mapped
        opt = TurnoverAwareOptimizer(groups=groups, max_per_group={"tech": 0.15})
        w = opt._calc_weights(ctx)
        tech_sum = w[0]  # A0 is index 0
        assert tech_sum <= 0.15 + 1e-6
        assert w.sum() == pytest.approx(1.0)

    def test_empty_group_skipped_safely(self) -> None:
        ctx = self._ctx()
        groups = {"NOT_ACTIVE": "nonexistent"}
        opt = TurnoverAwareOptimizer(
            groups=groups, max_per_group={"nonexistent": 0.1}
        )
        w = opt._calc_weights(ctx)  # should not raise
        assert w.sum() == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "cap", [0, -0.1, 1.1, float("inf"), float("nan"), True, np.bool_(True)]
    )
    def test_invalid_per_name_cap_rejected(self, cap: object) -> None:
        with pytest.raises(ValueError, match="max_per_name"):
            TurnoverAwareOptimizer(max_per_name=cap)

    def test_unknown_group_cap_rejected(self) -> None:
        with pytest.raises(ValueError, match="no mapped assets"):
            TurnoverAwareOptimizer(
                groups={"A0": "tech"}, max_per_group={"finance": 0.5}
            )

    @pytest.mark.parametrize("cap", [True, np.bool_(False)])
    def test_boolean_group_cap_rejected(self, cap: object) -> None:
        with pytest.raises(ValueError, match="not boolean"):
            TurnoverAwareOptimizer(
                groups={"A0": "tech"}, max_per_group={"tech": cap}
            )

    def test_infeasible_per_name_cap_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="infeasible"):
            TurnoverAwareOptimizer(max_per_name=0.19)._calc_weights(self._ctx())

    def test_infeasible_active_group_cap_fails_closed(self) -> None:
        ctx = self._ctx(n_assets=2)
        groups = {"A0": "tech", "A1": "tech", "NOT_ACTIVE": "other"}
        with pytest.raises(ValueError, match="infeasible"):
            TurnoverAwareOptimizer(
                groups=groups,
                max_per_group={"tech": 0.5, "other": 0.5},
            )._calc_weights(ctx)

    def test_solver_failure_does_not_return_equal_weight(self, monkeypatch) -> None:
        from scipy import optimize as scipy_optimize

        monkeypatch.setattr(
            scipy_optimize,
            "minimize",
            lambda *args, **kwargs: type(
                "FailedResult", (), {"success": False, "message": "forced failure"}
            )(),
        )
        with pytest.raises(RuntimeError, match="forced failure"):
            TurnoverAwareOptimizer(max_per_name=0.3)._calc_weights(self._ctx())

    def test_no_caps_unchanged(self) -> None:
        ctx = self._ctx()
        w1 = TurnoverAwareOptimizer()._calc_weights(ctx)
        w2 = TurnoverAwareOptimizer(
            max_per_name=None, groups=None, max_per_group=None
        )._calc_weights(ctx)
        np.testing.assert_allclose(w1, w2, atol=1e-10)

    def test_caps_work_together(self) -> None:
        ctx = self._ctx(n_assets=6)
        groups = {"A0": "tech", "A1": "tech", "A2": "tech"}
        opt = TurnoverAwareOptimizer(
            max_per_name=0.2,
            groups=groups,
            max_per_group={"tech": 0.4},
        )
        w = opt._calc_weights(ctx)
        assert w.max() <= 0.2 + 1e-6
        tech_sum = sum(w[i] for i in range(3))  # A0-A2 are group tech
        assert tech_sum <= 0.4 + 1e-6
        assert w.sum() == pytest.approx(1.0)
