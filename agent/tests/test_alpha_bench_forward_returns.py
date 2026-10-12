"""Regression tests for alpha-bench forward-return missing-data handling
and monthly-horizon support (issue #1789 follow-up #1)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.tools.alpha_bench_tool import _compute_forward_returns


def test_forward_returns_preserve_missing_close_boundaries() -> None:
    close = pd.DataFrame(
        {"AAA": [100.0, None, 121.0]},
        index=pd.date_range("2026-01-01", periods=3, freq="D"),
    )

    forward = _compute_forward_returns({"close": close})

    assert forward["AAA"].isna().all()


def _close(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"AAA": list(values)},
        index=pd.date_range("2026-01-01", periods=len(values), freq="D"),
    )


def test_horizon_default_is_byte_identical_to_legacy_formula() -> None:
    close = _close([100.0, 102.0, np.nan, 105.0, 104.0, 108.0, 110.0])
    legacy = close.pct_change(fill_method=None).shift(-1)

    assert _compute_forward_returns({"close": close}).equals(legacy)
    assert _compute_forward_returns({"close": close}, horizon=1).equals(legacy)


def test_horizon_three_samples_every_third_row_end_anchored() -> None:
    values = [100.0, 101.0, 103.0, 106.0, 110.0, 115.0, 121.0, 128.0, 136.0, 145.0]
    close = _close(values)

    forward = _compute_forward_returns({"close": close}, horizon=3)

    # n=10, h=3 → kept positions satisfy (9 - pos) % 3 == 0 → 0, 3, 6, 9.
    for pos in (0, 3, 6):
        expected = values[pos + 3] / values[pos] - 1.0
        assert forward["AAA"].iloc[pos] == pytest.approx(expected)
    # The most recent sampled row has no t+h close → NaN, never bridged.
    assert np.isnan(forward["AAA"].iloc[9])
    # Non-sampled rows are NaN so consecutive IC windows never overlap.
    for pos in (1, 2, 4, 5, 7, 8):
        assert np.isnan(forward["AAA"].iloc[pos])


def test_horizon_samples_the_most_recent_complete_window() -> None:
    # n=9, h=2 → sampled positions 0, 2, 4, 6, 8 (end-anchored); the row at
    # position 6 carries the return over the most recent complete window [6→8].
    values = [100.0, 102.0, 101.0, 104.0, 107.0, 106.0, 110.0, 112.0, 115.0]
    close = _close(values)

    forward = _compute_forward_returns({"close": close}, horizon=2)

    assert forward["AAA"].iloc[6] == pytest.approx(values[8] / values[6] - 1.0)
    assert np.isnan(forward["AAA"].iloc[8])  # sampled but no future close
    assert np.isnan(forward["AAA"].iloc[7])  # not sampled


def test_horizon_nan_close_at_t_plus_h_never_bridges() -> None:
    # n=6, h=3 → sampled positions 2 and 5. close[5] is NaN (halted), so the
    # return at position 2 must be NaN — no bridging off close[4].
    values = [100.0, 101.0, 103.0, 106.0, 110.0, np.nan]
    close = _close(values)

    forward = _compute_forward_returns({"close": close}, horizon=3)

    assert np.isnan(forward["AAA"].iloc[2])


def test_horizon_nan_close_at_t_never_bridges() -> None:
    # Same geometry, NaN at the sampled row t itself.
    values = [100.0, 101.0, np.nan, 106.0, 110.0, 115.0]
    close = _close(values)

    forward = _compute_forward_returns({"close": close}, horizon=3)

    assert np.isnan(forward["AAA"].iloc[2])


@pytest.mark.parametrize("bad", [0, -1, -21])
def test_horizon_below_one_raises(bad: int) -> None:
    close = _close([100.0, 101.0, 102.0])

    with pytest.raises(ValueError, match="horizon"):
        _compute_forward_returns({"close": close}, horizon=bad)


@pytest.mark.parametrize("bad", ["3", 1.5, True, None])
def test_horizon_non_int_raises(bad: object) -> None:
    close = _close([100.0, 101.0, 102.0])

    with pytest.raises(ValueError, match="horizon"):
        _compute_forward_returns({"close": close}, horizon=bad)


def test_horizon_missing_close_still_raises() -> None:
    with pytest.raises(ValueError, match="close"):
        _compute_forward_returns({}, horizon=3)
