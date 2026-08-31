"""India T+1 and price-limit bands under the composite engine.

Composite runs previously delegated to stateless sub-engines whose
positions dict was always empty and whose close panel was absent, so
india_equity.can_execute never blocked a T+1 sell and every
_blocked_by_limit returned None (fails open). This pins the uniform
state/parameter helper used for china_a and india_equity, mirroring the
existing HOSE interception.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engines.china_a import ChinaAEngine
from backtest.engines.composite import CompositeEngine
from backtest.engines.india_equity import IndiaEquityEngine
from backtest.models import Position


INDIA_CODE = "RELIANCE.NS"
A_SHARE_CODE = "000001.SZ"


def _india_only_composite(**overrides) -> CompositeEngine:
    codes = [INDIA_CODE, "TCS.NS"]
    config = {"initial_cash": 1_000_000, "codes": codes, **overrides}
    return CompositeEngine(config, codes)


def _a_share_composite(**overrides) -> CompositeEngine:
    codes = [A_SHARE_CODE, "600000.SH"]
    config = {"initial_cash": 1_000_000, "codes": codes, **overrides}
    return CompositeEngine(config, codes)


class TestCompositeIndiaT1:
    def test_blocks_in_day_sell_against_shared_positions(self):
        engine = _india_only_composite()
        ts = pd.Timestamp("2024-04-01")
        engine.positions[INDIA_CODE] = Position(
            symbol=INDIA_CODE,
            direction=1,
            size=10,
            entry_price=100,
            entry_time=ts,
        )
        bar = pd.Series({"close": 100, "open": 100})
        bar.name = ts
        assert engine.can_execute(INDIA_CODE, 0, bar) is False

    def test_allows_next_day_sell(self):
        engine = _india_only_composite()
        engine.positions[INDIA_CODE] = Position(
            symbol=INDIA_CODE,
            direction=1,
            size=10,
            entry_price=100,
            entry_time=pd.Timestamp("2024-04-01"),
        )
        bar = pd.Series({"close": 100, "open": 100})
        bar.name = pd.Timestamp("2024-04-02")
        assert engine.can_execute(INDIA_CODE, 0, bar) is True

    def test_single_market_india_still_blocks(self):
        eng = IndiaEquityEngine({"initial_cash": 1_000_000})
        ts = pd.Timestamp("2024-04-01")
        eng.positions[INDIA_CODE] = Position(
            symbol=INDIA_CODE,
            direction=1,
            size=10,
            entry_price=100,
            entry_time=ts,
        )
        bar = pd.Series({"close": 100, "open": 100})
        bar.name = ts
        assert eng.can_execute(INDIA_CODE, 0, bar) is False


class TestCompositeLimitBands:
    def test_a_share_composite_blocks_limit_up_via_panel(self):
        engine = _a_share_composite()
        engine._close_arr = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=float)
        engine._code_to_col = {A_SHARE_CODE: 0, "600000.SH": 1}
        engine._bar_idx = 1
        # base 10, limit 10% -> upper 11. Open at limit should be blocked even without pre_close
        bar = pd.Series({"open": 11.0})
        assert engine.can_execute(A_SHARE_CODE, 1, bar) is False

    def test_a_share_composite_allows_inside_band(self):
        engine = _a_share_composite()
        engine._close_arr = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=float)
        engine._code_to_col = {A_SHARE_CODE: 0, "600000.SH": 1}
        engine._bar_idx = 1
        bar = pd.Series({"open": 10.5})
        assert engine.can_execute(A_SHARE_CODE, 1, bar) is True

    def test_india_composite_blocks_limit_up_via_panel(self):
        engine = _india_only_composite(price_limit=0.20)
        engine._close_arr = np.array([[100.0, 100.0], [100.0, 100.0]], dtype=float)
        engine._code_to_col = {INDIA_CODE: 0, "TCS.NS": 1}
        engine._bar_idx = 1
        bar = pd.Series({"open": 120.0})
        assert engine.can_execute(INDIA_CODE, 1, bar) is False

    def test_india_composite_allows_inside_band(self):
        engine = _india_only_composite(price_limit=0.20)
        engine._close_arr = np.array([[100.0, 100.0], [100.0, 100.0]], dtype=float)
        engine._code_to_col = {INDIA_CODE: 0, "TCS.NS": 1}
        engine._bar_idx = 1
        bar = pd.Series({"open": 110.0})
        assert engine.can_execute(INDIA_CODE, 1, bar) is True

    def test_band_inactive_without_any_reference(self):
        engine = _a_share_composite()
        engine._bar_idx = 0
        engine._close_arr = None
        assert engine.can_execute(A_SHARE_CODE, 1, pd.Series({"open": 11.0})) is True

    def test_single_market_a_share_unchanged(self):
        eng = ChinaAEngine({"initial_cash": 1_000_000})
        eng._close_arr = np.array([[10.0], [10.0]], dtype=float)
        eng._code_to_col = {A_SHARE_CODE: 0}
        eng._bar_idx = 1
        assert eng.can_execute(A_SHARE_CODE, 1, pd.Series({"open": 11.0})) is False
        assert eng.can_execute(A_SHARE_CODE, 1, pd.Series({"open": 10.5})) is True
