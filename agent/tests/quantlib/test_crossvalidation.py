"""Tests for src.quantlib.crossvalidation.

The central test is the one that shows a NAIVE split leaks and the purged split
does not, over identical data. Asserting only that the purged splitter is clean
would pass just as well if purging were a no-op.
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.quantlib.crossvalidation import (
    DEFAULT_EMBARGO_FRACTION,
    MIN_FOLDS,
    Split,
    _as_label_spans,
    combinatorial_purged_splits,
    detect_boundary_leakage,
    group_purged_kfold_splits,
    purged_kfold_splits,
    purged_walk_forward_splits,
)


def _overlapping_labels(n=1000, horizon=20):
    """Label i resolves `horizon` bars later, so labels overlap heavily."""
    return np.minimum(np.arange(n) + horizon, n - 1)


# --- the leak exists, and purging is what removes it ---


def test_a_naive_split_leaks_and_the_purged_split_does_not():
    n, horizon = 1000, 20
    labels = _overlapping_labels(n, horizon)
    test = np.arange(400, 600)

    naive = Split(
        train=np.setdiff1d(np.arange(n), test),
        test=test,
        purged=0,
        embargoed=0,
        test_bounds=(400, 599),
    )
    naive_report = detect_boundary_leakage(naive, labels, n_samples=n)
    assert not naive_report.clean
    # Exactly the observations whose 20-bar label window reaches into the test
    # block: starts 380..399 before it, plus everything the test's own labels
    # cover after it.
    assert naive_report.overlapping.size > 0

    purged = next(
        s for s in purged_kfold_splits(n, labels, n_folds=5, embargo_fraction=0.0)
        if s.test_bounds == (400, 599)
    )
    assert detect_boundary_leakage(purged, labels, n_samples=n).clean
    assert purged.purged > 0


def test_purging_removes_exactly_the_overlapping_observations():
    n, horizon = 200, 10
    labels = _overlapping_labels(n, horizon)
    splits = list(purged_kfold_splits(n, labels, n_folds=4, embargo_fraction=0.0))
    fold = splits[1]  # test block 50..99
    assert fold.test_bounds == (50, 99)

    first_test = 50
    test_span_end = max(99, int(labels[np.arange(50, 100)].max()))
    expected_removed = {
        i
        for i in range(n)
        if i not in range(50, 100) and i <= test_span_end and labels[i] >= first_test
    }
    assert set(np.setdiff1d(np.arange(n), np.union1d(fold.train, fold.test))) == expected_removed
    assert fold.purged == len(expected_removed)


def test_no_observation_is_in_both_train_and_test():
    n = 500
    labels = _overlapping_labels(n, 15)
    for split in purged_kfold_splits(n, labels, n_folds=5):
        assert np.intersect1d(split.train, split.test).size == 0


def test_labels_touching_at_a_single_instant_count_as_overlapping():
    # Closed intervals on both ends. Observation 39's label ends exactly at 40,
    # the first test bar, so it must be purged.
    n = 100
    labels = np.arange(n) + 1
    labels[39] = 40
    split = next(
        s for s in purged_kfold_splits(n, labels, n_folds=5, embargo_fraction=0.0)
        if s.test_bounds[0] == 40
    )
    assert 39 not in split.train


# --- embargo ---


def test_embargo_removes_observations_after_the_test_block():
    n = 1000
    labels = np.arange(n)  # labels resolve same-bar, so purging alone does nothing
    embargo_fraction = 0.02
    embargo_size = int(round(n * embargo_fraction))

    split = next(
        s for s in purged_kfold_splits(n, labels, n_folds=5, embargo_fraction=embargo_fraction)
        if s.test_bounds == (200, 399)
    )
    assert split.embargoed == embargo_size
    # Nothing in (399, 399 + embargo] survives in training.
    assert not ((split.train > 399) & (split.train <= 399 + embargo_size)).any()
    # But training resumes immediately after the embargo.
    assert (split.train > 399 + embargo_size).any()


def test_zero_embargo_keeps_the_bar_right_after_the_test_block():
    n = 500
    labels = np.arange(n)
    split = next(
        s for s in purged_kfold_splits(n, labels, n_folds=5, embargo_fraction=0.0)
        if s.test_bounds == (100, 199)
    )
    assert split.embargoed == 0
    assert 200 in split.train


def test_detect_boundary_leakage_flags_a_missing_embargo():
    n = 300
    labels = np.arange(n)
    test = np.arange(100, 200)
    unembargoed = Split(
        train=np.setdiff1d(np.arange(n), test),
        test=test,
        purged=0,
        embargoed=0,
        test_bounds=(100, 199),
    )
    report = detect_boundary_leakage(unembargoed, labels, n_samples=n, embargo_size=10)
    assert report.embargo_violations.size == 10
    assert not report.clean


def test_default_embargo_fraction_is_small_but_nonzero():
    assert 0.0 < DEFAULT_EMBARGO_FRACTION < 0.1


# --- walk-forward ---


def test_walk_forward_never_trains_on_the_future():
    n = 1000
    labels = _overlapping_labels(n, 20)
    for split in purged_walk_forward_splits(n, labels, n_folds=5):
        assert split.train.max() < split.test.min()


def test_walk_forward_purges_past_labels_that_reach_into_the_test_block():
    n, horizon = 500, 25
    labels = _overlapping_labels(n, horizon)
    split = next(purged_walk_forward_splits(n, labels, n_folds=5))
    start = split.test.min()
    # Every retained training observation's label resolves strictly before the
    # test block opens.
    assert (labels[split.train] < start).all()
    assert split.purged > 0


def test_walk_forward_expanding_grows_and_rolling_does_not():
    n = 1000
    labels = np.arange(n)
    expanding = [s.train.size for s in purged_walk_forward_splits(n, labels, n_folds=5)]
    rolling = [
        s.train.size for s in purged_walk_forward_splits(n, labels, n_folds=5, expanding=False)
    ]
    assert expanding == sorted(expanding)
    assert expanding[-1] > expanding[0]
    assert max(rolling) - min(rolling) <= 1


def test_walk_forward_splits_are_leak_free():
    n = 800
    labels = _overlapping_labels(n, 30)
    for split in purged_walk_forward_splits(n, labels, n_folds=6):
        assert detect_boundary_leakage(split, labels, n_samples=n).clean


# --- combinatorial ---


def test_combinatorial_yields_every_combination():
    n = 600
    labels = np.arange(n)
    splits = list(combinatorial_purged_splits(n, labels, n_groups=6, n_test_groups=2))
    assert len(splits) == math.comb(6, 2)


def test_combinatorial_test_blocks_are_disjoint_from_training():
    n = 600
    labels = _overlapping_labels(n, 12)
    for split in combinatorial_purged_splits(n, labels, n_groups=6, n_test_groups=2):
        assert np.intersect1d(split.train, split.test).size == 0
        assert detect_boundary_leakage(split, labels, n_samples=n).clean


def test_combinatorial_holds_out_more_than_one_block_at_a_time():
    n = 600
    splits = list(combinatorial_purged_splits(n, np.arange(n), n_groups=6, n_test_groups=3))
    for split in splits:
        assert split.test.size >= 3 * (n // 6) - 3


def test_combinatorial_gap_between_test_blocks_stays_trainable():
    # Rows between two held-out blocks belong to neither test segment, so
    # with zero-width labels and no embargo they must survive the purge.
    n = 600
    labels = np.arange(n)
    saw_gap = False
    for split in combinatorial_purged_splits(
        n, labels, n_groups=6, n_test_groups=2, embargo_fraction=0.0
    ):
        test = np.sort(split.test)
        blocks = np.split(test, np.flatnonzero(np.diff(test) > 1) + 1)
        if len(blocks) < 2:
            continue  # adjacent held-out groups merge into one segment
        saw_gap = True
        for left, right in zip(blocks, blocks[1:]):
            gap = np.arange(left[-1] + 1, right[0])
            assert gap.size > 0
            assert np.isin(gap, split.train).all()
    assert saw_gap


# --- label end times as a pandas Series of timestamps ---


def test_label_end_times_accepts_a_timestamp_series():
    index = pd.date_range("2024-01-01", periods=200, freq="B")
    # Each label resolves 5 business days later.
    ends = pd.Series(index.to_series().shift(-5).bfill().values, index=index)
    splits = list(purged_kfold_splits(len(index), ends, n_folds=4, embargo_fraction=0.0))
    assert len(splits) == 4
    for split in splits:
        assert np.intersect1d(split.train, split.test).size == 0
        assert split.purged >= 0


def test_label_ending_between_observations_maps_to_the_prior_observation():
    index = pd.date_range("2024-01-01", periods=10, freq="B")
    ends = pd.Series(index, index=index)
    # Observation 3 starts on Thursday and resolves on Saturday. The second
    # fold begins on Monday, so this label does not overlap that test block.
    ends.iloc[3] = pd.Timestamp("2024-01-06")

    split = list(
        purged_kfold_splits(len(index), ends, n_folds=2, embargo_fraction=0.0)
    )[1]

    assert split.test_bounds == (5, 9)
    assert 3 in split.train
    assert split.purged == 0


def test_label_ending_on_an_observation_keeps_that_exact_position():
    index = pd.date_range("2024-01-01", periods=10, freq="B")
    ends = pd.Series(index, index=index)
    # Observation 3 resolves exactly when the second fold begins, so closed
    # intervals overlap at that instant and the observation must be purged.
    ends.iloc[3] = index[5]

    split = list(
        purged_kfold_splits(len(index), ends, n_folds=2, embargo_fraction=0.0)
    )[1]

    assert 3 not in split.train
    assert split.purged == 1


def test_a_label_ending_before_it_starts_is_rejected():
    bad = np.arange(100) - 5
    with pytest.raises(ValueError, match="cannot end before"):
        purged_kfold_splits(100, bad, n_folds=4).__next__()


# --- fold accounting and validation ---


def test_every_observation_is_tested_exactly_once_across_kfold():
    n = 1000
    tested = np.concatenate([s.test for s in purged_kfold_splits(n, np.arange(n), n_folds=5)])
    assert np.array_equal(np.sort(tested), np.arange(n))


def test_folds_come_back_in_chronological_order():
    n = 500
    bounds = [s.test_bounds for s in purged_kfold_splits(n, np.arange(n), n_folds=5)]
    assert bounds == sorted(bounds)


@pytest.mark.parametrize("n_folds", [0, 1, MIN_FOLDS - 1])
def test_too_few_folds_rejected(n_folds):
    with pytest.raises(ValueError, match="at least"):
        list(purged_kfold_splits(100, np.arange(100), n_folds=n_folds))


def test_more_folds_than_samples_rejected():
    with pytest.raises(ValueError, match="cannot make"):
        list(purged_kfold_splits(3, np.arange(3), n_folds=5))


@pytest.mark.parametrize("fraction", [-0.01, 1.0, 2.0])
def test_bad_embargo_fraction_rejected(fraction):
    with pytest.raises(ValueError, match="embargo_fraction"):
        list(purged_kfold_splits(100, np.arange(100), n_folds=4, embargo_fraction=fraction))


def test_mismatched_label_length_rejected():
    with pytest.raises(ValueError, match="entries but the sample has"):
        list(purged_kfold_splits(100, np.arange(50), n_folds=4))


def test_excessive_embargo_removing_all_training_samples_rejected():
    # A 2-fold split with 80% embargo removes all training samples
    with pytest.raises(ValueError, match="removed all training samples"):
        list(purged_kfold_splits(10, np.arange(10), n_folds=2, embargo_fraction=0.8))

    groups = [1, 1, 2, 2]
    with pytest.raises(ValueError, match="removed all training samples"):
        list(group_purged_kfold_splits(groups, n_folds=2, embargo_fraction=0.8))


@pytest.mark.parametrize("n_test_groups", [0, 6, 7])
def test_bad_combinatorial_group_count_rejected(n_test_groups):
    with pytest.raises(ValueError, match="n_test_groups"):
        list(combinatorial_purged_splits(600, np.arange(600), n_groups=6, n_test_groups=n_test_groups))


def test_purge_counts_are_reported_not_hidden():
    n = 1000
    labels = _overlapping_labels(n, 25)
    for split in purged_kfold_splits(n, labels, n_folds=5):
        removed = n - split.train.size - split.test.size
        assert split.purged + split.embargoed == removed

# --------------------------------------------------------------------------
# group_purged_kfold_splits
# --------------------------------------------------------------------------


def test_group_purged_kfold_splits_prevents_cross_sectional_leakage():
    # 10 assets x 100 dates = 1000 observations
    n_dates = 100
    n_assets = 10
    dates = np.repeat(np.arange(n_dates), n_assets)

    splits = list(group_purged_kfold_splits(dates, n_folds=5, embargo_fraction=0.05))
    assert len(splits) == 5

    for split in splits:
        # 1. No shared row indices
        assert len(np.intersect1d(split.train, split.test)) == 0

        # 2. No shared dates between train and test
        train_dates = set(dates[split.train])
        test_dates = set(dates[split.test])
        assert train_dates.intersection(test_dates) == set()

        # 3. Exactly n_assets * number of test dates in test set
        assert len(split.test) == len(test_dates) * n_assets

        # 4. Embargo is applied to subsequent dates
        test_max_date = max(test_dates)
        embargo_expected_end = test_max_date + int(round(n_dates * 0.05))
        for d in range(test_max_date + 1, min(n_dates, embargo_expected_end)):
            assert d not in train_dates


def test_group_purged_kfold_splits_input_validation():
    with pytest.raises(ValueError, match="at least 2"):
        list(group_purged_kfold_splits([1, 1, 2, 2], n_folds=1))
    with pytest.raises(ValueError, match="cannot make 5 folds"):
        list(group_purged_kfold_splits([1, 1, 2, 2], n_folds=5))
    with pytest.raises(ValueError, match="groups array cannot be empty"):
        list(group_purged_kfold_splits([], n_folds=2))


def test_group_purged_kfold_splits_leaks_a_forward_looking_label_without_purging():
    """Groups adjacent to the test block are embargoed, but a group further
    back whose own label reaches forward into the test window was never
    checked at all -- group_purged_kfold_splits hardcoded purged=0 and took
    no label_end_times, unlike every other splitter in this module. This
    reproduces the leak directly against the module's own leakage auditor.
    """
    n_dates, n_assets = 10, 2
    dates = np.repeat(np.arange(n_dates), n_assets)
    n = len(dates)
    # Each row's label resolves 3 rows (~1.5 dates) later.
    label_end_times = np.minimum(np.arange(n) + 3, n - 1)

    splits = list(
        group_purged_kfold_splits(dates, n_folds=5, embargo_fraction=0.3)
    )
    reports = [
        detect_boundary_leakage(split, label_end_times, n_samples=n, embargo_size=3)
        for split in splits
    ]

    assert any(not report.clean for report in reports)


def test_group_purged_kfold_splits_purges_a_forward_looking_label():
    n_dates, n_assets = 10, 2
    dates = np.repeat(np.arange(n_dates), n_assets)
    n = len(dates)
    label_end_times = np.minimum(np.arange(n) + 3, n - 1)

    splits = list(
        group_purged_kfold_splits(
            dates, label_end_times=label_end_times, n_folds=5, embargo_fraction=0.3
        )
    )

    for split in splits:
        report = detect_boundary_leakage(
            split, label_end_times, n_samples=n, embargo_size=3
        )
        assert report.clean, f"leak: overlapping={report.overlapping.tolist()}"


def test_group_purged_kfold_splits_reports_purged_count():
    n_dates, n_assets = 10, 2
    dates = np.repeat(np.arange(n_dates), n_assets)
    n = len(dates)
    label_end_times = np.minimum(np.arange(n) + 3, n - 1)

    splits = list(
        group_purged_kfold_splits(
            dates, label_end_times=label_end_times, n_folds=5, embargo_fraction=0.3
        )
    )

    assert any(split.purged > 0 for split in splits)


def test_group_purged_kfold_splits_without_label_end_times_is_unchanged():
    """The default (no label_end_times) path must behave exactly as before:
    no backward purging, purged always 0."""
    n_dates, n_assets = 100, 10
    dates = np.repeat(np.arange(n_dates), n_assets)

    splits = list(group_purged_kfold_splits(dates, n_folds=5, embargo_fraction=0.05))

    for split in splits:
        assert split.purged == 0


def test_timestamp_label_index_must_be_ordered_and_unique():
    index = pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-02", "2024-01-04"])
    ends = pd.Series(index, index=index)
    with pytest.raises(ValueError, match="monotonically increasing"):
        list(purged_kfold_splits(len(index), ends, n_folds=2))

    duplicate = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"])
    ends = pd.Series(duplicate, index=duplicate)
    with pytest.raises(ValueError, match="unique"):
        list(purged_kfold_splits(len(duplicate), ends, n_folds=2))



def test_a_timestamp_label_cannot_end_before_it_starts():
    """The positional branch rejected this; the Series branch clipped it to its start."""
    index = pd.date_range("2024-01-01", periods=4)
    ends = pd.Series([index[1], index[0], index[3], index[3]], index=index)
    with pytest.raises(ValueError, match="cannot end before"):
        list(purged_kfold_splits(len(index), ends, n_folds=2))


def test_a_nat_label_end_purges_through_the_last_observation():
    """NaT is the tail of ``shift(-h)``: a label resolving after the sample ends."""
    index = pd.date_range("2024-01-01", periods=4)
    ends = pd.Series([index[1], pd.NaT, index[3], index[3]], index=index)
    assert _as_label_spans(ends).tolist() == [1, 3, 3, 3]
