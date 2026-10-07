"""Semantic test for ``zoo/qlib158/wvma{5,10,20,30,60}``.

qlib's WVMA is ``ts_std(|ret|*v, n) / ts_mean(|ret|*v, n)`` — both the
numerator and denominator are volume-weighted by the *absolute* return, not
the signed one. This pins that the numerator does use ``|ret|``: with equal-
magnitude, alternating-sign returns and constant volume, ``|ret|*v`` is
constant within the window, so its rolling std is exactly zero. A rolling std
of the signed ``ret*v`` series would instead be large and nonzero.

Upstream formula (both operands use Abs):
https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/qlib/contrib/data/loader.py#L275-L282
The local operators deliberately require complete windows, unlike upstream's
min_periods=1. The scalar oracle below checks the formula on observed windows
without reusing pandas rolling or the production safe_div/std/mean helpers.
"""

from __future__ import annotations

from fractions import Fraction
from statistics import mean, stdev

import numpy as np
import pandas as pd
import pytest

from src.factors.zoo.qlib158.wvma5 import compute as wvma5
from src.factors.zoo.qlib158.wvma10 import compute as wvma10
from src.factors.zoo.qlib158.wvma20 import compute as wvma20
from src.factors.zoo.qlib158.wvma30 import compute as wvma30
from src.factors.zoo.qlib158.wvma60 import compute as wvma60


CASES = [(wvma5, 5), (wvma10, 10), (wvma20, 20), (wvma30, 30), (wvma60, 60)]


def _alternating_panel(window: int) -> dict[str, pd.DataFrame]:
    """One asset whose daily return alternates +/-2% with constant volume.

    ``|ret|*v`` is therefore constant across the window (2.0 per bar), so a
    correctly-implemented WVMA has a zero numerator and evaluates to 0.
    """
    n_bars = window + 1
    close = [100.0]
    for i in range(n_bars - 1):
        step = 1.02 if i % 2 == 0 else 0.98
        close.append(close[-1] * step)
    close_df = pd.DataFrame({"AAA": close})
    volume_df = pd.DataFrame({"AAA": [100.0] * n_bars})
    return {"close": close_df, "volume": volume_df}


@pytest.mark.parametrize(
    "compute,window",
    CASES,
)
def test_wvma_numerator_uses_absolute_return(compute, window: int) -> None:
    panel = _alternating_panel(window)
    out = compute(panel)
    last = out["AAA"].iloc[-1]
    assert last == pytest.approx(0.0, abs=1e-9)


def _varied_panel() -> dict[str, pd.DataFrame]:
    """Mixed signs/magnitudes, ties and zero volume, without price drift."""
    index = pd.date_range("2024-01-01", periods=160, freq="D", name="date")
    close_cycle = [100, 125, 100, 80, 100, 100, 150, 100]
    volume_cycle = [4, 12, 8, 20, 0, 16, 28]
    return {
        "close": pd.DataFrame(
            {symbol: [close_cycle[(i + offset) % 8] for i in range(160)]
             for symbol, offset in (("AAA", 0), ("BBB", 3))},
            index=index, dtype=float,
        ),
        "volume": pd.DataFrame(
            {symbol: [volume_cycle[(i + offset) % 7] for i in range(160)]
             for symbol, offset in (("AAA", 0), ("BBB", 2))},
            index=index, dtype=float,
        ),
    }


def _scalar_oracle(panel: dict[str, pd.DataFrame], window: int) -> pd.DataFrame:
    """Evaluate exact rational returns, then a scalar sample deviation."""
    close, volume = panel["close"], panel["volume"]
    expected = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for symbol in close.columns:
        for end in range(window, len(close)):
            weights = [
                abs(Fraction(close[symbol].iloc[i]) / Fraction(close[symbol].iloc[i - 1]) - 1)
                * Fraction(volume[symbol].iloc[i])
                for i in range(end - window + 1, end + 1)
            ]
            expected.loc[close.index[end], symbol] = float(stdev(weights) / mean(weights))
    return expected


@pytest.mark.parametrize("compute,window", CASES)
def test_wvma_nonzero_values_and_warmup_match_independent_oracle(compute, window: int) -> None:
    panel = _varied_panel()
    expected = _scalar_oracle(panel, window)
    actual = compute(panel)

    assert actual.iloc[:window].isna().all().all()
    assert np.isfinite(actual.iloc[window:].to_numpy()).all()
    assert (expected.iloc[window:] > 0).all().all()
    # safe_div adds a small epsilon; this is not a second implementation of it.
    pd.testing.assert_frame_equal(actual, expected, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("compute,window", CASES)
@pytest.mark.parametrize("field,extra_bar", [("close", 1), ("volume", 0)])
def test_wvma_gap_masks_exactly_its_reach_and_recovers(
    compute, window: int, field: str, extra_bar: int,
) -> None:
    panel = _varied_panel()
    expected = _scalar_oracle(panel, window)
    gap = 70
    recovery = gap + window + extra_bar
    # A close gap loses two returns; a volume gap loses only its own weight.
    panel[field].loc[panel[field].index[gap], "AAA"] = np.nan
    actual = compute(panel)

    assert np.isfinite(expected.iloc[window:].to_numpy()).all()
    assert actual["AAA"].iloc[gap:recovery].isna().all()
    assert np.isfinite(actual["AAA"].iloc[recovery])
    expected.loc[expected.index[gap:recovery], "AAA"] = np.nan
    # Checks recovery, earlier history, and the unaffected symbol together.
    pd.testing.assert_frame_equal(actual, expected, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("compute,window", CASES)
def test_wvma_zero_volume_keeps_local_zero_denominator_nan_contract(compute, window: int) -> None:
    panel = _varied_panel()
    panel["volume"].loc[:, "AAA"] = 0.0
    actual = compute(panel)
    assert actual["AAA"].isna().all()
    assert np.isfinite(actual["BBB"].iloc[window:]).all()
