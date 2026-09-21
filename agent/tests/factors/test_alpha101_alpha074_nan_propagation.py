"""Regression: alpha101_074 must propagate NaN through its warmup and a
data gap instead of fabricating a -0.0/0.0 "not less than" reading.

compute() builds lhs/rhs from layered rolling windows (adv30 -> 37-bar
sum -> 15-bar corr for lhs; an 11-bar corr for rhs), both NaN during
warmup or after a gap. A NaN comparison (lhs < rhs) evaluates False, not
NaN, so .astype(float) * -1.0 always falls through to a fabricated
finite reading instead of propagating NaN. Same bug class already fixed
in alpha101_046/049/051.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.registry import Registry

N_ROWS = 100
GAP_ROW = 40


def _panel(rng, n_rows=N_ROWS, n_symbols=6):
    idx = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    cols = [f"SYM{i}" for i in range(n_symbols)]
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(n_rows, n_symbols)), axis=0),
        index=idx,
        columns=cols,
    )
    high = close + rng.uniform(0.1, 1.0, size=(n_rows, n_symbols))
    volume = pd.DataFrame(
        rng.uniform(1000.0, 5000.0, size=(n_rows, n_symbols)), index=idx, columns=cols
    )
    vwap = (close + high) / 2.0
    return {"close": close, "high": high, "volume": volume, "vwap": vwap}


def test_no_signal_before_lhs_and_rhs_are_both_available():
    rng = np.random.default_rng(3)
    panel = _panel(rng)
    out = Registry().compute("alpha101_074", panel)

    # min_warmup_bars=60 is a lower bound; the layered adv30->sum(37)->
    # corr(15) chain in lhs needs at least 30+37+15-2 = 80 bars before it
    # can be finite. Every row before that must stay NaN, not -0.0/0.0.
    warmup = out.iloc[:79]
    assert warmup.isna().all().all(), (
        f"alpha101_074: rows before lhs/rhs are both defined must stay NaN, "
        f"got {warmup.stack().tolist()[:5]}"
    )
    assert (
        out.iloc[79:].notna().any().any()
    ), "alpha101_074: must produce real values once warmed up"


def test_gap_stays_nan_not_fabricated():
    rng = np.random.default_rng(3)
    panel = _panel(rng)
    panel["close"].loc[panel["close"].index[GAP_ROW], "SYM1"] = np.nan
    out = Registry().compute("alpha101_074", panel)

    # The gap feeds lhs's 15-bar corr window directly at the gap row and
    # for the following 14 rows.
    affected = out["SYM1"].iloc[GAP_ROW : GAP_ROW + 15]
    assert affected.isna().all(), (
        f"alpha101_074: every window still touching the gap must stay NaN, "
        f"got {affected.tolist()}"
    )

    # A gap confined to SYM1's close must not sink the whole panel: SYM0
    # (whose own close is untouched) still produces real values once
    # warmed up.
    assert (
        out["SYM0"].iloc[79:].notna().any()
    ), "alpha101_074: a symbol with no gap must still produce real values"
