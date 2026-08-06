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
    combinatorial_purged_splits,
    detect_boundary_leakage,
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
