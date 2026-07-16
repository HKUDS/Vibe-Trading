"""Tests for IndiaEquityEngine (NSE / BSE delivery) market rules.

Validates:
  - No short selling by default; allow_short opt-in
  - T+1: can't sell shares bought the same bar
  - Configurable circuit band blocks buys at upper / sells at lower limit
  - 1-share lots
  - India delivery cost stack (STT bilateral, stamp duty buy-only, GST, DP)
  - Engine routing (runner single-market + composite cross-market)
  - _calc_pct_change handles both Tushare (percentage points) and Yahoo (decimal) formats
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backtest.engines.india_equity import IndiaEquityEngine, _calc_pct_change
from backtest.models import Position


def _engine(**overrides) -> IndiaEquityEngine:
    config = {"initial_cash": 1_000_000}
    config.update(overrides)
    return IndiaEquityEngine(config)


def _bar(close: float = 100.0, pre_close: float | None = None) -> pd.Series:
    data = {"close": close, "open": close}
    if pre_close is not None:
        data["pre_close"] = pre_close
    return pd.Series(data)


# ---------------------------------------------------------------------------
# can_execute: shorting, T+1, circuit bands
# ---------------------------------------------------------------------------


class TestCanExecute:
    def test_long_allowed(self) -> None:
        assert _engine().can_execute("RELIANCE.NS", 1, _bar()) is True

    def test_short_blocked_by_default(self) -> None:
        assert _engine().can_execute("RELIANCE.NS", -1, _bar()) is False

    def test_short_allowed_when_opted_in(self) -> None:
        assert _engine(allow_short=True).can_execute("RELIANCE.NS", -1, _bar()) is True

    def test_t1_blocks_same_bar_sell(self) -> None:
        engine = _engine()
        ts = pd.Timestamp("2024-04-01")
        engine.positions["RELIANCE.NS"] = Position(
            symbol="RELIANCE.NS", direction=1, size=10, entry_price=100.0, entry_time=ts,
        )
        bar = _bar()
        bar.name = ts  # same date as entry -> T+1 blocks the sell
        assert engine.can_execute("RELIANCE.NS", 0, bar) is False

    def test_t1_allows_next_bar_sell(self) -> None:
        engine = _engine()
        engine.positions["RELIANCE.NS"] = Position(
            symbol="RELIANCE.NS", direction=1, size=10, entry_price=100.0,
            entry_time=pd.Timestamp("2024-04-01"),
        )
        bar = _bar()
        bar.name = pd.Timestamp("2024-04-02")  # later date -> allowed
        assert engine.can_execute("RELIANCE.NS", 0, bar) is True

    def test_upper_circuit_blocks_buy(self) -> None:
        engine = _engine(price_limit=0.20)
        bar = _bar(close=120.0, pre_close=100.0)  # +20% -> upper band
        assert engine.can_execute("RELIANCE.NS", 1, bar) is False

    def test_lower_circuit_blocks_sell(self) -> None:
        engine = _engine(price_limit=0.20)
        engine.positions["RELIANCE.NS"] = Position(
            symbol="RELIANCE.NS", direction=1, size=10, entry_price=100.0,
            entry_time=pd.Timestamp("2024-04-01"),
        )
        bar = _bar(close=80.0, pre_close=100.0)  # -20% -> lower band
        bar.name = pd.Timestamp("2024-04-02")
        assert engine.can_execute("RELIANCE.NS", 0, bar) is False

    def test_circuit_disabled_allows_trade_at_limit(self) -> None:
        engine = _engine(price_limit=0)
        bar = _bar(close=120.0, pre_close=100.0)
        assert engine.can_execute("RELIANCE.NS", 1, bar) is True


# ---------------------------------------------------------------------------
# round_size: 1-share lots
# ---------------------------------------------------------------------------


class TestRoundSize:
    def test_one_share_lots(self) -> None:
        engine = _engine()
        assert engine.round_size(10.9, 100.0) == 10.0
        assert engine.round_size(0.4, 100.0) == 0.0
        assert engine.round_size(-3.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# calc_commission: India delivery stack
# ---------------------------------------------------------------------------


class TestCommission:
    def test_nonzero_cost(self) -> None:
        assert _engine().calc_commission(100, 1000.0, 1, is_open=True) > 0

    def test_buy_costs_more_than_sell_due_to_stamp_duty(self) -> None:
        engine = _engine(in_dp_charge=0.0)
        comm_buy = engine.calc_commission(100, 1000.0, 1, is_open=True)
        comm_sell = engine.calc_commission(100, 1000.0, 1, is_open=False)
        notional = 100 * 1000.0
        assert comm_buy - comm_sell == pytest.approx(notional * engine.in_stamp_duty, abs=1e-6)

    def test_sell_components_exact(self) -> None:
        engine = _engine()
        size, price = 100, 1000.0
        notional = size * price
        comm = engine.calc_commission(size, price, 1, is_open=False)  # sell
        brokerage = notional * engine.in_brokerage
        exchange_txn = notional * engine.in_exchange_txn
        sebi_fee = notional * engine.in_sebi_fee
        gst = (brokerage + exchange_txn + sebi_fee) * engine.in_gst
        stt = notional * engine.in_stt
        expected = brokerage + exchange_txn + sebi_fee + gst + stt + engine.in_dp_charge
        assert comm == pytest.approx(expected, abs=1e-6)

    def test_dp_charge_applied_on_sell_only(self) -> None:
        engine = _engine(in_dp_charge=13.5)
        buy = engine.calc_commission(100, 1000.0, 1, is_open=True)
        sell = engine.calc_commission(100, 1000.0, 1, is_open=False)
        # Sell carries the flat DP charge; buy carries stamp duty instead.
        assert sell >= 13.5
        assert buy == pytest.approx(
            sell - 13.5 + 100 * 1000.0 * engine.in_stamp_duty, abs=1e-6
        )


# ---------------------------------------------------------------------------
# apply_slippage + leverage
# ---------------------------------------------------------------------------


class TestSlippageAndLeverage:
    def test_slippage_default(self) -> None:
        assert _engine().apply_slippage(100.0, 1) == pytest.approx(100.1)

    def test_no_leverage(self) -> None:
        # Cash delivery is forced to 1.0 leverage regardless of config input.
        assert _engine(leverage=5.0).default_leverage == 1.0


# ---------------------------------------------------------------------------
# Engine routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_single_market_india_routes_to_india_engine(self) -> None:
        from backtest.runner import _create_market_engine

        engine = _create_market_engine("yahoo", {"initial_cash": 100_000}, ["RELIANCE.NS"])
        assert isinstance(engine, IndiaEquityEngine)

    def test_cross_market_with_india_builds_india_subengine(self) -> None:
        from backtest.engines.composite import _build_rule_engines

        engines = _build_rule_engines(
            {"initial_cash": 100_000}, ["RELIANCE.NS", "AAPL.US"]
        )
        assert isinstance(engines["india_equity"], IndiaEquityEngine)


# ---------------------------------------------------------------------------
# _calc_pct_change: close/pre_close priority + pct_chg heuristic
# ---------------------------------------------------------------------------


class TestCalcPctChange:
    def test_close_pre_close_priority(self) -> None:
        """close/pre_close takes priority over pct_chg when both are present."""
        bar = pd.Series({"close": 110.0, "pre_close": 100.0, "pct_chg": 5.0})
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(0.10, abs=1e-6)  # (110-100)/100 = 0.10

    def test_tushare_pct_chg_format(self) -> None:
        """Tushare pct_chg in percentage points (e.g. 5.0 = 5%)."""
        bar = pd.Series({"pct_chg": 5.0})
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(0.05, abs=1e-6)  # 5.0 / 100 = 0.05

    def test_yahoo_pct_chg_decimal_format(self) -> None:
        """Yahoo/yfinance pct_chg in decimal fraction (e.g. 0.05 = 5%)."""
        bar = pd.Series({"pct_chg": 0.05})
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(0.05, abs=1e-6)  # Already decimal, keep as-is

    def test_large_pct_chg_assumed_percentage_points(self) -> None:
        """Values > 1.0 are treated as percentage points."""
        bar = pd.Series({"pct_chg": 10.0})  # 10% move
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(0.10, abs=1e-6)  # 10.0 / 100 = 0.10

    def test_small_pct_chg_assumed_decimal(self) -> None:
        """Values <= 1.0 are treated as decimal fractions."""
        bar = pd.Series({"pct_chg": 0.5})  # 50% move
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(0.5, abs=1e-6)  # Already decimal

    def test_negative_pct_chg_tushare(self) -> None:
        """Negative Tushare pct_chg in percentage points."""
        bar = pd.Series({"pct_chg": -5.0})  # -5% move
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(-0.05, abs=1e-6)  # -5.0 / 100 = -0.05

    def test_negative_pct_chg_yahoo(self) -> None:
        """Negative Yahoo pct_chg in decimal fraction."""
        bar = pd.Series({"pct_chg": -0.05})  # -5% move
        result = _calc_pct_change(bar)
        assert result is not None
        assert result == pytest.approx(-0.05, abs=1e-6)  # Already decimal

    def test_no_pct_data_returns_none(self) -> None:
        """Returns None when no price or pct_chg data is available."""
        bar = pd.Series({"volume": 1000})
        result = _calc_pct_change(bar)
        assert result is None

    def test_nan_pct_chg_returns_none(self) -> None:
        """Returns None when pct_chg is NaN."""
        bar = pd.Series({"pct_chg": float("nan")})
        result = _calc_pct_change(bar)
        assert result is None

    def test_pre_close_zero_returns_none(self) -> None:
        """Returns None when pre_close is zero (avoids division by zero)."""
        bar = pd.Series({"close": 100.0, "pre_close": 0.0})
        result = _calc_pct_change(bar)
        assert result is None


# ---------------------------------------------------------------------------
# Circuit band with different pct_chg formats
# ---------------------------------------------------------------------------


class TestCircuitBandPctFormats:
    def test_circuit_band_with_tushare_pct_chg(self) -> None:
        """Circuit band works correctly with Tushare percentage point format."""
        engine = _engine(price_limit=0.20)
        # Tushare format: 20.0 = 20%
        bar = pd.Series({"close": 120.0, "pre_close": 100.0, "pct_chg": 20.0})
        assert engine.can_execute("RELIANCE.NS", 1, bar) is False  # Upper circuit

    def test_circuit_band_with_yahoo_pct_chg(self) -> None:
        """Circuit band works correctly with Yahoo decimal format."""
        engine = _engine(price_limit=0.20)
        # Yahoo format: 0.20 = 20%
        bar = pd.Series({"close": 120.0, "pre_close": 100.0, "pct_chg": 0.20})
        assert engine.can_execute("RELIANCE.NS", 1, bar) is False  # Upper circuit

    def test_circuit_band_with_close_pre_close(self) -> None:
        """Circuit band uses close/pre_close when available (most accurate)."""
        engine = _engine(price_limit=0.20)
        # close/pre_close = 120/100 = 20%
        bar = pd.Series({"close": 120.0, "pre_close": 100.0, "pct_chg": 5.0})  # pct_chg is wrong
        assert engine.can_execute("RELIANCE.NS", 1, bar) is False  # Uses close/pre_close
