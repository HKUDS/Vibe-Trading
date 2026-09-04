"""Non-strict crypto liquidation must not exempt 1x shorts (#1291).

A leverage <= 1 exemption makes sense for a long -- bankruptcy price is zero --
but a 1x short survives an unbounded adverse move with equity below zero. The
hook also marks at the close instead of the adverse extremum, so a wick that
would liquidate any real position is ignored when high/low are present.
"""

from __future__ import annotations

import pandas as pd

import pytest

from backtest.engines._market_hooks import check_crypto_liquidation
from backtest.engines.composite import CompositeEngine
from backtest.engines.crypto import CryptoEngine
from backtest.models import Position


def _pos(direction: int, leverage: float = 1.0, entry: float = 100.0, size: float = 10.0) -> Position:
    return Position(
        "BTC-USDT-PERP", direction, entry, pd.Timestamp("2026-01-05"), size, leverage
    )


def _bar(close: float, high: float | None = None, low: float | None = None) -> pd.Series:
    row = {"close": close}
    if high is not None:
        row["high"] = high
    if low is not None:
        row["low"] = low
    return pd.Series(row)


def test_1x_short_liquidates_through_twice_the_entry_price() -> None:
    """Margin is the full notional; a 2x adverse move zeroes it."""
    bar = _bar(close=200.0, high=200.0, low=101.0)
    assert check_crypto_liquidation(
        "BTC-USDT-PERP", bar, {"BTC-USDT-PERP": _pos(direction=-1)}
    ) is True


def test_1x_short_favorable_move_survives() -> None:
    """Dropping the exemption must not over-liquidate a profitable short."""
    bar = _bar(close=50.0, high=51.0, low=49.0)
    assert check_crypto_liquidation(
        "BTC-USDT-PERP", bar, {"BTC-USDT-PERP": _pos(direction=-1)}
    ) is False


def test_1x_long_survives_ninety_percent_drawdown() -> None:
    """The direction-aware exemption keeps the 1x long protection."""
    bar = _bar(close=10.0, high=101.0, low=9.0)
    assert check_crypto_liquidation(
        "BTC-USDT-PERP", bar, {"BTC-USDT-PERP": _pos(direction=1)}
    ) is False


def test_wick_through_maintenance_triggers_when_high_low_present() -> None:
    """A levered long whose low pierces the maintenance margin is liquidated."""
    bar = _bar(close=100.0, high=101.0, low=30.0)
    assert check_crypto_liquidation(
        "BTC-USDT-PERP",
        bar,
        {"BTC-USDT-PERP": _pos(direction=1, leverage=2.0)},
    ) is True


def test_close_only_bar_keeps_legacy_behavior() -> None:
    """Without high/low, close-only bars mark at the close as before."""
    bar = _bar(close=100.0)
    assert check_crypto_liquidation(
        "BTC-USDT-PERP",
        bar,
        {"BTC-USDT-PERP": _pos(direction=1, leverage=2.0)},
    ) is False


def test_adverse_close_without_extremum_still_triggers_short() -> None:
    """A short marked at a catastrophic close liquidates even on close-only bars."""
    bar = _bar(close=250.0)
    assert check_crypto_liquidation(
        "BTC-USDT-PERP", bar, {"BTC-USDT-PERP": _pos(direction=-1)}
    ) is True


# ---------------------------------------------------------------------------
# Composite and strict paths, ported from PR #1300 which covered them while
# #1298 did not. The composite delegates slippage per symbol (composite.py:216),
# so the liquidation fill must land on the same adverse mark the check used;
# the strict path must stay on MarketRiskFrame and never reach this hook.
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
