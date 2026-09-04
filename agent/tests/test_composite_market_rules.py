"""Composite enforcement of A-share and India rules (#1292).

Sub-engines in a composite run are stateless rule books: their ``positions``
dict is always empty and they own no close panel. India T+1 therefore never
fired (the check read the empty dict), and price-limit bands failed open on
every bar (no loader emits ``pre_close``/``pct_chg``, and the panel fallback
lives only on the running engine). The rules now evaluate against the
composite's state through module-level helpers, with the sub-engine supplying
only market parameters.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engines.china_a import ChinaAEngine
from backtest.engines.composite import CompositeEngine
from backtest.models import Position

CODES = ["600000.SH", "RELIANCE.NS"]


def _composite(**overrides) -> CompositeEngine:
    config = {"initial_cash": 1_000_000, "codes": CODES, **overrides}
    return CompositeEngine(config, CODES)


def _bar(open_: float, close: float, day: str) -> pd.Series:
    return pd.Series(
        {"open": open_, "high": max(open_, close), "low": min(open_, close), "close": close},
        name=pd.Timestamp(day),
    )


def _hold(engine: CompositeEngine, symbol: str, entry_day: str) -> None:
    engine.positions[symbol] = Position(
        symbol=symbol,
        direction=1,
        entry_price=100.0,
        entry_time=pd.Timestamp(entry_day),
        size=100.0,
        leverage=1.0,
    )


def _panel(engine: CompositeEngine, prev_close: float, bar_idx: int = 1) -> None:
    engine._close_arr = np.array([[prev_close, prev_close]])
    engine._code_to_col = {code: i for i, code in enumerate(CODES)}
    engine._bar_idx = bar_idx


class TestIndiaT1InComposite:
    def test_same_day_sell_is_blocked(self) -> None:
        engine = _composite()
        engine._active_symbol = "RELIANCE.NS"
        _hold(engine, "RELIANCE.NS", entry_day="2026-03-03")
        _panel(engine, 100.0)
        # Open sits well inside the ±20% band, so only T+1 can block this.
        assert engine.can_execute("RELIANCE.NS", 0, _bar(101.0, 101.0, "2026-03-03")) is False

    def test_older_position_may_sell(self) -> None:
        engine = _composite()
        engine._active_symbol = "RELIANCE.NS"
        _hold(engine, "RELIANCE.NS", entry_day="2026-03-02")
        _panel(engine, 100.0)
        assert engine.can_execute("RELIANCE.NS", 0, _bar(101.0, 101.0, "2026-03-03")) is True


class TestLimitBandInComposite:
    def test_limit_up_open_is_not_fillable(self) -> None:
        engine = _composite()
        engine._active_symbol = "600000.SH"
        _panel(engine, 90.0)  # previous close 90 -> upper band 99.0 at ±10%
        # Open prints at the locked upper band; a buy fill would book above it.
        assert engine.can_execute("600000.SH", 1, _bar(99.2, 99.0, "2026-03-03")) is False

    def test_open_inside_band_is_fillable(self) -> None:
        engine = _composite()
        engine._active_symbol = "600000.SH"
        _panel(engine, 90.0)
        assert engine.can_execute("600000.SH", 1, _bar(95.0, 94.5, "2026-03-03")) is True


class TestSingleMarketUnchanged:
    def test_china_a_single_market_still_blocks_same_day_sell(self) -> None:
        engine = ChinaAEngine({"initial_cash": 100_000})
        engine.positions["600000.SH"] = Position(
            symbol="600000.SH",
            direction=1,
            entry_price=100.0,
            entry_time=pd.Timestamp("2026-03-03"),
            size=100.0,
            leverage=1.0,
        )
        engine._close_arr = np.array([[90.0]])
        engine._code_to_col = {"600000.SH": 0}
        engine._bar_idx = 1
        assert engine.can_execute("600000.SH", 0, _bar(95.0, 95.0, "2026-03-03")) is False
