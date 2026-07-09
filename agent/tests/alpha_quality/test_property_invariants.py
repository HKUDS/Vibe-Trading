from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.alpha_quality.forward_returns import compute_forward_return
from src.alpha_quality.ic_metrics import compute_ic_series_safe
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics, FactorOutputFrame


@given(
    prices=st.lists(
        st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
        min_size=3,
        max_size=30,
    ),
    horizon=st.integers(min_value=1, max_value=6),
    execution_lag=st.integers(min_value=1, max_value=6),
)
@settings(max_examples=80, deadline=None)
def test_forward_return_matches_lagged_close_to_close_identity(
    prices: list[float], horizon: int, execution_lag: int
) -> None:
    close = pd.DataFrame(
        {"S0": prices},
        index=pd.date_range("2024-01-01", periods=len(prices), freq="D"),
    )

    result = compute_forward_return(close, horizon=horizon, execution_lag=execution_lag)

    for row in range(len(prices)):
        exit_row = row + execution_lag + horizon
        entry_row = row + execution_lag
        if exit_row >= len(prices):
            assert pd.isna(result.iloc[row, 0])
        else:
            expected = prices[exit_row] / prices[entry_row] - 1.0
            assert result.iloc[row, 0] == pytest.approx(expected)


@given(
    factor_values=st.lists(
        st.lists(
            st.floats(min_value=-1_000.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
            min_size=5,
            max_size=8,
        ),
        min_size=2,
        max_size=8,
    ),
    return_values=st.lists(
        st.lists(
            st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=5,
            max_size=8,
        ),
        min_size=2,
        max_size=8,
    ),
)
@settings(max_examples=80, deadline=None)
def test_rank_ic_property_is_bounded(factor_values: list[list[float]], return_values: list[list[float]]) -> None:
    rows = min(len(factor_values), len(return_values))
    cols = min(min(len(row) for row in factor_values), min(len(row) for row in return_values))
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    symbols = [f"S{i}" for i in range(cols)]
    factor = pd.DataFrame([row[:cols] for row in factor_values[:rows]], index=dates, columns=symbols)
    forward_return = pd.DataFrame([row[:cols] for row in return_values[:rows]], index=dates, columns=symbols)
    mask = pd.DataFrame(True, index=dates, columns=symbols)

    ic = compute_ic_series_safe(factor, forward_return, mask, min_cross_section=5)

    assert ((ic >= -1.0) & (ic <= 1.0)).all()


def test_alpha_quality_scorecard_strict_json_sanitizes_non_finite_values() -> None:
    scorecard = AlphaQualityScorecard(
        factor_id="nan-check",
        formula="rank(close)",
        factor_definition_hash="sha256:nan",
        execution=ExecutionMetrics(
            uses_execution_return=True,
            return_mean=float("nan"),
            turnover_mean=float("inf"),
            cost_bps_mean=float("-inf"),
        ),
    )

    payload = scorecard.to_json()

    assert "NaN" not in payload
    assert "Infinity" not in payload
    decoded = json.loads(payload)
    assert decoded["execution"]["return_mean"] is None
    assert decoded["execution"]["turnover_mean"] is None
    assert decoded["execution"]["cost_bps_mean"] is None


def test_factor_output_frame_is_frozen_and_aligns_by_label() -> None:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    factor = pd.DataFrame([[1.0, 2.0], [3.0, np.nan], [5.0, 6.0]], index=dates, columns=["A", "B"])
    mask = factor.notna()
    output = FactorOutputFrame(
        factor_id="frozen",
        formula="rank(close)",
        factor=factor,
        valid_mask=mask,
        tradable_mask=mask,
        universe_mask=mask,
        metadata={"kind": "fixture"},
        factor_definition_hash="sha256:frozen",
    )

    with pytest.raises(FrozenInstanceError):
        output.factor_id = "mutated"  # type: ignore[misc]

    returns = pd.DataFrame(
        [[0.1], [0.2], [0.3]],
        index=dates,
        columns=["B"],
    )
    aligned = output.aligned(returns)

    assert list(aligned.factor.columns) == ["B"]
    assert list(aligned.factor.index) == list(dates)
