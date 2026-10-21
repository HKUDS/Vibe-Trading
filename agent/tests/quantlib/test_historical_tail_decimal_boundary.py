"""Exact hand-ranked tails at decimal confidence boundaries."""

import numpy as np
import pytest

from src.quantlib.risk import historical_cvar, historical_var


@pytest.mark.parametrize(
    "n,confidence,tail_count",
    [
        (20, 0.95, 1),
        (100, 0.95, 5),
        (100, 0.99, 1),
        (50, 0.9, 5),
        (100, 0.975, 3),
        (20, 0.75, 5),
        (100, 0.9500000000000001, 5),
        (100, 0.9499999999999998, 6),
    ],
)
@pytest.mark.parametrize("measure", ["var", "cvar"])
def test_historical_tail_matches_explicit_rank(n, confidence, tail_count, measure):
    # The ranks are specified independently above: e.g. five losses in a 100-row
    # lower 5% tail, and one loss in a 20-row lower 5% tail. No floating-point
    # subtraction or quantile routine is used to calculate this oracle.
    returns = -np.arange(n, 0, -1, dtype=float) / n
    expected_var = (n - tail_count + 1) / n
    expected_cvar = (n + (n - tail_count + 1)) / (2 * n)
    function, expected = (
        (historical_var, expected_var)
        if measure == "var"
        else (historical_cvar, expected_cvar)
    )
    assert function(returns[::-1], confidence) == pytest.approx(expected)
