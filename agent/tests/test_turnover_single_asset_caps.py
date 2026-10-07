"""A single-asset fast path must not silently bypass exposure caps."""

import numpy as np
import pandas as pd
import pytest

from backtest.optimizers.turnover_aware import TurnoverAwareOptimizer


@pytest.mark.parametrize("weight", [np.nan, np.inf, -np.inf])
def test_explicit_singleton_cap_rejects_nonfinite_weights(weight: float) -> None:
    dates = pd.date_range("2025-01-01", periods=1)
    pos = pd.DataFrame({"AAA": [weight]}, index=dates)
    optimizer = TurnoverAwareOptimizer(max_per_name=0.4)
    with pytest.raises(ValueError):
        optimizer.optimize(pos * 0, pos, dates)


@pytest.mark.parametrize("direction", [1.0, -1.0])
@pytest.mark.parametrize(
    "caps",
    [
        {"max_per_name": 0.4},
        {"groups": {"A": "tech"}, "max_per_group": {"tech": 0.6}},
    ],
)
def test_single_asset_infeasible_caps_fail_closed(caps: dict, direction: float) -> None:
    """A fully invested singleton cannot fit below a sub-unit exposure cap."""
    dates = pd.bdate_range("2025-01-01", periods=8)
    returns = pd.DataFrame({"A": np.linspace(-0.01, 0.02, 8)}, index=dates)
    positions = pd.DataFrame({"A": direction}, index=dates)
    optimizer = TurnoverAwareOptimizer(lookback=5, **caps)

    with pytest.raises(
        ValueError, match="single-asset allocation exceeds exposure caps"
    ):
        optimizer.optimize(returns, positions, dates)


@pytest.mark.parametrize(
    "caps",
    [
        {},
        {"max_per_name": 1.0},
        {"max_per_name": 0.4},
        {"groups": {"A": "tech"}, "max_per_group": {"tech": 1.0}},
        {"groups": {"OTHER": "tech"}, "max_per_group": {"tech": 0.4}},
    ],
)
def test_feasible_single_asset_fast_path_is_unchanged(caps: dict) -> None:
    dates = pd.bdate_range("2025-01-01", periods=8)
    returns = pd.DataFrame({"A": np.linspace(-0.01, 0.02, 8)}, index=dates)
    positions = pd.DataFrame({"A": -0.25}, index=dates)
    optimizer = TurnoverAwareOptimizer(lookback=5, **caps)

    pd.testing.assert_frame_equal(
        optimizer.optimize(returns, positions, dates), positions
    )


def test_all_cash_single_asset_has_no_infeasible_allocation() -> None:
    dates = pd.bdate_range("2025-01-01", periods=8)
    returns = pd.DataFrame({"A": np.linspace(-0.01, 0.02, 8)}, index=dates)
    positions = pd.DataFrame({"A": 0.0}, index=dates)
    optimizer = TurnoverAwareOptimizer(lookback=5, max_per_name=0.4)

    pd.testing.assert_frame_equal(
        optimizer.optimize(returns, positions, dates), positions
    )


@pytest.mark.parametrize(
    "caps",
    [{}, {"groups": {"OTHER": "tech"}, "max_per_group": {"tech": 0.4}}],
)
def test_uncapped_leveraged_singleton_retains_the_fast_path(caps: dict) -> None:
    dates = pd.bdate_range("2025-01-01", periods=8)
    returns = pd.DataFrame({"A": np.linspace(-0.01, 0.02, 8)}, index=dates)
    positions = pd.DataFrame({"A": -2.0}, index=dates)
    optimizer = TurnoverAwareOptimizer(lookback=5, **caps)

    pd.testing.assert_frame_equal(
        optimizer.optimize(returns, positions, dates), positions
    )
