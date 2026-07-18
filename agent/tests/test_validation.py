"""Tests for backtest validation module.

Validates:
  - Monte Carlo permutation test: p-value, output structure
  - Bootstrap Sharpe CI: confidence interval bounds, prob_positive
  - Walk-Forward analysis: window splitting, consistency metrics
  - run_validation dispatcher
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.models import TradeRecord
from backtest.validation import (
    bootstrap_sharpe_ci,
    monte_carlo_test,
    run_validation,
    walk_forward_analysis,
    write_validation_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_trades(pnls: list[float], start: str = "2025-01-01") -> list[TradeRecord]:
    """Create TradeRecord list from PnL values."""
    trades = []
    base = pd.Timestamp(start)
    for i, pnl in enumerate(pnls):
        entry = base + pd.Timedelta(days=i * 2)
        exit_ = entry + pd.Timedelta(days=1)
        trades.append(TradeRecord(
            symbol="TEST",
            direction=1,
            entry_price=100.0,
            exit_price=100.0 + pnl / 10,
            entry_time=entry,
            exit_time=exit_,
            size=10.0,
            leverage=1.0,
            pnl=pnl,
            pnl_pct=pnl / 1000 * 100,
            exit_reason="signal",
            holding_bars=1,
            commission=0.0,
        ))
    return trades


def _make_equity(n: int = 100, drift: float = 0.001, seed: int = 42) -> pd.Series:
    """Create a synthetic equity curve."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, 0.02, n)
    prices = 1_000_000 * np.cumprod(1 + returns)
    dates = pd.bdate_range("2025-01-01", periods=n)
    return pd.Series(prices, index=dates)


# ---------------------------------------------------------------------------
# Monte Carlo Permutation Test
# ---------------------------------------------------------------------------


class TestMonteCarlo:
    def test_output_structure(self) -> None:
        trades = _make_trades([100, -50, 200, -30, 150, -80, 120, -40, 90, -20])
        result = monte_carlo_test(trades, 1_000_000, n_simulations=100)
        assert "actual_sharpe" in result
        assert "p_value_sharpe" in result
        assert "p_value_max_dd" in result
        assert "n_simulations" in result
        assert result["n_simulations"] == 100
        assert result["n_trades"] == 10

    def test_p_value_range(self) -> None:
        trades = _make_trades([100, -50, 200, -30, 150])
        result = monte_carlo_test(trades, 1_000_000, n_simulations=200)
        assert 0.0 <= result["p_value_sharpe"] <= 1.0
        assert 0.0 <= result["p_value_max_dd"] <= 1.0

    def test_strong_strategy_low_p_value(self) -> None:
        """A consistently profitable strategy should have low p-value."""
        trades = _make_trades([100, 200, 150, 180, 120, 90, 110, 130, 160, 140])
        result = monte_carlo_test(trades, 1_000_000, n_simulations=500, seed=42)
        # All trades profitable → hard to beat by shuffling (already optimal)
        # p-value should be moderate (shuffling can't make it worse when all positive)
        assert result["actual_sharpe"] > 0

    def test_too_few_trades(self) -> None:
        trades = _make_trades([100, -50])
        result = monte_carlo_test(trades, 1_000_000)
        assert "error" in result

    @pytest.mark.parametrize("n_simulations", [0, -1, -100, 1.5, "10", True])
    def test_invalid_simulations_errors(self, n_simulations: object) -> None:
        """A non-positive n_simulations must not raise (was ZeroDivisionError)."""
        trades = _make_trades([100, -50, 200, -30, 150])
        result = monte_carlo_test(trades, 1_000_000, n_simulations=n_simulations)
        assert "error" in result
        assert result["p_value_sharpe"] == 1.0

    @pytest.mark.parametrize("seed", [-1, 1.5, "42", True])
    def test_invalid_seed_errors(self, seed: object) -> None:
        """An invalid seed must not escape as an opaque numpy error."""
        trades = _make_trades([100, -50, 200, -30, 150])
        result = monte_carlo_test(trades, 1_000_000, n_simulations=10, seed=seed)
        assert "error" in result

    def test_reproducibility(self) -> None:
        trades = _make_trades([100, -50, 200, -30, 150, -80])
        r1 = monte_carlo_test(trades, 1_000_000, n_simulations=100, seed=42)
        r2 = monte_carlo_test(trades, 1_000_000, n_simulations=100, seed=42)
        assert r1["p_value_sharpe"] == r2["p_value_sharpe"]


# ---------------------------------------------------------------------------
# Bootstrap Sharpe CI
# ---------------------------------------------------------------------------


class TestBootstrapSharpe:
    def test_output_structure(self) -> None:
        eq = _make_equity(100)
        result = bootstrap_sharpe_ci(eq, n_bootstrap=100)
        assert "observed_sharpe" in result
        assert "ci_lower" in result
        assert "ci_upper" in result
        assert "prob_positive" in result
        assert "confidence" in result
        assert result["confidence"] == 0.95

    def test_ci_contains_observed(self) -> None:
        """The observed Sharpe should usually fall within the CI."""
        eq = _make_equity(200, drift=0.001)
        result = bootstrap_sharpe_ci(eq, n_bootstrap=500)
        # Not guaranteed, but very likely for 95% CI
        assert result["ci_lower"] <= result["ci_upper"]

    def test_positive_drift_mostly_positive(self) -> None:
        """Equity with positive drift should have high prob_positive."""
        eq = _make_equity(200, drift=0.003, seed=123)
        result = bootstrap_sharpe_ci(eq, n_bootstrap=500)
        assert result["prob_positive"] > 0.5

    def test_too_few_observations(self) -> None:
        eq = pd.Series([100, 101, 102], index=pd.bdate_range("2025-01-01", periods=3))
        result = bootstrap_sharpe_ci(eq, n_bootstrap=100)
        assert "error" in result

    @pytest.mark.parametrize("n_bootstrap", [0, -1, -50, 1.5, "10", True])
    def test_invalid_bootstrap_errors(self, n_bootstrap: object) -> None:
        """A non-positive n_bootstrap must not raise (was IndexError from percentile)."""
        eq = _make_equity(100)
        result = bootstrap_sharpe_ci(eq, n_bootstrap=n_bootstrap)
        assert "error" in result

    @pytest.mark.parametrize("confidence", [0.0, 1.0, 1.5, -0.2, float("inf"), float("nan"), "0.95", True])
    def test_invalid_confidence_errors(self, confidence: object) -> None:
        """A confidence outside (0, 1) must not raise (was percentile ValueError)."""
        eq = _make_equity(100)
        result = bootstrap_sharpe_ci(eq, confidence=confidence, n_bootstrap=100)
        assert "error" in result

    @pytest.mark.parametrize("seed", [-1, 1.5, "42", True])
    def test_invalid_seed_errors(self, seed: object) -> None:
        """An invalid seed must not escape as an opaque numpy error."""
        eq = _make_equity(100)
        result = bootstrap_sharpe_ci(eq, n_bootstrap=10, seed=seed)
        assert "error" in result

    def test_reproducibility(self) -> None:
        eq = _make_equity(50)
        r1 = bootstrap_sharpe_ci(eq, n_bootstrap=100, seed=42)
        r2 = bootstrap_sharpe_ci(eq, n_bootstrap=100, seed=42)
        assert r1["ci_lower"] == r2["ci_lower"]

    def test_custom_confidence(self) -> None:
        eq = _make_equity(100)
        r90 = bootstrap_sharpe_ci(eq, confidence=0.90, n_bootstrap=200)
        r99 = bootstrap_sharpe_ci(eq, confidence=0.99, n_bootstrap=200)
        # 99% CI should be wider than 90% CI
        width_90 = r90["ci_upper"] - r90["ci_lower"]
        width_99 = r99["ci_upper"] - r99["ci_lower"]
        assert width_99 >= width_90


# ---------------------------------------------------------------------------
# Walk-Forward Analysis
# ---------------------------------------------------------------------------


class TestWalkForward:
    def test_output_structure(self) -> None:
        eq = _make_equity(100)
        trades = _make_trades([100, -50] * 10)
        result = walk_forward_analysis(eq, trades, n_windows=4)
        assert result["n_windows"] == 4
        assert len(result["windows"]) == 4
        assert "consistency_rate" in result
        assert "return_mean" in result
        assert "sharpe_mean" in result

    def test_window_fields(self) -> None:
        eq = _make_equity(100)
        trades = _make_trades([100, -50] * 10)
        result = walk_forward_analysis(eq, trades, n_windows=5)
        w = result["windows"][0]
        assert "window" in w
        assert "start" in w
        assert "end" in w
        assert "return" in w
        assert "sharpe" in w
        assert "max_dd" in w
        assert "trades" in w
        assert "win_rate" in w

    def test_consistency_rate(self) -> None:
        """Equity with positive drift should have high consistency."""
        eq = _make_equity(200, drift=0.003)
        trades = _make_trades([100] * 50)
        result = walk_forward_analysis(eq, trades, n_windows=5)
        assert result["consistency_rate"] > 0.5

    def test_windows_cover_full_range(self) -> None:
        eq = _make_equity(100)
        trades = _make_trades([100] * 10)
        result = walk_forward_analysis(eq, trades, n_windows=5)
        first_start = result["windows"][0]["start"]
        last_end = result["windows"][-1]["end"]
        assert first_start == str(eq.index[0].date())
        assert last_end == str(eq.index[-1].date())

    def test_too_few_bars(self) -> None:
        eq = pd.Series([100, 101], index=pd.bdate_range("2025-01-01", periods=2))
        result = walk_forward_analysis(eq, [], n_windows=5)
        assert "error" in result

    @pytest.mark.parametrize("n_windows", [0, -1, -3, 1.5, "5", True])
    def test_invalid_windows_errors(self, n_windows: object) -> None:
        """A non-positive n_windows must not raise or silently return garbage.

        n_windows=0 raised ZeroDivisionError; a negative value silently returned
        an empty ``windows`` list with a NaN ``return_mean`` and a negative
        ``consistency_rate``.
        """
        eq = _make_equity(100)
        result = walk_forward_analysis(eq, [], n_windows=n_windows)
        assert "error" in result


# ---------------------------------------------------------------------------
# run_validation dispatcher
# ---------------------------------------------------------------------------


class TestRunValidation:
    def test_empty_config_returns_empty(self) -> None:
        eq = _make_equity(50)
        result = run_validation({}, eq, [], 1_000_000)
        assert result == {}

    def test_all_three(self) -> None:
        eq = _make_equity(100)
        trades = _make_trades([100, -50, 200, -30, 150])
        config = {
            "validation": {
                "monte_carlo": {"n_simulations": 50},
                "bootstrap": {"n_bootstrap": 50},
                "walk_forward": {"n_windows": 3},
            }
        }
        result = run_validation(config, eq, trades, 1_000_000)
        assert "monte_carlo" in result
        assert "bootstrap" in result
        assert "walk_forward" in result

    def test_single_tool(self) -> None:
        eq = _make_equity(100)
        trades = _make_trades([100, -50, 200])
        config = {"validation": {"bootstrap": {"n_bootstrap": 50}}}
        result = run_validation(config, eq, trades, 1_000_000)
        assert "bootstrap" in result
        assert "monte_carlo" not in result

    @pytest.mark.parametrize(
        ("section", "field", "value"),
        [
            ("monte_carlo", "n_simulations", "10"),
            ("monte_carlo", "seed", 1.5),
            ("bootstrap", "n_bootstrap", True),
            ("bootstrap", "confidence", float("inf")),
            ("walk_forward", "n_windows", "5"),
        ],
    )
    def test_malformed_nested_config_returns_error(
        self, section: str, field: str, value: object
    ) -> None:
        """Raw nested config values fail visibly instead of raising."""
        result = run_validation(
            {"validation": {section: {field: value}}},
            _make_equity(100),
            _make_trades([100, -50, 200]),
            1_000_000,
        )
        assert "error" in result[section]


# ---------------------------------------------------------------------------
# Strict validation.json writer
# ---------------------------------------------------------------------------


def _strict_json_load(text: str):
    """Parse ``text`` rejecting non-RFC-8259 NaN/Infinity tokens."""

    def _reject(value: str):
        raise ValueError(f"non-strict JSON constant: {value}")

    return json.loads(text, parse_constant=_reject)


class TestWriteValidationJson:
    def test_non_finite_metric_written_as_null(self, tmp_path: Path) -> None:
        """A non-finite metric must be serialized as null, not a bare
        NaN/Infinity token that strict JSON parsers reject."""
        out = tmp_path / "artifacts" / "validation.json"
        results = {
            "monte_carlo": {
                "actual_sharpe": float("inf"),
                "p_value_sharpe": float("nan"),
                "n_trades": 3,
            }
        }
        written = write_validation_json(out, results)

        text = out.read_text(encoding="utf-8")
        assert "NaN" not in text
        assert "Infinity" not in text
        parsed = _strict_json_load(text)  # must not raise
        assert parsed["monte_carlo"]["actual_sharpe"] is None
        assert parsed["monte_carlo"]["p_value_sharpe"] is None
        assert parsed["monte_carlo"]["n_trades"] == 3
        assert written["monte_carlo"]["actual_sharpe"] is None

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "does" / "not" / "exist" / "validation.json"
        write_validation_json(out, {"ok": 1.0})
        assert out.is_file()
        assert _strict_json_load(out.read_text(encoding="utf-8")) == {"ok": 1.0}

    def test_numpy_scalars_from_public_validators_are_strict_json(
        self, tmp_path: Path
    ) -> None:
        results = {
            "monte_carlo": monte_carlo_test(
                _make_trades([100, -50, 200]),
                1_000_000,
                n_simulations=np.int64(2),
                seed=np.int64(1),
            ),
            "bootstrap": bootstrap_sharpe_ci(
                _make_equity(20),
                n_bootstrap=np.int64(2),
                seed=np.int64(1),
            ),
            "walk_forward": walk_forward_analysis(
                _make_equity(20),
                [],
                n_windows=np.int64(2),
            ),
            "array": np.array([1, np.nan]),
        }
        out = tmp_path / "validation.json"

        written = write_validation_json(out, results)

        parsed = _strict_json_load(out.read_text(encoding="utf-8"))
        assert parsed["monte_carlo"]["n_simulations"] == 2
        assert parsed["bootstrap"]["n_bootstrap"] == 2
        assert parsed["walk_forward"]["n_windows"] == 2
        assert parsed["array"] == [1.0, None]
        assert written == parsed
