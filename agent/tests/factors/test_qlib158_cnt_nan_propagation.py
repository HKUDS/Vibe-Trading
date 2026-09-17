"""Regression: qlib158 CNTP/CNTN/CNTD must propagate NaN through a data gap
instead of counting a missing close as a flat day.

Each factor converts a comparison against the prior close to 0.0/1.0 and takes
its rolling mean::

    up = (c > c.shift(1)).astype("float64")     # cntp
    dn = (c < c.shift(1)).astype("float64")     # cntn
    up_w = up.rolling(window, min_periods=window).mean()   # also cntd

A NaN comparison evaluates False, not NaN, so a missing close (a halt, a gap)
is counted as a day that did not rise — and because the comparison is False at
the gap *and* at the next bar (its prior close is missing), `window + 1`
rolling windows count the gap as a flat day instead of staying NaN. The count
is not wrong by a rounding step: a 5-day window with one gap reports 0.2 where
the observed days say 0.4, so a halt reads as a weaker signal rather than no
signal. That violates base.py's NaN policy ("every operator propagates NaN; no
silent fillna(0)") and the compute() contract for
`agent/src/factors/zoo/**` — NaN preserved at missing-data positions.

The gap must therefore stay NaN through every window that still touches it, and
leave once the gap scrolls out. A *real* tie (close == prior close) is not
missing data and must keep counting as a 0/1 observation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.registry import Registry

N_ROWS = 160
GAP_ROW = 70  # past every window below, so the clean fixture is finite here
SYMBOLS = ["SYM0", "SYM1"]
WINDOWS = (5, 10, 20, 30, 60)


def _panel(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"close": close}


def _close() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2024-01-01", periods=N_ROWS, freq="D")
    return pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(N_ROWS, len(SYMBOLS))), axis=0),
        index=idx,
        columns=SYMBOLS,
    )


def _panel_with_one_gap() -> dict[str, pd.DataFrame]:
    close = _close()
    close.loc[close.index[GAP_ROW], "SYM1"] = np.nan
    return _panel(close)


def _panel_without_gap() -> dict[str, pd.DataFrame]:
    return _panel(_close())


def _panel_with_a_real_tie() -> dict[str, pd.DataFrame]:
    """One exact tie: two consecutive closes equal, which is a 0.0 comparison."""
    close = _close()
    close.iloc[GAP_ROW + 1, 1] = close.iloc[GAP_ROW, 1]
    return _panel(close)


CASES = [
    (f"qlib158_{family}{window}", window)
    for family in ("cntp", "cntn", "cntd")
    for window in WINDOWS
]


@pytest.mark.parametrize(("alpha_id", "window"), CASES)
def test_gap_stays_nan_through_the_full_affected_window(alpha_id: str, window: int) -> None:
    out = Registry().compute(alpha_id, _panel_with_one_gap())

    # The missing close poisons the comparison at GAP_ROW (close missing) and
    # GAP_ROW + 1 (prior close missing), so window + 1 rolling windows still
    # touch it before an unbroken run of observations can fill min_periods.
    affected = out["SYM1"].iloc[GAP_ROW : GAP_ROW + window + 1]
    assert affected.isna().all(), (
        f"{alpha_id}: every window still touching the gap must stay NaN, "
        f"got {affected.tolist()}"
    )

    # And it must actually clear once the gap scrolls out of the window -- back
    # to exactly the no-gap value, not merely to some value.
    clean = Registry().compute(alpha_id, _panel_without_gap())
    after_gap = out["SYM1"].iloc[GAP_ROW + window + 1]
    assert not pd.isna(after_gap), f"{alpha_id}: NaN must not leak past the gap's own window"
    assert after_gap == clean["SYM1"].iloc[GAP_ROW + window + 1], (
        f"{alpha_id}: once the gap leaves the window the value must match the no-gap run, "
        f"got {after_gap} vs {clean['SYM1'].iloc[GAP_ROW + window + 1]}"
    )


@pytest.mark.parametrize(("alpha_id", "window"), CASES)
def test_warmup_edge_does_not_fabricate_from_the_missing_prior_close(alpha_id: str, window: int) -> None:
    """The first comparison has no prior close at all.

    Its window must stay NaN rather than counting a fabricated 0.0: before the
    fix, row ``window - 1`` was defined and wrong on every panel, gap or no
    gap, because the comparison at row 0 evaluated False against a missing
    prior close.
    """
    out = Registry().compute(alpha_id, _panel_without_gap())

    edge = out["SYM1"].iloc[window - 1]
    assert pd.isna(edge), (
        f"{alpha_id}: the window covering the missing prior close must stay NaN, got {edge}"
    )
    first_full = out["SYM1"].iloc[window]
    assert not pd.isna(first_full), (
        f"{alpha_id}: the first fully-observed window must compute, got {first_full}"
    )


@pytest.mark.parametrize(("alpha_id", "window"), CASES)
def test_the_same_span_is_finite_without_a_gap(alpha_id: str, window: int) -> None:
    """Fixture check: the span above is only NaN because of the gap.

    Without this, an all-NaN output (a broken or warmup-only factor) would
    satisfy the gap assertion while proving nothing.
    """
    out = Registry().compute(alpha_id, _panel_without_gap())

    span = out["SYM1"].iloc[GAP_ROW : GAP_ROW + window + 1]
    assert span.notna().all(), (
        f"{alpha_id}: the affected span must be finite when no data is missing, "
        f"got {span.tolist()}"
    )


@pytest.mark.parametrize(("alpha_id", "window"), CASES)
def test_a_real_tie_is_still_an_observation_not_missing_data(alpha_id: str, window: int) -> None:
    """A genuine tie (close == prior close) is a 0/1 observation, not NaN.

    Guards the opposite direction from the gap tests: NaN propagation must not
    be bought by NaNing ties, which would kill every window that happens to
    contain an unchanged close. A change that also masked ties would still pass
    the three tests above, because this fixture's random walk has no exact ties.
    """
    out = Registry().compute(alpha_id, _panel_with_a_real_tie())

    span = out["SYM1"].iloc[GAP_ROW : GAP_ROW + window + 1]
    assert span.notna().all(), (
        f"{alpha_id}: a real tie must stay a 0/1 observation, not NaN, "
        f"got {span.tolist()}"
    )


@pytest.mark.parametrize(("alpha_id", "window"), CASES)
def test_unaffected_symbol_still_computes_real_values(alpha_id: str, window: int) -> None:
    out = Registry().compute(alpha_id, _panel_with_one_gap())
    clean = Registry().compute(alpha_id, _panel_without_gap())

    # Past warmup (the first `window` rows are NaN for every symbol, gap or no
    # gap), a symbol with no gap must be untouched: no stray NaN, and no value
    # changed by another symbol's gap.
    tail_out = out["SYM0"].iloc[window:]
    tail_clean = clean["SYM0"].iloc[window:]
    assert not tail_out.isna().any(), (
        f"{alpha_id}: a symbol with no gap must not pick up stray NaN"
    )
    pd.testing.assert_series_equal(tail_out, tail_clean)
