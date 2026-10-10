"""Turnover penalties and reported changes operate on signed positions."""

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import calc_turnover_series
from backtest.optimizers.turnover_aware import TurnoverAwareOptimizer


def _inputs(flip: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    dates = pd.bdate_range("2025-01-01", periods=8)
    values = np.array([-0.01, 0.01, -0.02, 0.02, 0.01, 0.01, 0.02, -0.02])
    returns = pd.DataFrame({"A": values, "B": values}, index=dates)
    positions = pd.DataFrame(0.0, index=dates, columns=["A", "B"])
    positions.iloc[5:] = 1.0
    if flip:
        positions.iloc[6:, 0] = -1.0
    return returns, positions, dates


@pytest.mark.parametrize("flip", [False, True])
@pytest.mark.parametrize("initial_sign", [-1.0, 1.0])
def test_reported_turnover_matches_signed_optimized_allocations(
    flip: bool, initial_sign: float
) -> None:
    """A 50% long becoming a 50% short trades 100%, giving turnover 0.5."""
    returns, positions, dates = _inputs(flip)
    positions *= initial_sign
    optimizer = TurnoverAwareOptimizer(lookback=5, max_per_name=0.5)
    result = optimizer.optimize(returns, positions, dates)

    actual = calc_turnover_series(result).iloc[5:].tolist()
    np.testing.assert_allclose(optimizer.realized_turnover, actual, atol=1e-7)
    assert actual[1] == pytest.approx(0.5 if flip else 0.0)
    assert actual[2] == pytest.approx(0.0)


def test_reversal_penalty_can_reallocate_to_unchanged_direction() -> None:
    """Once reversing is correctly priced, holding the unflipped asset is cheaper."""
    returns, positions, dates = _inputs(True)
    optimizer = TurnoverAwareOptimizer(lookback=5, turnover_penalty=1.0)
    result = optimizer.optimize(returns, positions, dates)

    assert result.iloc[5]["A"] > 0.4
    assert abs(result.iloc[6]["A"]) < 0.01
    assert result.iloc[6]["B"] > 0.99


def test_all_positions_can_reverse_without_an_invalid_solver_seed() -> None:
    returns, positions, dates = _inputs(False)
    positions.iloc[6:] = -1.0
    optimizer = TurnoverAwareOptimizer(lookback=5, turnover_penalty=1.0)
    result = optimizer.optimize(returns, positions, dates)

    np.testing.assert_allclose(result.iloc[5:].abs().sum(axis=1), 1.0)
    assert (result.iloc[6:] <= 0.0).all().all()
    np.testing.assert_allclose(
        optimizer.realized_turnover,
        calc_turnover_series(result).iloc[5:].tolist(),
        atol=1e-7,
    )
    assert optimizer.realized_turnover[1] == pytest.approx(1.0)


@pytest.mark.parametrize("direction", [-1.0, 1.0])
def test_liquidation_and_reentry_are_both_recorded(direction: float) -> None:
    returns, positions, dates = _inputs(False)
    positions *= direction
    positions.iloc[6] = 0.0
    optimizer = TurnoverAwareOptimizer(lookback=5, max_per_name=0.5)
    result = optimizer.optimize(returns, positions, dates)

    np.testing.assert_allclose(
        optimizer.realized_turnover, calc_turnover_series(result).iloc[5:], atol=1e-7
    )
    np.testing.assert_allclose(optimizer.realized_turnover, [0.5, 0.5, 0.5])


def test_reentry_penalty_starts_from_cash_not_the_liquidated_book() -> None:
    dates = pd.bdate_range("2025-01-01", periods=8)
    returns = pd.DataFrame({"A": -0.02, "B": 0.02}, index=dates)
    positions = pd.DataFrame(0.0, index=dates, columns=["A", "B"])
    positions.iloc[5, 0] = 1.0
    positions.iloc[7] = 1.0
    optimizer = TurnoverAwareOptimizer(lookback=5, turnover_penalty=1.0)
    result = optimizer.optimize(returns, positions, dates)

    assert result.iloc[5]["A"] == pytest.approx(1.0)
    assert result.iloc[6].abs().sum() == 0.0
    assert result.iloc[7]["B"] > 0.99
    np.testing.assert_allclose(optimizer.realized_turnover, [0.5, 0.5, 0.5])


def test_retained_allocation_after_missing_history_updates_prior_holdings() -> None:
    returns, positions, dates = _inputs(False)
    # Row 6 lacks B's usable covariance, so its raw short allocation survives.
    # Row 7 only holds A and has a valid window again.
    returns.loc[dates[:6], "B"] = np.nan
    positions.iloc[5] = [1.0, 0.0]
    positions.iloc[6] = [0.0, -1.0]
    positions.iloc[7] = [1.0, 0.0]
    optimizer = TurnoverAwareOptimizer(lookback=5, turnover_penalty=1.0)
    result = optimizer.optimize(returns, positions, dates)

    np.testing.assert_allclose(result.iloc[5:], positions.iloc[5:])
    np.testing.assert_allclose(
        optimizer.realized_turnover, calc_turnover_series(result).iloc[5:], atol=1e-7
    )
    np.testing.assert_allclose(optimizer.realized_turnover, [0.5, 1.0, 1.0])
