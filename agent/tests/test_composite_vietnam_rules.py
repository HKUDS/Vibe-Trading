"""Vietnam (HOSE) rules under the cross-market composite engine.

``CompositeEngine`` uses sub-engines as stateless rule books and keeps all
positions, fills and the close panel itself. Two HOSE rules cannot be answered
from that stateless side:

  - the T+2 hold needs the position and the fill ledger;
  - the ±7% band needs the run's close panel to reach a reference price.

Without a ``vietnam_equity`` branch, ``_rule_for`` fell through to whichever
sub-engine happened to be first, pricing HOSE symbols under another market's
rules. These tests pin the branch and both intercepted rules.

A mixed book containing ``.VN`` is refused by the single-currency guard before
it can run, so this path is not reachable end to end today. It is enforced
anyway: the guard and the rule book are independent, and a market whose rules
silently vanish in a composite is a trap for whoever relaxes the guard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engines.composite import CompositeEngine, _build_rule_engines
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.vietnam_equity import VietnamEquityEngine
from backtest.models import Position

CODES = ["VIC.VN", "AAPL.US"]


def _composite(**overrides) -> CompositeEngine:
    config = {"initial_cash": 1_000_000_000, "codes": CODES, **overrides}
    return CompositeEngine(config, CODES)


def _hold(engine: CompositeEngine, *, open_bar: int, add_bar: int | None) -> None:
    """Give the composite a HOSE position with fill evidence."""
    for bar_idx, action in [(open_bar, "open"), (add_bar, "increase")]:
        if bar_idx is None:
            continue
        engine._bar_idx = bar_idx
        engine._record_fill(
            symbol="VIC.VN",
            timestamp=pd.Timestamp("2026-03-02") + pd.Timedelta(days=bar_idx),
            action=action,
            signed_quantity=1_000.0,
            execution_price=24_250.0,
            fee=0.0,
            margin=24_250_000.0,
            leverage=1.0,
            reason="signal",
        )
    engine.positions["VIC.VN"] = Position(
        symbol="VIC.VN",
        direction=1,
        entry_price=24_250.0,
        entry_time=pd.Timestamp("2026-03-02"),
        size=1_000.0 if add_bar is None else 2_000.0,
        leverage=1.0,
        entry_bar_idx=open_bar,
    )


class TestRuleEngineWiring:
    def test_a_vietnam_rule_engine_is_built(self):
        engines = _build_rule_engines({}, CODES)
        assert isinstance(engines["vietnam_equity"], VietnamEquityEngine)

    def test_hose_symbols_do_not_borrow_another_markets_rules(self):
        engine = _composite()
        assert isinstance(engine._rule_for("VIC.VN"), VietnamEquityEngine)
        assert isinstance(engine._rule_for("AAPL.US"), GlobalEquityEngine)

    def test_board_lot_still_applies_through_delegation(self):
        engine = _composite()
        engine._active_symbol = "VIC.VN"
        assert engine.round_size(1_234, 24_250.0) == 1_200


class TestSettlementInterception:
    """The hold is enforced against the composite's own state."""

    @pytest.mark.parametrize("bar_idx,allowed", [(0, False), (1, False), (2, True)])
    def test_hold_is_enforced_not_skipped(self, bar_idx: int, allowed: bool):
        engine = _composite(price_limit=0)
        _hold(engine, open_bar=0, add_bar=None)
        engine._bar_idx = bar_idx
        bar = pd.Series({"open": 24_250.0, "close": 24_300.0})
        assert engine.can_execute("VIC.VN", 0, bar) is allowed

    @pytest.mark.parametrize("bar_idx,allowed", [(2, False), (3, True)])
    def test_hold_runs_from_the_newest_lot(self, bar_idx: int, allowed: bool):
        engine = _composite(price_limit=0)
        _hold(engine, open_bar=0, add_bar=1)
        engine._bar_idx = bar_idx
        bar = pd.Series({"open": 24_250.0, "close": 24_300.0})
        assert engine.can_execute("VIC.VN", 0, bar) is allowed

    def test_the_us_leg_is_unaffected(self):
        engine = _composite(price_limit=0)
        _hold(engine, open_bar=0, add_bar=None)
        engine._bar_idx = 0
        bar = pd.Series({"open": 190.0, "close": 191.0})
        assert engine.can_execute("AAPL.US", 0, bar) is True


class TestBandInterception:
    def test_buy_at_the_ceiling_is_blocked(self):
        engine = _composite()
        # Reference 24,250 -> ceiling 25,900; an open at the ceiling has no ask.
        bar = pd.Series({"open": 25_900.0, "pre_close": 24_250.0})
        assert engine.can_execute("VIC.VN", 1, bar) is False

    def test_buy_inside_the_band_is_allowed(self):
        engine = _composite()
        bar = pd.Series({"open": 24_500.0, "pre_close": 24_250.0})
        assert engine.can_execute("VIC.VN", 1, bar) is True

    def test_short_is_still_refused(self):
        engine = _composite()
        bar = pd.Series({"open": 24_250.0, "pre_close": 24_250.0})
        assert engine.can_execute("VIC.VN", -1, bar) is False

    def test_reference_price_comes_from_the_composites_close_panel(self):
        """The band works off shared bar state, not just a ``pre_close`` column.

        A stateless sub-engine has no close panel, so this is the half of the
        band rule that silently vanished before the interception: with no
        ``pre_close`` on the bar there was no reference price and every fill
        passed.
        """
        engine = _composite()
        # Panel shaped as BaseEngine builds it: (n_dates, n_codes).
        engine._close_arr = np.array(
            [[24_250.0, 190.0], [25_900.0, 191.0]], dtype=float,
        )
        engine._code_to_col = {"VIC.VN": 0, "AAPL.US": 1}
        engine._bar_idx = 1  # reference price is row 0 -> 24,250

        at_ceiling = pd.Series({"open": 25_900.0})
        inside_band = pd.Series({"open": 24_500.0})
        assert engine.can_execute("VIC.VN", 1, at_ceiling) is False
        assert engine.can_execute("VIC.VN", 1, inside_band) is True

    def test_band_is_inactive_without_any_reference(self):
        engine = _composite()
        engine._bar_idx = 0  # no prior row, no pre_close column
        assert engine.can_execute("VIC.VN", 1, pd.Series({"open": 24_500.0})) is True


class TestMixedBookIsStillRefused:
    def test_a_vn_book_cannot_run_beside_another_currency(self):
        engine = _composite()
        with pytest.raises(ValueError, match="one settlement currency"):
            engine.run_backtest(
                {"initial_cash": 1_000_000_000, "codes": CODES},
                loader=None,
                signal_engine=None,
                run_dir=None,
            )
