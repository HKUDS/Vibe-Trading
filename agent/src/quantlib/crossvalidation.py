"""Purged and embargoed cross-validation for overlapping financial labels.

Plain K-fold assumes observations are independent. Financial labels are not: a
label formed at time ``t`` from the next 20 days of returns overlaps the labels
of the following 19 observations. Split such a sample naively and the training
set contains observations whose outcome window covers the test period. The model
is then evaluated on information it already saw, and the out-of-sample score is
not out of sample.

Two corrections, both from Lopez de Prado's treatment, and they fix different
leaks:

**Purging** removes from the training set any observation whose label interval
overlaps the test interval. This is the leak above, and it is *symmetric*: an
overlap matters whether the training observation starts before or after the test
window opens.

**Embargo** additionally removes training observations that begin shortly after
the test set ends. Purging alone does not catch this, because those labels do
not overlap -- they are merely serially correlated with the test period through
autocorrelated features and slow-moving state. The embargo is a blunt instrument
by design; its size is a judgement about how fast the series forgets.

THE OFF-BY-ONE IS THE WHOLE POINT
---------------------------------
The single most common implementation bug in this area is a boundary that leaks
exactly one bar: taking the test block as ``[start, end]`` and the training
block as everything outside ``[start, end)``, so the bar at ``end`` sits in both.
:func:`detect_boundary_leakage` exists to make that class of error assertable
rather than reviewable, and every splitter here is checked with it.

INTERVALS ARE CLOSED ON BOTH ENDS
---------------------------------
A label spanning ``[t0, t1]`` includes both endpoints. Two labels touching at a
single instant therefore *do* overlap. This is the conservative reading and it
is stated here because the alternative silently keeps one bar of contamination
at every boundary.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "DEFAULT_EMBARGO_FRACTION",
    "MIN_FOLDS",
    "LeakageReport",
    "Split",
    "combinatorial_purged_splits",
    "detect_boundary_leakage",
    "group_purged_kfold_splits",
    "purged_kfold_splits",
    "purged_walk_forward_splits",
]

#: Fraction of the total sample embargoed after each test block. 0.01 is the
#: published default; it is a judgement about serial correlation, not a constant
#: of nature, and a strongly autocorrelated feature set deserves more.
DEFAULT_EMBARGO_FRACTION: float = 0.01

#: Fewest folds that leave anything to train on.
MIN_FOLDS: int = 2


@dataclass(frozen=True)
class Split:
    """One train/test partition of the sample.

    Attributes:
        train: Positional indices of the training observations, ascending.
        test: Positional indices of the test observations, ascending.
        purged: How many observations were removed from training for overlapping
            the test interval.
        embargoed: How many were removed for falling inside the embargo window.
        test_bounds: ``(first, last)`` positional index of the test block. For a
            combinatorial split with several blocks this is the outer hull.
    """

    train: np.ndarray
    test: np.ndarray
    purged: int
    embargoed: int
    test_bounds: tuple[int, int]


@dataclass(frozen=True)
class LeakageReport:
    """Result of auditing a split for contamination.

    Attributes:
        overlapping: Positional indices of training observations whose label
            interval overlaps the test interval. Non-empty means purging failed.
        shared: Indices present in both the training and the test set. Non-empty
            means an off-by-one at the boundary.
        embargo_violations: Training indices that start inside the embargo
            window after the test block.
        clean: True when all three are empty.
    """

    overlapping: np.ndarray
    shared: np.ndarray
    embargo_violations: np.ndarray
    clean: bool


def _as_label_spans(
    label_end_times: pd.Series | Sequence[int] | np.ndarray,
    n_samples: int | None = None,
) -> np.ndarray:
    """Normalise label end times into positional spans.

    Args:
        label_end_times: Either a pandas Series whose index is the label start
            time and whose values are the label end time, or a positional array
            where element ``i`` is the last positional index observation ``i``'s
            label depends on.
        n_samples: Expected number of samples, checked when supplied.

    Returns:
        Integer array ``ends`` where ``ends[i]`` is the last positional index
        that observation ``i``'s label covers. Always at least ``i``.

    Raises:
        ValueError: If the input is empty, not 1-D, holds a non-finite value, or
            declares a label ending before it starts.
    """
    if isinstance(label_end_times, pd.Series):
        if label_end_times.empty:
            raise ValueError("label_end_times is empty")
        starts = label_end_times.index
        if not starts.is_monotonic_increasing or not starts.is_unique:
            raise ValueError(
                "label_end_times index must be unique and monotonically increasing"
            )
        ends = label_end_times.to_numpy()
        # A NaT end is a label that resolves after the sample ends (the tail of
        # ``index.shift(-h)``); searchsorted places it last, which purges the
        # most. An end before its own start is an error here as in the
        # positional branch -- the clip below would lift it without a word.
        if (ends < starts.to_numpy()).any():
            raise ValueError(
                "a label cannot end before the observation it belongs to starts"
            )
        # searchsorted on the start index converts label end *times* into label
        # end *positions*; the right insertion point minus one keeps a label
        # that ends between two observations attached to the earlier one.
        positions = np.searchsorted(starts, ends, side="right") - 1
        positions = np.clip(positions, np.arange(len(starts)), len(starts) - 1)
        span_ends = positions.astype(int)
    else:
        span_ends = np.asarray(label_end_times, dtype=float)
        if span_ends.ndim != 1:
            raise ValueError(f"label_end_times must be 1-D, got shape {span_ends.shape}")
        if span_ends.size == 0:
            raise ValueError("label_end_times is empty")
        if not np.isfinite(span_ends).all():
            raise ValueError("label_end_times holds a non-finite value")
        span_ends = span_ends.astype(int)
        if (span_ends < np.arange(span_ends.size)).any():
            raise ValueError(
                "a label cannot end before the observation it belongs to starts"
            )

    if n_samples is not None and span_ends.size != n_samples:
        raise ValueError(
            f"label_end_times has {span_ends.size} entries but the sample has {n_samples}"
        )
    return span_ends


def _apply_purge_and_embargo(
    label_ends: np.ndarray,
    test_mask: np.ndarray,
    embargo_size: int,
) -> tuple[np.ndarray, int, int]:
    """Build a training mask that is purged of overlap and embargoed after.

    Args:
        label_ends: Last positional index each observation's label covers.
        test_mask: Boolean mask of the test observations.
        embargo_size: Observations embargoed immediately after each test block.

    Returns:
        Tuple of ``(train_indices, purged_count, embargoed_count)``.
    """
    n = label_ends.size
    starts = np.arange(n)
    test_positions = np.flatnonzero(test_mask)
    if test_positions.size == 0:
        return (starts, 0, 0)

    candidate = ~test_mask
    breaks = np.where(np.diff(test_positions) > 1)[0]
    segment_starts = np.insert(test_positions[breaks + 1], 0, test_positions[0])
    segment_ends = np.append(test_positions[breaks], test_positions[-1])

    purged_mask = np.zeros(n, dtype=bool)
    embargo_mask = np.zeros(n, dtype=bool)

    for seg_start, seg_end in zip(segment_starts, segment_ends):
        seg_positions = np.arange(seg_start, seg_end + 1)
        seg_span_end = int(max(seg_end, label_ends[seg_positions].max()))

        overlaps = (starts <= seg_span_end) & (label_ends >= seg_start)
        purged_mask |= (candidate & overlaps)

        if embargo_size > 0:
            emb_end = min(seg_span_end + embargo_size, n - 1)
            in_emb = (starts > seg_span_end) & (starts <= emb_end)
            embargo_mask |= (candidate & in_emb)

    candidate_after_purge = candidate & ~purged_mask
    embargo_mask = candidate_after_purge & embargo_mask
    train_mask = candidate_after_purge & ~embargo_mask

    return (
        np.flatnonzero(train_mask),
        int(purged_mask.sum()),
        int(embargo_mask.sum()),
    )


def purged_kfold_splits(
    n_samples: int,
    label_end_times: pd.Series | Sequence[int] | np.ndarray | None = None,
    n_folds: int = 5,
    embargo_fraction: float = DEFAULT_EMBARGO_FRACTION,
) -> Iterator[Split]:
    """K contiguous test blocks, each with training purged and embargoed.

    Folds are contiguous in time rather than shuffled: shuffling destroys the
    very ordering purging exists to respect.

    Args:
        n_samples: Number of observations.
        label_end_times: Where each label's outcome window ends. When None, each
            label is assumed to resolve within its own bar, so purging removes
            only the boundary and the embargo does the remaining work.
        n_folds: Number of folds, at least :data:`MIN_FOLDS`.
        embargo_fraction: Fraction of the sample embargoed after each test block.

    Yields:
        One :class:`Split` per fold, in chronological order of the test block.

    Raises:
        ValueError: If ``n_folds`` is below :data:`MIN_FOLDS`, exceeds the
            sample size, if ``embargo_fraction`` is negative or at least 1, or
            if ``label_end_times`` does not match the sample.
    """
    if n_folds < MIN_FOLDS:
        raise ValueError(f"n_folds must be at least {MIN_FOLDS}, got {n_folds}")
    if n_samples < n_folds:
        raise ValueError(f"{n_samples} samples cannot make {n_folds} folds")
    if not 0.0 <= embargo_fraction < 1.0:
        raise ValueError(
            f"embargo_fraction must be in [0, 1), got {embargo_fraction}"
        )

    if label_end_times is None:
        label_ends = np.arange(n_samples)
    else:
        label_ends = _as_label_spans(label_end_times, n_samples)

    embargo_size = int(round(n_samples * embargo_fraction))
    boundaries = np.linspace(0, n_samples, n_folds + 1).astype(int)

    for fold in range(n_folds):
        start, stop = int(boundaries[fold]), int(boundaries[fold + 1])
        if stop <= start:
            continue
        test_mask = np.zeros(n_samples, dtype=bool)
        test_mask[start:stop] = True

        train, purged, embargoed = _apply_purge_and_embargo(
            label_ends, test_mask, embargo_size
        )
        if train.size == 0:
            raise ValueError(f"Purge and embargo removed all training samples for fold {fold}")
        yield Split(
            train=train,
            test=np.arange(start, stop),
            purged=purged,
            embargoed=embargoed,
            test_bounds=(start, stop - 1),
        )


def group_purged_kfold_splits(
    groups: Sequence[object] | pd.Series | np.ndarray,
    n_folds: int = 5,
    embargo_fraction: float = DEFAULT_EMBARGO_FRACTION,
    *,
    label_end_times: pd.Series | Sequence[int] | np.ndarray | None = None,
) -> Iterator[Split]:
    """Purged and embargoed K-fold cross-validation for panel and multi-asset datasets.

    Groups all observations sharing a time group identifier (e.g. date or bar timestamp)
    so that simultaneous observations across different assets are never split across
    train and test partitions.

    Args:
        groups: Group identifiers (e.g. dates or bar index) for each sample row in order.
        n_folds: Number of folds, at least :data:`MIN_FOLDS`.
        embargo_fraction: Fraction of unique ordered groups embargoed after each test block.
        label_end_times: Where each row's label resolves, in the same form
            :func:`purged_kfold_splits` takes. Groups must be contiguous and
            chronological when supplied. Overlap removes a whole group;
            embargo starts after the furthest test label ends. When None,
            labels resolve within their own group and only embargo applies.

    Yields:
        One :class:`Split` per fold, with ``train`` and ``test`` containing row indices.

    Raises:
        ValueError: If ``n_folds`` is invalid, fewer unique groups than folds exist,
            or ``embargo_fraction`` is out of bounds.
    """
    if n_folds < MIN_FOLDS:
        raise ValueError(f"n_folds must be at least {MIN_FOLDS}, got {n_folds}")
    if not 0.0 <= embargo_fraction < 1.0:
        raise ValueError(f"embargo_fraction must be in [0, 1), got {embargo_fraction}")

    grp_array = np.asarray(groups)
    n_samples = len(grp_array)
    if n_samples == 0:
        raise ValueError("groups array cannot be empty")

    # Find unique groups preserving chronological order of appearance
    unique_groups, first_indices = np.unique(grp_array, return_index=True)
    # Sort by appearance order
    order = np.argsort(first_indices)
    unique_groups = unique_groups[order]
    n_groups = len(unique_groups)

    if n_groups < n_folds:
        raise ValueError(f"{n_groups} unique groups cannot make {n_folds} folds")

    # Map each group to its member row indices
    group_to_rows: dict[object, np.ndarray] = {}
    for idx, g in enumerate(grp_array):
        group_to_rows.setdefault(g, []).append(idx)
    for g in group_to_rows:
        group_to_rows[g] = np.array(group_to_rows[g], dtype=int)

    # Position of each group in chronological order, and the same per row --
    # used below to translate a row-level label span into the furthest group
    # a group's own rows reach into.
    group_order = {g: i for i, g in enumerate(unique_groups)}
    row_group_order = np.array([group_order[g] for g in grp_array])

    if label_end_times is None:
        # A label resolves within its own group: it can never reach forward
        # into a later group, so there is nothing for backward purging to do.
        group_reach = np.arange(n_groups)
    else:
        if np.any(np.diff(row_group_order) < 0):
            raise ValueError("groups must be contiguous and chronological when label_end_times is supplied")
        label_ends = _as_label_spans(label_end_times, n_samples)
        group_reach = np.array(
            [row_group_order[np.minimum(label_ends[group_to_rows[g]], n_samples - 1)].max() for g in unique_groups]
        )

    embargo_groups = int(round(n_groups * embargo_fraction))
    boundaries = np.linspace(0, n_groups, n_folds + 1).astype(int)

    for fold in range(n_folds):
        start_g, stop_g = int(boundaries[fold]), int(boundaries[fold + 1])
        if stop_g <= start_g:
            continue

        test_groups = set(unique_groups[start_g:stop_g])
        test_reach = int(group_reach[start_g:stop_g].max())
        embargo_start_g = test_reach + 1
        embargo_end_g = min(n_groups, embargo_start_g + embargo_groups)
        embargo_groups_set = set(unique_groups[embargo_start_g:embargo_end_g])

        # Closed label intervals overlap on either side of the test block.
        # Future groups inside the test labels' horizon must be purged too.
        purge_groups_set = {
            unique_groups[g_idx]
            for g_idx in range(n_groups)
            if g_idx <= test_reach and group_reach[g_idx] >= start_g
            and unique_groups[g_idx] not in test_groups
        }

        test_rows_list = [group_to_rows[g] for g in unique_groups[start_g:stop_g]]
        test_rows = np.concatenate(test_rows_list) if test_rows_list else np.array([], dtype=int)
        if test_rows.size == 0:
            continue
        train_rows_list = []
        for g in unique_groups:
            if g not in test_groups and g not in embargo_groups_set and g not in purge_groups_set:
                train_rows_list.append(group_to_rows[g])

        train_rows = np.concatenate(train_rows_list) if train_rows_list else np.array([], dtype=int)
        if train_rows.size == 0:
            raise ValueError(f"Purge and embargo removed all training samples for fold {fold}")
        train_rows.sort()
        test_rows.sort()

        embargoed_count = sum(len(group_to_rows[g]) for g in embargo_groups_set)
        purged_count = sum(len(group_to_rows[g]) for g in purge_groups_set)

        yield Split(
            train=train_rows,
            test=test_rows,
            purged=purged_count,
            embargoed=embargoed_count,
            test_bounds=(int(test_rows.min()), int(test_rows.max())),
        )


def purged_walk_forward_splits(
    n_samples: int,
    label_end_times: pd.Series | Sequence[int] | np.ndarray | None = None,
    n_folds: int = 5,
    embargo_fraction: float = DEFAULT_EMBARGO_FRACTION,
    expanding: bool = True,
) -> Iterator[Split]:
    """Walk-forward splits that only ever train on the past.

    Purged K-fold trains on data from *after* the test block as well, which is
    correct for estimating generalisation but wrong for simulating a strategy
    that had to be run in real time. This variant keeps training strictly before
    the test block, and still purges the boundary, because the last training
    label can easily reach into the test window.

    Args:
        n_samples: Number of observations.
        label_end_times: Where each label's outcome window ends.
        n_folds: Number of test blocks; the first block of the sample is used
            only for training.
        embargo_fraction: Retained for signature symmetry with
            :func:`purged_kfold_splits`. An embargo *after* the test block is
            vacuous here because nothing after the test block is ever trained
            on, so this only affects the reported ``embargoed`` count.
        expanding: True for an expanding training window (all history so far),
            False for a rolling window the size of one fold.

    Yields:
        One :class:`Split` per test block, chronologically. A block whose
        training set would be empty is skipped.

    Raises:
        ValueError: Same conditions as :func:`purged_kfold_splits`.
    """
    if n_folds < MIN_FOLDS:
        raise ValueError(f"n_folds must be at least {MIN_FOLDS}, got {n_folds}")
    if n_samples < n_folds:
        raise ValueError(f"{n_samples} samples cannot make {n_folds} folds")
    if not 0.0 <= embargo_fraction < 1.0:
        raise ValueError(f"embargo_fraction must be in [0, 1), got {embargo_fraction}")

    if label_end_times is None:
        label_ends = np.arange(n_samples)
    else:
        label_ends = _as_label_spans(label_end_times, n_samples)

    boundaries = np.linspace(0, n_samples, n_folds + 1).astype(int)

    for fold in range(1, n_folds):
        start, stop = int(boundaries[fold]), int(boundaries[fold + 1])
        if stop <= start:
            continue

        train_start = 0 if expanding else int(boundaries[fold - 1])
        candidate = np.arange(train_start, start)
        if candidate.size == 0:
            continue

        # Purge: a past label whose outcome window reaches into the test block
        # has already seen the test period.
        reaches_in = label_ends[candidate] >= start
        train = candidate[~reaches_in]
        yield Split(
            train=train,
            test=np.arange(start, stop),
            purged=int(reaches_in.sum()),
            embargoed=0,
            test_bounds=(start, stop - 1),
        )


def combinatorial_purged_splits(
    n_samples: int,
    label_end_times: pd.Series | Sequence[int] | np.ndarray | None = None,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo_fraction: float = DEFAULT_EMBARGO_FRACTION,
) -> Iterator[Split]:
    """Every combination of ``n_test_groups`` blocks held out at once.

    A single K-fold gives one estimate of generalisation per fold; combinatorial
    splits give ``C(n_groups, n_test_groups)`` of them, from which a distribution
    of out-of-sample performance can be built rather than a point estimate. This
    is the sampler behind CSCV-style overfitting diagnostics.

    Args:
        n_samples: Number of observations.
        label_end_times: Where each label's outcome window ends.
        n_groups: Contiguous blocks the sample is divided into.
        n_test_groups: Blocks held out per split.
        embargo_fraction: Fraction embargoed after each held-out region.

    Yields:
        One :class:`Split` per combination, with ``test`` holding the union of
        the held-out blocks.

    Raises:
        ValueError: If ``n_test_groups`` is not in ``[1, n_groups - 1]``, if
            ``n_groups`` exceeds the sample size, or if ``embargo_fraction`` is
            out of range.
    """
    from itertools import combinations

    if n_groups > n_samples:
        raise ValueError(f"{n_samples} samples cannot make {n_groups} groups")
    if not 1 <= n_test_groups < n_groups:
        raise ValueError(
            f"n_test_groups must be in [1, {n_groups - 1}], got {n_test_groups}"
        )
    if not 0.0 <= embargo_fraction < 1.0:
        raise ValueError(f"embargo_fraction must be in [0, 1), got {embargo_fraction}")

    if label_end_times is None:
        label_ends = np.arange(n_samples)
    else:
        label_ends = _as_label_spans(label_end_times, n_samples)

    embargo_size = int(round(n_samples * embargo_fraction))
    boundaries = np.linspace(0, n_samples, n_groups + 1).astype(int)
    blocks = [
        np.arange(int(boundaries[i]), int(boundaries[i + 1])) for i in range(n_groups)
    ]

    for chosen in combinations(range(n_groups), n_test_groups):
        test = np.concatenate([blocks[i] for i in chosen])
        if test.size == 0:
            continue
        test_mask = np.zeros(n_samples, dtype=bool)
        test_mask[test] = True

        train, purged, embargoed = _apply_purge_and_embargo(
            label_ends, test_mask, embargo_size
        )
        if train.size == 0:
            raise ValueError("Purge and embargo removed all training samples for fold")
        yield Split(
            train=train,
            test=np.sort(test),
            purged=purged,
            embargoed=embargoed,
            test_bounds=(int(test.min()), int(test.max())),
        )


def detect_boundary_leakage(
    split: Split,
    label_end_times: pd.Series | Sequence[int] | np.ndarray | None = None,
    n_samples: int | None = None,
    embargo_size: int = 0,
) -> LeakageReport:
    """Audit a split for the three ways training can see the test period.

    This is the assertion that makes the off-by-one class of bug testable. Point
    it at any splitter -- including one from another library -- and it reports
    contamination rather than requiring the boundary arithmetic to be reviewed
    by eye.

    Args:
        split: The split to audit.
        label_end_times: Where each label's outcome window ends. When None, each
            label is assumed to resolve within its own bar and only the shared
            index check is meaningful.
        n_samples: Total sample size, needed only when ``label_end_times`` is a
            positional array of a different length.
        embargo_size: Observations that should have been embargoed after the
            test block, for checking the embargo was actually applied.

    Returns:
        A :class:`LeakageReport`.

    Raises:
        ValueError: If ``label_end_times`` cannot be normalised.
    """
    shared = np.intersect1d(split.train, split.test)

    if label_end_times is None:
        overlapping = np.array([], dtype=int)
    else:
        label_ends = _as_label_spans(label_end_times, n_samples)
        test_positions = np.sort(split.test)
        breaks = np.where(np.diff(test_positions) > 1)[0]
        segment_starts = np.insert(test_positions[breaks + 1], 0, test_positions[0])
        segment_ends = np.append(test_positions[breaks], test_positions[-1])

        train_starts = split.train
        train_ends = label_ends[split.train]
        overlapping_mask = np.zeros(len(train_starts), dtype=bool)
        for seg_start, seg_end in zip(segment_starts, segment_ends):
            seg_positions = np.arange(seg_start, seg_end + 1)
            seg_span_end = int(max(seg_end, label_ends[seg_positions].max()))
            overlapping_mask |= (train_starts <= seg_span_end) & (train_ends >= seg_start)
        overlapping = train_starts[overlapping_mask]

    if embargo_size > 0:
        if label_end_times is None:
            label_ends = np.arange(n_samples or (int(split.test.max()) + 1))
        else:
            label_ends = _as_label_spans(label_end_times, n_samples)
        test_positions = np.sort(split.test)
        breaks = np.where(np.diff(test_positions) > 1)[0]
        segment_starts = np.insert(test_positions[breaks + 1], 0, test_positions[0])
        segment_ends = np.append(test_positions[breaks], test_positions[-1])

        violations_mask = np.zeros(len(split.train), dtype=bool)
        for seg_start, seg_end in zip(segment_starts, segment_ends):
            seg_positions = np.arange(seg_start, seg_end + 1)
            seg_span_end = int(max(seg_end, label_ends[seg_positions].max()))
            violations_mask |= (split.train > seg_span_end) & (split.train <= seg_span_end + embargo_size)
        violations = split.train[violations_mask]
    else:
        violations = np.array([], dtype=int)

    return LeakageReport(
        overlapping=overlapping,
        shared=shared,
        embargo_violations=violations,
        clean=overlapping.size == 0 and shared.size == 0 and violations.size == 0,
    )
