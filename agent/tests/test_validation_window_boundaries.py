"""Every observed equity return must belong to a validation window."""

import numpy as np
import pandas as pd
import pytest

from backtest.validation import run_validation, walk_forward_analysis


@pytest.mark.parametrize("last", [50.0, 200.0])
@pytest.mark.parametrize("jump_at", [3, 4])
def test_returns_are_conserved_across_window_boundaries(last, jump_at):
    equity = pd.Series([100.0] * jump_at + [last] * (8 - jump_at), index=pd.bdate_range("2026-01-01", periods=8))
    result = walk_forward_analysis(equity, [], n_windows=2)
    compounded = np.prod([1 + window["return"] for window in result["windows"]])
    assert compounded == pytest.approx(last / 100)
    if last < 100:
        assert min(window["max_dd"] for window in result["windows"]) == -0.5


def test_first_loss_is_measured_from_declared_starting_cash():
    equity = pd.Series([80.0] * 8, index=pd.bdate_range("2026-01-01", periods=8))
    result = run_validation({"validation": {"walk_forward": {"n_windows": 2}}}, equity, [], 100)
    first = result["walk_forward"]["windows"][0]
    assert first["return"] == -0.2
    assert first["max_dd"] == -0.2
    assert result["walk_forward"]["analysis_type"] == "window_consistency"


@pytest.mark.parametrize("capital", [0, -1, float("nan"), float("inf"), True])
def test_invalid_opening_capital_is_refused(capital):
    equity = pd.Series([100.0] * 8)
    assert "error" in walk_forward_analysis(equity, [], n_windows=2, initial_capital=capital)
