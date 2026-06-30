"""Regression test: vectorized vs loop _calc_equity produce identical results."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.models import Position


class _StubEngine(BaseEngine):
    """Minimal concrete BaseEngine for testing _calc_equity."""

    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return raw_size

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price


def _make_close_df(symbols, n_days=50):
    """Create a close price DataFrame."""
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    prices = {}
    for s in symbols:
        prices[s] = np.cumsum(np.random.randn(n_days)) + 100
    return pd.DataFrame(prices, index=dates)


class TestEquityVectorization:
    def test_empty_positions(self):
        """No positions → equity = capital."""
        engine = _StubEngine({"initial_cash": 1_000_000})
        close_df = _make_close_df(["A", "B"])
        ts = close_df.index[10]
        assert engine._calc_equity(close_df, ts) == 1_000_000

    def test_single_position(self):
        """Single long position: equity matches manual calculation."""
        engine = _StubEngine({"initial_cash": 1_000_000})
        close_df = _make_close_df(["AAPL"])
        ts = close_df.index[10]

        entry_price = 100.0
        size = 50.0
        engine.positions["AAPL"] = Position(
            symbol="AAPL", direction=1, size=size,
            entry_price=entry_price, leverage=1.0, entry_time=ts,
        )
        engine.capital = 1_000_000 - size * entry_price

        equity = engine._calc_equity(close_df, ts)
        cp = float(close_df.at[ts, "AAPL"])
        expected = engine.capital + size * entry_price + 1 * size * (cp - entry_price)
        assert abs(equity - expected) < 1e-8

    def test_multiple_positions(self):
        """Multiple positions: vectorized matches loop."""
        engine = _StubEngine({"initial_cash": 1_000_000})
        symbols = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA"]
        close_df = _make_close_df(symbols)
        ts = close_df.index[20]

        engine.capital = 500_000
        for i, sym in enumerate(symbols):
            direction = 1 if i % 2 == 0 else -1
            engine.positions[sym] = Position(
                symbol=sym, direction=direction, size=10.0 + i * 5,
                entry_price=95.0 + i * 2, leverage=1.0 + i * 0.5,
                entry_time=ts,
            )

        equity = engine._calc_equity(close_df, ts)

        loop_equity = engine.capital
        for sym, pos in engine.positions.items():
            cp = engine._safe_price(close_df, ts, sym, pos.entry_price)
            margin = pos.size * pos.entry_price / pos.leverage
            pnl = pos.direction * pos.size * (cp - pos.entry_price)
            loop_equity += margin + pnl

        assert abs(equity - loop_equity) < 1e-8

    def test_mixed_leverage(self):
        """Different leverage values produce correct margin calculations."""
        engine = _StubEngine({"initial_cash": 1_000_000})
        close_df = _make_close_df(["A", "B"])
        ts = close_df.index[10]

        engine.capital = 800_000
        engine.positions["A"] = Position(
            symbol="A", direction=1, size=100.0,
            entry_price=50.0, leverage=2.0, entry_time=ts,
        )
        engine.positions["B"] = Position(
            symbol="B", direction=-1, size=50.0,
            entry_price=80.0, leverage=1.0, entry_time=ts,
        )

        equity = engine._calc_equity(close_df, ts)

        cp_a = float(close_df.at[ts, "A"])
        cp_b = float(close_df.at[ts, "B"])
        expected = (
            800_000
            + (100 * 50 / 2.0 + 1 * 100 * (cp_a - 50))
            + (50 * 80 / 1.0 + (-1) * 50 * (cp_b - 80))
        )
        assert abs(equity - expected) < 1e-8
