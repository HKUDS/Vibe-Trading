"""Tests for enhanced backtest validation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.enhanced_validation import (
    parameter_sensitivity,
    regime_conditioned_backtest,
    run_enhanced_validation,
    stress_scenarios,
    walk_forward_oos,
)
from backtest.validation import run_validation


def _equity(n: int = 200, seed: int = 11) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.015, n)
    eq = 1_000_000 * np.cumprod(1 + rets)
    return pd.Series(eq, index=pd.bdate_range("2022-01-03", periods=n))


class TestStress:
    def test_default_scenarios(self) -> None:
        result = stress_scenarios(_equity())
        assert result["n_scenarios"] >= 4
        assert result["baseline"]["sharpe"] is not None
        assert result["worst_return_scenario"]

    def test_custom_scenario(self) -> None:
        result = stress_scenarios(
            _equity(),
            scenarios=[{"name": "custom", "shock_return": -0.15, "spread_bars": 3}],
        )
        assert result["scenarios"][0]["name"] == "custom"
        assert result["scenarios"][0]["delta_return"] <= 0


class TestWalkForwardOOS:
    def test_rolling_folds(self) -> None:
        result = walk_forward_oos(_equity(300), n_windows=4, mode="rolling")
        assert "error" not in result
        assert result["n_windows"] == 4
        assert "oos_sharpe_mean" in result
        assert all("sharpe_degradation" in f for f in result["folds"])

    def test_expanding_mode(self) -> None:
        result = walk_forward_oos(_equity(250), n_windows=3, mode="expanding")
        assert result["mode"] == "expanding"


class TestSensitivity:
    def test_grid_stability(self) -> None:
        result = parameter_sensitivity(
            _equity(),
            return_scales=(0.8, 1.0, 1.2),
            vol_scales=(1.0, 1.5),
            cost_drags_bps=(0.0, 10.0),
        )
        assert result["n_combinations"] == 3 * 2 * 2
        assert 0.0 <= result["stability_rate"] <= 1.0
        assert result["best"]["sharpe"] >= result["worst"]["sharpe"]


class TestRegime:
    def test_high_low_split(self) -> None:
        result = regime_conditioned_backtest(_equity(180), vol_window=15)
        assert "high_vol" in result["regimes"]
        assert "low_vol" in result["regimes"]
        assert "sharpe_spread_high_minus_low" in result


class TestDispatcher:
    def test_run_validation_includes_enhanced(self) -> None:
        eq = _equity(180)
        result = run_validation(
            {
                "validation": {
                    "stress": {},
                    "walk_forward_oos": {"n_windows": 3},
                    "parameter_sensitivity": {
                        "return_scales": [1.0],
                        "vol_scales": [1.0],
                        "cost_drags_bps": [0.0],
                    },
                    "regime_conditioned": {"vol_window": 10},
                    "monte_carlo_paths": {"method": "bootstrap", "n_paths": 100, "horizon": 40},
                }
            },
            eq,
            trades=[],
            initial_capital=float(eq.iloc[0]),
        )
        assert "stress" in result
        assert "walk_forward_oos" in result
        assert "parameter_sensitivity" in result
        assert "regime_conditioned" in result
        assert "monte_carlo_paths" in result

    def test_enhanced_runner_direct(self) -> None:
        out = run_enhanced_validation({"stress": {}}, _equity(), trades=[])
        assert "stress" in out
