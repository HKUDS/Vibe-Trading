"""Timing, weighting and truthful-empty invariants for factor combination."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.quantlib.combination import combine_factors
from src.tools.quantlib_tool import ALLOWED_MODULES, QuantlibCallTool

ASSETS = 20


def panel(values, columns=ASSETS, start="2024-01-01"):
    values = np.atleast_2d(np.asarray(values, dtype=float))
    index = pd.date_range(start, periods=values.shape[0], freq="D")
    return pd.DataFrame(values, index=index, columns=[f"s{i}" for i in range(columns)])


def sample(rows=40, seed=11):
    rng = np.random.default_rng(seed)
    first = panel(rng.normal(size=(rows, ASSETS)))
    second = panel(rng.normal(size=(rows, ASSETS)))
    return first, second


def test_equal_weights_reproduce_the_mean_of_standardized_factors():
    first, second = sample()
    result = combine_factors({"a": first, "b": second}, method="equal")

    def z(frame):
        return frame.sub(frame.mean(axis=1), axis=0).div(frame.std(axis=1, ddof=1), axis=0)

    expected = (z(first) + z(second)) / 2
    np.testing.assert_allclose(result.composite.to_numpy(), expected.to_numpy(), atol=1e-12)
    assert result.weights["a"].eq(0.5).all()
    assert result.weights["b"].eq(0.5).all()


def test_a_missing_factor_is_excluded_not_read_as_zero():
    first, second = sample(rows=5)
    second.iloc[2] = np.nan
    result = combine_factors({"a": first, "b": second}, method="equal")
    row = first.iloc[2]
    expected = (row - row.mean()) / row.std(ddof=1)
    np.testing.assert_allclose(result.composite.iloc[2].to_numpy(), expected.to_numpy(), atol=1e-12)


def test_a_row_with_no_available_factor_stays_nan():
    first, second = sample(rows=4)
    first.iloc[1] = np.nan
    second.iloc[1] = np.nan
    result = combine_factors({"a": first, "b": second}, method="equal")
    assert result.composite.iloc[1].isna().all()


def test_ic_weights_favour_the_predictive_factor():
    first, second = sample(rows=60)
    returns = first * 0.01  # monotone in the first factor: IC = 1, second is noise
    result = combine_factors({"a": first, "b": second}, returns, method="ic", min_periods=20)
    tail = result.weights.dropna(how="all").iloc[-5:]
    assert (tail["a"] > 0.8).all()
    assert (tail["b"].abs() < 0.2).all()


def test_weights_never_use_the_return_of_the_row_they_apply_to():
    first, second = sample(rows=40)
    returns = panel(np.random.default_rng(3).normal(size=(40, ASSETS)))
    baseline = combine_factors({"a": first, "b": second}, returns, method="ic", min_periods=10, window=20)
    changed = returns.copy()
    changed.iloc[20:] = changed.iloc[20:] * -3.0
    altered = combine_factors({"a": first, "b": second}, changed, method="ic", min_periods=10, window=20)
    pd.testing.assert_frame_equal(baseline.weights.iloc[:20], altered.weights.iloc[:20])
    assert not baseline.weights.iloc[20:].equals(altered.weights.iloc[20:])


def test_history_shorter_than_min_periods_is_skipped_not_defaulted():
    first, second = sample(rows=30)
    returns = first * 0.01
    result = combine_factors({"a": first, "b": second}, returns, method="ic", min_periods=15)
    assert result.weights.iloc[:15].isna().all().all()
    assert result.composite.iloc[:15].isna().all().all()
    assert result.composite.iloc[15:].notna().any().any()
    assert result.diagnostics["rows_without_weights"] == 15


def test_combination_is_invariant_to_factor_units():
    first, second = sample(rows=40)
    returns = first * 0.01
    base = combine_factors({"a": first, "b": second}, returns, method="ic", min_periods=10)
    for scale in (1e6, 1e-6):
        scaled = combine_factors(
            {"a": first * scale, "b": second * scale},
            returns,
            method="ic",
            min_periods=10,
        )
        np.testing.assert_allclose(base.composite, scaled.composite, atol=1e-10)
        np.testing.assert_allclose(base.weights, scaled.weights, atol=1e-12)


def test_correlation_diagnostic_marks_duplicate_factors():
    first, _ = sample()
    result = combine_factors({"a": first, "b": first.copy()}, method="equal")
    correlation = result.diagnostics["correlation"]
    assert correlation.loc["a", "b"] == pytest.approx(1.0, abs=1e-9)


def test_static_weights_are_normalised_and_must_cover_every_factor():
    first, second = sample(rows=10)
    result = combine_factors({"a": first, "b": second}, method="explicit", weights={"a": 3.0, "b": 1.0})
    assert result.weights["a"].iloc[0] == pytest.approx(0.75)
    assert result.weights["b"].iloc[0] == pytest.approx(0.25)
    with pytest.raises(ValueError, match="cover every factor"):
        combine_factors({"a": first, "b": second}, method="explicit", weights={"a": 1.0})
    with pytest.raises(ValueError, match="at least one weight"):
        combine_factors({"a": first, "b": second}, method="explicit", weights={"a": 0.0, "b": 0.0})


@pytest.mark.parametrize("weight_kind", ["mapping", "table"])
def test_large_finite_explicit_weights_are_normalised_without_overflow(weight_kind):
    first, second = sample(rows=5)
    if weight_kind == "mapping":
        weights = {"a": 1e308, "b": 1e308}
    else:
        weights = pd.DataFrame(
            {"a": [1e308] * len(first), "b": [1e308] * len(first)}, index=first.index
        )

    result = combine_factors(
        {"a": first, "b": second}, method="explicit", weights=weights
    )

    np.testing.assert_allclose(result.weights.to_numpy(), 0.5, atol=1e-12)
    assert result.composite.notna().all().all()


def test_a_weight_table_changes_the_composite_over_time():
    first, second = sample(rows=6)
    weights = pd.DataFrame(
        {"a": [1.0, 1.0, 1.0, 0.0, 0.0, 0.0], "b": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]},
        index=first.index,
    )
    result = combine_factors({"a": first, "b": second}, method="explicit", weights=weights)

    def z(frame):
        return frame.sub(frame.mean(axis=1), axis=0).div(frame.std(axis=1, ddof=1), axis=0)

    np.testing.assert_allclose(result.composite.iloc[0], z(first).iloc[0], atol=1e-12)
    np.testing.assert_allclose(result.composite.iloc[-1], z(second).iloc[-1], atol=1e-12)
    assert result.diagnostics["weights_source"] == "caller_table"


def test_a_weight_table_may_cover_only_rebalance_dates():
    first, second = sample(rows=6)
    weights = pd.DataFrame({"a": [1.0, 0.0], "b": [0.0, 1.0]}, index=[first.index[0], first.index[3]])
    result = combine_factors({"a": first, "b": second}, method="explicit", weights=weights)
    assert result.weights["a"].iloc[2] == pytest.approx(1.0)
    assert result.weights["b"].iloc[4] == pytest.approx(1.0)


def test_weights_are_rejected_outside_explicit_mode():
    first, second = sample(rows=5)
    with pytest.raises(ValueError, match="only accepted with method='explicit'"):
        combine_factors({"a": first, "b": second}, weights={"a": 0.5, "b": 0.5})


def test_ic_method_requires_returns():
    first, second = sample(rows=5)
    with pytest.raises(ValueError, match="requires a forward-return panel"):
        combine_factors({"a": first, "b": second}, method="ic")


def test_rebalance_holds_weights_between_estimates():
    first, second = sample(rows=40)
    returns = first * 0.01
    result = combine_factors(
        {"a": first, "b": second},
        returns,
        method="ic",
        min_periods=10,
        rebalance=5,
    )
    defined = result.weights.dropna(how="all")
    changes = defined.diff().abs().sum(axis=1)
    rebalance_dates = set(result.weights.index[::5])
    for timestamp, change in changes.items():
        if timestamp not in rebalance_dates:
            assert change == pytest.approx(0.0)


def test_combination_is_allowlisted_and_dispatchable():
    assert ALLOWED_MODULES["combination"] == "src.quantlib.combination"
    tool = QuantlibCallTool()
    listed = json.loads(tool.execute(action="list", module="combination"))
    names = {entry["name"] for entry in listed["functions"]}
    assert "combine_factors" in names
