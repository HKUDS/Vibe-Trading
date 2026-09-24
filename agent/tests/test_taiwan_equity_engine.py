"""Tests for the Taiwan (TWSE/TPEx) cash-equity engine.

The rule sources are cited in ``backtest/engines/taiwan_equity.py``; these tests
pin the numbers that module encodes. Nothing here touches the network.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.taiwan_equity import (
    TW_LOT_SIZE,
    TaiwanEquityEngine,
    tw_can_execute,
    tw_is_etf,
    tw_price_limits,
    tw_tick_size,
)
from backtest.models import Position

STOCK = "2330.TW"
ETF = "0050.TW"


def _engine(**overrides) -> TaiwanEquityEngine:
    # BaseEngine reads ``initial_cash``; an ``initial_capital`` key is ignored.
    config = {"initial_cash": 1_000_000_000.0, **overrides}
    return TaiwanEquityEngine(config)


def _bar(open_price: float, **extra: float) -> pd.Series:
    return pd.Series({"open": open_price, "close": open_price, **extra})


def _with_close_panel(engine: TaiwanEquityEngine, symbol: str, closes: list[float], bar_idx: int) -> None:
    """Give *engine* the pre-extracted close panel BaseEngine builds for a run."""
    engine._close_arr = np.array(closes, dtype=float).reshape(-1, 1)
    engine._code_to_col = {symbol: 0}
    engine._bar_idx = bar_idx


# Published daily limits on real ex-rights / ex-dividend days.
# Source: TWSE ex-rights/dividend calculation table (``exRight/TWT49U``), fetched 2026-09-24, public exchange data:
# https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20260801&endDate=20260924&response=json
# Columns kept: ex-date, code, reference price, limit-up price, limit-down price.
# Only rows where the single published reference price reproduces BOTH published limits are kept. Rows that
# include a cash capital increase are left out on purpose: the exchange uses a different base for each side there.
_TWSE_STOCK_ROWS = [
    ("2026-08-31", "9105", 8.28, 9.10, 7.46),  # tick 0.01
    ("2026-09-01", "2701", 10.37, 11.40, 9.34),  # lower candidate 9.333 falls in the 0.01 range, upper in 0.05
    ("2026-08-03", "1465", 12.40, 13.60, 11.20),  # tick 0.05
    ("2026-08-03", "1527", 32.25, 35.45, 29.05),
    ("2026-08-04", "3545", 49.28, 54.20, 44.40),  # upper candidate crosses 50
    ("2026-08-04", "2393", 57.00, 62.70, 51.30),  # tick 0.1
    ("2026-08-04", "6209", 69.30, 76.20, 62.40),
    ("2026-08-12", "3605", 109.42, 120.00, 98.50),  # lower candidate falls below 100
    ("2026-08-03", "2376", 324.50, 356.50, 292.50),  # tick 0.5
    ("2026-09-02", "6139", 747.00, 821.00, 673.00),  # tick 1
    ("2026-08-28", "7822", 950.61, 1045.00, 856.00),  # upper candidate crosses 1000
    ("2026-08-13", "3008", 4543.50, 4995.00, 4090.00),  # tick 5
    ("2026-08-04", "3533", 1970.06, 2165.00, 1775.00),
    ("2026-08-27", "2059", 14459.00, 15900.00, 13015.00),  # above 9999.95: the ceiling is not capped there
]

# Same table, codes beginning with "0" (ETFs, including active ETFs with a letter suffix).
_TWSE_ETF_ROWS = [
    ("2026-08-11", "00940", 12.39, 13.62, 11.16),  # tick 0.01 where a stock would use 0.05
    ("2026-08-18", "00894", 47.85, 52.60, 43.07),  # upper candidate crosses 50
    ("2026-08-18", "00690", 78.01, 85.80, 70.25),  # tick 0.05 where a stock would use 0.1
    ("2026-08-21", "00850", 88.35, 97.15, 79.55),
    ("2026-08-05", "00400A", 13.45, 14.79, 12.11),
    ("2026-08-18", "009808", 30.55, 33.60, 27.50),  # six-digit code
]

# ETF rows whose limits would come out different on the stock tick table.
_ETF_ROWS_SENSITIVE_TO_TABLE = {"00940", "00894", "00690", "00850", "00400A"}


def _row_id(row: tuple) -> str:
    return f"{row[1]}-{row[0]}"


class TestTickSize:
    @pytest.mark.parametrize(
        "price,tick",
        [
            (9.99, 0.01),
            (10, 0.05),
            (49.95, 0.05),
            (50, 0.1),
            (99.9, 0.1),
            (100, 0.5),
            (499.5, 0.5),
            (500, 1),
            (999, 1),
            (1000, 5),
            (4543.5, 5),
        ],
    )
    def test_stock_tick_bands(self, price: float, tick: float) -> None:
        assert tw_tick_size(price) == tick

    @pytest.mark.parametrize("price,tick", [(1.0, 0.01), (49.99, 0.01), (50, 0.05), (78.01, 0.05), (1500, 0.05)])
    def test_etf_tick_bands(self, price: float, tick: float) -> None:
        assert tw_tick_size(price, etf=True) == tick

    @pytest.mark.parametrize("price", [0.0, -3.0])
    def test_non_positive_price_takes_the_finest_tick(self, price: float) -> None:
        assert tw_tick_size(price) == 0.01
        assert tw_tick_size(price, etf=True) == 0.01


class TestEtfDetection:
    @pytest.mark.parametrize(
        "symbol", ["0050.TW", "0050", "00878.TW", "00400A.TW", "009808.TWO", "0050.tw", " 0056.TW "]
    )
    def test_codes_starting_with_zero_are_etfs(self, symbol: str) -> None:
        assert tw_is_etf(symbol) is True

    @pytest.mark.parametrize("symbol", ["2330.TW", "2330", "6488.TWO", "9105.TW", "1101.tw", ""])
    def test_other_codes_are_stocks(self, symbol: str) -> None:
        assert tw_is_etf(symbol) is False


class TestPriceLimits:
    def test_official_worked_example(self) -> None:
        # TWSE trading-system page: reference 40.60 -> 44.65 up / 36.55 down (returned as (upper, lower)).
        assert tw_price_limits(40.60) == (44.65, 36.55)

    @pytest.mark.parametrize("row", _TWSE_STOCK_ROWS, ids=_row_id)
    def test_real_exchange_rows_stocks(self, row: tuple) -> None:
        _, code, ref, limit_up, limit_down = row
        assert tw_price_limits(ref, etf=tw_is_etf(code)) == (limit_up, limit_down)

    @pytest.mark.parametrize("row", _TWSE_ETF_ROWS, ids=_row_id)
    def test_real_exchange_rows_etfs(self, row: tuple) -> None:
        _, code, ref, limit_up, limit_down = row
        assert tw_is_etf(code) is True
        assert tw_price_limits(ref, etf=True) == (limit_up, limit_down)

    @pytest.mark.parametrize("row", [r for r in _TWSE_ETF_ROWS if r[1] in _ETF_ROWS_SENSITIVE_TO_TABLE], ids=_row_id)
    def test_etf_rows_are_not_reproduced_by_the_stock_table(self, row: tuple) -> None:
        _, _, ref, limit_up, limit_down = row
        assert tw_price_limits(ref, etf=False) != (limit_up, limit_down)

    def test_fixture_spans_every_stock_tick_band(self) -> None:
        ref_ticks = {tw_tick_size(row[2]) for row in _TWSE_STOCK_ROWS}
        assert ref_ticks == {0.01, 0.05, 0.1, 0.5, 1, 5}
        assert not any(tw_is_etf(row[1]) for row in _TWSE_STOCK_ROWS)

    def test_fixture_has_several_etf_codes(self) -> None:
        assert len({row[1] for row in _TWSE_ETF_ROWS}) >= 2
        assert len(_TWSE_STOCK_ROWS) + len(_TWSE_ETF_ROWS) >= 10

    def test_floor_and_ceiling_use_the_tick_of_the_candidate_price(self) -> None:
        # Reference 10.37: the upper candidate 11.407 sits in the 0.05 range, the lower candidate 9.333 in the 0.01
        # range. A lower bound ceiled on the 0.05 grid would be 9.35.
        upper, lower = tw_price_limits(10.37)
        assert upper == 11.40
        assert lower == 9.34

    def test_reference_price_is_not_rounded_to_a_tick_first(self) -> None:
        # Rounding 10.37 to the nearest 0.05 tick (10.35) first would move both bounds.
        assert tw_price_limits(10.35) == (11.35, 9.32)
        assert tw_price_limits(10.37) == (11.40, 9.34)

    def test_float_noise_in_the_reference_does_not_cost_a_tick(self) -> None:
        # Adjusted price series are not exact decimals; 1 ulp under 100 must still give the 110.0 ceiling.
        assert tw_price_limits(99.99999999999999)[0] == 110.0
        assert tw_price_limits(100.00000000000001)[1] == 90.0

    def test_custom_band(self) -> None:
        assert tw_price_limits(100.0, 0.05) == (105.0, 95.0)

    def test_band_wider_than_the_price_stops_at_the_minimum_price(self) -> None:
        assert tw_price_limits(50.0, 1.0)[1] == 0.01

    def test_limits_bracket_the_reference_and_sit_on_the_tick_grid(self) -> None:
        for etf in (False, True):
            for cents in range(100, 600_000, 137):
                ref = cents / 100
                upper, lower = tw_price_limits(ref, etf=etf)
                assert lower <= ref <= upper
                for bound in (upper, lower):
                    tick = Decimal(str(tw_tick_size(bound, etf=etf)))
                    assert Decimal(str(bound)) % tick == 0, (ref, etf, bound)


class TestLotSize:
    def test_board_lot_is_one_thousand_shares(self) -> None:
        assert TW_LOT_SIZE == 1000

    @pytest.mark.parametrize("raw,rounded", [(1999, 1000), (1000, 1000), (2500, 2000), (999, 0), (1, 0)])
    def test_orders_floor_to_whole_lots(self, raw: float, rounded: float) -> None:
        assert _engine().round_size(raw, 100.0) == rounded

    @pytest.mark.parametrize("raw", [0, -500, float("nan")])
    def test_non_positive_or_undefined_size_rounds_to_zero(self, raw: float) -> None:
        assert _engine().round_size(raw, 100.0) == 0

    def test_float_noise_below_a_lot_boundary_does_not_drop_a_lot(self) -> None:
        # notional / price can land a hair under a whole number of lots.
        assert _engine().round_size(2999.9999999999995, 100.0) == 3000


class TestCosts:
    def test_buy_pays_brokerage_only(self) -> None:
        cost = _engine().calc_commission(1000, 100.0, direction=1, is_open=True)
        assert cost == pytest.approx(100_000 * 0.001425)

    def test_sell_of_a_stock_adds_three_tenths_of_a_percent_tax(self) -> None:
        engine = _engine()
        engine._active_symbol = STOCK
        cost = engine.calc_commission(1000, 100.0, direction=1, is_open=False)
        assert cost == pytest.approx(100_000 * (0.001425 + 0.003))

    def test_sell_of_an_etf_adds_one_tenth_of_a_percent_tax(self) -> None:
        engine = _engine()
        engine._active_symbol = ETF
        cost = engine.calc_commission(1000, 100.0, direction=1, is_open=False)
        assert cost == pytest.approx(100_000 * (0.001425 + 0.001))

    @pytest.mark.parametrize("symbol,tax", [("0050.TW", 0.001), ("00878.TW", 0.001), ("6488.TWO", 0.003), ("", 0.003)])
    def test_tax_rate_follows_the_active_symbol(self, symbol: str, tax: float) -> None:
        engine = _engine()
        engine._active_symbol = symbol
        cost = engine.calc_commission(1000, 100.0, direction=1, is_open=False)
        assert cost == pytest.approx(100_000 * (0.001425 + tax))

    def test_buying_an_etf_pays_no_tax(self) -> None:
        engine = _engine()
        engine._active_symbol = ETF
        assert engine.calc_commission(1000, 100.0, direction=1, is_open=True) == pytest.approx(100_000 * 0.001425)

    def test_brokerage_has_a_twenty_dollar_minimum_on_both_legs(self) -> None:
        engine = _engine()
        engine._active_symbol = STOCK
        # 1000 x 10.0 = 10,000 -> 14.25 by rate, lifted to the 20 minimum.
        assert engine.calc_commission(1000, 10.0, direction=1, is_open=True) == pytest.approx(20.0)
        assert engine.calc_commission(1000, 10.0, direction=1, is_open=False) == pytest.approx(20.0 + 10_000 * 0.003)

    def test_minimum_does_not_apply_once_the_rate_exceeds_it(self) -> None:
        # 1000 x 14.03 -> 19.99, still below 20; 1000 x 14.04 -> 20.007.
        engine = _engine()
        assert engine.calc_commission(1000, 14.03, direction=1, is_open=True) == pytest.approx(20.0)
        assert engine.calc_commission(1000, 14.04, direction=1, is_open=True) == pytest.approx(14_040 * 0.001425)

    def test_an_empty_trade_costs_nothing(self) -> None:
        assert _engine().calc_commission(0, 100.0, direction=1, is_open=True) == 0.0

    @pytest.mark.parametrize(
        "direction,is_open,taxed", [(1, True, False), (1, False, True), (-1, True, True), (-1, False, False)]
    )
    def test_tax_follows_the_trade_side(self, direction: int, is_open: bool, taxed: bool) -> None:
        engine = _engine()
        engine._active_symbol = STOCK
        expected = 100_000 * (0.001425 + (0.003 if taxed else 0.0))
        assert engine.calc_commission(1000, 100.0, direction=direction, is_open=is_open) == pytest.approx(expected)

    def test_config_overrides_reach_the_cost_stack(self) -> None:
        engine = _engine(tw_fee_rate=0.002, tw_fee_discount=0.5, tw_fee_min=1.0, tw_tax_stock=0.0015, tw_tax_etf=0.0005)
        engine._active_symbol = STOCK
        assert engine.calc_commission(1000, 100.0, 1, True) == pytest.approx(100_000 * 0.002 * 0.5)
        assert engine.calc_commission(1000, 100.0, 1, False) == pytest.approx(100_000 * (0.002 * 0.5 + 0.0015))
        engine._active_symbol = ETF
        assert engine.calc_commission(1000, 100.0, 1, False) == pytest.approx(100_000 * (0.002 * 0.5 + 0.0005))
        # The overridden minimum (1.0) replaces the default 20.
        assert engine.calc_commission(1000, 1.0, 1, True) == pytest.approx(1.0)

    def test_defaults_are_the_published_standard_rates(self) -> None:
        engine = _engine()
        assert engine.tw_fee_rate == 0.001425
        assert engine.tw_fee_discount == 1.0
        assert engine.tw_fee_min == 20.0
        assert engine.tw_tax_stock == 0.003
        assert engine.tw_tax_etf == 0.001


class TestSlippage:
    def test_default_is_a_plain_tenth_of_a_percent(self) -> None:
        engine = _engine()
        assert engine.apply_slippage(100.0, 1) == pytest.approx(100.1)
        assert engine.apply_slippage(100.0, -1) == pytest.approx(99.9)

    def test_slipped_price_is_not_snapped_to_the_tick_grid(self) -> None:
        # Dividend-adjusted (Yahoo) prices are off-grid, and stock and ETF tick tables differ, so no snapping.
        filled = _engine().apply_slippage(10.37, 1)
        assert filled == pytest.approx(10.37 * 1.001)
        assert filled not in (10.40, 10.35, 10.38)

    def test_slippage_is_configurable(self) -> None:
        assert _engine(slippage=0.0).apply_slippage(10.37, 1) == 10.37
        assert _engine(slippage=0.005).apply_slippage(200.0, -1) == pytest.approx(199.0)


class TestShortSelling:
    def test_allow_short_is_refused(self) -> None:
        with pytest.raises(ValueError, match="long-only"):
            _engine(allow_short=True)

    def test_a_false_flag_is_accepted(self) -> None:
        _engine(allow_short=False)

    def test_short_direction_is_blocked(self) -> None:
        assert _engine().can_execute(STOCK, -1, _bar(100.0, pre_close=100.0)) is False

    def test_leverage_is_forced_to_one(self) -> None:
        assert _engine(leverage=5).default_leverage == 1.0


class TestNoSettlementHold:
    """Unlike Vietnam, shares bought on the previous business day may be sold (TWSE Operating Rules Art. 79-1)."""

    def _hold(self, engine: TaiwanEquityEngine, entry_idx: int, action: str = "open") -> None:
        engine._bar_idx = entry_idx
        engine._record_fill(
            symbol=STOCK,
            timestamp=pd.Timestamp("2026-03-02"),
            action=action,
            signed_quantity=1_000.0,
            execution_price=100.0,
            fee=0.0,
            margin=100_000.0,
            leverage=1.0,
            reason="signal",
        )
        engine.positions[STOCK] = Position(
            symbol=STOCK,
            direction=1,
            entry_price=100.0,
            entry_time=pd.Timestamp("2026-03-02"),
            size=1_000.0,
            leverage=1.0,
            entry_bar_idx=entry_idx,
        )

    @pytest.mark.parametrize("elapsed", [1, 2, 5])
    def test_buy_on_bar_n_may_be_sold_on_bar_n_plus_one(self, elapsed: int) -> None:
        engine = _engine(price_limit=None)
        self._hold(engine, entry_idx=10)
        engine._bar_idx = 10 + elapsed
        assert engine.can_execute(STOCK, 0, _bar(100.0)) is True

    def test_an_add_does_not_restart_any_clock(self) -> None:
        engine = _engine(price_limit=None)
        self._hold(engine, entry_idx=10)
        self._hold(engine, entry_idx=11, action="increase")
        engine._bar_idx = 12
        assert engine.can_execute(STOCK, 0, _bar(100.0)) is True

    def test_engine_has_no_settlement_setting(self) -> None:
        assert not hasattr(_engine(), "settlement_bars")


class TestBandBlocking:
    """Reference 40.60 -> ceiling 44.65, floor 36.55 (the official worked example)."""

    @pytest.mark.parametrize(
        "open_price,allowed", [(44.60, True), (44.65, False), (44.70, False), (40.60, True), (36.55, True)]
    )
    def test_buy_is_blocked_at_or_above_the_ceiling(self, open_price: float, allowed: bool) -> None:
        engine = _engine(slippage=0.0)
        assert engine.can_execute(STOCK, 1, _bar(open_price, pre_close=40.60)) is allowed

    @pytest.mark.parametrize(
        "open_price,allowed", [(36.60, True), (36.55, False), (36.50, False), (40.60, True), (44.65, True)]
    )
    def test_sell_is_blocked_at_or_below_the_floor(self, open_price: float, allowed: bool) -> None:
        engine = _engine(slippage=0.0)
        assert engine.can_execute(STOCK, 0, _bar(open_price, pre_close=40.60)) is allowed

    def test_the_prospective_fill_includes_slippage(self) -> None:
        engine = _engine()  # slippage 0.1%
        # 44.62 is inside the band, but the buy would fill at 44.6646, above the ceiling.
        assert engine.can_execute(STOCK, 1, _bar(44.62, pre_close=40.60)) is False
        assert engine.can_execute(STOCK, 1, _bar(44.60, pre_close=40.60)) is True
        # Likewise a sell at 36.57 would fill at 36.5334, below the floor.
        assert engine.can_execute(STOCK, 0, _bar(36.57, pre_close=40.60)) is False
        assert engine.can_execute(STOCK, 0, _bar(36.60, pre_close=40.60)) is True

    def test_band_is_disabled_by_a_falsy_price_limit(self) -> None:
        for disabled in (None, 0):
            engine = _engine(price_limit=disabled, slippage=0.0)
            assert engine.can_execute(STOCK, 1, _bar(50.0, pre_close=40.60)) is True
            assert engine.can_execute(STOCK, 0, _bar(30.0, pre_close=40.60)) is True

    def test_band_width_follows_config(self) -> None:
        engine = _engine(price_limit=0.05, slippage=0.0)
        assert engine.can_execute(STOCK, 1, _bar(105.0, pre_close=100.0)) is False
        assert engine.can_execute(STOCK, 1, _bar(104.5, pre_close=100.0)) is True

    def test_default_band_is_ten_percent(self) -> None:
        assert _engine().price_limit == 0.10

    def test_etf_band_uses_the_etf_tick_table(self) -> None:
        # Reference 40.60: stock ceiling 44.65 (0.05 tick), ETF ceiling 44.66 (0.01 tick).
        engine = _engine(slippage=0.0)
        assert engine.can_execute(STOCK, 1, _bar(44.65, pre_close=40.60)) is False
        assert engine.can_execute(ETF, 1, _bar(44.65, pre_close=40.60)) is True
        assert engine.can_execute(ETF, 1, _bar(44.66, pre_close=40.60)) is False

    def test_reference_price_is_not_tick_rounded_before_the_check(self) -> None:
        # Reference 10.37: floor 9.34 and ceiling 11.40. Rounding the reference to 10.35 would give 9.32 / 11.35.
        engine = _engine(slippage=0.0)
        assert engine.can_execute(STOCK, 0, _bar(9.33, pre_close=10.37)) is False  # at/below the true floor
        assert engine.can_execute(STOCK, 1, _bar(11.37, pre_close=10.37)) is True  # under the true ceiling

    def test_reference_comes_from_the_previous_close_of_the_panel(self) -> None:
        engine = _engine(slippage=0.0)
        _with_close_panel(engine, STOCK, [39.0, 40.60, 41.0], bar_idx=2)  # previous row is 40.60
        assert engine.can_execute(STOCK, 1, _bar(44.65)) is False
        assert engine.can_execute(STOCK, 1, _bar(44.60)) is True

    def test_the_current_bar_close_is_never_used(self) -> None:
        # The decision bar's own close is unknown when the order is placed; a limit-up close must not block the buy.
        engine = _engine(slippage=0.0)
        _with_close_panel(engine, STOCK, [39.0, 40.60, 41.0], bar_idx=2)
        bar = pd.Series({"open": 40.70, "close": 44.65})
        assert engine.can_execute(STOCK, 1, bar) is True

    def test_state_and_rules_may_be_separate_engines(self) -> None:
        # A composite run keeps the panel on itself and the parameters on a stateless rule-book engine.
        state = _engine()
        _with_close_panel(state, STOCK, [100.0, 100.0], bar_idx=1)
        rules = _engine(price_limit=0.05, slippage=0.0)
        assert tw_can_execute(state, rules, STOCK, 1, _bar(105.0)) is False
        assert tw_can_execute(state, rules, STOCK, 1, _bar(104.5)) is True
        assert tw_can_execute(state, rules, STOCK, -1, _bar(104.5)) is False

    def test_no_reference_price_allows_the_trade_and_warns_once(self, caplog: pytest.LogCaptureFixture) -> None:
        engine = _engine()
        with caplog.at_level(logging.WARNING, logger="backtest.engines.taiwan_equity"):
            assert engine.can_execute(STOCK, 1, _bar(500.0)) is True
            assert engine.can_execute(STOCK, 0, _bar(500.0)) is True
        assert len([r for r in caplog.records if "reference price" in r.getMessage()]) == 1

    def test_first_bar_of_a_run_has_no_reference(self) -> None:
        engine = _engine()
        _with_close_panel(engine, STOCK, [40.60], bar_idx=0)
        assert engine.can_execute(STOCK, 1, _bar(500.0)) is True

    @pytest.mark.parametrize("bad_open", [0.0, -1.0, float("nan")])
    def test_unusable_open_price_is_left_to_order_sizing(self, bad_open: float) -> None:
        assert _engine().can_execute(STOCK, 1, _bar(bad_open, pre_close=40.60)) is True


# --- end to end through BaseEngine's real execution paths -------------------------------------------------------

_DATES = pd.bdate_range("2026-03-02", periods=8)


def _bars(start: float, step: float) -> pd.DataFrame:
    """Eight sessions rising ``step`` a bar, far inside the +/-10% band."""
    opens = [round(start + step * i, 2) for i in range(8)]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [o + 0.5 for o in opens],
            "low": [o - 0.5 for o in opens],
            "close": [round(o + step, 2) for o in opens],
            "volume": [1_000_000] * 8,
        },
        index=_DATES,
    )


class _FakeLoader:
    def fetch(self, *args, **kwargs):
        return {STOCK: _bars(100.0, 0.5), ETF: _bars(60.0, 0.3)}


class _WeightSignal:
    """Replay one target-weight path for every symbol, one weight per bar."""

    def __init__(self, weights: list[float]) -> None:
        self._weights = weights

    def generate(self, data_map):
        return {code: pd.Series(self._weights, index=frame.index) for code, frame in data_map.items()}


def _run(weights: list[float], run_dir: Path, loader=None, **overrides) -> TaiwanEquityEngine:
    config = {
        "codes": [ETF, STOCK],
        "start_date": "2026-03-02",
        "end_date": "2026-03-20",
        "source": "auto",
        "initial_cash": 100_000_000,
        "slippage": 0.0,
        **overrides,
    }
    engine = TaiwanEquityEngine(config)
    engine.run_backtest(config, loader or _FakeLoader(), _WeightSignal(weights), run_dir)
    return engine


def _fills(engine: TaiwanEquityEngine, symbol: str) -> list[tuple[int, str]]:
    return [(f.bar_idx, f.action) for f in engine.fill_records if f.symbol == symbol]


def _expected_fee(fill, tax_rate: float) -> float:
    notional = abs(fill.signed_quantity) * fill.execution_price
    return max(notional * 0.001425, 20.0) + notional * tax_rate


class TestRunBacktest:
    def test_a_buy_is_sold_on_the_next_bar_with_the_right_tax(self, tmp_path: Path) -> None:
        # Weights execute one bar late: the 0.4 target opens on bar 1 and the flat target closes on bar 2.
        engine = _run([0.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], tmp_path)

        for symbol, tax in ((STOCK, 0.003), (ETF, 0.001)):
            assert _fills(engine, symbol) == [(1, "open"), (2, "close")]
            opening, closing = [f for f in engine.fill_records if f.symbol == symbol]
            assert abs(closing.signed_quantity) % TW_LOT_SIZE == 0
            assert opening.fee == pytest.approx(_expected_fee(opening, 0.0))
            # The closing leg is priced by BaseEngine._close_position, which sets the active symbol itself.
            assert closing.fee == pytest.approx(_expected_fee(closing, tax))

    def test_partial_reduction_and_final_liquidation_use_the_symbols_own_tax(self, tmp_path: Path) -> None:
        # 'rebalance' mode plans reductions through _plan_reduction; the last position is closed by the
        # end-of-backtest liquidation. A tolerance band keeps float drift from producing stray one-lot trades.
        engine = _run(
            [0.4, 0.4, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
            tmp_path,
            position_adjustment="rebalance",
            rebalance_tolerance=0.05,
        )

        for symbol, tax in ((STOCK, 0.003), (ETF, 0.001)):
            fills = [f for f in engine.fill_records if f.symbol == symbol]
            assert [f.action for f in fills] == ["open", "reduce", "close"]
            assert fills[1].bar_idx == 3
            assert fills[2].reason == "end_of_backtest"
            for fill in fills[1:]:
                assert fill.fee == pytest.approx(_expected_fee(fill, tax))

    def test_full_exit_in_rebalance_mode_uses_the_symbols_own_tax(self, tmp_path: Path) -> None:
        # In 'rebalance' mode a flat target is planned as a reduction to zero, then committed by _close_position.
        # The tolerance band keeps float drift from producing stray one-lot trades.
        engine = _run(
            [0.4, 0.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            tmp_path,
            position_adjustment="rebalance",
            rebalance_tolerance=0.05,
        )

        for symbol, tax in ((STOCK, 0.003), (ETF, 0.001)):
            assert _fills(engine, symbol) == [(1, "open"), (3, "close")]
            closing = [f for f in engine.fill_records if f.symbol == symbol][-1]
            assert closing.reason == "signal"
            assert closing.fee == pytest.approx(_expected_fee(closing, tax))

    def test_a_limit_up_open_blocks_the_buy(self, tmp_path: Path) -> None:
        class _LockedLoader:
            def fetch(self, *args, **kwargs):
                frame = _bars(100.0, 0.5)
                # Bar 0 closes at 100.5, so the ceiling for bar 1 is 110.5 (110.55 floored to the 0.5 tick).
                frame.loc[frame.index[1], ["open", "close"]] = 110.5
                return {STOCK: frame}

        engine = _run([0.4] * 8, tmp_path, loader=_LockedLoader(), codes=[STOCK])

        assert engine.fill_records, "the buy should go through once the stock leaves the limit"
        assert engine.fill_records[0].bar_idx > 1
