"""Tests for Task 9 Taiwan options pipeline on existing engine="options" flow."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backtest.engines import options_portfolio


def _txf_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=4)
    return pd.DataFrame(
        {
            "open": [22000.0, 22100.0, 22200.0, 22300.0],
            "high": [22100.0, 22200.0, 22300.0, 22400.0],
            "low": [21900.0, 22000.0, 22100.0, 22200.0],
            "close": [22050.0, 22150.0, 22250.0, 22350.0],
            "volume": [1000, 1100, 1200, 1300],
        },
        index=dates,
    )


class _FakeLoader:
    name = "finmind"

    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars

    def fetch(self, codes, start_date, end_date):
        del start_date
        del end_date
        return {code: self._bars.copy() for code in codes}


class _OpenCloseSignalEngine:
    def generate(self, data_map):
        del data_map
        return [
            {
                "date": "2025-01-01",
                "action": "open",
                "underlying": "TXF.TAIFEX",
                "legs": [{"type": "call", "strike": 22100.0, "expiry": "2025-03-19", "qty": 1}],
            },
            {
                "date": "2025-01-03",
                "action": "close",
                "underlying": "TXF.TAIFEX",
                "legs": [{"type": "call", "strike": 22100.0, "expiry": "2025-03-19", "qty": 1}],
            },
        ]


class _OpenOnlySignalEngine:
    def generate(self, data_map):
        del data_map
        return [
            {
                "date": "2025-01-01",
                "action": "open",
                "underlying": "TXF.TAIFEX",
                "legs": [{"type": "call", "strike": 22000.0, "expiry": "2025-03-19", "qty": 1}],
            },
        ]


def _run_taiwan_options_backtest(tmp_path: Path, options_config: dict, engine) -> dict:
    return options_portfolio.run_options_backtest(
        {
            "codes": ["TXF.TAIFEX"],
            "start_date": "2025-01-01",
            "end_date": "2025-01-06",
            "source": "finmind",
            "engine": "options",
            "initial_cash": 100_000,
            "options_config": options_config,
        },
        _FakeLoader(_txf_bars()),
        engine,
        tmp_path,
    )


def test_txf_underlying_and_txo_style_legs_write_expected_artifacts(tmp_path: Path) -> None:
    metrics = _run_taiwan_options_backtest(
        tmp_path,
        {
            "contract_multiplier": 50,
            "exercise_style": "european",
            "risk_free_rate": 0.01,
        },
        _OpenCloseSignalEngine(),
    )

    artifacts = tmp_path / "artifacts"
    trades = pd.read_csv(artifacts / "trades.csv")
    run_card = json.loads((tmp_path / "run_card.json").read_text(encoding="utf-8"))

    assert metrics["trade_count"] == 2
    assert list(trades["code"]) == ["TXF.TAIFEX", "TXF.TAIFEX"]
    assert list(trades["option_type"]) == ["call", "call"]
    assert list(trades["side"]) == ["buy", "close"]
    assert trades["strike"].tolist() == [22100.0, 22100.0]
    assert {path.name for path in artifacts.iterdir()} >= {
        "equity.csv",
        "trades.csv",
        "greeks.csv",
        "metrics.csv",
        "ohlcv_TXF.TAIFEX.csv",
    }
    assert run_card["backtest"]["engine"] == "options"
    assert run_card["data_sources"] == ["finmind"]


def test_contract_multiplier_50_changes_trade_pnl_scale(tmp_path: Path, monkeypatch) -> None:
    def fake_bs_price(spot, strike, T, r, sigma, option_type="call") -> float:
        del strike
        del T
        del r
        del sigma
        del option_type
        return spot / 1000.0

    monkeypatch.setattr(options_portfolio, "bs_price", fake_bs_price)

    run_one = tmp_path / "multiplier_1"
    run_fifty = tmp_path / "multiplier_50"
    _run_taiwan_options_backtest(
        run_one,
        {"contract_multiplier": 1, "exercise_style": "european", "risk_free_rate": 0.01},
        _OpenCloseSignalEngine(),
    )
    _run_taiwan_options_backtest(
        run_fifty,
        {"contract_multiplier": 50, "exercise_style": "european", "risk_free_rate": 0.01},
        _OpenCloseSignalEngine(),
    )

    pnl_one = pd.read_csv(run_one / "artifacts" / "trades.csv").query("side == 'close'")["pnl"].iloc[0]
    pnl_fifty = pd.read_csv(run_fifty / "artifacts" / "trades.csv").query("side == 'close'")["pnl"].iloc[0]

    assert pnl_fifty == pnl_one * 50


def test_exercise_style_european_prevents_american_early_exercise(tmp_path: Path, monkeypatch) -> None:
    def fake_bs_price(spot, strike, T, r, sigma, option_type="call") -> float:
        del spot
        del strike
        del T
        del r
        del sigma
        del option_type
        return 1.0

    monkeypatch.setattr(options_portfolio, "bs_price", fake_bs_price)

    european_dir = tmp_path / "european"
    american_dir = tmp_path / "american"
    _run_taiwan_options_backtest(
        european_dir,
        {"contract_multiplier": 50, "exercise_style": "european", "risk_free_rate": 0.01},
        _OpenOnlySignalEngine(),
    )
    _run_taiwan_options_backtest(
        american_dir,
        {"contract_multiplier": 50, "exercise_style": "american", "risk_free_rate": 0.01},
        _OpenOnlySignalEngine(),
    )

    european_trades = pd.read_csv(european_dir / "artifacts" / "trades.csv")
    american_trades = pd.read_csv(american_dir / "artifacts" / "trades.csv")

    assert "early_exercise" not in set(european_trades["side"])
    assert "early_exercise" in set(american_trades["side"])
