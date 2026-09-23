"""End-to-end smoke test: backtest runs on Kenyan (NSE) symbols.

Drives ``KenyaEquityEngine`` through the real execution path, so the T+3 hold,
the tick grid and the cost stack are exercised as ``BaseEngine`` applies them.
All data is in-memory; no network access.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.kenya_equity import KenyaEquityEngine, nse_tick_size

CODE = "SCOM.NR"

# Ten sessions rising five cents a bar, shaped like the NSE daily price list:
# open == close == VWAP, pre_close the prior VWAP. Every move sits far inside
# the +/-10% band, so a band block cannot be mistaken for a settlement block.
_VWAP = [36.00 + 0.05 * i for i in range(10)]
_BARS = pd.DataFrame(
    {
        "open": _VWAP,
        "high": [v + 0.20 for v in _VWAP],
        "low": [v - 0.20 for v in _VWAP],
        "close": _VWAP,
        "volume": [5_000_000.0] * 10,
        "pre_close": [35.95] + _VWAP[:-1],
    },
    index=pd.bdate_range("2026-09-07", periods=10, name="trade_date"),
)


class _FakeLoader:
    def fetch(self, *args, **kwargs):
        return {CODE: _BARS.copy()}


class _WeightSignal:
    def __init__(self, weights: list[float]) -> None:
        self._weights = weights

    def generate(self, data_map):
        return {CODE: pd.Series(self._weights, index=data_map[CODE].index)}


def _run(weights: list[float], run_dir: Path, **overrides) -> KenyaEquityEngine:
    config = {
        "codes": [CODE],
        "start_date": "2026-09-07",
        "end_date": "2026-09-18",
        "source": "auto",
        "initial_cash": 10_000_000,
        "slippage": 0.0,
        "position_adjustment": "rebalance",
        **overrides,
    }
    engine = KenyaEquityEngine(config)
    engine.run_backtest(config, _FakeLoader(), _WeightSignal(weights), run_dir)
    return engine


def _fills(engine: KenyaEquityEngine) -> list[tuple[int, str]]:
    return [(f.bar_idx, f.action) for f in engine.fill_records]


def test_backtest_completes_on_nse_bars(tmp_path: Path) -> None:
    engine = _run([0.5] * 10, tmp_path)
    assert engine.fill_records
    for fill in engine.fill_records:
        price = fill.execution_price
        tick = nse_tick_size(price)
        assert abs(round(price / tick) * tick - price) < 1e-9


def test_exit_waits_for_t_plus_3(tmp_path: Path) -> None:
    """Enter, then signal an immediate exit.

    Weights act a bar late: the open fills on bar 1 and the exit signal is
    live from bar 2, but the shares only settle on bar 4 (T+3).
    """
    engine = _run([0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], tmp_path)
    assert _fills(engine) == [(1, "open"), (4, "close")]


def test_pre_2025_lot_regime(tmp_path: Path) -> None:
    engine = _run([0.5] * 10, tmp_path, ke_lot_size=100)
    for fill in engine.fill_records:
        assert abs(fill.signed_quantity) % 100 == 0
