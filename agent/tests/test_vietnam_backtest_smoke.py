"""End-to-end smoke test: backtest runs on Vietnamese (HOSE) symbols.

Drives ``VietnamEquityEngine`` through the real execution path so the market
rules are exercised as ``BaseEngine`` actually applies them, rather than
against hand-built state. All data is in-memory; no network access.

The settlement case here is the one unit tests cannot reach: it needs
``_execute_position_increase`` to run for real, because the defect it guards
lives in that method's interaction with the settlement clock — an increase
folds new shares into the open position while preserving its original
``entry_bar_idx``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.vietnam_equity import VietnamEquityEngine

CODE = "VIC.VN"

# Nine sessions rising 50 VND a bar: every move sits well inside the +/-7%
# band, so a band block cannot be mistaken for a settlement block.
_BASE = 24_250.0
_BARS = pd.DataFrame(
    {
        "open": [_BASE + 50 * i for i in range(9)],
        "high": [_BASE + 50 * i + 150 for i in range(9)],
        "low": [_BASE + 50 * i - 150 for i in range(9)],
        "close": [_BASE + 50 * i + 50 for i in range(9)],
        "volume": [1_000_000] * 9,
    },
    index=pd.bdate_range("2026-03-02", periods=9),
)


class _FakeLoader:
    def fetch(self, *args, **kwargs):
        return {CODE: _BARS.copy()}


class _WeightSignal:
    """Replay a fixed target-weight path, one weight per bar."""

    def __init__(self, weights: list[float]) -> None:
        self._weights = weights

    def generate(self, data_map):
        return {CODE: pd.Series(self._weights, index=data_map[CODE].index)}


def _run(weights: list[float], run_dir: Path) -> VietnamEquityEngine:
    config = {
        "codes": [CODE],
        "start_date": "2026-03-02",
        "end_date": "2026-03-20",
        "source": "auto",
        "initial_cash": 1_000_000_000,
        "slippage": 0.0,
        # Increases only occur under 'rebalance'; 'hold' never scales in.
        "position_adjustment": "rebalance",
    }
    engine = VietnamEquityEngine(config)
    engine.run_backtest(config, _FakeLoader(), _WeightSignal(weights), run_dir)
    return engine


def _fills(engine: VietnamEquityEngine) -> list[tuple[int, str]]:
    return [(f.bar_idx, f.action) for f in engine.fill_records]


def test_backtest_completes_on_hose_bars(tmp_path: Path) -> None:
    # Half weight: a fully invested target cannot fund its own commissions
    # once equity drifts, which is BaseEngine behaviour and not under test.
    engine = _run([0.5] * 9, tmp_path)
    assert engine.fill_records
    # Every fill lands on a whole board lot and on the tick grid.
    for fill in engine.fill_records:
        assert abs(fill.signed_quantity) % 100 == 0
        assert fill.execution_price % 10 == 0


def test_scaling_in_holds_the_whole_position_for_the_new_lot(tmp_path: Path) -> None:
    """Buy, add, then try to exit one session after the add.

    Weights execute a bar late, so this path is: open on bar 1, increase on
    bar 3, exit signal acting on bar 4. Bar 4 is T+3 for the first lot but only
    T+1 for the added one, so the sell must wait for bar 5.

    Reading the clock from ``Position.entry_bar_idx`` instead closes on bar 4 —
    selling shares that arrived one session earlier.
    """
    engine = _run([0.5, 0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], tmp_path)

    assert _fills(engine) == [(1, "open"), (3, "increase"), (5, "close")]


def test_no_partial_exit_slips_through_before_the_new_lot_settles(
    tmp_path: Path,
) -> None:
    """A reduction to a smaller non-zero weight is held on the same rule.

    The compressed position carries no lot identity, so a partial sell cannot
    be shown to consume settled shares only; it waits with the rest.
    """
    engine = _run([0.5, 0.5, 1.0, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25], tmp_path)

    reducing = [
        (idx, action)
        for idx, action in _fills(engine)
        if action in {"reduce", "partial_reduction", "close"}
    ]
    assert reducing, "expected the weight cut to reduce the position eventually"
    increase_bar = next(idx for idx, action in _fills(engine) if action == "increase")
    assert all(idx >= increase_bar + 2 for idx, _ in reducing)
