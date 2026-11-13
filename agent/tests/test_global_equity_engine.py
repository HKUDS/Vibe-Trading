"""Tests for GlobalEquityEngine (US / HK / Canada) market rules.

Validates:
  - US: zero commission, fractional shares, low slippage
  - HK: stamp tax bilateral, 100-share lots, levies
  - Canada: whole shares, configurable broker cost, TSX/TSXV tick grid
  - Same-session trading for all three markets
  - Both directions allowed
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(close: float = 180.0) -> pd.Series:
    return pd.Series({"close": close, "open": close})


def _us_engine(**overrides) -> GlobalEquityEngine:
    config = {"initial_cash": 500_000}
    config.update(overrides)
    return GlobalEquityEngine(config, market="us")


def _hk_engine(**overrides) -> GlobalEquityEngine:
    config = {"initial_cash": 1_000_000}
    config.update(overrides)
    return GlobalEquityEngine(config, market="hk")


def _ca_engine(**overrides) -> GlobalEquityEngine:
    config = {"initial_cash": 500_000}
    config.update(overrides)
    return GlobalEquityEngine(config, market="ca")


# ---------------------------------------------------------------------------
# can_execute: T+0 both directions
# ---------------------------------------------------------------------------


class TestCanExecute:
    def test_us_long(self) -> None:
        assert _us_engine().can_execute("AAPL.US", 1, _make_bar()) is True

    def test_us_short(self) -> None:
        assert _us_engine().can_execute("AAPL.US", -1, _make_bar()) is True

    def test_us_close(self) -> None:
        assert _us_engine().can_execute("AAPL.US", 0, _make_bar()) is True

    def test_hk_long(self) -> None:
        assert _hk_engine().can_execute("0700.HK", 1, _make_bar()) is True

    def test_hk_short(self) -> None:
        assert _hk_engine().can_execute("0700.HK", -1, _make_bar()) is True

    def test_canada_long_and_short(self) -> None:
        engine = _ca_engine()
        assert engine.can_execute("TD.TO", 1, _make_bar()) is True
        assert engine.can_execute("PNG.V", -1, _make_bar()) is True


# ---------------------------------------------------------------------------
# round_size: US fractional vs HK lots
# ---------------------------------------------------------------------------


class TestRoundSize:
    def test_us_fractional(self) -> None:
        engine = _us_engine()
        assert engine.round_size(10.567, 180.0) == 10.57

    def test_us_tiny_fraction(self) -> None:
        engine = _us_engine()
        assert engine.round_size(0.005, 180.0) == 0.01

    def test_us_negative_clamps(self) -> None:
        engine = _us_engine()
        assert engine.round_size(-5.0, 180.0) == 0.0

    def test_hk_100_share_lots(self) -> None:
        engine = _hk_engine()
        assert engine.round_size(350.0, 350.0) == 300
        assert engine.round_size(99.0, 350.0) == 0
        assert engine.round_size(500.0, 350.0) == 500

    def test_hk_rounds_down(self) -> None:
        engine = _hk_engine()
        assert engine.round_size(199.0, 80.0) == 100

    def test_canada_uses_whole_shares_but_keeps_odd_lots(self) -> None:
        engine = _ca_engine()
        assert engine.round_size(19.9, 85.0) == 19.0
        assert engine.round_size(1.1, 85.0) == 1.0
        assert engine.round_size(0.9, 85.0) == 0.0
        assert engine.round_size(-3.0, 85.0) == 0.0


# ---------------------------------------------------------------------------
# calc_commission: US zero vs HK complex
# ---------------------------------------------------------------------------


class TestCommission:
    def test_us_zero_commission(self) -> None:
        engine = _us_engine()
        comm = engine.calc_commission(100.0, 180.0, 1, is_open=True)
        assert comm == 0.0

    def test_us_zero_both_sides(self) -> None:
        engine = _us_engine()
        assert engine.calc_commission(100.0, 180.0, 1, is_open=True) == 0.0
        assert engine.calc_commission(100.0, 180.0, 1, is_open=False) == 0.0

    def test_hk_has_commission(self) -> None:
        engine = _hk_engine()
        comm = engine.calc_commission(1000, 350.0, 1, is_open=True)
        assert comm > 0

    def test_hk_stamp_tax_bilateral(self) -> None:
        """HK stamp tax charged on both buy and sell."""
        engine = _hk_engine()
        comm_buy = engine.calc_commission(1000, 350.0, 1, is_open=True)
        comm_sell = engine.calc_commission(1000, 350.0, 1, is_open=False)
        # Both should be approximately equal (stamp tax bilateral)
        assert comm_buy == pytest.approx(comm_sell, rel=0.01)

    def test_hk_commission_components(self) -> None:
        """Verify HK commission includes all components."""
        engine = _hk_engine()
        size, price = 1000, 350.0
        notional = size * price  # 350,000
        comm = engine.calc_commission(size, price, 1, is_open=True)
        # Expected components:
        expected = (
            notional * engine.hk_commission      # broker ~¥52.5
            + notional * engine.hk_stamp_tax     # stamp ~¥350
            + notional * engine.hk_levy          # SFC+FRC ~¥19.8
            + notional * engine.hk_settlement    # CCASS ~¥7
        )
        assert comm == pytest.approx(expected, abs=0.01)

    def test_canada_commission_is_broker_configured(self) -> None:
        engine = _ca_engine(ca_commission=0.001)
        assert engine.calc_commission(100, 25.0, 1, is_open=True) == 2.5
        assert engine.calc_commission(100, 25.0, 1, is_open=False) == 2.5


# ---------------------------------------------------------------------------
# apply_slippage: US low vs HK moderate
# ---------------------------------------------------------------------------


class TestSlippage:
    def test_us_lower_slippage(self) -> None:
        engine = _us_engine()
        us_slipped = engine.apply_slippage(100.0, 1) - 100.0
        hk_engine = _hk_engine()
        hk_slipped = hk_engine.apply_slippage(100.0, 1) - 100.0
        assert us_slipped < hk_slipped

    def test_us_slippage_rate(self) -> None:
        engine = _us_engine()
        assert engine.apply_slippage(100.0, 1) == pytest.approx(100.05)

    def test_hk_slippage_rate(self) -> None:
        engine = _hk_engine()
        assert engine.apply_slippage(100.0, 1) == pytest.approx(100.1)

    def test_custom_slippage(self) -> None:
        engine = GlobalEquityEngine(
            {"initial_cash": 500_000, "slippage_us": 0.002}, market="us",
        )
        assert engine.apply_slippage(100.0, 1) == pytest.approx(100.2)

    @pytest.mark.parametrize(
        ("price", "direction", "expected"),
        [
            (10.001, 1, 10.01),
            (10.009, -1, 10.00),
            (0.421, 1, 0.425),
            (0.424, -1, 0.420),
        ],
    )
    def test_canada_rounds_against_trader_on_official_tick_grid(
        self, price: float, direction: int, expected: float,
    ) -> None:
        engine = _ca_engine(slippage_ca=0.0)
        assert engine.apply_slippage(price, direction) == expected

    def test_canada_slippage_is_configurable(self) -> None:
        engine = _ca_engine(slippage_ca=0.001)
        assert engine.apply_slippage(100.0, 1) == 100.1


# ---------------------------------------------------------------------------
# Market parameter
# ---------------------------------------------------------------------------


class TestMarketParam:
    def test_default_is_us(self) -> None:
        engine = GlobalEquityEngine({"initial_cash": 100_000})
        assert engine.market == "us"

    def test_hk_market(self) -> None:
        engine = GlobalEquityEngine({"initial_cash": 100_000}, market="hk")
        assert engine.market == "hk"

    def test_canada_market(self) -> None:
        engine = GlobalEquityEngine({"initial_cash": 100_000}, market="ca")
        assert engine.market == "ca"


def test_us_ignored_commission_is_refused_and_explicit_slippage_changes_fills():
    import pytest
    with pytest.raises(ValueError, match='slippage_us'):
        _us_engine(codes=['SPY.US'], commission=0.0005)
    engine = _us_engine(codes=['SPY.US'], slippage_us=0.0013)
    assert engine._execution_price(100, 1) == pytest.approx(100.13)
    assert engine._execution_price(100, -1) == pytest.approx(99.87)
    costs = engine._engine_diagnostics()['execution_costs']
    assert costs['slippage_buy_rate'] == pytest.approx(.0013)
    assert costs['slippage_sell_rate'] == pytest.approx(.0013)
    assert costs['commission_rate'] == 0
    # A composite portfolio may apply the generic commission to crypto.
    _us_engine(codes=['SPY.US', 'BTC-USDT'], commission=.001)
