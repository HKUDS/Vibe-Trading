"""GTJA report p31 counts the distance to today, which is zero for today.

The original 2017-06-15 report is linked in gtja191/LICENSE.md. It does not
specify ties; these ports choose the most recent occurrence. Expected values
come from explicit bar ages or a scalar timestamp oracle, never the shared
arg-extreme operators or another alpha.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors import base
from src.factors.zoo.gtja191.alpha_103 import compute as alpha_103
from src.factors.zoo.gtja191.alpha_133 import compute as alpha_133
from src.factors.zoo.gtja191.alpha_177 import compute as alpha_177

N = 20


@pytest.fixture(params=[False, True], ids=["pandas", "bottleneck"])
def backend(request, monkeypatch):
    """Optional acceleration must not change the GTJA tie convention."""
    if request.param and not base.HAS_BOTTLENECK:
        pytest.skip("bottleneck is not installed")
    monkeypatch.setattr(base, "HAS_BOTTLENECK", request.param)


def _panel(high_age=0, low_age=0, rows=N):
    index = pd.bdate_range("2026-01-01", periods=rows, name="date")
    panel = {
        name: pd.DataFrame(value, index=index, columns=["AAA", "BBB"])
        for name, value in (("close", 100.0), ("low", 90.0), ("high", 110.0))
    }
    panel["high"].iloc[rows - 1 - high_age] = 1000.0
    panel["low"].iloc[rows - 1 - low_age] = 1.0
    return panel


@pytest.mark.parametrize("age", range(N))
@pytest.mark.parametrize("compute", [alpha_103, alpha_177], ids=["103", "177"])
def test_single_recency_uses_zero_days_since_today(compute, age, backend):
    out = compute(_panel(high_age=age, low_age=age))
    # Today=100; yesterday=95; oldest member of the 20-bar window=5.
    assert out.iloc[-1].tolist() == pytest.approx([100.0 - age * 5.0] * 2)
    assert out.iloc[:-1].isna().all().all()


@pytest.mark.parametrize(
    "high_age, low_age, expected",
    [(0, 19, 95.0), (19, 0, -95.0), (3, 14, 55.0), (14, 3, -55.0), (7, 7, 0.0)],
)
def test_133_preserves_the_direction_of_distinct_extrema(
    high_age, low_age, expected, backend
):
    out = alpha_133(_panel(high_age=high_age, low_age=low_age))
    assert out.iloc[-1].tolist() == pytest.approx([expected] * 2)


@pytest.mark.parametrize(
    "compute, expected", [(alpha_103, 80.0), (alpha_177, 90.0), (alpha_133, 10.0)],
    ids=["103", "177", "133"],
)
def test_tied_extrema_use_the_most_recent_occurrence(compute, expected, backend):
    panel = _panel(high_age=2, low_age=4)
    panel["high"].iloc[0] = 1000.0
    panel["low"].iloc[1] = 1.0
    assert compute(panel).iloc[-1].tolist() == pytest.approx([expected] * 2)


@pytest.mark.parametrize(
    "compute, expected", [(alpha_103, 100.0), (alpha_177, 100.0), (alpha_133, 0.0)],
    ids=["103", "177", "133"],
)
def test_constant_window_chooses_today(compute, expected, backend):
    panel = _panel()
    panel["high"].iloc[:] = 110.0
    panel["low"].iloc[:] = 90.0
    assert compute(panel).iloc[-1].tolist() == pytest.approx([expected] * 2)


@pytest.mark.parametrize(
    "compute, missing_field",
    [(alpha_103, "low"), (alpha_177, "high"), (alpha_133, "low"), (alpha_133, "high")],
    ids=["103-low", "177-high", "133-low", "133-high"],
)
def test_gap_invalidates_exactly_the_windows_that_contain_it(
    compute, missing_field, backend
):
    panel = _panel(rows=65)
    expected = compute(panel)
    gap = 30
    panel[missing_field].iloc[gap, 0] = np.nan
    actual = compute(panel)
    assert actual.iloc[:N - 1].isna().all().all()
    assert actual["AAA"].iloc[gap:gap + N].isna().all()
    pd.testing.assert_series_equal(actual["BBB"], expected["BBB"])
    pd.testing.assert_series_equal(actual["AAA"].iloc[:gap], expected["AAA"].iloc[:gap])
    pd.testing.assert_series_equal(actual["AAA"].iloc[gap + N:], expected["AAA"].iloc[gap + N:])
    assert actual["AAA"].iloc[gap + N] == expected["AAA"].iloc[gap + N]


def _scalar_score(values, row, maximum):
    """Find the last absolute row holding the extreme, then count its age."""
    window = values[row - N + 1:row + 1]
    if row < N - 1 or any(pd.isna(value) for value in window):
        return np.nan
    extreme = max(window) if maximum else min(window)
    last_seen = max(i for i in range(row - N + 1, row + 1) if values[i] == extreme)
    days_since = row - last_seen
    return (N - days_since) * 100.0 / N


@pytest.mark.parametrize("compute, which", [(alpha_103, "low"), (alpha_177, "high"), (alpha_133, "both")])
def test_rolling_output_matches_independent_timestamp_oracle(compute, which, backend):
    panel = _panel(rows=73)
    rng = np.random.default_rng(27)
    # Small integer ranges intentionally create repeated extrema.
    panel["high"].iloc[:] = rng.integers(110, 116, size=(73, 2))
    panel["low"].iloc[:] = rng.integers(85, 91, size=(73, 2))
    panel["low"].iloc[31, 0] = np.nan
    panel["high"].iloc[40, 1] = np.nan
    expected = pd.DataFrame(np.nan, index=panel["close"].index, columns=panel["close"].columns)
    for symbol in expected.columns:
        for row in range(len(expected)):
            high = _scalar_score(panel["high"][symbol].tolist(), row, True)
            low = _scalar_score(panel["low"][symbol].tolist(), row, False)
            expected.loc[expected.index[row], symbol] = (
                high - low if which == "both" else high if which == "high" else low
            )
    pd.testing.assert_frame_equal(compute(panel), expected)
