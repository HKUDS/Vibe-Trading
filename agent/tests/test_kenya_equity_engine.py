"""Tests for the Kenya (Nairobi Securities Exchange) equity engine."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines._market_hooks import _detect_market, code_currency
from backtest.engines.kenya_equity import (
    NSE_LOT_SIZE,
    KenyaEquityEngine,
    nse_price_limits,
    nse_round_down,
    nse_round_up,
    nse_tick_size,
)
from backtest.models import Position

CODE = "SCOM.NR"


def _engine(**overrides) -> KenyaEquityEngine:
    config = {"initial_capital": 10_000_000.0, **overrides}
    return KenyaEquityEngine(config)


def _on_grid(price: float) -> bool:
    tick = nse_tick_size(price)
    return abs(round(price / tick) * tick - price) < 1e-9


class TestMarketDetection:
    @pytest.mark.parametrize(
        "code", ["SCOM.NR", "scom.nr", "KPLC-P4.NR", "KE0000000281.NR"]
    )
    def test_nr_symbols_route_to_kenya(self, code: str) -> None:
        assert _detect_market(code) == "kenya_equity"

    def test_india_nse_suffix_is_not_claimed(self) -> None:
        # ``.NR`` (Nairobi) and ``.NS`` (India's NSE) are distinct suffixes.
        assert _detect_market("RELIANCE.NS") == "india_equity"

    def test_currency_is_kes(self) -> None:
        assert code_currency(CODE) == "KES"


class TestTickGrid:
    @pytest.mark.parametrize(
        "price,tick",
        [
            (1.10, 0.01), (4.99, 0.01),
            (5.00, 0.02), (9.98, 0.02),
            (10.00, 0.05), (36.60, 0.05), (49.95, 0.05),
            (50.00, 0.25), (285.25, 0.25), (499.75, 0.25),
            (500.00, 1.00), (999.00, 1.00),
            (1_000.00, 5.00), (1_355.00, 5.00),
        ],
    )
    def test_rule_5_9_spread_table(self, price: float, tick: float) -> None:
        assert nse_tick_size(price) == tick

    def test_round_down_and_up(self) -> None:
        assert nse_round_down(36.62) == pytest.approx(36.60)
        assert nse_round_up(36.62) == pytest.approx(36.65)
        assert nse_round_down(285.40) == pytest.approx(285.25)
        assert nse_round_up(285.40) == pytest.approx(285.50)

    @pytest.mark.parametrize("price", [0.37, 7.44, 36.60, 285.25, 560.0, 1_355.0])
    def test_on_grid_price_is_unchanged(self, price: float) -> None:
        assert nse_round_down(price) == pytest.approx(price)
        assert nse_round_up(price) == pytest.approx(price)

    def test_float_noise_does_not_move_a_grid_price(self) -> None:
        # 0.1 + 0.2 style binary error must not push 36.60 off its own tick.
        assert nse_round_down(36.6 + 1e-12) == pytest.approx(36.60)
        assert nse_round_up(36.6 - 1e-12) == pytest.approx(36.60)


class TestPriceBand:
    def test_band_is_ten_percent_on_grid(self) -> None:
        upper, lower = nse_price_limits(36.60, 0.10)
        # 36.60 * 1.10 = 40.26 -> 40.25 ; 36.60 * 0.90 = 32.94 -> 32.95
        assert upper == pytest.approx(40.25)
        assert lower == pytest.approx(32.95)
        assert _on_grid(upper) and _on_grid(lower)

    def test_bounds_stay_inside_the_band(self) -> None:
        for base in (0.45, 7.30, 36.60, 118.00, 560.00, 1_355.00):
            upper, lower = nse_price_limits(base, 0.10)
            assert upper <= base * 1.10 + 1e-9
            assert lower >= base * 0.90 - 1e-9

    def test_buy_blocked_at_the_ceiling(self) -> None:
        engine = _engine(slippage=0.0)
        bar = pd.Series({"open": 40.25, "pre_close": 36.60})
        assert engine.can_execute(CODE, 1, bar) is False

    def test_buy_allowed_inside_band(self) -> None:
        engine = _engine(slippage=0.0)
        bar = pd.Series({"open": 37.00, "pre_close": 36.60})
        assert engine.can_execute(CODE, 1, bar) is True

    def test_band_reference_falls_back_to_the_close_panel(self) -> None:
        engine = _engine(slippage=0.0)
        engine._close_arr = pd.DataFrame({CODE: [36.60, 36.60]}).to_numpy()
        engine._code_to_col = {CODE: 0}
        engine._bar_idx = 1
        assert engine.can_execute(CODE, 1, pd.Series({"open": 40.25})) is False
        assert engine.can_execute(CODE, 1, pd.Series({"open": 38.00})) is True

    def test_band_can_be_disabled(self) -> None:
        engine = _engine(slippage=0.0, price_limit=0)
        bar = pd.Series({"open": 45.00, "pre_close": 36.60})
        assert engine.can_execute(CODE, 1, bar) is True

    def test_band_check_inactive_without_reference(self) -> None:
        engine = _engine()
        assert engine.can_execute(CODE, 1, pd.Series({"open": 45.00})) is True


class TestLongOnly:
    def test_allow_short_is_refused(self) -> None:
        with pytest.raises(ValueError, match="long-only"):
            _engine(allow_short=True)

    def test_short_direction_blocked(self) -> None:
        engine = _engine(price_limit=0)
        assert engine.can_execute(CODE, -1, pd.Series({"open": 36.60})) is False

    def test_leverage_is_pinned_to_one(self) -> None:
        engine = _engine(leverage=3.0)
        assert engine.default_leverage == 1.0


class TestBoardLot:
    def test_default_lot_is_one_share(self) -> None:
        assert NSE_LOT_SIZE == 1
        engine = _engine()
        assert engine.round_size(137.9, 36.60) == 137.0

    def test_pre_august_2025_regime_uses_100_share_lots(self) -> None:
        engine = _engine(ke_lot_size=100)
        assert engine.round_size(1_379, 36.60) == 1_300.0
        assert engine.round_size(99, 36.60) == 0.0

    def test_negative_size_floors_to_zero(self) -> None:
        assert _engine().round_size(-5, 36.60) == 0.0

    @pytest.mark.parametrize("bad", [0, -1, 2.5, "100", True])
    def test_lot_size_must_be_a_positive_integer(self, bad) -> None:
        with pytest.raises(ValueError, match="ke_lot_size"):
            _engine(ke_lot_size=bad)


class TestSettlement:
    """T+3: a buy at bar N is sellable from bar N+3."""

    def _open(self, engine: KenyaEquityEngine, entry_idx: int) -> None:
        engine.positions[CODE] = Position(
            symbol=CODE,
            direction=1,
            entry_price=36.60,
            entry_time=pd.Timestamp("2026-09-01"),
            size=1_000.0,
            leverage=1.0,
            entry_bar_idx=entry_idx,
        )

    @pytest.mark.parametrize(
        "elapsed,allowed", [(0, False), (1, False), (2, False), (3, True), (6, True)]
    )
    def test_sell_is_held_until_t_plus_3(self, elapsed: int, allowed: bool) -> None:
        engine = _engine(price_limit=0)
        self._open(engine, entry_idx=10)
        engine._bar_idx = 10 + elapsed
        assert engine.can_execute(CODE, 0, pd.Series({"open": 36.60})) is allowed

    def test_settlement_lag_is_configurable(self) -> None:
        engine = _engine(price_limit=0, ke_settlement_bars=1)
        self._open(engine, entry_idx=10)
        engine._bar_idx = 11
        assert engine.can_execute(CODE, 0, pd.Series({"open": 36.60})) is True

    def test_buy_is_never_held(self) -> None:
        engine = _engine(price_limit=0)
        self._open(engine, entry_idx=10)
        engine._bar_idx = 10
        assert engine.can_execute(CODE, 1, pd.Series({"open": 36.60})) is True


class TestCostStack:
    def test_small_ticket_pays_2_10_percent(self) -> None:
        engine = _engine()
        cost = engine.calc_commission(1_000, 36.60, direction=1, is_open=True)
        assert cost == pytest.approx(36_600 * 0.0210)

    def test_large_ticket_pays_1_84_percent(self) -> None:
        engine = _engine()
        cost = engine.calc_commission(10_000, 36.60, direction=1, is_open=True)
        assert cost == pytest.approx(366_000 * 0.0184)

    def test_tier_boundary_is_inclusive_of_100k(self) -> None:
        engine = _engine()
        cost = engine.calc_commission(1_000, 100.0, direction=1, is_open=True)
        assert cost == pytest.approx(100_000 * 0.0210)

    def test_both_sides_cost_the_same(self) -> None:
        engine = _engine()
        buy = engine.calc_commission(10_000, 36.60, direction=1, is_open=True)
        sell = engine.calc_commission(10_000, 36.60, direction=1, is_open=False)
        assert buy == pytest.approx(sell)

    def test_levies_are_configurable(self) -> None:
        # e.g. the disputed 0.08% CMA levy reading: 0.34% -> 0.30%.
        engine = _engine(ke_levies=0.0030)
        cost = engine.calc_commission(10_000, 36.60, direction=1, is_open=True)
        assert cost == pytest.approx(366_000 * (0.015 + 0.0030))


class TestSlippage:
    def test_buy_slips_up_onto_the_grid(self) -> None:
        engine = _engine(slippage=0.002)
        filled = engine.apply_slippage(36.60, 1)
        assert filled == pytest.approx(nse_round_up(36.60 * 1.002))
        assert _on_grid(filled)

    def test_sell_slips_down_onto_the_grid(self) -> None:
        engine = _engine(slippage=0.002)
        filled = engine.apply_slippage(36.60, -1)
        assert filled == pytest.approx(nse_round_down(36.60 * 0.998))
        assert _on_grid(filled)

    def test_penny_stock_never_slips_below_one_tick(self) -> None:
        engine = _engine(slippage=0.5)
        assert engine.apply_slippage(0.01, -1) == pytest.approx(0.01)


class TestCompositeDispatch:
    def test_composite_applies_nse_rules_to_its_kenya_leg(self) -> None:
        from backtest.engines.composite import CompositeEngine

        engine = CompositeEngine(
            {"initial_capital": 10_000_000.0, "slippage": 0.0},
            codes=[CODE, "KCB.NR"],
        )
        assert "kenya_equity" in engine._rule_engines
        bar = pd.Series({"open": 40.25, "pre_close": 36.60})
        assert engine.can_execute(CODE, 1, bar) is False
        assert engine.can_execute(CODE, -1, pd.Series({"open": 36.60})) is False
