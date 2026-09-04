"""Regression: options signals must fill on the next bar, not the signal date.

The options engine priced and filled a signal dated T with T's own close and
IV, so a signal computed on T's close embeded the information it was computed
from -- a full day of underlying move times delta on every options backtest.
The equity engines in the same framework execute the next bar; this pins the
options engine to the same convention. ``same_day_fill: True`` restores the
legacy same-date fill for strategies that want it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.options_portfolio import bs_price, run_options_backtest

_DATES = pd.bdate_range("2025-01-01", periods=4)
_CLOSES = [100.0, 110.0, 90.0, 120.0]
_BARS = pd.DataFrame(
    {
        "open": _CLOSES,
        "high": [c + 1.0 for c in _CLOSES],
        "low": [c - 1.0 for c in _CLOSES],
        "close": _CLOSES,
        "volume": [1000, 1000, 1000, 1000],
    },
    index=_DATES,
)

_EXPIRY = "2025-02-21"
_STRIKE = 100.0
_QTY = 10


class _FlatLoader:
    name = "yfinance"

    def fetch(self, codes, start_date, end_date):  # noqa: ANN001
        return {"SPY": _BARS.copy()}


def _signal(date: str, expiry: str = _EXPIRY):
    class _Engine:
        def generate(self, data_map):  # noqa: ANN001
            return [
                {
                    "date": date,
                    "action": "open",
                    "underlying": "SPY",
                    "legs": [{"type": "call", "strike": _STRIKE, "expiry": expiry, "qty": _QTY}],
                }
            ]

    return _Engine()


def _fill_price(day: pd.Timestamp, iv: float) -> float:
    t = max((pd.Timestamp(_EXPIRY) - day).days / 365.0, 0.001)
    return bs_price(_BARS.at[day, "close"], _STRIKE, t, 0.0, iv, "call")


def _run(
    tmp_path: Path,
    *,
    date: str,
    same_day: bool = False,
    warmup_bars: int = 0,
    expiry: str = _EXPIRY,
):
    run_options_backtest(
        {
            "codes": ["SPY"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-07",
            "source": "yfinance",
            "engine": "options",
            "initial_cash": 100_000.0,
            "commission": 0.0,
            **({"warmup_bars": warmup_bars} if warmup_bars else {}),
            "options_config": {
                "risk_free_rate": 0.0,
                "contract_multiplier": 1.0,
                **({"same_day_fill": True} if same_day else {}),
            },
        },
        _FlatLoader(),
        _signal(date, expiry=expiry),
        tmp_path,
    )
    return pd.read_csv(tmp_path / "artifacts" / "trades.csv")


def test_signal_dated_t_fills_on_the_next_bar(tmp_path: Path) -> None:
    trades = _run(tmp_path, date="2025-01-02")

    assert len(trades) == 1
    assert trades.iloc[0]["timestamp"] == "2025-01-03"
    assert trades.iloc[0]["price"] == pytest.approx(
        _fill_price(pd.Timestamp("2025-01-03"), 0.3), abs=1e-4
    )


def test_fill_price_uses_next_bar_spot_not_signal_date_spot(tmp_path: Path) -> None:
    """Pricing at 90 (2025-01-03) with an expiry 49 days out differs from 110."""
    trades = _run(tmp_path, date="2025-01-02")

    price_on_02 = bs_price(110.0, _STRIKE, max((pd.Timestamp(_EXPIRY) - pd.Timestamp("2025-01-02")).days / 365.0, 0.001), 0.0, 0.3, "call")
    assert trades.iloc[0]["price"] != pytest.approx(price_on_02)


def test_same_day_fill_flag_preserves_legacy_behavior(tmp_path: Path) -> None:
    trades = _run(tmp_path, date="2025-01-02", same_day=True)

    assert len(trades) == 1
    assert trades.iloc[0]["timestamp"] == "2025-01-02"
    assert trades.iloc[0]["price"] == pytest.approx(
        _fill_price(pd.Timestamp("2025-01-02"), 0.3), abs=1e-4
    )


def test_signal_dated_before_first_bar_never_executes(tmp_path: Path) -> None:
    trades = _run(tmp_path, date="2024-12-31")
    assert len(trades) == 0


def test_signal_on_last_bar_has_no_next_bar_to_fill(tmp_path: Path) -> None:
    trades = _run(tmp_path, date="2025-01-06")
    assert len(trades) == 0


def test_last_warmup_bar_signal_fills_on_first_eval_bar(tmp_path: Path) -> None:
    """Equity parity: the warm-up cut applies after the signal shift, so a
    signal dated the last warm-up bar fills on the first evaluated bar."""
    trades = _run(tmp_path, date="2025-01-01", warmup_bars=1)

    assert len(trades) == 1
    assert trades.iloc[0]["timestamp"] == "2025-01-02"


def test_fill_on_expiry_bar_settles_same_bar_never_a_bar_late(tmp_path: Path) -> None:
    """Signal dated 2025-01-02 fills 2025-01-03 == expiry: settlement must
    happen on that bar (entry T floored at 0.001, intrinsic at expiry spot),
    not on the next bar at the next bar's spot."""
    trades = _run(tmp_path, date="2025-01-02", expiry="2025-01-03")

    assert list(trades["timestamp"]) == ["2025-01-03", "2025-01-03"]
    assert trades.iloc[0]["side"] == "buy"
    assert trades.iloc[1]["side"] == "expire"  # K=100 vs close 90: OTM
    assert trades.iloc[1]["price"] == pytest.approx(0.0)
