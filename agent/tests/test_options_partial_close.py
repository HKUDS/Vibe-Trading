"""Regression (#577): options close honors a partial-close quantity.

The options engine's ``close`` branch used to compute cash/PnL from the full
matched lot and remove the whole position, ignoring the leg's requested ``qty``.
A partial close therefore flattened the entire lot. These tests pin the new
behavior: an explicit ``qty`` closes only that many contracts and leaves the
remainder open; a close leg with no ``qty`` still closes the whole lot.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.options_portfolio import run_options_backtest

_DATES = pd.bdate_range("2025-01-01", periods=4)
_BARS = pd.DataFrame(
    {
        "open": [100.0, 101.0, 102.0, 103.0],
        "high": [101.0, 102.0, 103.0, 104.0],
        "low": [99.0, 100.0, 101.0, 102.0],
        "close": [100.5, 101.5, 102.5, 103.5],
        "volume": [1000, 1100, 1200, 1300],
    },
    index=_DATES,
)


class _FakeLoader:
    name = "yfinance"

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        return {"SPY": _BARS.copy()}


def _signal_engine(close_qty):
    """Build a signal engine that opens 10 contracts then closes ``close_qty``.

    ``close_qty=None`` omits the leg qty entirely (legacy full-close path).
    """
    close_leg = {"type": "call", "strike": 101.0, "expiry": "2025-03-21"}
    if close_qty is not None:
        close_leg["qty"] = close_qty

    class _Engine:
        def generate(self, data_map):  # noqa: ANN001
            return [
                {
                    "date": "2025-01-01",
                    "action": "open",
                    "underlying": "SPY",
                    "legs": [{"type": "call", "strike": 101.0, "expiry": "2025-03-21", "qty": 10}],
                },
                {
                    "date": "2025-01-03",
                    "action": "close",
                    "underlying": "SPY",
                    "legs": [close_leg],
                },
            ]

    return _Engine()


def _run(tmp_path: Path, close_qty):
    run_options_backtest(
        {
            "codes": ["SPY"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-06",
            "source": "yfinance",
            "engine": "options",
            "initial_cash": 100_000,
        },
        _FakeLoader(),
        _signal_engine(close_qty),
        tmp_path,
    )
    artifacts = tmp_path / "artifacts"
    trades = pd.read_csv(artifacts / "trades.csv")
    greeks = pd.read_csv(artifacts / "greeks.csv")
    return trades, greeks


def test_partial_close_closes_only_requested_qty(tmp_path: Path) -> None:
    trades, greeks = _run(tmp_path, close_qty=4)

    closes = trades[trades["side"] == "close"]
    assert len(closes) == 1
    # Only 4 of the 10 contracts closed — not the whole lot.
    assert closes.iloc[0]["qty"] == 4

    # 6 contracts remain open, so the final-day total delta stays non-zero.
    final_delta = float(greeks.iloc[-1]["delta"])
    assert abs(final_delta) > 1e-6


def test_full_close_without_qty_flattens_lot(tmp_path: Path) -> None:
    trades, greeks = _run(tmp_path, close_qty=None)

    closes = trades[trades["side"] == "close"]
    assert len(closes) == 1
    # Legacy behavior preserved: the whole 10-lot closes.
    assert closes.iloc[0]["qty"] == 10
    assert abs(float(greeks.iloc[-1]["delta"])) < 1e-9


def test_close_qty_exceeding_open_clamps_to_lot(tmp_path: Path) -> None:
    trades, greeks = _run(tmp_path, close_qty=25)

    closes = trades[trades["side"] == "close"]
    assert len(closes) == 1
    # Requested 25 but only 10 open — clamp, don't over-close.
    assert closes.iloc[0]["qty"] == 10
    assert abs(float(greeks.iloc[-1]["delta"])) < 1e-9
