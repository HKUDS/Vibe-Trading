"""Regression for non-strict direction-aware liquidation.

Covers:
- 1x short through 2x adverse bar is liquidated (equity never <0)
- 1x long at -90% survives
- adverse extremum marking (high/low) vs close-only fallback
- composite path shares the corrected hook
- strict data-mode path unchanged
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines._market_hooks import (
    check_crypto_liquidation,
    crypto_liquidation_mark_price,
)
from backtest.engines.crypto import CryptoEngine
from backtest.engines.composite import CompositeEngine
from backtest.models import Position


def _bar(
    close: float, high: float | None = None, low: float | None = None, **extra
) -> pd.Series:
    data: dict = {"close": close}
    if high is not None:
        data["high"] = high
    if low is not None:
        data["low"] = low
    data.update(extra)
    return pd.Series(data)


# ---------------------------------------------------------------------------
# Hook-level
# ---------------------------------------------------------------------------


class TestDirectionAwareHook:
    def test_1x_short_liquidated_through_2x_adverse(self) -> None:
        pos = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0
        )
        bar = _bar(close=300.0, high=300.0, low=90.0)
        assert check_crypto_liquidation("BTC-USDT", bar, {"BTC-USDT": pos}) is True
        # mark uses high for shorts
        assert crypto_liquidation_mark_price(bar, pos) == pytest.approx(300.0)

    def test_1x_long_survives_minus_90(self) -> None:
        pos = Position(
            "BTC-USDT", 1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0
        )
        bar = _bar(close=10.0, high=110.0, low=10.0)
        assert check_crypto_liquidation("BTC-USDT", bar, {"BTC-USDT": pos}) is False
        assert crypto_liquidation_mark_price(bar, pos) == pytest.approx(10.0)

    def test_wick_through_maintenance_triggers_when_high_low_exist(self) -> None:
        # short: close 110 not enough, high 150 triggers
        pos = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar_close = _bar(close=110.0)
        bar_wick = _bar(close=110.0, high=150.0, low=100.0)
        assert (
            check_crypto_liquidation("BTC-USDT", bar_close, {"BTC-USDT": pos}) is False
        )
        assert check_crypto_liquidation("BTC-USDT", bar_wick, {"BTC-USDT": pos}) is True

        # long: close 90 not enough, low 60 triggers
        pos_long = Position(
            "BTC-USDT", 1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar_close_l = _bar(close=90.0)
        bar_wick_l = _bar(close=90.0, high=110.0, low=60.0)
        assert (
            check_crypto_liquidation("BTC-USDT", bar_close_l, {"BTC-USDT": pos_long})
            is False
        )
        assert (
            check_crypto_liquidation("BTC-USDT", bar_wick_l, {"BTC-USDT": pos_long})
            is True
        )

    def test_close_only_bars_retain_behavior(self) -> None:
        pos = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar = _bar(close=150.0)
        assert crypto_liquidation_mark_price(bar, pos) == pytest.approx(150.0)
        assert check_crypto_liquidation("BTC-USDT", bar, {"BTC-USDT": pos}) is True

        pos_long = Position(
            "BTC-USDT", 1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar2 = _bar(close=60.0)
        assert crypto_liquidation_mark_price(bar2, pos_long) == pytest.approx(60.0)

    def test_mark_high_low_alias(self) -> None:
        pos_short = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar = _bar(close=110.0, mark_high=150.0)
        assert crypto_liquidation_mark_price(bar, pos_short) == pytest.approx(150.0)
        assert (
            check_crypto_liquidation("BTC-USDT", bar, {"BTC-USDT": pos_short}) is True
        )

        pos_long = Position(
            "BTC-USDT", 1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar2 = _bar(close=90.0, mark_low=60.0)
        assert crypto_liquidation_mark_price(bar2, pos_long) == pytest.approx(60.0)
        assert (
            check_crypto_liquidation("BTC-USDT", bar2, {"BTC-USDT": pos_long}) is True
        )


# ---------------------------------------------------------------------------
# Engine integration — CryptoEngine (non-strict)
# ---------------------------------------------------------------------------


class TestCryptoEngineNonStrict:
    def _engine(self) -> CryptoEngine:
        return CryptoEngine(
            {
                "initial_cash": 10_000,
                "leverage": 1.0,
                "slippage": 0.0,
                "maker_rate": 0.0,
                "taker_rate": 0.0,
            }
        )

    def test_1x_short_liquidated_equity_never_negative(self) -> None:
        engine = self._engine()
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0
        )
        bar = _bar(close=300.0, high=300.0, low=90.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" not in engine.positions
        assert engine.trades[0].exit_reason == "liquidation"
        # equity after liquidation is capital (no negative unrealized left)
        assert engine.capital >= 0

    def test_1x_long_survives(self) -> None:
        engine = self._engine()
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0
        )
        bar = _bar(close=10.0, high=110.0, low=10.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" in engine.positions

    def test_wick_liquidation_uses_high_for_short(self) -> None:
        engine = CryptoEngine(
            {
                "initial_cash": 10_000,
                "leverage": 3.0,
                "slippage": 0.0,
                "maker_rate": 0.0,
                "taker_rate": 0.0,
            }
        )
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        # close 110 would not liquidate, high 150 should
        bar_no_wick = _bar(close=110.0)
        bar_wick = _bar(close=110.0, high=150.0, low=100.0)
        ts = pd.Timestamp("2025-01-02")
        # close-only: survives
        engine2 = CryptoEngine(
            {
                "initial_cash": 10_000,
                "leverage": 3.0,
                "slippage": 0.0,
                "maker_rate": 0.0,
                "taker_rate": 0.0,
            }
        )
        engine2.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        engine2.on_bar("BTC-USDT", bar_no_wick, ts)
        assert "BTC-USDT" in engine2.positions
        # wick: liquidated at high price
        engine.on_bar("BTC-USDT", bar_wick, ts)
        assert "BTC-USDT" not in engine.positions
        assert engine.trades[0].exit_price == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# CompositeEngine (non-strict) shares the same hook
# ---------------------------------------------------------------------------


class TestCompositeEngineNonStrict:
    def test_composite_1x_short_liquidated(self) -> None:
        engine = CompositeEngine(
            {
                "initial_cash": 10_000,
                "leverage": 1.0,
                "slippage": 0.0,
                "maker_rate": 0.0,
                "taker_rate": 0.0,
            },
            ["BTC-USDT", "ETH-USDT"],
        )
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0
        )
        bar = _bar(close=300.0, high=300.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" not in engine.positions

    def test_composite_1x_long_survives(self) -> None:
        engine = CompositeEngine(
            {
                "initial_cash": 10_000,
                "leverage": 1.0,
                "slippage": 0.0,
                "maker_rate": 0.0,
                "taker_rate": 0.0,
            },
            ["BTC-USDT"],
        )
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", 1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=1.0
        )
        bar = _bar(close=10.0, low=10.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" in engine.positions

    def test_composite_wick_uses_adverse_extremum(self) -> None:
        engine = CompositeEngine(
            {
                "initial_cash": 10_000,
                "leverage": 3.0,
                "slippage": 0.0,
                "maker_rate": 0.0,
                "taker_rate": 0.0,
            },
            ["BTC-USDT"],
        )
        engine.positions["BTC-USDT"] = Position(
            "BTC-USDT", -1, 100.0, pd.Timestamp("2025-01-01"), 1.0, leverage=3.0
        )
        bar = _bar(close=110.0, high=150.0)
        ts = pd.Timestamp("2025-01-02")
        engine.on_bar("BTC-USDT", bar, ts)
        assert "BTC-USDT" not in engine.positions
        assert engine.trades[0].exit_price == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# Strict path unchanged — strict liquidation uses MarketRiskFrame, not the
# non-strict hook. Verify a known strict isolated liquidation still closes.
# ---------------------------------------------------------------------------


class TestStrictPathUntouched:
    def test_strict_isolated_liquidation_still_closes(self) -> None:
        dates = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        brackets = '[{"bracket_tier":1,"notional_cap":1000000.0,"maintenance_rate":0.004,"cumulative_maintenance_amount":0.0}]'

        def _strict_frame(dates, **kwargs):
            base = [100.0] * len(dates)
            mark_low = kwargs.get("mark_low", base)
            return pd.DataFrame(
                {
                    "execution_open": base,
                    "mark_open": base,
                    "mark_high": base,
                    "mark_low": mark_low,
                    "mark_close": base,
                    "funding_rate": [0.0] * len(dates),
                    "funding_settlement_time": [pd.NaT] * len(dates),
                    "maintenance_brackets": [brackets] * len(dates),
                    "maintenance_bracket_version": ["fixture-v1"] * len(dates),
                },
                index=dates,
            )

        frames = {
            "BTC-USDT-PERP": _strict_frame(dates, mark_low=[100.0, 80.0]),
            "ETH-USDT-PERP": _strict_frame(dates),
        }
        engine = CryptoEngine(
            {
                "initial_cash": 2_000.0,
                "leverage": 10.0,
                "perpetual_strict": True,
                "funding_mode": "data",
                "margin_mode": "isolated",
                "interval": "1H",
                "taker_rate": 0.0,
                "maker_rate": 0.0,
                "liquidation_fee_rate": 0.01,
            }
        )
        close_df = pd.DataFrame(index=dates)
        target = {s: [0.5, 0.5] for s in frames}
        engine._execute_bars(
            dates, frames, close_df, pd.DataFrame(target, index=dates), list(frames)
        )
        reasons = {t.symbol: t.exit_reason for t in engine.trades}
        assert reasons["BTC-USDT-PERP"] == "position_liquidation"
        assert reasons["ETH-USDT-PERP"] == "end_of_backtest"
