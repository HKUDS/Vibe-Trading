"""Tests for ChinaFuturesEngine market rules.

Validates:
  - T+0: can close same-day positions (unlike A-shares)
  - Both long and short allowed
  - Price limit enforcement (varies by product)
  - Integer contract rounding
  - Commission (fixed per-lot and per-notional)
  - Contract multiplier lookup
  - Margin rate lookup
  - Product code extraction
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.china_futures import (
    ChinaFuturesEngine,
    _extract_product,
    _MULTIPLIER,
    _MARGIN_RATE,
    _COMMISSION,
    _PRICE_LIMIT,
    _DEFAULT_PRICE_LIMIT,
)
from backtest.models import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(
    close: float = 5000.0,
    pre_close: float | None = None,
    pct_chg: float | None = None,
    settle: float | None = None,
    pre_settle: float | None = None,
    open_: float | None = None,
) -> pd.Series:
    d: dict = {"close": close, "open": open_ or close}
    if pre_close is not None:
        d["pre_close"] = pre_close
    if pct_chg is not None:
        d["pct_chg"] = pct_chg
    if settle is not None:
        d["settle"] = settle
    if pre_settle is not None:
        d["pre_settle"] = pre_settle
    return pd.Series(d)


def _make_engine(**overrides) -> ChinaFuturesEngine:
    config = {"initial_cash": 1_000_000, "codes": ["IF2406.CFFEX"]}
    config.update(overrides)
    return ChinaFuturesEngine(config)


# ---------------------------------------------------------------------------
# Product extraction
# ---------------------------------------------------------------------------


class TestExtractProduct:
    @pytest.mark.parametrize(
        "symbol, expected",
        [
            ("IF2406.CFFEX", "IF"),
            ("rb2410.SHFE", "rb"),
            ("au2412", "au"),
            ("CF501.ZCE", "CF"),
            ("sc2503.INE", "sc"),
            ("si2406.GFEX", "si"),
        ],
    )
    def test_extract(self, symbol: str, expected: str) -> None:
        assert _extract_product(symbol) == expected


# ---------------------------------------------------------------------------
# can_execute: T+0 (both directions allowed)
# ---------------------------------------------------------------------------


class TestDirectionAndT0:
    def test_long_allowed(self) -> None:
        engine = _make_engine()
        bar = _make_bar()
        assert engine.can_execute("IF2406.CFFEX", 1, bar) is True

    def test_short_allowed(self) -> None:
        """China futures allow short selling (unlike A-shares)."""
        engine = _make_engine()
        bar = _make_bar()
        assert engine.can_execute("IF2406.CFFEX", -1, bar) is True

    def test_close_same_day_allowed(self) -> None:
        """T+0: can close positions opened today."""
        engine = _make_engine()
        engine.positions["IF2406.CFFEX"] = Position(
            symbol="IF2406.CFFEX",
            direction=1,
            entry_price=5000.0,
            entry_time=pd.Timestamp("2025-06-10"),
            size=2.0,
            leverage=1 / 0.12,
        )
        bar = _make_bar()
        assert engine.can_execute("IF2406.CFFEX", 0, bar) is True


# ---------------------------------------------------------------------------
# can_execute: price limits
# ---------------------------------------------------------------------------


class TestPriceLimits:
    def test_stock_index_limit_up_blocks_long(self) -> None:
        """IF has ±10% limit; at limit-up, can't open long."""
        engine = _make_engine()
        bar = _make_bar(close=5500.0, pre_close=5000.0)  # +10%
        assert engine.can_execute("IF2406.CFFEX", 1, bar) is False

    def test_stock_index_limit_down_blocks_short(self) -> None:
        engine = _make_engine()
        bar = _make_bar(close=4500.0, pre_close=5000.0)  # -10%
        assert engine.can_execute("IF2406.CFFEX", -1, bar) is False

    def test_stock_index_within_limit(self) -> None:
        engine = _make_engine()
        bar = _make_bar(close=5200.0, pre_close=5000.0)  # +4%
        assert engine.can_execute("IF2406.CFFEX", 1, bar) is True

    def test_commodity_default_5pct(self) -> None:
        """Commodity like rb uses default ±5% limit."""
        engine = _make_engine(codes=["rb2410.SHFE"])
        bar = _make_bar(close=4250.0, pre_close=4000.0)  # +6.25% > 5%
        assert engine.can_execute("rb2410.SHFE", 1, bar) is False

    def test_commodity_within_limit(self) -> None:
        engine = _make_engine(codes=["rb2410.SHFE"])
        bar = _make_bar(close=4100.0, pre_close=4000.0)  # +2.5%
        assert engine.can_execute("rb2410.SHFE", 1, bar) is True

    def test_limit_down_blocks_long_close(self) -> None:
        """At limit-down, can't sell (close long position)."""
        engine = _make_engine()
        engine.positions["IF2406.CFFEX"] = Position(
            "IF2406.CFFEX", 1, 5000.0, pd.Timestamp("2025-06-09"), 2.0,
        )
        bar = _make_bar(close=4500.0, pre_close=5000.0)  # -10%
        assert engine.can_execute("IF2406.CFFEX", 0, bar) is False


# ---------------------------------------------------------------------------
# round_size
# ---------------------------------------------------------------------------


class TestRoundSize:
    def test_rounds_down_to_integer(self) -> None:
        engine = _make_engine()
        assert engine.round_size(2.7, 5000.0) == 2

    def test_exact_integer(self) -> None:
        engine = _make_engine()
        assert engine.round_size(5.0, 5000.0) == 5

    def test_less_than_one_becomes_zero(self) -> None:
        engine = _make_engine()
        assert engine.round_size(0.9, 5000.0) == 0

    def test_negative_clamps_to_zero(self) -> None:
        engine = _make_engine()
        assert engine.round_size(-2.0, 5000.0) == 0


# ---------------------------------------------------------------------------
# calc_commission
# ---------------------------------------------------------------------------


class TestCommission:
    def test_rate_commission_via_active_symbol(self) -> None:
        """calc_commission uses _active_symbol for product-specific rate."""
        engine = _make_engine()
        engine._active_symbol = "IF2406.CFFEX"
        comm = engine.calc_commission(2, 5000.0, 1, is_open=True)
        # 2 contracts × 5000 × 300 (multiplier) × 0.000023 = 69
        expected = 2 * 5000 * 300 * 0.000023
        assert comm == pytest.approx(expected, rel=0.01)

    def test_fixed_commission_via_active_symbol(self) -> None:
        """au uses fixed per-lot commission."""
        engine = _make_engine()
        engine._active_symbol = "au2412.SHFE"
        comm = engine.calc_commission(3, 500.0, 1, is_open=True)
        expected = 3 * 10.0  # 10 RMB per lot
        assert comm == pytest.approx(expected)

    def test_symbol_aware_rate_commission(self) -> None:
        engine = _make_engine()
        comm = engine.calc_commission_for_symbol("IF2406.CFFEX", 2, 5000.0, is_open=True)
        expected = 2 * 5000 * 300 * 0.000023
        assert comm == pytest.approx(expected, rel=0.01)

    @pytest.mark.parametrize("symbol", ["T2412.CFFEX", "TF2412.CFFEX", "TS2412.CFFEX", "TL2412.CFFEX"])
    def test_every_treasury_future_pays_the_treasury_fee(self, symbol: str) -> None:
        """The 30-year TL is charged per lot like T/TF/TS, not the generic default."""
        engine = _make_engine(codes=[symbol])
        comm = engine.calc_commission_for_symbol(symbol, 2, 100.0, is_open=True)
        assert comm == pytest.approx(2 * 3.0)
        assert "pricing_assumptions" not in engine._engine_diagnostics()

    def test_commission_override(self) -> None:
        engine = _make_engine(commission_override=0.001)
        comm = engine.calc_commission(5, 4000.0, 1, is_open=True)
        assert comm == pytest.approx(5 * 4000.0 * 0.001)


# ---------------------------------------------------------------------------
# Contract multiplier and margin rate
# ---------------------------------------------------------------------------


class TestContractMultiplier:
    @pytest.mark.parametrize(
        "symbol, expected",
        [
            ("IF2406.CFFEX", 300),
            ("IC2406.CFFEX", 200),
            ("rb2410.SHFE", 10),
            ("au2412.SHFE", 1000),
            ("sc2503.INE", 1000),
            ("c2501.DCE", 10),
            ("CF501.ZCE", 5),
        ],
    )
    def test_multipliers(self, symbol: str, expected: int) -> None:
        engine = _make_engine()
        assert engine.get_contract_multiplier(symbol) == expected


class TestMarginRate:
    def test_stock_index_12pct(self) -> None:
        engine = _make_engine()
        assert engine.get_margin_rate("IF2406.CFFEX") == 0.12

    def test_copper_8pct(self) -> None:
        engine = _make_engine()
        assert engine.get_margin_rate("cu2410.SHFE") == 0.08

    def test_unknown_product_default_10pct(self) -> None:
        engine = _make_engine()
        assert engine.get_margin_rate("XX9999.SHFE") == 0.10


# ---------------------------------------------------------------------------
# Product-key casing: every table lookup keys off _extract_product, so the
# fold lives there and these tests guard the invariant that makes it safe
# ---------------------------------------------------------------------------


class TestProductKeyCasing:
    def test_extract_folds_to_the_table_spelling(self) -> None:
        """A symbol reaches the tables in their own spelling, either casing in."""
        assert _extract_product("AU2412.SHFE") == "au"
        assert _extract_product("au2412.SHFE") == "au"
        assert _extract_product("if2406.CFFEX") == "IF"
        assert _extract_product("IF2406.CFFEX") == "IF"

    def test_unlisted_product_keeps_its_own_letters(self) -> None:
        """An unknown product still falls through to the generic defaults."""
        assert _extract_product("XX9999.SHFE") == "XX"

    def test_no_product_collides_when_case_folded(self) -> None:
        """Folding is only safe while no two keys in a table share an
        upper-cased spelling; a future 'ao' beside an existing 'AO' would
        silently merge two different products into one."""
        for table in (_MULTIPLIER, _MARGIN_RATE, _PRICE_LIMIT, _COMMISSION):
            folded: dict[str, str] = {}
            for key in table:
                first = folded.setdefault(key.upper(), key)
                assert first == key, f"{first!r} and {key!r} fold together"

    def test_tables_agree_on_how_a_product_is_spelled(self) -> None:
        """One product, one spelling across all four tables — otherwise the
        canonical map would send a lookup to the wrong casing."""
        spelling: dict[str, str] = {}
        for table in (_MULTIPLIER, _MARGIN_RATE, _PRICE_LIMIT, _COMMISSION):
            for key in table:
                first = spelling.setdefault(key.upper(), key)
                assert first == key, f"product spelled {first!r} and {key!r}"


# ---------------------------------------------------------------------------
# Case-insensitive product lookup (this project's documented symbol
# convention, and Tushare's real ts_code values, use uppercase product
# codes across every exchange, including SHFE/DCE/INE/GFEX)
# ---------------------------------------------------------------------------


class TestCaseInsensitiveLookup:
    def test_uppercase_shfe_multiplier(self) -> None:
        engine = _make_engine()
        assert engine.get_contract_multiplier("AU2412.SHFE") == 1000

    def test_uppercase_shfe_margin_rate(self) -> None:
        engine = _make_engine()
        assert engine.get_margin_rate("AU2412.SHFE") == 0.08

    def test_uppercase_dce_multiplier(self) -> None:
        # pg's real multiplier (20) differs from the generic default
        # (10), so a missed case-sensitive lookup can't coincidentally
        # pass by falling back to the same number.
        engine = _make_engine()
        assert engine.get_contract_multiplier("PG2501.DCE") == 20

    def test_uppercase_ine_multiplier(self) -> None:
        engine = _make_engine()
        assert engine.get_contract_multiplier("SC2503.INE") == 1000

    def test_uppercase_shfe_fixed_commission(self) -> None:
        engine = _make_engine()
        comm = engine.calc_commission_for_symbol("AU2412.SHFE", 3, 500.0, is_open=True)
        assert comm == pytest.approx(3 * 10.0)

    def test_lowercase_cffex_multiplier(self) -> None:
        """The opposite direction: CFFEX/ZCE keys are uppercase-only."""
        engine = _make_engine()
        assert engine.get_contract_multiplier("if2406.cffex") == 300

    def test_lowercase_zce_multiplier(self) -> None:
        engine = _make_engine()
        assert engine.get_contract_multiplier("cf501.zce") == 5

    def test_uppercase_shfe_leverage_from_margin(self) -> None:
        """__init__ derives leverage from the first code's margin rate."""
        engine = ChinaFuturesEngine(
            {"initial_cash": 1_000_000, "codes": ["AU2412.SHFE"]}
        )
        assert engine.default_leverage == pytest.approx(1.0 / 0.08)

    def test_lowercase_cffex_price_limit_still_specific(self) -> None:
        """IF's own 10% limit must still apply lowercase, not the 5%
        generic default a missed lookup would silently substitute."""
        engine = _make_engine()
        # +6%: inside IF's real 10% band, but outside the 5% default a
        # missed case-sensitive lookup would wrongly fall back to.
        bar = _make_bar(close=5300.0, pre_close=5000.0)
        assert engine.can_execute("if2406.cffex", 1, bar) is True


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------


class TestSlippage:
    def test_buy_slippage_increases_price(self) -> None:
        engine = _make_engine()
        assert engine.apply_slippage(5000.0, 1) > 5000.0

    def test_sell_slippage_decreases_price(self) -> None:
        engine = _make_engine()
        assert engine.apply_slippage(5000.0, -1) < 5000.0

    def test_custom_slippage(self) -> None:
        engine = _make_engine(slippage=0.002)
        assert engine.apply_slippage(5000.0, 1) == pytest.approx(5010.0)


# ---------------------------------------------------------------------------
# Leverage derived from margin
# ---------------------------------------------------------------------------


class TestLeverageFromMargin:
    def test_if_leverage(self) -> None:
        """IF margin=12% → leverage≈8.33."""
        engine = _make_engine(codes=["IF2406.CFFEX"])
        assert engine.default_leverage == pytest.approx(1 / 0.12, rel=0.01)

    def test_override_margin_rate(self) -> None:
        engine = _make_engine(margin_rate_override=0.20)
        assert engine.default_leverage == pytest.approx(5.0)

    def test_order_sizing_does_not_depend_on_symbol_order(self) -> None:
        timestamp = pd.Timestamp("2026-01-05")
        frame = pd.DataFrame(
            {"open": [5_000.0], "close": [5_000.0]},
            index=pd.DatetimeIndex([timestamp]),
        )
        first = _make_engine(codes=["IF2406.CFFEX", "T2406.CFFEX"])
        second = _make_engine(codes=["T2406.CFFEX", "IF2406.CFFEX"])

        first_order = first._plan_open_order(
            "IF2406.CFFEX", 0.5, frame, timestamp, 1_000_000.0
        )
        second_order = second._plan_open_order(
            "IF2406.CFFEX", 0.5, frame, timestamp, 1_000_000.0
        )

        assert first_order is not None
        assert second_order is not None
        assert first_order.size == second_order.size
        assert first_order.leverage == pytest.approx(1 / 0.12)
        assert second_order.leverage == pytest.approx(1 / 0.12)

    def test_composite_delegates_symbol_leverage(self) -> None:
        from backtest.engines.composite import CompositeEngine

        engine = CompositeEngine(
            {"initial_cash": 1_000_000, "codes": ["AAPL.US", "IF2406.CFFEX"]},
            ["AAPL.US", "IF2406.CFFEX"],
        )

        assert engine._leverage_for_symbol("IF2406.CFFEX") == pytest.approx(1 / 0.12)
