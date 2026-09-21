"""Regression: gtja191_038 must propagate NaN through a data gap instead
of fabricating a 0.0 "below MA20" signal.

compute() builds m20 as a 20-day rolling mean that correctly goes NaN
across a gap, but out.where(cond, 0.0) falls through to the hard-coded
0.0 branch whenever m20 is NaN, since a NaN comparison evaluates False,
not NaN. Same bug class already fixed in gtja191_003/004/059/069.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.registry import Registry

N_ROWS = 60
GAP_ROW = 30  # past min_warmup_bars=21
WINDOW = 20


def _panel_with_one_gap() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(2)
    idx = pd.date_range("2024-01-01", periods=N_ROWS, freq="D")
    cols = ["SYM0", "SYM1"]

    high = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, size=(N_ROWS, 2)), axis=0),
        index=idx,
        columns=cols,
    )
    high.loc[idx[GAP_ROW], "SYM1"] = np.nan

    return {"high": high}


def test_gap_stays_nan_through_the_full_affected_window():
    panel = _panel_with_one_gap()
    out = Registry().compute("gtja191_038", panel)

    affected = out["SYM1"].iloc[GAP_ROW : GAP_ROW + WINDOW]
    assert affected.isna().all(), (
        f"gtja191_038: every window still touching the gap must stay NaN, "
        f"got {affected.tolist()}"
    )

    after = out["SYM1"].iloc[GAP_ROW + WINDOW]
    assert not pd.isna(
        after
    ), "gtja191_038: NaN must not leak past the gap's own window"


def test_unaffected_symbol_still_computes_real_values():
    panel = _panel_with_one_gap()
    out = Registry().compute("gtja191_038", panel)

    unaffected = out["SYM0"].iloc[25:]
    assert not unaffected.isna().any(), (
        "gtja191_038: a symbol with no gap must not pick up stray NaN "
        "from another symbol's column"
    )
