"""Regression: alpha101_007 and alpha101_051 must not fabricate a signal
before their declared warmup, and must propagate NaN through a gap.

Both use where_ternary(cond, a, b), where cond is a comparison against a
rolling or delay-based intermediate that is NaN during warmup. A NaN
comparison evaluates False, not NaN, so where_ternary always falls to
the else branch, which stays finite well before the real lookback is
available. where_ternary's own np.isfinite safety net only catches a
non-finite output, not an output computed from an undefined condition,
so it never fires. Same bug class already fixed in alpha101_049.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.registry import Registry

N_ROWS = 120
GAP_ROW = 80


def test_alpha007_no_signal_before_declared_warmup():
    idx = pd.date_range("2024-01-01", periods=N_ROWS, freq="D")
    rng = np.random.default_rng(5)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(N_ROWS, 2)), axis=0),
        index=idx,
        columns=["SYM0", "SYM1"],
    )
    volume = pd.DataFrame(
        rng.integers(1_000, 2_000, size=(N_ROWS, 2)).astype(float),
        index=idx,
        columns=["SYM0", "SYM1"],
    )
    out = Registry().compute("alpha101_007", {"close": close, "volume": volume})

    # adv20 needs 20 observations: rows 0-18 must stay NaN, not the
    # else branch's fabricated constant -1.0.
    warmup = out.iloc[:66]
    assert warmup.isna().all().all(), (
        f"alpha101_007: rows before the complete 67-bar expression history must stay NaN, "
        f"got {warmup.stack().tolist()}"
    )


def test_alpha007_volume_gap_stays_nan():
    idx = pd.date_range("2024-01-01", periods=N_ROWS, freq="D")
    rng = np.random.default_rng(5)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(N_ROWS, 2)), axis=0),
        index=idx,
        columns=["SYM0", "SYM1"],
    )
    volume = pd.DataFrame(
        rng.integers(1_000, 2_000, size=(N_ROWS, 2)).astype(float),
        index=idx,
        columns=["SYM0", "SYM1"],
    )
    volume.loc[idx[GAP_ROW], "SYM1"] = np.nan
    out = Registry().compute("alpha101_007", {"close": close, "volume": volume})

    assert pd.isna(out["SYM1"].iloc[GAP_ROW]), (
        f"alpha101_007: the gap row itself must stay NaN, "
        f"got {out['SYM1'].iloc[GAP_ROW]!r}"
    )


def test_alpha051_no_signal_before_declared_warmup():
    idx = pd.date_range("2024-01-01", periods=N_ROWS, freq="D")
    rng = np.random.default_rng(6)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(N_ROWS, 2)), axis=0),
        index=idx,
        columns=["SYM0", "SYM1"],
    )
    out = Registry().compute("alpha101_051", {"close": close})

    warmup = out.iloc[:20]
    assert warmup.isna().all().all(), (
        f"alpha101_051: rows before the 20-day lookback must stay NaN, "
        f"got {warmup.stack().tolist()}"
    )
    assert pd.notna(out["SYM0"].iloc[20])


def test_alpha051_gap_stays_nan():
    idx = pd.date_range("2024-01-01", periods=N_ROWS, freq="D")
    rng = np.random.default_rng(6)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(N_ROWS, 2)), axis=0),
        index=idx,
        columns=["SYM0", "SYM1"],
    )
    close.loc[idx[GAP_ROW], "SYM1"] = np.nan
    out = Registry().compute("alpha101_051", {"close": close})

    assert pd.isna(out["SYM1"].iloc[GAP_ROW]), (
        f"alpha101_051: the gap row itself must stay NaN, "
        f"got {out['SYM1'].iloc[GAP_ROW]!r}"
    )
    unaffected = out["SYM0"].iloc[20:]
    assert (
        not unaffected.isna().any()
    ), "alpha101_051: a symbol with no gap must not pick up stray NaN"
