"""Missing returns or forecasts must not invent consecutive breach pairs."""

import numpy as np
import pandas as pd
import pytest

from src.quantlib.var_backtest import christoffersen_conditional_coverage, var_backtest


@pytest.mark.parametrize("missing_side", ["returns", "var"])
def test_var_backtest_counts_only_originally_adjacent_observations(
    missing_side: str,
) -> None:
    index = pd.date_range("2024-01-01", periods=6)
    returns = pd.Series([-0.03, -0.03, 0.01, 0.01, -0.03, 0.01], index=index)
    forecasts = pd.Series(0.02, index=index)
    if missing_side == "returns":
        returns.iloc[2] = np.nan
    else:
        forecasts.iloc[2] = np.nan
    report = var_backtest(returns, forecasts, confidence=0.5)
    # Valid original pairs: breach->breach (0,1), calm->breach (3,4),
    # breach->calm (4,5). Pair (1,3) crosses an unknown observation.
    assert report.independence.transitions == (0, 1, 1, 1)
    assert report.independence.prob_breach_after_breach == pytest.approx(0.5)
    expected_lr = -2 * (np.log(1 / 3) + 2 * np.log(2 / 3) - 2 * np.log(0.5))
    assert report.independence.statistic == pytest.approx(expected_lr)
    assert report.observations == 5
    assert report.violations == 3
    assert report.dropped_observations == 1
    assert report.breach_dates == tuple(index[[0, 1, 4]])
    assert report.conditional_coverage.statistic == pytest.approx(
        report.kupiec.statistic + report.independence.statistic
    )


def test_no_original_adjacent_pairs_leave_independence_unidentified() -> None:
    report = var_backtest([-0.03, np.nan, -0.03, np.nan, 0.01], 0.02)
    assert report.independence.transitions == (0, 0, 0, 0)
    assert not report.independence.identified
    assert not report.independence.rejected
    assert report.independence.statistic == 0.0
    assert report.kupiec.observations == 3


def test_complete_series_and_missing_edges_keep_the_same_transitions() -> None:
    complete = [-0.03, -0.03, 0.01, 0.01, -0.03]
    expected = christoffersen_conditional_coverage([True, True, False, False, True])
    for returns in [complete, [np.nan, *complete, np.inf]]:
        report = var_backtest(returns, 0.02)
        assert report.independence == expected.independence
        assert report.conditional_coverage == expected
        assert report.kupiec.observations == len(complete)
