"""Tests for KoreaEquityEngine (KRX: KOSPI / KOSDAQ) market rules.

Validates:
  - No short selling by default; allow_short opt-in
  - Same-day sell is ALLOWED (no T+1 — unlike China A-share / India delivery)
  - ±30% daily price limit blocks buys at limit-up / sells at limit-down
  - 1-share lots
  - Korea cost stack (bilateral brokerage, sell-only transaction tax)
  - Engine routing (runner single-market + composite cross-market)
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.korea_equity import KoreaEquityEngine
from backtest.models import Position


def _engine(**overrides) -> KoreaEquityEngine:
    config = {"initial_cash": 10_000_000}
    config.update(overrides)
    return KoreaEquityEngine(config)


def _bar(close: float = 100.0, pre_close: float | None = None) -> pd.Series:
    data = {"close": close, "open": close}
    if pre_close is not None:
        data["pre_close"] = pre_close
    return pd.Series(data)


# ---------------------------------------------------------------------------
# can_execute: shorting, same-day sell, price limits
# ---------------------------------------------------------------------------


class TestCanExecute:
    def test_long_allowed(self) -> None:
        assert _engine().can_execute("005930.KS", 1, _bar()) is True

    def test_short_blocked_by_default(self) -> None:
        assert _engine().can_execute("005930.KS", -1, _bar()) is False

    def test_short_allowed_when_opted_in(self) -> None:
        assert _engine(allow_short=True).can_execute("005930.KS", -1, _bar()) is True

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
        bar = _bar(close=130.0, pre_close=100.0)  # +30% -> limit-up (상한가)
        assert _engine().can_execute("005930.KS", 1, bar) is False

    def test_limit_down_blocks_sell(self) -> None:
        engine = _engine()
        engine.positions["005930.KS"] = Position(
            symbol="005930.KS", direction=1, size=10, entry_price=100.0,
            entry_time=pd.Timestamp("2024-04-01"),
        )
        bar = _bar(close=70.0, pre_close=100.0)  # -30% -> limit-down (하한가)
        bar.name = pd.Timestamp("2024-04-02")
        assert engine.can_execute("005930.KS", 0, bar) is False

    def test_within_band_allows_both_sides(self) -> None:
        bar = _bar(close=105.0, pre_close=100.0)
        engine = _engine()
        assert engine.can_execute("005930.KS", 1, bar) is True
        assert engine.can_execute("005930.KS", 0, bar) is True

    def test_limit_disabled_allows_trade_at_band(self) -> None:
        engine = _engine(price_limit=0)
        bar = _bar(close=130.0, pre_close=100.0)
        assert engine.can_execute("005930.KS", 1, bar) is True


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
# calc_commission: Korea cost stack
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

    def test_rates_are_config_overridable(self) -> None:
        engine = _engine(kr_brokerage=0.0, kr_tax_sell=0.002)
        comm = engine.calc_commission(10, 100_000.0, 1, is_open=False)
        assert comm == pytest.approx(10 * 100_000.0 * 0.002, abs=1e-9)


# ---------------------------------------------------------------------------
# apply_slippage + leverage
# ---------------------------------------------------------------------------


class TestSlippageAndLeverage:
    def test_slippage_default(self) -> None:
        assert _engine().apply_slippage(100.0, 1) == pytest.approx(100.1)

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
