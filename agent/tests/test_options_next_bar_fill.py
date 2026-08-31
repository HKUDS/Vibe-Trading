"""Regression (#1293): options signals fill on the next bar, and the HV
warm-up no longer leaks the first computed window into earlier bars.

A signal computed on T's close used to fill at a price built from T's own
close and IV, embedding the information it was computed from (about a full
day of underlying move times delta of phantom edge). Signals now fill on the
bar after the decision; ``same_day_fill: true`` restores the legacy fill for
reproduction. The HV warm-up fills with the configured default IV instead of
the 30th bar's volatility.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.options_portfolio import historical_volatility, run_options_backtest

_DATES = pd.bdate_range("2025-01-01", periods=5)
_BARS = pd.DataFrame(
    {
        "open": [100.0, 110.0, 120.0, 120.0, 120.0],
        "high": [101.0, 111.0, 121.0, 121.0, 121.0],
        "low": [99.0, 109.0, 119.0, 119.0, 119.0],
        "close": [100.5, 110.5, 120.5, 120.5, 120.5],
        "volume": [1000] * 5,
    },
    index=_DATES,
)


class _Loader:
    name = "yfinance"

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        return {"SPY": _BARS.copy()}


class _Engine:
    def generate(self, data_map):  # noqa: ANN001
        return [
            {
                "date": "2025-01-02",
                "action": "open",
                "underlying": "SPY",
                "legs": [{"type": "call", "strike": 110.0, "expiry": "2025-03-21", "qty": 1}],
            }
        ]


def _run(tmp_path: Path, options_config=None):
    config = {
        "codes": ["SPY"],
        "start_date": "2025-01-01",
        "end_date": "2025-01-07",
        "source": "yfinance",
        "engine": "options",
        "initial_cash": 100_000,
        "commission": 0.0,
        "options_config": options_config or {"risk_free_rate": 0.0, "contract_multiplier": 1.0},
    }
    run_options_backtest(config, _Loader(), _Engine(), tmp_path)
    return pd.read_csv(tmp_path / "artifacts" / "trades.csv")


def test_signal_fills_on_the_next_bar(tmp_path: Path) -> None:
    trades = _run(tmp_path)
    assert len(trades) == 1
    # Signal dated 2025-01-02 must fill on the next trading bar, 2025-01-03.
    assert trades.iloc[0]["timestamp"] == "2025-01-03"
    # And the fill price must be computed from the T+1 close (120.5), not the
    # signal date's close (110.5).
    from src.quantlib.options import bs_price

    expected = bs_price(120.5, 110.0, (pd.Timestamp("2025-03-21") - pd.Timestamp("2025-01-03")).days / 365.0, 0.0, 0.3, "call")
    assert trades.iloc[0]["price"] == round(expected, 4)


def test_same_day_fill_restores_legacy_timing(tmp_path: Path) -> None:
    trades = _run(tmp_path, options_config={
        "risk_free_rate": 0.0, "contract_multiplier": 1.0, "same_day_fill": True,
    })
    assert len(trades) == 1
    assert trades.iloc[0]["timestamp"] == "2025-01-02"


def test_hv_warmup_uses_default_iv_not_first_window() -> None:
    close = pd.Series([100.0 + i for i in range(40)])
    hv = historical_volatility(close, window=30, default_iv=0.25)
    # The first 30 bars have no full window of returns (the leading NaN
    # return eats one): they must read the default, not the volatility
    # computed over the first valid window.
    assert (hv.iloc[:30] == 0.25).all()
    # From the first full window on, real values take over.
    assert hv.iloc[30] != 0.25
