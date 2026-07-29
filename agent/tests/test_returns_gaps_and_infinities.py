"""bar_returns must not change behaviour for gapped positive series.

#872 replaced ``close.pct_change().fillna(0.0)`` with :func:`bar_returns` and
claimed results for strictly positive series are bit-identical. That claim was
verified only on gapless series. On the pinned pandas (``>=2.0,<3.0``)
``pct_change`` defaults to ``fill_method='pad'``, so it forward-fills the
divisor; ``bar_returns`` divided by the raw shifted series instead. For any
positive series with an interior NaN -- a halt longer than ``_align``'s
``ffill_limit``, or a thinly-traded symbol -- the two diverged, and the real
move across the gap was silently reported as ``0.0`` with the undefined-bar
counter deliberately not firing (it excludes NaN priors).

Injecting a zero where a large move occurred understates realised volatility
and inflates Sharpe, one-directionally: on a 20-symbol universe with two
halted symbols, annualised vol fell 4.96% -> 4.47% and Sharpe rose 3.05 ->
3.38. Return deltas can cancel by sign; dispersion damage cannot.

These tests are written to be pandas-version-independent, so they pin the
intended behaviour rather than whatever the installed default happens to be.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import bar_returns, buy_and_hold_return


# ---------------------------------------------------------------------------
# Gapped positive series
# ---------------------------------------------------------------------------


def test_gap_does_not_erase_the_move_across_it() -> None:
    """The bar resuming after a gap carries the real move, not 0.0."""
    close = pd.Series([100.0, 110.0, np.nan, np.nan, np.nan, 121.0])

    ret = bar_returns(close, label="halted")

    # 110 -> 121 is a real +10%, earned by anyone holding through the halt.
    assert ret.iloc[5] == pytest.approx(0.10)
    # Bars with no price at all are flat, not NaN.
    assert ret.iloc[2:5].tolist() == [0.0, 0.0, 0.0]


def test_gapped_series_match_explicit_pad_on_every_pandas() -> None:
    """Pins the pre-#872 answer without depending on the pct_change default."""
    close = pd.Series([100.0, 110.0, np.nan, 121.0, np.nan, np.nan, 133.1, 140.0])

    padded = close.ffill()
    expected = (padded / padded.shift(1) - 1).fillna(0.0)

    assert (bar_returns(close).to_numpy() == expected.to_numpy()).all()


def test_gap_does_not_deflate_realised_volatility() -> None:
    """Zero-injection shrinks dispersion; that is the non-cancelling harm."""
    close = pd.Series([100.0, 101.0, 100.5, np.nan, np.nan, np.nan, 130.0, 131.0])

    ret = bar_returns(close)

    zeroed = ret.copy()
    zeroed.iloc[6] = 0.0  # what the unpatched helper produced
    assert ret.std(ddof=1) > zeroed.std(ddof=1)


def test_leading_nan_is_still_flat_not_forward_filled_backwards() -> None:
    """A symbol that starts late has no prior price; ffill cannot invent one."""
    close = pd.Series([np.nan, np.nan, 50.0, 55.0])

    ret = bar_returns(close)

    assert ret.iloc[:3].tolist() == [0.0, 0.0, 0.0]
    assert ret.iloc[3] == pytest.approx(0.10)


def test_gapped_frame_isolates_symbols() -> None:
    frame = pd.DataFrame(
        {"HALTED": [10.0, np.nan, np.nan, 12.0], "NORMAL": [1.0, 2.0, 4.0, 8.0]}
    )

    ret = bar_returns(frame)

    assert ret["HALTED"].tolist() == [0.0, 0.0, 0.0, pytest.approx(0.2)]
    assert ret["NORMAL"].tolist() == [0.0, 1.0, 1.0, 1.0]


# ---------------------------------------------------------------------------
# Non-finite prior prices
# ---------------------------------------------------------------------------


def test_infinite_prior_price_is_undefined_not_minus_one() -> None:
    """``inf > 0`` is True, so finiteness must be asserted explicitly."""
    close = pd.Series([10.0, np.inf, 42.0, 50.0])

    ret = bar_returns(close)

    # 42 / inf - 1 == -1.0 would read as a clean, plausible -100%.
    assert ret.iloc[2] == 0.0
    assert np.isfinite(ret.to_numpy()).all()


def test_infinite_prior_price_is_logged(caplog) -> None:
    """It must be loud, like every other undefined bar."""
    with caplog.at_level(logging.WARNING, logger="backtest.metrics"):
        bar_returns(pd.Series([10.0, np.inf, 42.0]), label="INF")

    assert "INF" in caplog.text
    assert "non-positive or non-finite prior price" in caplog.text


def test_buy_and_hold_rejects_an_infinite_entry_price() -> None:
    """No honest percentage exists, so report nothing rather than -100%."""
    assert buy_and_hold_return(pd.Series([np.inf, 42.0])) is None
    assert buy_and_hold_return(pd.Series([-np.inf, 42.0])) is None
    assert buy_and_hold_return(pd.Series([10.0, np.inf])) is None


# ---------------------------------------------------------------------------
# The #872 contract must survive the patch
# ---------------------------------------------------------------------------


def test_nonpositive_prior_is_still_undefined() -> None:
    """The original fix is untouched: a gap must not resurrect a bad divisor."""
    close = pd.Series([10.0, -0.02, -1.03, 42.0])

    ret = bar_returns(close)

    assert ret.iloc[2] == 0.0
    assert ret.iloc[3] == 0.0
    assert np.isfinite(ret.to_numpy()).all()


def test_gapless_positive_series_unchanged() -> None:
    prices = pd.Series(np.random.default_rng(7).uniform(1.0, 400.0, 200))
    expected = (prices / prices.shift(1) - 1).fillna(0.0)

    assert (bar_returns(prices).to_numpy() == expected.to_numpy()).all()


# ---------------------------------------------------------------------------
# The engine boundary where the gap actually leaks in
# ---------------------------------------------------------------------------


def test_align_keeps_move_across_halt_longer_than_ffill_limit() -> None:
    """A suspension longer than ``_align``'s ffill limit must not erase the move.

    ``_align`` forward-fills close with ``limit=5`` (single market) precisely so
    long halts stay visible as NaN; the returns matrix it hands to the optimizer
    and the benchmark must still credit the across-gap move to the resumed bar.
    """
    from backtest.engines.base import _align

    dates = pd.date_range("2025-01-06", periods=10, freq="B")

    def _frame(closes: pd.Series) -> pd.DataFrame:
        return pd.DataFrame({"close": closes})

    # HALTED prints days 0-1, goes dark for six sessions (> limit 5), resumes
    # day 8 at 121: a real +10% earned by anyone holding through the halt.
    halted = pd.Series([100.0, 110.0, 121.0, 122.0],
                       index=dates[[0, 1, 8, 9]])
    normal = pd.Series(np.linspace(50.0, 59.0, 10), index=dates)

    data_map = {"HALTED": _frame(halted), "NORMAL": _frame(normal)}
    signal_map = {c: pd.Series(1.0, index=df.index) for c, df in data_map.items()}

    _, close, _, ret = _align(data_map, signal_map, ["HALTED", "NORMAL"])

    # Precondition: the halt really does outlive the ffill limit.
    assert np.isnan(close.loc[dates[7], "HALTED"])
    # The resumed bar carries 110 -> 121, not a silent 0.0.
    assert ret.loc[dates[8], "HALTED"] == pytest.approx(121.0 / 110.0 - 1.0)
    # Bars inside the halt stay flat.
    assert ret.loc[dates[7], "HALTED"] == 0.0
