"""Regression for options one-bar fill delay and HV warm-up lookahead.

Signals dated T must fill at T+1's bar (next-bar semantics, matching equity
engines). HV warm-up bars must use the configured default IV, not the first
computed 30-day window.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.options_portfolio import (
    historical_volatility,
    run_options_backtest,
)

_DATES = pd.bdate_range("2025-01-01", periods=5)
_BARS = pd.DataFrame(
    {
        "open": [100.0, 110.0, 120.0, 130.0, 140.0],
        "high": [101.0, 111.0, 121.0, 131.0, 141.0],
        "low": [99.0, 109.0, 119.0, 129.0, 139.0],
        "close": [100.5, 110.5, 120.5, 130.5, 140.5],
        "volume": [1000] * 5,
    },
    index=_DATES,
)


class _Loader:
    name = "yfinance"

    def fetch(
        self, codes, start_date, end_date, fields=None, interval=None
    ):  # noqa: ANN001
        return {"SPY": _BARS.copy()}


class _EngineT:
    def generate(self, data_map):  # noqa: ANN001
        return [
            {
                "date": "2025-01-02",
                "action": "open",
                "underlying": "SPY",
                "legs": [
                    {"type": "call", "strike": 110.0, "expiry": "2025-03-21", "qty": 1}
                ],
            }
        ]


def test_signal_fills_at_next_bar(tmp_path: Path) -> None:
    run_options_backtest(
        {
            "codes": ["SPY"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-06",
            "source": "yfinance",
            "engine": "options",
            "initial_cash": 100_000,
            "commission": 0.0,
            "options_config": {"risk_free_rate": 0.0, "contract_multiplier": 1.0},
        },
        _Loader(),
        _EngineT(),
        tmp_path,
    )
    trades = pd.read_csv(tmp_path / "artifacts" / "trades.csv")
    assert len(trades) == 1
    # Signal dated 2025-01-02 must fill on the next trading bar 2025-01-03
    assert trades.iloc[0]["timestamp"] == "2025-01-03"
    # Price must reflect T+1 spot (120.5), not T spot (110.5)
    from src.quantlib.options import bs_price

    price_t1 = bs_price(
        120.5,
        110.0,
        (pd.Timestamp("2025-03-21") - pd.Timestamp("2025-01-03")).days / 365.0,
        0.0,
        0.3,
        "call",
    )
    assert float(trades.iloc[0]["price"]) == round(price_t1, 4)
    # Equity shift: no position on signal bar, position appears next bar
    equity = pd.read_csv(tmp_path / "artifacts" / "equity.csv")
    # equity[1] corresponds to 2025-01-02 (signal bar) — should be near initial cash
    assert float(equity.iloc[1]["positions_value"]) == 0.0


def test_same_day_flag_restores_legacy_fill(tmp_path: Path) -> None:
    run_options_backtest(
        {
            "codes": ["SPY"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-06",
            "source": "yfinance",
            "engine": "options",
            "initial_cash": 100_000,
            "commission": 0.0,
            "options_config": {
                "risk_free_rate": 0.0,
                "contract_multiplier": 1.0,
                "same_day_fill": True,
            },
        },
        _Loader(),
        _EngineT(),
        tmp_path,
    )
    trades = pd.read_csv(tmp_path / "artifacts" / "trades.csv")
    assert trades.iloc[0]["timestamp"] == "2025-01-02"


def test_hv_warmup_uses_default_iv() -> None:
    # Vol regime change after window: first 25 flat, then volatile.
    vals = [100.0] * 25 + [
        100,
        102,
        98,
        103,
        97,
        104,
        96,
        105,
        95,
        106,
        94,
        107,
        93,
        108,
        92,
    ]
    close = pd.Series(vals, index=pd.bdate_range("2025-01-01", periods=len(vals)))
    hv = historical_volatility(close, window=30)
    # First 29 bars must be default, not leaked future window
    assert all(v == 0.3 for v in hv.iloc[:29])
    assert hv.iloc[29] == 0.3
    assert hv.iloc[30] != 0.3  # first computed window
    # Custom default
    hv2 = historical_volatility(close, window=30, default_iv=0.25)
    assert hv2.iloc[0] == 0.25
