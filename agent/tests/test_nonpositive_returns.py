"""Sign-safe returns: the buy-and-hold path must not assume positive prices.

Issue #872. ``close.pct_change()`` assumes ``price[t-1] > 0``. As the divisor
approaches zero an ordinary absolute move reads as an enormous percentage move,
so the compounded benchmark explodes (+39,560% on a real power-price run); at
exactly zero the next bar is ``inf``, which ``fillna(0.0)`` does not neutralise
and which collapses ``(1 + r).prod()`` to ``nan``.

Contract pinned here:

1. A return is defined only when the previous price is finite and strictly
   positive; otherwise it is ``0.0``, never ``inf``/``nan``.
2. Buy-and-hold total return is the price relative ``P_end / P_start - 1``,
   which is bit-identical to the old compounded product while prices are
   positive, and is ``None`` when the entry price is not positive.
3. Undefined bars are logged, not silently swallowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.metrics import bar_returns, buy_and_hold_return

FIXTURE = Path(__file__).parent / "fixtures" / "negative_close_bars.csv"


@pytest.fixture()
def delu() -> pd.Series:
    """The four DE-LU non-positive closes from the #816 fixture."""
    df = pd.read_csv(FIXTURE, comment="#")
    return (
        df[df.code == "POWER-DA-DELU"]
        .sort_values("trade_date")
        .set_index("trade_date")["close"]
    )


# ---------------------------------------------------------------------------
# No behaviour change for ordinary, strictly positive series
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [2, 5, 50, 500])
def test_positive_series_are_bit_identical_to_pct_change(n: int) -> None:
    """Equities and crypto must be untouched — not close, identical."""
    prices = pd.Series(np.random.default_rng(7).uniform(1.0, 400.0, n))

    assert (
        bar_returns(prices).to_numpy() == prices.pct_change().fillna(0.0).to_numpy()
    ).all()


def test_positive_frames_are_bit_identical_to_pct_change() -> None:
    prices = pd.DataFrame(
        np.random.default_rng(11).uniform(1.0, 400.0, (200, 4)), columns=list("ABCD")
    )

    assert (
        bar_returns(prices).to_numpy() == prices.pct_change().fillna(0.0).to_numpy()
    ).all()


def test_buy_and_hold_equals_the_compounded_product_when_prices_are_positive() -> None:
    """The price relative is what the old product telescoped to all along."""
    prices = pd.Series(np.random.default_rng(3).uniform(1.0, 400.0, 300))

    compounded = float((1 + prices.pct_change().fillna(0.0)).prod() - 1)

    assert buy_and_hold_return(prices) == pytest.approx(compounded)


# ---------------------------------------------------------------------------
# Symptom A — a near-zero divisor exploded the percentage return
# ---------------------------------------------------------------------------


def test_near_zero_prior_close_no_longer_explodes(delu: pd.Series) -> None:
    """-0.02 -> -1.03 read as +5050% purely because the divisor was near zero."""
    assert delu.pct_change().fillna(0.0).loc["2025-10-04"] == pytest.approx(50.5)

    assert bar_returns(delu).loc["2025-10-04"] == 0.0


def test_compounded_aggregate_no_longer_explodes(delu: pd.Series) -> None:
    pre_zero = delu.iloc[:-1]
    assert float((1 + pre_zero.pct_change().fillna(0.0)).prod() - 1) == pytest.approx(
        10.444, rel=1e-3
    )

    assert (bar_returns(pre_zero) == 0.0).all()


# ---------------------------------------------------------------------------
# Symptom B — an exact-zero close produced inf, then nan
# ---------------------------------------------------------------------------


def test_bar_after_an_exact_zero_is_finite(delu: pd.Series) -> None:
    series = pd.concat([delu, pd.Series({"2025-10-27": 42.0})])

    assert np.isinf(series.pct_change().fillna(0.0).iloc[-1])

    result = bar_returns(series)
    assert result.iloc[-1] == 0.0
    assert np.isfinite(result.to_numpy()).all()


def test_compounded_aggregate_stays_finite_through_zero(delu: pd.Series) -> None:
    series = pd.concat([delu, pd.Series({"2025-10-27": 42.0})])
    with np.errstate(invalid="ignore"):
        assert not np.isfinite(float((1 + series.pct_change().fillna(0.0)).prod()))

    assert np.isfinite(float((1 + bar_returns(series)).prod()))


def test_zero_prices_do_not_leak_through_a_frame() -> None:
    """The engine's per-symbol matrix feeds optimizers and correlation math."""
    frame = pd.DataFrame({"A": [10.0, 0.0, 42.0], "B": [1.0, 2.0, 4.0]})

    result = bar_returns(frame)

    assert np.isfinite(result.to_numpy()).all()
    assert result["A"].tolist() == [0.0, -1.0, 0.0]
    # An unaffected symbol keeps its ordinary returns.
    assert result["B"].tolist() == [0.0, 1.0, 1.0]


# ---------------------------------------------------------------------------
# buy_and_hold_return contract
# ---------------------------------------------------------------------------


def test_buy_and_hold_is_none_without_a_positive_entry_price(delu: pd.Series) -> None:
    """No honest percentage exists, so report nothing rather than a number."""
    assert buy_and_hold_return(delu) is None


def test_buy_and_hold_is_none_for_a_series_too_short_to_move() -> None:
    assert buy_and_hold_return(pd.Series([42.0])) is None


def test_buy_and_hold_survives_a_negative_bar_mid_series() -> None:
    """Entry and exit are positive, so the held position has a real return."""
    prices = pd.Series([100.0, -5.0, 0.0, 80.0])

    assert buy_and_hold_return(prices) == pytest.approx(-0.2)


# ---------------------------------------------------------------------------
# Undefined bars must be loud
# ---------------------------------------------------------------------------


def test_undefined_bars_are_logged(delu: pd.Series, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="backtest.metrics"):
        bar_returns(delu, label="DE-LU")

    assert "DE-LU" in caplog.text
    assert "3 bar(s) follow a non-positive or non-finite prior price" in caplog.text


def test_clean_series_log_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="backtest.metrics"):
        bar_returns(pd.Series([1.0, 2.0, 3.0]), label="SPY")

    assert caplog.text == ""
