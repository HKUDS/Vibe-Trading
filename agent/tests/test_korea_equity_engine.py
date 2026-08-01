"""Tests for KoreaEquityEngine (KRX: KOSPI / KOSDAQ) market rules.

Validates:
  - Long-only by construction: allow_short is refused, never mis-modelled
  - Same-day sell is ALLOWED (no T+1 — unlike China A-share / India delivery)
  - KRX tick grid (호가가격단위) and the published limit-price arithmetic
  - ±30% band derived from the PREVIOUS close and compared with the fill price
    (execution-time safe: no dependence on the decision bar's own close)
  - 1-share lots
  - Korea cost stack keyed to the real trade side (bilateral brokerage,
    sell-side transaction tax)
  - Engine routing (runner single-market + composite cross-market)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engines.korea_equity import (
    KoreaEquityEngine,
    krx_price_limits,
    krx_round_down,
    krx_round_up,
    krx_tick_size,
)
from backtest.models import Position


def _engine(**overrides) -> KoreaEquityEngine:
    config = {"initial_cash": 10_000_000}
    config.update(overrides)
    return KoreaEquityEngine(config)


def _bar(close: float = 100.0, pre_close: float | None = None,
         open_: float | None = None) -> pd.Series:
    data = {"close": close, "open": close if open_ is None else open_}
    if pre_close is not None:
        data["pre_close"] = pre_close
    return pd.Series(data)


def _with_close_panel(engine: KoreaEquityEngine, symbol: str,
                      closes: list[float], bar_idx: int) -> None:
    """Attach the close panel BaseEngine pre-extracts for a run."""
    engine._close_arr = np.array([[c] for c in closes], dtype=float)
    engine._code_to_col = {symbol: 0}
    engine._bar_idx = bar_idx


# ---------------------------------------------------------------------------
# KRX tick grid (호가가격단위), unified across KOSPI/KOSDAQ since 2023-01-25
# ---------------------------------------------------------------------------


class TestTickGrid:
    @pytest.mark.parametrize(
        "price,tick",
        [
            (500.0, 1.0),
            (1_999.0, 1.0),
            (2_000.0, 5.0),      # bands are lower-bound inclusive (이상)
            (4_999.0, 5.0),
            (5_000.0, 10.0),
            (19_999.0, 10.0),
            (20_000.0, 50.0),
            (49_999.0, 50.0),
            (50_000.0, 100.0),
            (199_999.0, 100.0),
            (200_000.0, 500.0),
            (499_999.0, 500.0),
            (500_000.0, 1_000.0),
            (2_987_000.0, 1_000.0),
        ],
    )
    def test_tick_bands(self, price: float, tick: float) -> None:
        assert krx_tick_size(price) == tick

    def test_round_down_and_up(self) -> None:
        assert krx_round_down(12_345.0) == 12_340.0   # tick 10
        assert krx_round_up(12_341.0) == 12_350.0
        assert krx_round_up(300_100.0) == 300_500.0   # tick 500
        assert krx_round_down(300_100.0) == 300_000.0

    def test_already_on_grid_is_unchanged(self) -> None:
        assert krx_round_up(300_000.0) == 300_000.0
        assert krx_round_down(300_000.0) == 300_000.0

    def test_round_up_never_returns_zero(self) -> None:
        assert krx_round_up(0.4) == 1.0

    @pytest.mark.parametrize(
        "base,upper,lower",
        [
            # KRX's own worked examples for the ±30% band.
            (9_980.0, 12_970.0, 6_990.0),
            (9_940.0, 12_920.0, 6_960.0),
        ],
    )
    def test_limit_prices_match_krx_worked_examples(
        self, base: float, upper: float, lower: float
    ) -> None:
        assert krx_price_limits(base, 0.30) == (upper, lower)

    def test_limit_prices_stay_inside_the_band(self) -> None:
        """Truncation must never widen the band beyond ±30%."""
        for base in (1_000.0, 4_500.0, 33_300.0, 190_000.0, 480_000.0, 750_000.0):
            upper, lower = krx_price_limits(base, 0.30)
            assert upper <= base * 1.30 + 1e-9
            assert lower >= base * 0.70 - 1e-9
            assert krx_round_down(upper) == upper
            assert krx_round_down(lower) == lower


# ---------------------------------------------------------------------------
# can_execute: shorting, same-day sell, price limits
# ---------------------------------------------------------------------------


class TestCanExecute:
    def test_long_allowed(self) -> None:
        assert _engine().can_execute("005930.KS", 1, _bar()) is True

    def test_short_always_blocked(self) -> None:
        assert _engine().can_execute("005930.KS", -1, _bar()) is False

    def test_allow_short_is_refused_not_simulated(self) -> None:
        """KRX covered-short / uptick rules are unmodelled — refuse loudly."""
        with pytest.raises(ValueError, match="long-only"):
            _engine(allow_short=True)

    def test_same_day_sell_allowed(self) -> None:
        """KRX permits same-day round trips — no T+1 interception."""
        engine = _engine()
        ts = pd.Timestamp("2024-04-01")
        engine.positions["005930.KS"] = Position(
            symbol="005930.KS", direction=1, size=10, entry_price=100.0, entry_time=ts,
        )
        bar = _bar()
        bar.name = ts  # same date as entry -> still sellable on KRX
        assert engine.can_execute("005930.KS", 0, bar) is True

    def test_limit_up_blocks_buy(self) -> None:
        # pre_close 10,000 -> upper limit 13,000; opening there is locked (상한가).
        bar = _bar(close=13_000.0, pre_close=10_000.0, open_=13_000.0)
        assert _engine(slippage=0).can_execute("005930.KS", 1, bar) is False

    def test_limit_down_blocks_sell(self) -> None:
        # pre_close 10,000 -> lower limit 7,000; opening there is locked (하한가).
        bar = _bar(close=7_000.0, pre_close=10_000.0, open_=7_000.0)
        assert _engine(slippage=0).can_execute("005930.KS", 0, bar) is False

    def test_slippage_that_crosses_the_limit_blocks_the_buy(self) -> None:
        """The check is on the FILL price, so adverse slippage can breach it."""
        bar = _bar(close=12_990.0, pre_close=10_000.0, open_=12_990.0)
        assert _engine(slippage=0).can_execute("005930.KS", 1, bar) is True
        # +0.1% slippage rounds the fill to 13,000 = the limit price.
        assert _engine(slippage=0.001).can_execute("005930.KS", 1, bar) is False

    def test_within_band_allows_both_sides(self) -> None:
        bar = _bar(close=10_500.0, pre_close=10_000.0)
        engine = _engine()
        assert engine.can_execute("005930.KS", 1, bar) is True
        assert engine.can_execute("005930.KS", 0, bar) is True

    def test_limit_disabled_allows_trade_at_band(self) -> None:
        engine = _engine(price_limit=0)
        bar = _bar(close=13_000.0, pre_close=10_000.0)
        assert engine.can_execute("005930.KS", 1, bar) is True

    def test_current_bar_close_does_not_drive_the_check(self) -> None:
        """Regression: a limit-up CLOSE must not block a fill at a normal open.

        The engine fills at this bar's open, which is known before the close, so
        keying the guard to the close would be lookahead.
        """
        bar = _bar(close=13_000.0, pre_close=10_000.0, open_=10_000.0)
        assert _engine().can_execute("005930.KS", 1, bar) is True

    def test_base_price_from_close_panel_when_no_pre_close(self) -> None:
        """pykrx/Yahoo bars carry OHLCV only — use the prior close panel row."""
        engine = _engine(slippage=0)
        _with_close_panel(engine, "005930.KS", [10_000.0, 13_000.0], bar_idx=1)
        bar = _bar(close=13_000.0, open_=13_000.0)
        assert engine.can_execute("005930.KS", 1, bar) is False
        assert engine.can_execute("005930.KS", 0, bar) is True

    def test_first_bar_without_history_is_permitted(self) -> None:
        engine = _engine()
        _with_close_panel(engine, "005930.KS", [10_000.0], bar_idx=0)
        assert engine.can_execute("005930.KS", 1, _bar(close=10_000.0)) is True

    def test_missing_base_price_warns_once(self, caplog) -> None:
        engine = _engine()
        with caplog.at_level("WARNING"):
            assert engine.can_execute("005930.KS", 1, _bar()) is True
            assert engine.can_execute("005930.KS", 1, _bar()) is True
        assert caplog.text.count("limit check is inactive") == 1

    def test_off_grid_base_price_is_rounded_up(self) -> None:
        """Adjusted (Naver-rebased) closes need not sit on a tick."""
        engine = _engine(slippage=0)
        # 9,996 rounds up to 10,000 (절상) -> upper limit 13,000.
        bar = _bar(close=13_000.0, pre_close=9_996.0, open_=13_000.0)
        assert engine.can_execute("005930.KS", 1, bar) is False


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
# calc_commission: Korea cost stack, keyed to the real trade side
# ---------------------------------------------------------------------------


class TestCommission:
    def test_buy_carries_brokerage_only(self) -> None:
        engine = _engine()
        size, price = 10, 100_000.0
        comm = engine.calc_commission(size, price, 1, is_open=True)
        assert comm == pytest.approx(size * price * engine.kr_brokerage, abs=1e-9)

    def test_sell_adds_transaction_tax(self) -> None:
        engine = _engine()
        size, price = 10, 100_000.0
        notional = size * price
        comm = engine.calc_commission(size, price, 1, is_open=False)
        expected = notional * (engine.kr_brokerage + engine.kr_tax_sell)
        assert comm == pytest.approx(expected, abs=1e-9)

    def test_default_sell_tax_is_the_2026_rate(self) -> None:
        # 0.20% aggregate sell-side rate from 2026-01-01 on both boards.
        assert _engine().kr_tax_sell == pytest.approx(0.0020)

    def test_short_open_is_the_taxed_leg_not_the_cover(self) -> None:
        """Tax follows the trade side, so a short book taxes the OPEN."""
        engine = _engine()
        notional = 10 * 100_000.0
        short_open = engine.calc_commission(10, 100_000.0, -1, is_open=True)
        cover = engine.calc_commission(10, 100_000.0, -1, is_open=False)
        assert short_open == pytest.approx(
            notional * (engine.kr_brokerage + engine.kr_tax_sell), abs=1e-9
        )
        assert cover == pytest.approx(notional * engine.kr_brokerage, abs=1e-9)

    def test_rates_are_config_overridable(self) -> None:
        engine = _engine(kr_brokerage=0.0, kr_tax_sell=0.001)  # e.g. KONEX
        comm = engine.calc_commission(10, 100_000.0, 1, is_open=False)
        assert comm == pytest.approx(10 * 100_000.0 * 0.001, abs=1e-9)


# ---------------------------------------------------------------------------
# apply_slippage + leverage
# ---------------------------------------------------------------------------


class TestSlippageAndLeverage:
    def test_buy_slippage_rounds_up_to_a_valid_tick(self) -> None:
        # 100,000 x 1.001 = 100,100 -> already a multiple of the 100 tick.
        assert _engine().apply_slippage(100_000.0, 1) == pytest.approx(100_100.0)
        # 10,000 x 1.001 = 10,010 -> tick 10, on grid.
        assert _engine().apply_slippage(10_000.0, 1) == pytest.approx(10_010.0)
        # 3,000 x 1.001 = 3,003 -> tick 5 -> next valid ask is 3,005.
        assert _engine().apply_slippage(3_000.0, 1) == pytest.approx(3_005.0)

    def test_sell_slippage_rounds_down_to_a_valid_tick(self) -> None:
        # 3,000 x 0.999 = 2,997 -> tick 5 -> next valid bid is 2,995.
        assert _engine().apply_slippage(3_000.0, -1) == pytest.approx(2_995.0)

    def test_zero_slippage_keeps_an_on_grid_price(self) -> None:
        engine = _engine(slippage=0)
        assert engine.apply_slippage(300_000.0, 1) == pytest.approx(300_000.0)
        assert engine.apply_slippage(300_000.0, -1) == pytest.approx(300_000.0)

    def test_sell_price_never_collapses_to_zero(self) -> None:
        assert _engine(slippage=0.9).apply_slippage(1.0, -1) == pytest.approx(1.0)

    def test_no_leverage(self) -> None:
        # Cash equity is forced to 1.0 leverage regardless of config input.
        assert _engine(leverage=5.0).default_leverage == 1.0


# ---------------------------------------------------------------------------
# Engine routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_single_market_korea_routes_to_korea_engine(self) -> None:
        from backtest.runner import _create_market_engine

        engine = _create_market_engine("auto", {"initial_cash": 100_000}, ["005930.KS"])
        assert isinstance(engine, KoreaEquityEngine)

    def test_cross_market_with_korea_builds_korea_subengine(self) -> None:
        from backtest.engines.composite import _build_rule_engines

        engines = _build_rule_engines(
            {"initial_cash": 100_000}, ["005930.KS", "AAPL.US"]
        )
        assert isinstance(engines["kr_equity"], KoreaEquityEngine)

    def test_cross_market_short_config_fails_loudly(self) -> None:
        """A shared allow_short config must not yield a silently long-only KRX leg."""
        from backtest.engines.composite import _build_rule_engines

        with pytest.raises(ValueError, match="long-only"):
            _build_rule_engines(
                {"initial_cash": 100_000, "allow_short": True},
                ["005930.KS", "BTC-USDT"],
            )
