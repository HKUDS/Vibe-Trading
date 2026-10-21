"""The ``insufficient='equal'`` fallback must emit normalised equal weights."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.quantlib.combination import combine_factors

ASSETS = 8
NAMES = ("a", "b", "c")


def _sample(rows=40, seed=7):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=rows, freq="D")
    columns = [f"s{i}" for i in range(ASSETS)]
    panels = {
        name: pd.DataFrame(rng.normal(size=(rows, ASSETS)), index=index, columns=columns)
        for name in NAMES
    }
    returns = pd.DataFrame(rng.normal(size=(rows, ASSETS)), index=index, columns=columns)
    return panels, returns


def test_equal_fallback_rows_sum_to_one_like_method_equal():
    """A fallback row is the same weight vector ``method='equal'`` would use."""
    panels, returns = _sample()
    fallback = combine_factors(
        panels, returns, method="ic", min_periods=5, insufficient="equal"
    )
    reference = combine_factors(panels, method="equal")

    first = fallback.weights.iloc[0]
    assert first.abs().sum() == 1.0
    np.testing.assert_allclose(
        first.to_numpy(), reference.weights.iloc[0].to_numpy(), atol=1e-12
    )
    assert first.eq(1.0 / len(NAMES)).all()


def test_every_emitted_fallback_weight_row_is_normalised():
    """No emitted row escapes the absolute-sum normalisation the docs promise."""
    panels, returns = _sample()
    result = combine_factors(
        panels, returns, method="ic", min_periods=5, insufficient="equal"
    )
    rows = result.weights.dropna(how="all")
    assert not rows.empty
    np.testing.assert_allclose(
        rows.abs().sum(axis=1).to_numpy(), np.ones(len(rows)), atol=1e-12
    )
