"""Unit contract for ``src.factors.base.zscore_by_group``.

The shared within-group z-score the industry-neutralized CN value factors run
on. Expected values are hand-computed (or recomputed with independent numpy
math) rather than derived from the helper itself, so a regression in the
helper cannot validate itself. The refusal cases matter as much as the numbers:
a singleton group, a zero-variance group, a missing label and a ±inf input all
stay NaN — there is no global fallback wearing an industry-neutral label.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.base import zscore_by_group

_DATES = pd.to_datetime(["2024-01-01", "2024-01-02"])
_COLS = ["A", "B", "C", "D"]


def _frame(rows: list[list], cols: list[str] | None = None) -> pd.DataFrame:
    return pd.DataFrame(rows, index=_DATES, columns=cols or _COLS, dtype=object)


def _labels(rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=_DATES, columns=_COLS, dtype=object)


def test_two_group_row_matches_hand_computation() -> None:
    """Row [1,3 | 10,20] in two groups: every cell is ±1/sqrt(2)."""
    values = pd.DataFrame(
        [[1.0, 3.0, 10.0, 20.0], [2.0, 4.0, 4.0, 2.0]],
        index=_DATES, columns=_COLS, dtype="float64",
    )
    groups = _labels([["G1", "G1", "G2", "G2"]] * 2)

    out = zscore_by_group(values, groups)

    s = 1.0 / np.sqrt(2.0)  # (x - mean) / sample-std of a two-point group
    np.testing.assert_allclose(
        out.to_numpy(dtype=np.float64),
        np.array([[-s, s, -s, s], [-s, s, s, -s]]),
        rtol=1e-12, atol=1e-15,
    )


def test_group_stats_use_only_that_group() -> None:
    """A three-member group's mean/std come from its own cells, not the row."""
    values = pd.DataFrame(
        [[1.0, 2.0, 3.0, 100.0]], index=_DATES[:1], columns=_COLS, dtype="float64"
    )
    groups = pd.DataFrame(
        [["G1", "G1", "G1", "G2"]], index=_DATES[:1], columns=_COLS, dtype=object
    )

    out = zscore_by_group(values, groups)

    # G1: mean 2, sample std 1 → [-1, 0, 1]; G2 singleton → NaN (not 100's z vs the row).
    np.testing.assert_allclose(
        out.to_numpy(dtype=np.float64)[0, :3], [-1.0, 0.0, 1.0], rtol=1e-12
    )
    assert np.isnan(out.to_numpy(dtype=np.float64)[0, 3])


def test_singleton_group_is_nan() -> None:
    values = pd.DataFrame([[1.0, 3.0, 7.0, 9.0]], index=_DATES[:1], columns=_COLS, dtype="float64")
    groups = pd.DataFrame([["G1", "G1", "G2", "G3"]], index=_DATES[:1], columns=_COLS, dtype=object)

    out = zscore_by_group(values, groups)

    row = out.to_numpy(dtype=np.float64)[0]
    assert np.isfinite(row[0]) and np.isfinite(row[1])
    assert np.isnan(row[2]) and np.isnan(row[3])


def test_zero_variance_group_is_nan_never_inf_never_zero() -> None:
    values = pd.DataFrame([[5.0, 5.0, 1.0, 2.0]], index=_DATES[:1], columns=_COLS, dtype="float64")
    groups = pd.DataFrame([["G1", "G1", "G2", "G2"]], index=_DATES[:1], columns=_COLS, dtype=object)

    out = zscore_by_group(values, groups)

    row = out.to_numpy(dtype=np.float64)[0]
    assert np.isnan(row[0]) and np.isnan(row[1])
    assert not np.isinf(row).any()
    assert np.isfinite(row[2]) and np.isfinite(row[3])


def test_nan_cell_stays_nan_and_is_excluded_from_group_stats() -> None:
    """The NaN cell does not enter the mean/std; the survivors still z-score."""
    values = pd.DataFrame(
        [[1.0, np.nan, 3.0, 10.0]], index=_DATES[:1], columns=_COLS, dtype="float64"
    )
    groups = pd.DataFrame(
        [["G1", "G1", "G1", "G2"]], index=_DATES[:1], columns=_COLS, dtype=object
    )

    out = zscore_by_group(values, groups)

    row = out.to_numpy(dtype=np.float64)[0]
    # G1 finite {1, 3}: mean 2, std sqrt(2) → ±1/sqrt(2); the NaN cell stays NaN.
    s = 1.0 / np.sqrt(2.0)
    assert row[0] == pytest.approx(-s)
    assert np.isnan(row[1])
    assert row[2] == pytest.approx(s)


def test_none_and_nan_labels_are_nan_with_no_global_fallback() -> None:
    values = pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=_DATES[:1], columns=_COLS, dtype="float64")
    groups = pd.DataFrame(
        [[None, np.nan, "G1", "G1"]], index=_DATES[:1], columns=_COLS, dtype=object
    )

    out = zscore_by_group(values, groups)

    row = out.to_numpy(dtype=np.float64)[0]
    assert np.isnan(row[0]) and np.isnan(row[1])
    assert np.isfinite(row[2]) and np.isfinite(row[3])


def test_inf_inputs_are_scrubbed_to_nan() -> None:
    values = pd.DataFrame(
        [[np.inf, 1.0, 3.0, -np.inf]], index=_DATES[:1], columns=_COLS, dtype="float64"
    )
    groups = pd.DataFrame([["G1"] * 4], index=_DATES[:1], columns=_COLS, dtype=object)

    out = zscore_by_group(values, groups)

    row = out.to_numpy(dtype=np.float64)[0]
    assert not np.isinf(row).any()
    assert np.isnan(row[0]) and np.isnan(row[3])
    # G1 finite {1, 3} → ±1/sqrt(2), the infinities excluded from mean/std.
    s = 1.0 / np.sqrt(2.0)
    assert row[1] == pytest.approx(-s)
    assert row[2] == pytest.approx(s)


def test_shape_index_columns_preserved() -> None:
    values = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]], index=_DATES, columns=_COLS, dtype="float64"
    )
    groups = _labels([["G1", "G1", "G2", "G2"]] * 2)

    out = zscore_by_group(values, groups)

    assert out.shape == values.shape
    assert list(out.index) == list(_DATES)
    assert list(out.columns) == _COLS


def test_groups_align_positionally_not_by_label() -> None:
    """A groups frame with different index/column labels gives the same result."""
    values = pd.DataFrame(
        [[1.0, 3.0, 10.0, 20.0]], index=_DATES[:1], columns=_COLS, dtype="float64"
    )
    aligned = pd.DataFrame(
        [["G1", "G1", "G2", "G2"]], index=_DATES[:1], columns=_COLS, dtype=object
    )
    shifted_labels = pd.DataFrame(
        [["G1", "G1", "G2", "G2"]],
        index=pd.to_datetime(["1999-12-31"]),
        columns=["W", "X", "Y", "Z"],
        dtype=object,
    )

    a = zscore_by_group(values, aligned)
    b = zscore_by_group(values, shifted_labels)

    np.testing.assert_allclose(
        a.to_numpy(dtype=np.float64), b.to_numpy(dtype=np.float64), equal_nan=True
    )
    assert list(b.columns) == _COLS  # output keeps df's columns, not groups'


def test_integer_labels_work() -> None:
    """The sweep panels carry integer sector buckets; labels need not be str."""
    values = pd.DataFrame([[1.0, 3.0, 10.0, 20.0]], index=_DATES[:1], columns=_COLS, dtype="float64")
    groups = pd.DataFrame([[0, 0, 1, 1]], index=_DATES[:1], columns=_COLS)

    out = zscore_by_group(values, groups)

    s = 1.0 / np.sqrt(2.0)
    np.testing.assert_allclose(
        out.to_numpy(dtype=np.float64)[0], [-s, s, -s, s], rtol=1e-12
    )


def test_shape_mismatch_raises() -> None:
    values = pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=_DATES[:1], columns=_COLS, dtype="float64")
    groups = pd.DataFrame([["G1", "G1", "G2"]], index=_DATES[:1], columns=_COLS[:3], dtype=object)

    with pytest.raises(ValueError, match=r"groups shape .* != df shape"):
        zscore_by_group(values, groups)
