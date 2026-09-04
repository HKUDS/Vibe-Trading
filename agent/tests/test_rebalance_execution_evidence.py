"""Rebalance execution evidence must come from fills, not targets (#1275).

Before this fix, ``rebalance_count`` was derived from changes in
``target_positions``. A strategy with constant target weights and
``position_adjustment="rebalance"`` executes drift corrections on many bars
while reporting one (or zero) requested rebalance. The evidence counters must
count what the immutable fill records actually did.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.models import FillRecord
from backtest.rebalance_notes import (
    compute_rebalance_execution_evidence,
    compute_rebalance_notes,
)


class _Engine(BaseEngine):
    def can_execute(self, symbol, direction, bar):
        return True

    def round_size(self, raw_size, price):
        return float(int(raw_size))

    def calc_commission(self, size, price, direction, is_open):
        return 0.0

    def apply_slippage(self, price, direction):
        return price * (1 + 0.0005 * direction)


def _fill(symbol: str, bar_idx: int, margin: float, reason: str = "target_rebalance"):
    return FillRecord(
        symbol=symbol,
        timestamp=pd.Timestamp("2026-01-05") + pd.offsets.Day(bar_idx),
        bar_idx=bar_idx,
        action="increase",
        signed_quantity=10.0,
        notional=1000.0,
        execution_price=100.0,
        fee=0.0,
        margin=margin,
        reason=reason,
    )


def test_execution_evidence_counts_fills_and_distinct_bars() -> None:
    """Three target-rebalance fills on two bars, one signal fill ignored."""
    equity = pd.Series(
        [100_000.0] * 4, index=pd.bdate_range("2026-01-05", periods=4)
    )
    fills = [
        _fill("A", 1, 5_000.0),
        _fill("A", 2, 5_000.0),
        _fill("B", 2, 5_000.0),
        _fill("C", 3, 5_000.0, reason="signal"),
    ]
    evidence = compute_rebalance_execution_evidence(fills, equity)

    assert evidence["rebalance_executed_fills"] == 3
    assert evidence["rebalance_executed_bars"] == 2
    # One-sided traded margin over 2 * equity per bar, summed.
    assert evidence["rebalance_realized_turnover"] == pytest.approx(
        3 * 5_000.0 / (2 * 100_000.0)
    )


def test_execution_evidence_is_zero_without_fills() -> None:
    """A run that never traded a target change reports zeros, not NaNs."""
    equity = pd.Series([100_000.0], index=[pd.Timestamp("2026-01-05")])
    evidence = compute_rebalance_execution_evidence([], equity)

    assert evidence == {
        "rebalance_executed_bars": 0,
        "rebalance_executed_fills": 0,
        "rebalance_realized_turnover": 0.0,
    }


def test_constant_target_rebalance_runs_execute_many_bars_but_request_one_change() -> None:
    """Issue #1275 reproduction: one requested change, many executed fills.

    A constant 40% target with rising prices makes the held weight drift
    above the target on every bar; ``position_adjustment="rebalance"`` re-pins
    the book each time. The requested count stays the number of target changes
    the strategy asked for while the executed counts follow the fills.
    """
    periods = 6
    dates = pd.bdate_range("2026-01-05", periods=periods)
    prices = [100.0 * (1.01**i) for i in range(periods)]
    bars = pd.DataFrame({"open": prices, "close": prices}, index=dates)
    close_df = pd.DataFrame({"A": bars["close"]}, index=dates)
    targets = pd.DataFrame({"A": [0.0, 0.4, 0.4, 0.4, 0.4, 0.4]}, index=dates)
    engine = _Engine({"initial_cash": 100_000.0, "position_adjustment": "rebalance"})

    engine._execute_bars(dates, {"A": bars}, close_df, targets, ["A"])

    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots], index=dates
    )
    requested = compute_rebalance_notes(targets)["summary"]
    evidence = compute_rebalance_execution_evidence(engine.fill_records, equity)

    assert requested["target_change_count"] == 1
    assert evidence["rebalance_executed_fills"] > 1  # entry plus drift corrections
    assert evidence["rebalance_executed_bars"] > 1
    assert evidence["rebalance_realized_turnover"] > 0.0
    # Provenance taxonomy: direction-flip entry stays a "signal" event, the
    # same-direction resize fills carry "target_rebalance" and are what the
    # executed counts report. The evidence counts must exactly match the
    # engine's own tag, independently recomputed from fill_records.
    fills = engine.fill_records
    assert fills[0].reason == "signal"  # entry 0 -> 0.4 is a flip
    assert fills[-1].reason == "end_of_backtest"  # terminal liquidation, not a rebalance
    assert {f.reason for f in fills[1:-1]} == {"target_rebalance"}  # resizes
    resizes = [f for f in fills if f.reason == "target_rebalance"]
    assert evidence["rebalance_executed_fills"] == len(resizes)
    assert evidence["rebalance_executed_bars"] == len({f.bar_idx for f in resizes})


class _StubLoader:
    name = "local"

    def __init__(self, periods: int = 8):
        self.periods = periods

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        dates = pd.bdate_range("2026-01-05", periods=self.periods)
        prices = [100.0 * (1.01**i) for i in range(self.periods)]
        return {
            code: pd.DataFrame(
                {"open": prices, "close": prices, "high": prices, "low": prices},
                index=dates,
            )
            for code in codes
        }


class _StubSignal:
    """Constant 40% target after one entry change."""

    def generate(self, data_map):
        dates = next(iter(data_map.values())).index
        weights = [0.0 if i < 2 else 0.4 for i in range(len(dates))]
        return {"A": pd.Series(weights, index=dates)}


def test_run_pipeline_injects_execution_metrics_and_artifacts(tmp_path) -> None:
    """The run() wiring: requested and executed fields reach m, notes and card."""
    config = {
        "codes": ["A"],
        "start_date": "2026-01-05",
        "end_date": "2026-01-16",
        "initial_cash": 100_000.0,
        "position_adjustment": "rebalance",
    }
    engine = _Engine(config)

    metrics = engine.run_backtest(config, _StubLoader(), _StubSignal(), tmp_path, bars_per_year=252)

    assert metrics["target_change_count"] == 1
    assert metrics["rebalance_executed_fills"] > 1
    assert metrics["rebalance_executed_bars"] > 1
    assert metrics["rebalance_realized_turnover"] > 0.0
    assert "rebalance_count" not in metrics

    notes = json.loads(
        (tmp_path / "artifacts" / "rebalance_notes.json").read_text(encoding="utf-8")
    )
    summary = notes["summary"]
    assert summary["target_change_count"] == metrics["target_change_count"]
    assert summary["rebalance_executed_fills"] == metrics["rebalance_executed_fills"]
    assert summary["rebalance_executed_bars"] == metrics["rebalance_executed_bars"]
    assert summary["rebalance_realized_turnover"] == metrics["rebalance_realized_turnover"]

    card = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))
    assert card["metrics"]["rebalance_executed_fills"] == metrics["rebalance_executed_fills"]
    assert card["metrics"]["target_change_count"] == metrics["target_change_count"]
    assert "rebalance_count" not in card["metrics"]

    md = (tmp_path / "artifacts" / "rebalance_notes.md").read_text(encoding="utf-8")
    assert "target changes (requested): 1" in md
    assert f"rebalance fills (executed): {metrics['rebalance_executed_fills']}" in md


def test_run_pipeline_without_target_changes_reports_zeros(tmp_path) -> None:
    """A run that never moved a target reports zeros, not missing fields."""
    config = {
        "codes": ["A"],
        "start_date": "2026-01-05",
        "end_date": "2026-01-09",
        "initial_cash": 100_000.0,
        "position_adjustment": "rebalance",
    }
    engine = _Engine(config)

    metrics = engine.run_backtest(
        config, _StubLoader(periods=3), _StubSignal(), tmp_path, bars_per_year=252
    )

    assert metrics["target_change_count"] == 0
    assert metrics["rebalance_executed_fills"] == 0
    assert metrics["rebalance_executed_bars"] == 0
    assert metrics["rebalance_realized_turnover"] == 0.0

    md = (tmp_path / "artifacts" / "rebalance_notes.md").read_text(encoding="utf-8")
    assert "target changes (requested): 0" in md
    assert "rebalance fills (executed): 0" in md
