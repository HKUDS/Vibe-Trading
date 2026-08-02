"""Tests for large-batch Monte Carlo path simulation."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backtest.monte_carlo import (
    aggregate_path_outcomes,
    run_monte_carlo_from_config,
    run_monte_carlo_paths,
)


def _equity(n: int = 120, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, n)
    eq = 100_000 * np.cumprod(1 + rets)
    return pd.Series(eq, index=pd.bdate_range("2024-01-02", periods=n))


class TestAggregateOutcomes:
    def test_percentiles_and_ruin(self) -> None:
        tw = np.array([40_000.0, 80_000.0, 100_000.0, 120_000.0, 150_000.0])
        mdd = np.array([-0.5, -0.2, -0.1, -0.05, -0.01])
        out = aggregate_path_outcomes(tw, mdd, initial_capital=100_000.0, ruin_level=0.5)
        assert out["n_paths"] == 5
        assert out["ruin_probability"] == pytest.approx(0.2)
        assert "p50" in out["terminal_wealth"]["percentiles"]
        assert out["expected_shortfall_return"] >= 0


class TestMonteCarloPaths:
    def test_bootstrap_structure(self) -> None:
        result = run_monte_carlo_paths(
            method="bootstrap",
            equity_curve=_equity(),
            n_paths=500,
            batch_size=200,
            seed=42,
            horizon=60,
        )
        assert "error" not in result
        assert result["n_paths"] == 500
        assert result["method"] == "bootstrap"
        assert "outcomes" in result
        assert "equity_paths" in result
        assert result["outcomes"]["terminal_wealth"]["percentiles"]["p50"] > 0

    def test_gbm_reproducible(self) -> None:
        eq = _equity()
        a = run_monte_carlo_paths(method="gbm", equity_curve=eq, n_paths=300, seed=7, horizon=40)
        b = run_monte_carlo_paths(method="gbm", equity_curve=eq, n_paths=300, seed=7, horizon=40)
        assert a["outcomes"]["ruin_probability"] == b["outcomes"]["ruin_probability"]
        assert a["outcomes"]["terminal_wealth"]["mean"] == b["outcomes"]["terminal_wealth"]["mean"]

    def test_block_bootstrap(self) -> None:
        result = run_monte_carlo_paths(
            method="block_bootstrap",
            equity_curve=_equity(),
            n_paths=200,
            batch_size=100,
            block_size=10,
            horizon=50,
            seed=3,
        )
        assert result["calibration"]["block_size"] == 10
        assert result["outcomes"]["n_paths"] == 200

    def test_progress_callback(self) -> None:
        events = []

        def cb(stage, current, total, message):
            events.append((stage, current, total))

        run_monte_carlo_paths(
            method="bootstrap",
            equity_curve=_equity(),
            n_paths=250,
            batch_size=100,
            horizon=30,
            progress=cb,
        )
        assert events
        assert events[-1][0] == "done"
        assert events[-1][1] == 250

    @pytest.mark.parametrize("n_paths", [0, -1, True, "10"])
    def test_invalid_n_paths(self, n_paths: object) -> None:
        result = run_monte_carlo_paths(
            method="bootstrap",
            equity_curve=_equity(),
            n_paths=n_paths,  # type: ignore[arg-type]
        )
        assert "error" in result

    def test_raw_returns_input(self) -> None:
        rets = list(np.random.default_rng(0).normal(0.001, 0.02, 80))
        result = run_monte_carlo_paths(
            method="bootstrap",
            returns=rets,
            n_paths=100,
            horizon=40,
            initial_capital=50_000,
        )
        assert result["outcomes"]["initial_capital"] == 50_000

    def test_large_batch_smoke(self) -> None:
        """Scale check: 50k paths should complete quickly when vectorized."""
        result = run_monte_carlo_paths(
            method="gbm",
            equity_curve=_equity(80),
            n_paths=50_000,
            batch_size=10_000,
            horizon=30,
            seed=1,
            keep_fan_chart=False,
        )
        assert result["outcomes"]["n_paths"] == 50_000


class TestConfigDispatch:
    def test_from_config_bootstrap(self) -> None:
        result = run_monte_carlo_from_config(
            {"method": "bootstrap", "n_paths": 200, "horizon": 40, "seed": 1},
            _equity(),
            initial_capital=100_000,
        )
        assert result["method"] == "bootstrap"
        assert result["n_paths"] == 200

    def test_tool_json_roundtrip_shape(self) -> None:
        from src.tools.monte_carlo_tool import run_monte_carlo_tool

        raw = run_monte_carlo_tool(
            returns=list(np.random.default_rng(2).normal(0.0, 0.01, 60)),
            n_paths=150,
            horizon=30,
            method="bootstrap",
            initial_capital=10_000,
        )
        payload = json.loads(raw)
        assert payload["status"] == "ok"
        assert payload["result"]["outcomes"]["n_paths"] == 150
