"""Tests for PSR / DSR / PBO risk metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest.risk_metrics import (
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    run_risk_metrics,
)


def _equity(n: int = 252, seed: int = 9, mu: float = 0.001, sigma: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(mu, sigma, n)
    eq = 100_000 * np.cumprod(1 + rets)
    return pd.Series(eq, index=pd.bdate_range("2023-01-03", periods=n))


class TestPSR:
    def test_strong_edge_high_psr(self) -> None:
        # High Sharpe, many obs → PSR vs 0 should be near 1.
        out = probabilistic_sharpe_ratio(2.0, n_obs=500, skew=0.0, kurtosis=3.0)
        assert out["psr"] > 0.95

    def test_zero_sharpe_near_half(self) -> None:
        out = probabilistic_sharpe_ratio(0.0, n_obs=200, skew=0.0, kurtosis=3.0)
        assert out["psr"] == pytest.approx(0.5, abs=0.02)


class TestDSR:
    def test_expected_max_increases_with_trials(self) -> None:
        e1 = expected_max_sharpe(1)
        e10 = expected_max_sharpe(10)
        e100 = expected_max_sharpe(100)
        assert e1 == 0.0
        assert e10 > e1
        assert e100 > e10

    def test_dsr_falls_with_more_trials(self) -> None:
        d1 = deflated_sharpe_ratio(1.5, n_obs=400, n_trials=1)
        d50 = deflated_sharpe_ratio(1.5, n_obs=400, n_trials=50)
        assert d1["dsr"] >= d50["dsr"]
        assert d50["expected_max_sharpe"] > d1["expected_max_sharpe"]


class TestPBO:
    def test_requires_enough_trials(self) -> None:
        assert "error" in probability_of_backtest_overfitting([1.0, 0.5, 0.2])

    def test_approx_runs(self) -> None:
        rng = np.random.default_rng(0)
        trials = list(rng.normal(0.5, 1.0, 20))
        out = probability_of_backtest_overfitting(trials, n_splits=16, seed=1)
        assert 0.0 <= out["pbo"] <= 1.0
        assert out["method"] == "cscv_sharpe_vector_approx"

    def test_cscv_exact_on_return_matrix(self) -> None:
        rng = np.random.default_rng(3)
        # T=128, N=6 independent trials — low overfitting expected.
        mat = rng.normal(0.0005, 0.01, size=(128, 6))
        out = cscv_probability_of_backtest_overfitting(mat, n_groups=8)
        assert "error" not in out
        assert out["method"] == "cscv_exact"
        assert out["n_combinations"] == 70  # C(8,4)
        assert 0.0 <= out["pbo"] <= 1.0
        assert 0.0 <= out["pbo_logit"] <= 1.0

    def test_cscv_elevated_for_many_noise_trials(self) -> None:
        rng = np.random.default_rng(0)
        # Large trial universe of pure noise → PBO near coin-flip.
        mat = rng.normal(0.0001, 0.015, size=(256, 50))
        out = cscv_probability_of_backtest_overfitting(mat, n_groups=8)
        assert "error" not in out
        assert out["pbo"] >= 0.35
        assert out["method"] == "cscv_exact"

    def test_cscv_rejects_odd_groups(self) -> None:
        mat = np.random.default_rng(0).normal(0, 0.01, size=(64, 4))
        assert "error" in cscv_probability_of_backtest_overfitting(mat, n_groups=5)

    def test_cscv_random_subsample_when_groups_large(self) -> None:
        # C(20,10)=184756 ≫ max_combinations → random subsample path.
        rng = np.random.default_rng(5)
        mat = rng.normal(0.0003, 0.01, size=(400, 8))
        out = cscv_probability_of_backtest_overfitting(mat, n_groups=20, max_combinations=200, seed=11)
        assert "error" not in out
        assert out["method"] == "cscv_random_subsample"
        assert out["subsampled"] is True
        assert out["n_combinations"] == 200
        assert out["n_combinations_full"] == 184_756
        assert 0.0 <= out["pbo"] <= 1.0

    def test_cscv_subsample_reproducible(self) -> None:
        rng = np.random.default_rng(6)
        mat = rng.normal(0.0002, 0.012, size=(320, 6))
        a = cscv_probability_of_backtest_overfitting(mat, n_groups=18, max_combinations=100, seed=99)
        b = cscv_probability_of_backtest_overfitting(mat, n_groups=18, max_combinations=100, seed=99)
        assert a["pbo"] == b["pbo"]
        assert a["n_combinations"] == b["n_combinations"]

    def test_cscv_forced_subsample_via_low_cap(self) -> None:
        # Even with n_groups=8 (exact would be 70), a tiny cap triggers subsample.
        rng = np.random.default_rng(7)
        mat = rng.normal(0.0004, 0.01, size=(128, 5))
        out = cscv_probability_of_backtest_overfitting(mat, n_groups=8, max_combinations=12, seed=3)
        assert out["method"] == "cscv_random_subsample"
        assert out["n_combinations"] == 12
        assert out["n_combinations_full"] == 70


class TestBundle:
    def test_run_risk_metrics(self) -> None:
        out = run_risk_metrics(_equity(), n_trials=10, n_bootstrap=300, seed=2)
        assert "error" not in out
        assert "probabilistic_sharpe" in out
        assert "deflated_sharpe" in out
        assert "bootstrap_sharpe_ci" in out
        assert math.isfinite(out["observed_sharpe"])

    def test_pbo_requires_trials_flag(self) -> None:
        out = run_risk_metrics(_equity(120), include_pbo=True)
        assert "error" in out["pbo"]

    def test_pbo_with_trials(self) -> None:
        out = run_risk_metrics(
            _equity(120),
            include_pbo=True,
            trial_sharpes=list(np.linspace(-0.5, 2.0, 12)),
            n_bootstrap=100,
        )
        assert "pbo" in out["pbo"]
        assert out["pbo"]["method"] == "cscv_sharpe_vector_approx"

    def test_pbo_prefers_exact_cscv_matrix(self) -> None:
        rng = np.random.default_rng(4)
        mat = rng.normal(0.0004, 0.01, size=(96, 5))
        out = run_risk_metrics(
            _equity(120),
            include_pbo=True,
            trial_returns=mat,
            trial_sharpes=[1.0, 2.0, 0.5, 0.1, -0.2],  # ignored when matrix present
            pbo_n_groups=8,
            n_bootstrap=50,
        )
        assert out["pbo"]["method"] == "cscv_exact"
