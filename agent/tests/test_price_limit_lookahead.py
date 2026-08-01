"""Price-limit bands must be judged at execution time, not from the bar's close.

``BaseEngine`` calls ``can_execute`` before filling at the CURRENT bar's open,
so a limit check derived from that bar's close is lookahead. It was wrong in
both directions: a name that opened locked but drifted back by the close was
allowed to trade at the locked open (an optimistic fill that could not have
happened), and a name that opened freely but closed at the limit was refused a
fill it would have got.

Every engine with a daily band is covered here: A-share, India equity, China
futures and global futures.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.china_a import ChinaAEngine
from backtest.engines.china_futures import ChinaFuturesEngine
from backtest.engines.global_futures import GlobalFuturesEngine
from backtest.engines.india_equity import IndiaEquityEngine
from backtest.models import Position

_BASE = 100.0


def _equity_cases():
    """(engine, symbol, band) for the two cash-equity engines."""
    return [
        (ChinaAEngine({}), "000001.SZ", 0.10),
        (IndiaEquityEngine({}), "RELIANCE.NS", 0.20),
    ]


def _futures_cases():
    """(engine, symbol, band) for the two futures engines."""
    return [
        (ChinaFuturesEngine({}), "IF2406.CFFEX", 0.10),
        (GlobalFuturesEngine({}), "ESZ4", 0.07),
    ]


def _bar(open_: float, close: float, base_field: str = "pre_close") -> pd.Series:
    return pd.Series({"open": open_, "high": max(open_, close), "low": min(open_, close),
                      "close": close, base_field: _BASE})


# --------------------------------------------------------------------------- #
# The optimistic failure: opened locked, drifted back by the close
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("engine, symbol, band", _equity_cases())
def test_equity_open_locked_at_upper_band_refuses_the_buy(engine, symbol, band) -> None:
    """Opening AT the upper band means no buy, whatever the close later did."""
    bar = _bar(open_=_BASE * (1 + band), close=_BASE * 1.01)
    assert engine.can_execute(symbol, 1, bar) is False


@pytest.mark.parametrize("engine, symbol, band", _futures_cases())
def test_futures_open_locked_at_upper_band_refuses_the_long(engine, symbol, band) -> None:
    bar = _bar(open_=_BASE * (1 + band), close=_BASE * 1.01, base_field="pre_settle")
    assert engine.can_execute(symbol, 1, bar) is False


# --------------------------------------------------------------------------- #
# The pessimistic failure: opened freely, closed at the band
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("engine, symbol, band", _equity_cases())
def test_equity_open_inside_band_allows_the_buy_even_if_close_locks(engine, symbol, band) -> None:
    """A close at the limit says nothing about whether the open was tradeable."""
    bar = _bar(open_=_BASE * 1.005, close=_BASE * (1 + band))
    assert engine.can_execute(symbol, 1, bar) is True


@pytest.mark.parametrize("engine, symbol, band", _futures_cases())
def test_futures_open_inside_band_allows_the_long_even_if_close_locks(engine, symbol, band) -> None:
    bar = _bar(open_=_BASE * 1.005, close=_BASE * (1 + band), base_field="pre_settle")
    assert engine.can_execute(symbol, 1, bar) is True


# --------------------------------------------------------------------------- #
# Lower band, and futures close-side direction handling
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("engine, symbol, band", _equity_cases())
def test_equity_open_locked_at_lower_band_refuses_the_sell(engine, symbol, band) -> None:
    bar = _bar(open_=_BASE * (1 - band), close=_BASE * 0.99)
    assert engine.can_execute(symbol, 0, bar) is False


def test_futures_closing_a_long_is_blocked_at_the_lower_band() -> None:
    """Closing a long is a sell, so the LOWER band blocks it."""
    engine = ChinaFuturesEngine({})
    engine.positions["IF2406.CFFEX"] = Position(
        "IF2406.CFFEX", 1, _BASE, pd.Timestamp("2025-06-09"), 1.0,
    )
    bar = _bar(open_=_BASE * 0.90, close=_BASE * 0.99, base_field="pre_settle")
    assert engine.can_execute("IF2406.CFFEX", 0, bar) is False


def test_futures_closing_a_short_is_blocked_at_the_upper_band() -> None:
    """Closing a short is a buy, so the UPPER band blocks it."""
    engine = ChinaFuturesEngine({})
    engine.positions["IF2406.CFFEX"] = Position(
        "IF2406.CFFEX", -1, _BASE, pd.Timestamp("2025-06-09"), 1.0,
    )
    bar = _bar(open_=_BASE * 1.10, close=_BASE * 1.01, base_field="pre_settle")
    assert engine.can_execute("IF2406.CFFEX", 0, bar) is False


# --------------------------------------------------------------------------- #
# Base-price resolution
# --------------------------------------------------------------------------- #


def test_no_reachable_base_price_never_fabricates_a_block() -> None:
    """First bar of a run, or a composite sub-engine: allow rather than invent."""
    engine = ChinaAEngine({})
    bar = pd.Series({"open": 200.0, "close": 100.0})  # no pre_close, no panel
    assert engine.can_execute("000001.SZ", 1, bar) is True


def test_prior_close_panel_supplies_the_base_price() -> None:
    """With no pre_close on the bar, the run's own close panel is used."""
    engine = ChinaAEngine({})
    engine._close_arr = pd.DataFrame({"a": [_BASE, 0.0]}).values
    engine._code_to_col = {"000001.SZ": 0}
    engine._bar_idx = 1
    bar = pd.Series({"open": _BASE * 1.10, "close": _BASE * 1.01})
    assert engine.can_execute("000001.SZ", 1, bar) is False


def test_tushare_pct_chg_reconstructs_the_prior_close() -> None:
    """pct_chg + close yields the PREVIOUS close, which is historical."""
    engine = ChinaAEngine({})
    # close 15.0 with pct_chg +10pp implies a prior close of 13.636..., so the
    # upper band is exactly 15.0 and an open there is locked.
    bar = pd.Series({"open": 15.0, "close": 15.0, "pct_chg": 10.0})
    assert engine.can_execute("000001.SZ", 1, bar) is False


def test_futures_prefer_pre_settle_over_pre_close() -> None:
    """Exchanges set futures bands off the previous settlement."""
    engine = ChinaFuturesEngine({})
    # pre_settle 100 puts the +10% band at 110; pre_close 120 would put it at
    # 132 and would wrongly allow this open.
    bar = pd.Series({"open": 110.0, "close": 101.0, "pre_settle": 100.0, "pre_close": 120.0})
    assert engine.can_execute("IF2406.CFFEX", 1, bar) is False


# --------------------------------------------------------------------------- #
# The booked price, not the raw open, must be the one tested
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("engine, symbol, band", _equity_cases())
def test_close_is_judged_on_the_price_actually_booked(engine, symbol, band) -> None:
    """A close is booked with the opposite of the position direction.

    Testing the raw open would approve a fill whose booked sell price, after
    slippage, lands outside the band.
    """
    engine.positions[symbol] = Position(symbol, 1, _BASE, pd.Timestamp("2025-06-09"), 100.0)
    lower = _BASE * (1 - band)
    just_inside = lower * 1.0005          # inside the band before slippage...
    booked = engine.apply_slippage(just_inside, -1)   # ...outside it after
    assert booked < lower, "fixture no longer exercises the slippage gap"
    bar = _bar(open_=just_inside, close=_BASE * 0.99)
    bar["trade_date"] = pd.Timestamp("2025-06-10")
    assert engine.can_execute(symbol, 0, bar) is False


def test_closing_a_short_is_judged_as_a_buy_after_slippage() -> None:
    """Covering a short is booked as a buy, so slippage pushes it UP."""
    engine = ChinaFuturesEngine({})
    engine.positions["IF2406.CFFEX"] = Position(
        "IF2406.CFFEX", -1, _BASE, pd.Timestamp("2025-06-09"), 1.0,
    )
    upper = _BASE * 1.10
    just_inside = upper * 0.9999
    booked = engine.apply_slippage(just_inside, 1)
    assert booked > upper, "fixture no longer exercises the slippage gap"
    bar = _bar(open_=just_inside, close=_BASE * 1.01, base_field="pre_settle")
    assert engine.can_execute("IF2406.CFFEX", 0, bar) is False
