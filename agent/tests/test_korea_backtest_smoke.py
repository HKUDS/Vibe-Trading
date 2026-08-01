"""End-to-end smoke test: backtest runs on Korean (KRX) symbols.

Drives ``KoreaEquityEngine`` so strategies can run on KOSPI/KOSDAQ data with
the Korea cost stack. This test feeds KRX-shaped bars through a fake loader +
trivial long signal and asserts:

  1. The backtest completes and emits metrics + a run card.
  2. Korea trading costs are applied **exactly** — every won of the recorded
     commission is reproduced from ``kr_brokerage`` / ``kr_tax_sell``, and the
     final equity satisfies the cash identity. Slippage is set to zero on both
     engines so a cost-stack regression cannot hide behind a slippage
     difference (``GlobalEquityEngine`` reads ``slippage_us``, not
     ``slippage``, so the two engines do NOT share a default).

All data is in-memory; no network access (and no pykrx dependency).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.korea_equity import KoreaEquityEngine, krx_round_down


def _krx_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 106.0, 108.0],
            "high": [101.0, 103.0, 105.0, 107.0, 109.0],
            "low": [99.0, 101.0, 103.0, 105.0, 107.0],
            "close": [102.0, 104.0, 106.0, 108.0, 110.0],
            "volume": [10_000, 10_000, 10_000, 10_000, 10_000],
        },
        index=pd.bdate_range("2024-04-01", periods=5),
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


def _run(engine, code: str, run_dir: Path, **config_overrides) -> dict:
    config = {
        "codes": [code],
        "start_date": "2024-04-01",
        "end_date": "2024-04-30",
        "source": "auto",
        "initial_cash": 1_000_000,
    }
    config.update(config_overrides)
    return engine.run_backtest(
        config, _FakeLoader(code, _krx_bars()), _LongSignal(code), run_dir
    )


def test_korea_backtest_completes_and_emits_run_card(tmp_path: Path) -> None:
    engine = KoreaEquityEngine({"initial_cash": 1_000_000})
    metrics = _run(engine, "005930.KS", tmp_path)

    assert metrics  # non-empty metrics dict
    assert (tmp_path / "run_card.json").exists()
    assert metrics.get("final_value") is not None
    assert metrics["trade_count"] >= 1


def test_korea_costs_are_exact(tmp_path: Path) -> None:
    """Pin commission + transaction tax to the won, not just 'costs happened'."""
    engine = KoreaEquityEngine({"initial_cash": 1_000_000, "slippage": 0})
    metrics = _run(engine, "005930.KS", tmp_path, slippage=0)

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.size > 0
    # Zero slippage must leave both fills on the KRX tick grid untouched.
    assert trade.entry_price == krx_round_down(trade.entry_price)
    assert trade.exit_price == krx_round_down(trade.exit_price)

    entry_comm = trade.size * trade.entry_price * engine.kr_brokerage
    exit_comm = trade.size * trade.exit_price * (
        engine.kr_brokerage + engine.kr_tax_sell
    )
    # Buy pays brokerage only; sell pays brokerage + the sell-side tax.
    assert trade.commission == pytest.approx(entry_comm + exit_comm, abs=1e-6)
    assert metrics["final_value"] == pytest.approx(
        1_000_000 + trade.size * (trade.exit_price - trade.entry_price)
        - entry_comm - exit_comm,
        abs=1e-6,
    )


def test_zero_rates_leave_a_costless_run(tmp_path: Path) -> None:
    """With both rates zeroed the same run must record no cost at all."""
    engine = KoreaEquityEngine(
        {"initial_cash": 1_000_000, "slippage": 0, "kr_brokerage": 0, "kr_tax_sell": 0}
    )
    metrics = _run(
        engine, "005930.KS", tmp_path,
        slippage=0, kr_brokerage=0, kr_tax_sell=0,
    )

    trade = engine.trades[0]
    assert trade.commission == pytest.approx(0.0, abs=1e-9)
    assert metrics["final_value"] == pytest.approx(
        1_000_000 + trade.size * (trade.exit_price - trade.entry_price), abs=1e-6
    )


def test_korea_costs_are_applied_vs_zero_commission_us(tmp_path: Path) -> None:
    """Identical data, signal AND slippage: only Korea's cost stack differs."""
    kr_engine = KoreaEquityEngine({"initial_cash": 1_000_000, "slippage": 0})
    us_engine = GlobalEquityEngine(
        {"initial_cash": 1_000_000, "slippage_us": 0}, market="us"
    )

    kr_metrics = _run(kr_engine, "005930.KS", tmp_path / "kr", slippage=0)
    us_metrics = _run(us_engine, "AAPL.US", tmp_path / "us", slippage_us=0)

    # Same fills on both sides, so the gap can only come from Korea's costs.
    assert kr_engine.trades[0].entry_price == pytest.approx(
        us_engine.trades[0].entry_price
    )
    assert kr_engine.trades[0].exit_price == pytest.approx(
        us_engine.trades[0].exit_price
    )
    assert us_engine.trades[0].commission == pytest.approx(0.0, abs=1e-9)
    assert kr_engine.trades[0].commission > 0
    assert kr_metrics["final_value"] < us_metrics["final_value"]
