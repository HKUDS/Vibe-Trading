"""End-to-end smoke test: backtest runs on Indian (NSE) symbols.

Drives ``IndiaEquityEngine`` so strategies can run on NSE/BSE data with the
India cost stack. This test feeds NSE bars through a fake loader + trivial long
signal and asserts:

  1. The backtest completes and emits metrics + a run card.
  2. India trading costs are actually applied — the identical strategy on the
     zero-commission US engine ends with strictly more cash than on the India
     engine.

All data is in-memory; no network access.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.india_equity import IndiaEquityEngine


def _nse_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-04-01", periods=5)
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 106.0, 108.0],
            "high": [101.0, 103.0, 105.0, 107.0, 109.0],
            "low": [99.0, 101.0, 103.0, 105.0, 107.0],
            "close": [102.0, 104.0, 106.0, 108.0, 110.0],
            "volume": [10_000, 10_000, 10_000, 10_000, 10_000],
        },
        index=dates,
    )


class _FakeLoader:
    def __init__(self, code: str, bars: pd.DataFrame) -> None:
        self._code = code
        self._bars = bars

    def fetch(self, *args, **kwargs):
        return {self._code: self._bars.copy()}


class _LongSignal:
    """Allocate fully long to the single instrument every bar."""

    def __init__(self, code: str) -> None:
        self._code = code

    def generate(self, data_map):
        idx = data_map[self._code].index
        return {self._code: pd.Series(1.0, index=idx)}


def _run(engine, code: str, run_dir: Path) -> dict:
    bars = _nse_bars()
    return engine.run_backtest(
        {
            "codes": [code],
            "start_date": "2024-04-01",
            "end_date": "2024-04-30",
            "source": "yahoo",
            "initial_cash": 1_000_000,
        },
        _FakeLoader(code, bars),
        _LongSignal(code),
        run_dir,
    )


def test_india_backtest_completes_and_emits_run_card(tmp_path: Path) -> None:
    engine = IndiaEquityEngine({"initial_cash": 1_000_000})
    metrics = _run(engine, "RELIANCE.NS", tmp_path)

    assert metrics  # non-empty metrics dict
    assert (tmp_path / "run_card.json").exists()
    # The equity curve must have advanced through the bars.
    assert metrics.get("final_value") is not None
    assert metrics["trade_count"] >= 1


def test_india_costs_are_applied_vs_zero_commission_us(tmp_path: Path) -> None:
    """Identical data + signal: the India engine pays costs the US engine does not."""
    in_engine = IndiaEquityEngine({"initial_cash": 1_000_000})
    us_engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="us")

    in_metrics = _run(in_engine, "RELIANCE.NS", tmp_path / "in")
    us_metrics = _run(us_engine, "AAPL.US", tmp_path / "us")

    # Same price path; the only difference is India's cost stack, so India must
    # end strictly poorer than the zero-commission US run.
    assert in_metrics["final_value"] < us_metrics["final_value"]
