"""GTJA #17 raises the percentile rank to the signed 5-day close change.

A rank of 0.5 and a close change of -2 is 0.5 ** -2 = 4. Taking the absolute
value of the exponent reported 0.25.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.zoo.gtja191 import alpha_017


@pytest.mark.parametrize("width", [2, 5, 100])
def test_negative_close_change_inverts_the_rank_power(width):
    idx = pd.bdate_range("2024-01-01", periods=20)
    columns = ["A", *[f"X{i}" for i in range(width - 2)], "B"]
    close = pd.DataFrame(10.0, index=idx, columns=columns)
    close.loc[idx[-1], ["A", "B"]] = [8.0, 12.0]
    vwap = pd.DataFrame(10.0, index=idx, columns=columns)
    vwap.iloc[-1] = np.linspace(8.0, 10.0, width)
    panel = {
        "close": close,
        "vwap": vwap,
        "volume": pd.DataFrame(1.0, index=idx, columns=columns),
        "amount": pd.DataFrame(1.0, index=idx, columns=columns),
    }

    got = alpha_017.compute(panel).iloc[-1]

    # vwap - 15-day max is -2 and 0, so the percentile ranks are 0.5 and 1.
    # Deltas are -2 and +2.
    assert got["A"] == pytest.approx((1.0 / width) ** -2)
    assert got["B"] == 1.0
    assert not np.isclose(got["A"], 0.25)


def test_incomplete_windows_stay_missing_instead_of_powering_to_one():
    """NaN ** 0 and 1 ** NaN are both 1 under IEEE pow.

    A flat close makes the 5-day change exactly 0 while the 15-bar VWAP max
    is still warming up, and the top-ranked name has a base of 1 while the
    close change is still undefined; neither bar may report 1.0.
    """
    idx = pd.bdate_range("2024-01-01", periods=20)
    columns = ["A", "B", "C"]
    close = pd.DataFrame(10.0, index=idx, columns=columns)
    # A missing close on bar 17 leaves that bar's 5-day change undefined
    # while every VWAP window is complete; C ranks first, a base of 1.
    close.iloc[16] = np.nan
    vwap = pd.DataFrame([[9.0, 10.0, 11.0]] * len(idx), index=idx, columns=columns)
    # A and B trade below their 15-bar VWAP high on that bar, C at it.
    vwap.iloc[16, [0, 1]] = [8.0, 9.5]
    panel = {
        "close": close,
        "vwap": vwap,
        "volume": pd.DataFrame(1.0, index=idx, columns=columns),
        "amount": pd.DataFrame(1.0, index=idx, columns=columns),
    }

    got = alpha_017.compute(panel)

    # ts_max(VWAP, 15) is undefined on the first 14 bars, so is the base.
    assert got.iloc[:14].isna().all().all()
    assert got.iloc[16].isna().all()
    # Elsewhere the window and the 5-day change are both complete.
    assert got.iloc[[14, 15, 17, 18, 19]].notna().all().all()
