"""Closed-trade identity survives the production CSV round trip."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest.engines.china_a import ChinaAEngine
from backtest.models import TradeRecord
from backtest.validation import _load_trades, monte_carlo_test
from src.strategy_discovery.run_artifacts import read_trade_activity


@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("same_day", [False, True])
@pytest.mark.parametrize("middle_pnl", [0.0, 0.00001, 1.0])
def test_exported_trades_keep_zero_pnl_exits(
    tmp_path: Path, direction: int, same_day: bool, middle_pnl: float
) -> None:
    engine = ChinaAEngine({"initial_cash": 1000.0})
    dates = pd.date_range("2026-01-01", periods=6)
    engine.trades = [
        TradeRecord(
            symbol="TEST",
            direction=direction,
            entry_price=100.0,
            exit_price=100.0 + direction * pnl,
            entry_time=dates[2 * i],
            exit_time=dates[2 * i if same_day else 2 * i + 1],
            size=1.0,
            leverage=1.0,
            pnl=pnl,
            pnl_pct=pnl,
            exit_reason="signal",
            holding_bars=0 if same_day else 1,
            commission=0.0,
        )
        for i, pnl in enumerate([10.0, middle_pnl, -5.0])
    ]
    equity = pd.Series(1000.0, index=dates)
    engine._write_artifacts(
        tmp_path,
        {},
        dates,
        equity,
        equity,
        pd.Series(0.0, index=dates),
        pd.DataFrame(index=dates),
        {},
        ["TEST"],
    )

    restored = _load_trades(tmp_path)
    # The artifact already rounds cash PnL to four decimals; preserve that
    # contract while retaining even trades rounded to zero.
    assert [t.pnl for t in restored] == [10.0, round(middle_pnl, 4), -5.0]
    assert [t.direction for t in restored] == [direction] * 3
    assert read_trade_activity(tmp_path / "artifacts/trades.csv") == (
        [t.exit_time.date() for t in engine.trades],
        1,
    )
    frame = pd.read_csv(tmp_path / "artifacts/trades.csv")
    assert frame["event"].tolist() == ["entry", "exit"] * 3
    if middle_pnl != 0.00001:
        assert monte_carlo_test(restored, 1000.0, n_simulations=30) == (
            monte_carlo_test(engine.trades, 1000.0, n_simulations=30)
        )


def test_explicit_events_override_pnl_and_skip_unknown_rows(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "trades.csv"
    path.write_text(
        "timestamp,code,side,price,qty,pnl,event\n"
        "2026-01-01,A,buy,100,1,7,entry\n"
        "2026-01-02,A,sell,100,1,0,exit\n"
        "2026-01-03,A,sell,100,1,9,unknown\n"
        "2026-01-04,A,sell,100,1,8,\n",
        encoding="utf-8",
    )
    assert [t.pnl for t in _load_trades(tmp_path)] == [0.0]
    assert read_trade_activity(path) == ([date(2026, 1, 2)], 1)


@pytest.mark.parametrize("options_format", [False, True])
def test_unmarked_csv_keeps_legacy_loading(
    tmp_path: Path, options_format: bool
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "trades.csv"
    side = "close" if options_format else "sell"
    path.write_text(
        "timestamp,code,side,price,qty,pnl\n"
        "2026-01-01,A,buy,100,1,0\n"
        f"2026-01-02,A,{side},101,1,1\n"
        f"2026-01-03,A,{side},100,1,0\n",
        encoding="utf-8",
    )
    assert [t.pnl for t in _load_trades(tmp_path)] == [1.0]
    assert read_trade_activity(path) == ([date(2026, 1, 2)], 1)


@pytest.mark.parametrize("overlap", [False, True])
def test_all_breakeven_events_preserve_activity(tmp_path: Path, overlap: bool) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "trades.csv"
    second_entry = "2026-01-02" if overlap else "2026-01-04"
    path.write_text(
        "timestamp,code,side,price,qty,pnl,event\n"
        "2026-01-01,A,buy,100,1,0,entry\n"
        "2026-01-03,A,sell,100,1,0,exit\n"
        f"{second_entry},B,sell,100,1,0,entry\n"
        "2026-01-05,B,buy,100,1,0,exit\n",
        encoding="utf-8",
    )
    assert [t.pnl for t in _load_trades(tmp_path)] == [0.0, 0.0]
    assert read_trade_activity(path) == (
        [date(2026, 1, 3), date(2026, 1, 5)],
        2 if overlap else 1,
    )


def test_empty_export_keeps_event_header(tmp_path: Path) -> None:
    engine = ChinaAEngine({"initial_cash": 1000.0})
    dates = pd.date_range("2026-01-01", periods=2)
    equity = pd.Series(1000.0, index=dates)
    engine._write_artifacts(
        tmp_path,
        {},
        dates,
        equity,
        equity,
        pd.Series(0.0, index=dates),
        pd.DataFrame(index=dates),
        {},
        [],
    )
    path = tmp_path / "artifacts/trades.csv"
    assert "event" in pd.read_csv(path).columns
    assert _load_trades(tmp_path) == []
    assert read_trade_activity(path) == ([], None)
