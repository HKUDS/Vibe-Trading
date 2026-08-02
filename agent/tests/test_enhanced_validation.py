"""Tests for enhanced backtest validation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.enhanced_validation import (
    parameter_sensitivity,
    regime_conditioned_backtest,
    regime_conditional_ic,
    regime_labels_to_frame,
    run_enhanced_validation,
    signal_engine_param_grid,
    signal_parameter_grid,
    stress_scenarios,
    walk_forward_oos,
)
from backtest.validation import run_validation


def _equity(n: int = 200, seed: int = 11) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.015, n)
    eq = 1_000_000 * np.cumprod(1 + rets)
    return pd.Series(eq, index=pd.bdate_range("2022-01-03", periods=n))


def _prices(n: int = 250, seed: int = 3) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    px = 100 * np.cumprod(1 + rets)
    return pd.Series(px, index=pd.bdate_range("2021-01-04", periods=n))


def _multi_asset_returns(n: int = 180, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    factor = rng.normal(0, 0.01, n)
    a = 0.7 * factor + 0.3 * rng.normal(0, 0.01, n)
    b = 0.7 * factor + 0.3 * rng.normal(0, 0.01, n)
    c = 0.2 * factor + 0.8 * rng.normal(0, 0.012, n)
    idx = pd.bdate_range("2022-06-01", periods=n)
    return pd.DataFrame({"A": a, "B": b, "C": c}, index=idx)


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


class TestMultiAxisRegime:
    def test_high_low_split(self) -> None:
        result = regime_conditioned_backtest(_equity(180), vol_window=15)
        assert "high_vol" in result["regimes"]
        assert "low_vol" in result["regimes"]
        assert "sharpe_spread_high_minus_low" in result

    def test_trend_and_vol_axes(self) -> None:
        result = regime_conditioned_backtest(_equity(220), vol_window=15, trend_window=40)
        assert "error" not in result
        assert "trend" in result["axes"]
        assert "uptrend" in result["regimes"]
        assert "downtrend" in result["regimes"]
        assert "vol_trend_cross" in result
        assert "sharpe_spread_up_minus_down" in result

    def test_trend_can_be_disabled(self) -> None:
        result = regime_conditioned_backtest(_equity(120), include_trend=False)
        assert result["axes"] == ["vol"]
        assert "uptrend" not in result["regimes"]

    def test_correlation_fused_integration(self) -> None:
        eq = _equity(180)
        rets = _multi_asset_returns(180)
        rets.index = eq.index
        result = regime_conditioned_backtest(
            eq,
            returns_matrix=rets,
            corr_window=30,
            enter_threshold=0.55,
            exit_threshold=0.35,
            include_trend=True,
            trend_window=30,
        )
        assert "correlation" in result["axes"]
        assert "fused" in result["regimes"]
        assert "defused" in result["regimes"]
        assert "sharpe_spread_fused_minus_defused" in result["correlation_regime"]


class TestSignalParameterGrid:
    def test_ma_crossover_grid(self) -> None:
        result = signal_parameter_grid(
            _prices(),
            strategy="ma_crossover",
            param_grid={"fast": [5, 10], "slow": [20, 40]},
            cost_bps=5.0,
        )
        assert "error" not in result
        assert result["n_combinations"] == 4
        assert result["best"]["sharpe"] >= result["worst"]["sharpe"]
        assert 0.0 <= result["stability_rate"] <= 1.0
        assert "True signal re-runs" in result["note"]

    def test_invalid_ma_pairs_filtered(self) -> None:
        result = signal_parameter_grid(
            _prices(),
            strategy="ma_crossover",
            param_grid={"fast": [30, 5], "slow": [20, 40]},
        )
        assert result["n_combinations"] == 3

    def test_custom_signal_fn(self) -> None:
        def always_long(prices, thresh=0.0):  # noqa: ANN001
            return pd.Series(1.0, index=prices.index)

        result = signal_parameter_grid(
            _prices(80),
            signal_fn=always_long,
            param_grid={"thresh": [0.0, 1.0]},
        )
        assert result["strategy"] == "custom"
        assert result["n_combinations"] == 2

    def test_rsi_and_macd_builtins(self) -> None:
        rsi = signal_parameter_grid(
            _prices(180),
            strategy="rsi_mean_reversion",
            param_grid={"period": [10, 14], "lower": [30.0], "upper": [70.0]},
        )
        macd = signal_parameter_grid(
            _prices(180),
            strategy="macd_crossover",
            param_grid={"fast": [8, 12], "slow": [26], "signal": [9]},
        )
        assert rsi["n_combinations"] == 2
        assert macd["n_combinations"] == 2

    def test_collect_trial_returns_cscv(self) -> None:
        result = signal_parameter_grid(
            _prices(200),
            strategy="ma_crossover",
            param_grid={"fast": [5, 10], "slow": [20, 40]},
            collect_trial_returns=True,
            pbo_n_groups=8,
        )
        assert "trial_returns" in result
        assert result["trial_returns_shape"][1] == 4
        assert "cscv_pbo" in result
        assert result["cscv_pbo"]["method"] == "cscv_exact"

    def test_signal_engine_adapter_grid(self) -> None:
        result = signal_engine_param_grid(
            _prices(160),
            strategy="ma_crossover",
            param_grid={"fast": [5, 10], "slow": [30]},
            collect_trial_returns=True,
            pbo_n_groups=4,
        )
        assert "error" not in result
        assert result["interface"] == "SignalEngine.generate"
        assert result["n_combinations"] == 2
        assert "cscv_pbo" in result

    def test_regime_labels_export(self) -> None:
        result = regime_conditioned_backtest(
            _equity(180),
            include_trend=True,
            trend_window=30,
            export_regime_labels=True,
        )
        assert "regime_labels" in result
        assert "vol" in result["regime_labels"]
        assert "trend" in result["regime_labels"]
        frame = regime_labels_to_frame(result)
        assert not frame.empty
        assert "vol" in frame.columns

    def test_regime_conditional_ic(self) -> None:
        eq = _equity(160)
        regime = regime_conditioned_backtest(
            eq, include_trend=False, export_regime_labels=True, vol_window=10
        )
        idx = eq.index
        rng = np.random.default_rng(12)
        cols = [f"A{i}" for i in range(10)]
        factor = pd.DataFrame(rng.normal(0, 1, size=(len(idx), 10)), index=idx, columns=cols)
        rets = pd.DataFrame(
            0.1 * factor.to_numpy() + rng.normal(0, 0.05, size=factor.shape),
            index=idx,
            columns=cols,
        )
        out = regime_conditional_ic(
            factor, rets, regime_result=regime, axis="vol", min_obs=5
        )
        assert "error" not in out
        assert "overall" in out
        assert out["overall"]["mean_ic"] is not None
        assert "by_regime" in out
        assert "high_vol" in out["by_regime"] or "low_vol" in out["by_regime"]

    def test_signal_engine_rejects_forbidden_import(self, tmp_path) -> None:
        bad = tmp_path / "signal_engine.py"
        bad.write_text(
            "import os\nclass SignalEngine:\n    def __init__(self, **kw): pass\n"
            "    def generate(self, data_map): return {}\n",
            encoding="utf-8",
        )
        out = signal_engine_param_grid(
            _prices(80),
            param_grid={"fast": [5], "slow": [20]},
            module_path=bad,
            allow_roots=[tmp_path],
        )
        assert "error" in out
        assert "forbidden import" in out["error"]

    def test_signal_engine_rejects_path_outside_roots(self, tmp_path) -> None:
        # File lives under tmp_path but allow_roots points elsewhere.
        eng = tmp_path / "signal_engine.py"
        eng.write_text(
            "class SignalEngine:\n"
            "    def __init__(self, fast=5, slow=20):\n"
            "        self.fast, self.slow = fast, slow\n"
            "    def generate(self, data_map):\n"
            "        import pandas as pd\n"
            "        out = {}\n"
            "        for s, df in data_map.items():\n"
            "            c = df['close']\n"
            "            out[s] = (c.rolling(self.fast).mean() > "
            "c.rolling(self.slow).mean()).astype(float).fillna(0.0)\n"
            "        return out\n",
            encoding="utf-8",
        )
        other = tmp_path / "other_root"
        other.mkdir()
        out = signal_engine_param_grid(
            _prices(100),
            param_grid={"fast": [5], "slow": [20]},
            module_path=eng,
            allow_roots=[other],
        )
        assert "error" in out
        assert "outside allow_roots" in out["error"]

    def test_signal_engine_safe_module_loads(self, tmp_path) -> None:
        eng = tmp_path / "signal_engine.py"
        eng.write_text(
            "class SignalEngine:\n"
            "    def __init__(self, fast=5, slow=20):\n"
            "        self.fast = int(fast)\n"
            "        self.slow = int(slow)\n"
            "    def generate(self, data_map):\n"
            "        out = {}\n"
            "        for s, df in data_map.items():\n"
            "            c = df['close'].astype(float)\n"
            "            f = c.rolling(self.fast).mean()\n"
            "            sl = c.rolling(self.slow).mean()\n"
            "            out[s] = (f > sl).astype(float).fillna(0.0)\n"
            "        return out\n",
            encoding="utf-8",
        )
        out = signal_engine_param_grid(
            _prices(120),
            param_grid={"fast": [5, 8], "slow": [30]},
            module_path=eng,
            allow_roots=[tmp_path],
            collect_trial_returns=True,
            pbo_n_groups=4,
        )
        assert "error" not in out
        assert out["module_path_security"] == "allow_roots+ast_scan"
        assert out["n_combinations"] == 2


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
                    "regime_conditioned": {"vol_window": 10, "include_trend": False},
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

    def test_new_keys_dispatch(self) -> None:
        eq = _equity(160)
        result = run_validation(
            {
                "validation": {
                    "signal_parameter_grid": {
                        "strategy": "ma_crossover",
                        "param_grid": {"fast": [5], "slow": [20]},
                    },
                    "regime_conditioned": {"include_trend": True, "trend_window": 20},
                    "risk_metrics": {"n_trials": 5, "n_bootstrap": 200},
                }
            },
            eq,
            trades=[],
            initial_capital=float(eq.iloc[0]),
        )
        assert "signal_parameter_grid" in result
        assert "regime_conditioned" in result
        assert "risk_metrics" in result
        assert "deflated_sharpe" in result["risk_metrics"]

    def test_enhanced_runner_direct(self) -> None:
        out = run_enhanced_validation({"stress": {}}, _equity(), trades=[])
        assert "stress" in out

    def test_enhanced_runner_signal_grid(self) -> None:
        out = run_enhanced_validation(
            {
                "signal_parameter_grid": {
                    "strategy": "breakout",
                    "param_grid": {"lookback": [10], "exit_lookback": [5]},
                }
            },
            _equity(100),
            trades=[],
        )
        assert out["signal_parameter_grid"]["n_combinations"] == 1
