"""Missing equity observations must not manufacture validation returns."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.validation import (
    _load_equity,
    bootstrap_sharpe_ci,
    run_validation,
    walk_forward_analysis,
)


@pytest.mark.parametrize(
    "values",
    [
        [100, 110, float("nan"), 121, 120, 122, 123],
        [100, 110, 99, float("nan"), float("nan"), float("nan")],
    ],
    ids=["interior-gap", "trailing-gap"],
)
def test_bootstrap_counts_only_observed_adjacent_returns(values: list[float]) -> None:
    result = bootstrap_sharpe_ci(pd.Series(values), n_bootstrap=20)

    assert result == {"error": "need at least 5 return observations"}


def test_bootstrap_sharpe_excludes_gap_and_recovery_jump() -> None:
    # The five observable returns are +10%, -10%, +10%, -10%, +10%.
    equity = pd.Series([100, 110, 99, float("nan"), 200, 220, 198, 217.8])
    result = bootstrap_sharpe_ci(equity, n_bootstrap=20)
    expected = 0.02 / (math.sqrt(0.0096) + 1e-10) * math.sqrt(252)

    assert result["observed_sharpe"] == pytest.approx(expected, abs=5e-5)
    assert len(result["sharpe_samples"]) == 20


@pytest.mark.parametrize("n_windows", [1, 2])
def test_walk_forward_excludes_gap_without_changing_window_boundaries(
    n_windows: int,
) -> None:
    # Within each window only +10% and -10% are observable: Sharpe = 0.
    values = [100, 110, float("nan"), 220, 198] * n_windows
    equity = pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values)))
    result = walk_forward_analysis(equity, [], n_windows=n_windows)

    for i, window in enumerate(result["windows"]):
        assert window["sharpe"] == 0.0
        assert window["start"] == str(equity.index[i * 5].date())
        assert window["end"] == str(equity.index[i * 5 + 4].date())
        assert window["return"] == 0.98
        assert window["max_dd"] == -0.1


def test_complete_equity_retains_sharpe_calculation() -> None:
    # Six alternating +/-10% returns have mean zero.
    equity = pd.Series([100, 110, 99, 108.9, 98.01, 107.811, 97.0299])

    assert bootstrap_sharpe_ci(equity, n_bootstrap=20)["observed_sharpe"] == 0.0
    assert walk_forward_analysis(equity, [], n_windows=1)["sharpe_mean"] == 0.0


def test_loaded_equity_gap_reaches_validation_sample_guard(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "equity.csv").write_text(
        "date,equity\n2026-01-01,100\n2026-01-02,110\n2026-01-03,\n"
        "2026-01-04,121\n2026-01-05,120\n2026-01-06,122\n2026-01-07,123\n",
        encoding="utf-8",
    )
    equity = _load_equity(tmp_path)
    result = run_validation(
        {"validation": {"bootstrap": {"n_bootstrap": 20}}}, equity, [], 100
    )

    assert result["bootstrap"] == {"error": "need at least 5 return observations"}


@pytest.mark.parametrize(
    "values",
    [
        [float("nan"), 100, 110, 99],
        [100, 110, 99, float("nan")],
        [float("nan")] * 4,
        [100, float("nan"), float("nan"), 110],
    ],
    ids=["missing-start", "missing-end", "empty-window", "no-adjacent-pair"],
)
def test_walk_forward_refuses_unmeasurable_window(values) -> None:
    """No boundary value or no observed period cannot become a zero score."""
    equity = pd.Series(values, index=pd.date_range("2026-01-01", periods=4))
    result = walk_forward_analysis(equity, [], n_windows=1)
    assert "error" in result
    assert "window 1" in result["error"]
    assert "sharpe_mean" not in result


def test_walk_forward_does_not_silently_drop_an_unmeasurable_window() -> None:
    equity = pd.Series([100, 110, 99, 108.9, float("nan"), 120, 132, 118.8])
    result = walk_forward_analysis(equity, [], n_windows=2)
    assert "error" in result and "window 2" in result["error"]
    assert "consistency_rate" not in result
