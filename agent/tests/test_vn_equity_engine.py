"""Tests for VNEquityEngine market rules.

Validates:
  - Default config values (commission, sell tax, lot, T+2, price bands)
  - Leverage forced to 1.0
  - Exchange classification (HOSE / HNX / UPCoM)
  - No retail short selling
  - T+2 settlement lock
  - Price band enforcement per exchange
  - 100-share lot rounding
  - Bilateral commission with sell-side tax
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from backtest.engines.vn_equity import (
    VNEquityEngine,
    _classify_vn_exchange,
)
from backtest.models import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(
    close: float = 100.0,
    pre_close: float | None = None,
    pct_chg: float | None = None,
    trade_date: str | pd.Timestamp | None = None,
) -> pd.Series:
    """Build a minimal bar Series for testing."""
    d: dict = {"close": close}
    if pre_close is not None:
        d["pre_close"] = pre_close
    if pct_chg is not None:
        d["pct_chg"] = pct_chg
    if trade_date is not None:
        d["trade_date"] = pd.Timestamp(trade_date)
    return pd.Series(d)


def _make_engine(**overrides) -> VNEquityEngine:
    config = {"initial_cash": 1_000_000_000}
    config.update(overrides)
    return VNEquityEngine(config)


def _make_position(symbol: str, entry_days_ago: int) -> Position:
    """Build a Position whose entry_time is N days before today."""
    entry = pd.Timestamp.now().normalize() - timedelta(days=entry_days_ago)
    return Position(
        symbol=symbol,
        direction=1,
        entry_price=100.0,
        entry_time=entry,
        size=100.0,
    )


# ---------------------------------------------------------------------------
# Group A — Configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_default_config_values(self) -> None:
        engine = _make_engine()
        assert engine.commission_rate == 0.0015
        assert engine.sell_tax_rate == 0.001
        assert engine.lot_size == 100
        assert engine.t_plus == 2
        assert engine.price_band_hose == 0.07
        assert engine.price_band_hnx == 0.10
        assert engine.price_band_upcom == 0.15

    def test_config_overrides(self) -> None:
        engine = _make_engine(
            commission_rate=0.0025,
            sell_tax_rate=0.0005,
            lot_size=10,
            t_plus=3,
            price_band_hose=0.05,
            price_band_hnx=0.08,
            price_band_upcom=0.12,
        )
        assert engine.commission_rate == 0.0025
        assert engine.sell_tax_rate == 0.0005
        assert engine.lot_size == 10
        assert engine.t_plus == 3
        assert engine.price_band_hose == 0.05
        assert engine.price_band_hnx == 0.08
        assert engine.price_band_upcom == 0.12

    def test_no_leverage(self) -> None:
        """VN equity must always be leverage=1, regardless of input."""
        engine = _make_engine(leverage=10.0)
        assert engine.default_leverage == 1.0

        engine2 = _make_engine()  # default
        assert engine2.default_leverage == 1.0


# ---------------------------------------------------------------------------
# Group B — Exchange classification
# ---------------------------------------------------------------------------


class TestExchangeClassification:
    def test_classify_hose_explicit(self) -> None:
        assert _classify_vn_exchange("VNM.HOSE") == "HOSE"

    def test_classify_hnx_explicit(self) -> None:
        assert _classify_vn_exchange("SHB.HNX") == "HNX"

    def test_classify_upcom_explicit(self) -> None:
        assert _classify_vn_exchange("VEA.UPCOM") == "UPCOM"

    def test_classify_case_insensitive(self) -> None:
        assert _classify_vn_exchange("vnm.hose") == "HOSE"

    def test_classify_bare_ticker_default(self) -> None:
        """Bare 3-letter tickers default to HOSE."""
        assert _classify_vn_exchange("VNM") == "HOSE"


# ---------------------------------------------------------------------------
# Group C — Short selling (always blocked)
# ---------------------------------------------------------------------------


class TestNoShortSelling:
    def test_short_blocked(self) -> None:
        engine = _make_engine()
        bar = _make_bar()
        assert engine.can_execute("VNM.HOSE", -1, bar) is False

    def test_short_blocked_regardless_of_bar_data(self) -> None:
        engine = _make_engine()
        # Even a benign bar with no signals should reject shorts
        bar = _make_bar(close=100.0, pre_close=100.0, trade_date="2026-05-10")
        assert engine.can_execute("SHB.HNX", -1, bar) is False


# ---------------------------------------------------------------------------
# Group D — T+2 settlement
# ---------------------------------------------------------------------------


class TestTPlusTwo:
    def test_sell_t0_blocked(self) -> None:
        """Position entered today, attempt sell today → blocked."""
        engine = _make_engine()
        today = pd.Timestamp.now().normalize()
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=today,
            size=100.0,
        )
        bar = _make_bar(trade_date=today)
        assert engine.can_execute("VNM.HOSE", 0, bar) is False

    def test_sell_t1_blocked(self) -> None:
        """Position entered yesterday, attempt sell today → blocked."""
        engine = _make_engine()
        today = pd.Timestamp.now().normalize()
        yesterday = today - timedelta(days=1)
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=yesterday,
            size=100.0,
        )
        bar = _make_bar(trade_date=today)
        assert engine.can_execute("VNM.HOSE", 0, bar) is False

    def test_sell_t2_allowed(self) -> None:
        """Position entered 2 days ago → sellable today."""
        engine = _make_engine()
        today = pd.Timestamp.now().normalize()
        two_days_ago = today - timedelta(days=2)
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=two_days_ago,
            size=100.0,
        )
        # Flat bar (no price band block)
        bar = _make_bar(close=100.0, pre_close=100.0, trade_date=today)
        assert engine.can_execute("VNM.HOSE", 0, bar) is True

    def test_sell_t5_allowed(self) -> None:
        """Position entered 5 days ago → sellable."""
        engine = _make_engine()
        today = pd.Timestamp.now().normalize()
        five_days_ago = today - timedelta(days=5)
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=five_days_ago,
            size=100.0,
        )
        bar = _make_bar(close=100.0, pre_close=100.0, trade_date=today)
        assert engine.can_execute("VNM.HOSE", 0, bar) is True

    def test_buy_no_t_constraint(self) -> None:
        """Buy direction is unaffected by T+2."""
        engine = _make_engine()
        today = pd.Timestamp.now().normalize()
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=today,
            size=100.0,
        )
        bar = _make_bar(close=100.0, pre_close=100.0, trade_date=today)
        assert engine.can_execute("VNM.HOSE", 1, bar) is True


# ---------------------------------------------------------------------------
# Group E — Price band enforcement
# ---------------------------------------------------------------------------


class TestPriceBandHOSE:
    def test_buy_at_band_blocked_hose(self) -> None:
        """+6.95% on HOSE → buy blocked (within ±0.001 of +7% band)."""
        engine = _make_engine()
        bar = _make_bar(close=106.95, pre_close=100.0)
        assert engine.can_execute("VNM.HOSE", 1, bar) is False

    def test_buy_below_band_allowed_hose(self) -> None:
        """+5% on HOSE → buy allowed."""
        engine = _make_engine()
        bar = _make_bar(close=105.0, pre_close=100.0)
        assert engine.can_execute("VNM.HOSE", 1, bar) is True

    def test_sell_at_lower_band_blocked_hose(self) -> None:
        """-6.95% on HOSE → sell blocked (limit-down region)."""
        engine = _make_engine()
        # Configure a sellable position to isolate price-band rule from T+2
        old_entry = pd.Timestamp.now().normalize() - timedelta(days=10)
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=old_entry,
            size=100.0,
        )
        bar = _make_bar(
            close=93.05, pre_close=100.0,
            trade_date=pd.Timestamp.now().normalize(),
        )
        assert engine.can_execute("VNM.HOSE", 0, bar) is False

    def test_sell_above_lower_band_allowed_hose(self) -> None:
        """-5% on HOSE → sell allowed."""
        engine = _make_engine()
        old_entry = pd.Timestamp.now().normalize() - timedelta(days=10)
        engine.positions["VNM.HOSE"] = Position(
            symbol="VNM.HOSE",
            direction=1,
            entry_price=100.0,
            entry_time=old_entry,
            size=100.0,
        )
        bar = _make_bar(
            close=95.0, pre_close=100.0,
            trade_date=pd.Timestamp.now().normalize(),
        )
        assert engine.can_execute("VNM.HOSE", 0, bar) is True


class TestPriceBandHNX:
    def test_buy_at_band_blocked_hnx(self) -> None:
        """+9.95% on HNX → buy blocked."""
        engine = _make_engine()
        bar = _make_bar(close=109.95, pre_close=100.0)
        assert engine.can_execute("SHB.HNX", 1, bar) is False

    def test_buy_at_8pct_allowed_hnx(self) -> None:
        """+8% on HNX → allowed (would be blocked on HOSE's ±7% band)."""
        engine = _make_engine()
        bar = _make_bar(close=108.0, pre_close=100.0)
        assert engine.can_execute("SHB.HNX", 1, bar) is True
        # Sanity: same bar would be blocked on HOSE
        assert engine.can_execute("VNM.HOSE", 1, bar) is False


class TestPriceBandUPCoM:
    def test_buy_at_14pct_allowed_upcom(self) -> None:
        """+14% on UPCoM → allowed."""
        engine = _make_engine()
        bar = _make_bar(close=114.0, pre_close=100.0)
        assert engine.can_execute("VEA.UPCOM", 1, bar) is True

    def test_buy_at_band_blocked_upcom(self) -> None:
        """+14.95% on UPCoM → blocked."""
        engine = _make_engine()
        bar = _make_bar(close=114.95, pre_close=100.0)
        assert engine.can_execute("VEA.UPCOM", 1, bar) is False


# ---------------------------------------------------------------------------
# Group F — Lot rounding
# ---------------------------------------------------------------------------


class TestRoundSize:
    def test_round_500_to_500(self) -> None:
        engine = _make_engine()
        assert engine.round_size(500, 100.0) == 500

    def test_round_550_to_500(self) -> None:
        engine = _make_engine()
        assert engine.round_size(550, 100.0) == 500

    def test_round_99_to_0(self) -> None:
        engine = _make_engine()
        assert engine.round_size(99, 100.0) == 0

    def test_round_negative_to_zero(self) -> None:
        engine = _make_engine()
        assert engine.round_size(-50, 100.0) == 0

    def test_round_with_custom_lot(self) -> None:
        """Custom lot_size flows through."""
        engine = _make_engine(lot_size=10)
        assert engine.round_size(57, 100.0) == 50
        assert engine.round_size(9, 100.0) == 0
        assert engine.round_size(100, 100.0) == 100


# ---------------------------------------------------------------------------
# Group G — Commission and sell-side tax
# ---------------------------------------------------------------------------


class TestCommission:
    def test_buy_no_tax(self) -> None:
        """Buy: only commission, no sell-side tax."""
        engine = _make_engine()
        # 1000 shares × $100 × 0.15% = 150
        comm = engine.calc_commission(1000, 100.0, direction=1, is_open=True)
        assert comm == pytest.approx(150.0)

    def test_sell_with_tax(self) -> None:
        """Sell: commission + 0.1% tax."""
        engine = _make_engine()
        # commission 150 + tax (1000 × 100 × 0.001 = 100) = 250
        comm = engine.calc_commission(1000, 100.0, direction=0, is_open=False)
        assert comm == pytest.approx(250.0)

    def test_custom_commission_rate(self) -> None:
        engine = _make_engine(commission_rate=0.0025)
        # Buy: 1000 × 100 × 0.0025 = 250
        comm = engine.calc_commission(1000, 100.0, direction=1, is_open=True)
        assert comm == pytest.approx(250.0)

    def test_custom_tax_rate(self) -> None:
        engine = _make_engine(sell_tax_rate=0.0005)
        # Sell: commission 150 + tax (1000 × 100 × 0.0005 = 50) = 200
        comm = engine.calc_commission(1000, 100.0, direction=0, is_open=False)
        assert comm == pytest.approx(200.0)
