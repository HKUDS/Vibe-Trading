"""Tests for BaseEngine shared logic: alignment, trade accounting, and artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import BaseEngine, _align, _load_optimizer
from backtest.engines.china_a import ChinaAEngine
from backtest.models import FillRecord, Position, TradeRecord


class DummyEngine(BaseEngine):
    """Deterministic engine for accounting tests."""

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        return float(raw_size)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        return size * (0.01 if is_open else 0.02)

    def apply_slippage(self, price: float, direction: int) -> float:
        return price + (0.5 * direction)


def _simple_data_and_signals():
    """Build minimal data_map and signal_map for alignment tests."""
    dates = pd.bdate_range("2025-01-01", periods=10)
    df_a = pd.DataFrame(
        {"close": np.linspace(10, 20, 10), "open": np.linspace(10, 20, 10)},
        index=dates,
    )
    df_b = pd.DataFrame(
        {"close": np.linspace(100, 110, 10), "open": np.linspace(100, 110, 10)},
        index=dates,
    )
    data_map = {"A": df_a, "B": df_b}

    sig_a = pd.Series(0.0, index=dates)
    sig_a.iloc[3:] = 1.0
    sig_b = pd.Series(0.0, index=dates)
    sig_b.iloc[5:] = 1.0
    signal_map = {"A": sig_a, "B": sig_b}

    return data_map, signal_map, dates


class TestAlign:
    def test_output_shapes(self) -> None:
        data_map, signal_map, dates = _simple_data_and_signals()
        out_dates, close_df, pos_df, ret_df = _align(data_map, signal_map, ["A", "B"])
        assert len(out_dates) == len(dates)
        assert close_df.shape == (len(dates), 2)
        assert pos_df.shape == (len(dates), 2)
        assert ret_df.shape == (len(dates), 2)

    def test_signal_shifted_by_one(self) -> None:
        data_map, signal_map, dates = _simple_data_and_signals()
        _, _, pos_df, _ = _align(data_map, signal_map, ["A", "B"])
        assert pos_df.at[dates[3], "A"] == 0.0
        assert pos_df.at[dates[4], "A"] > 0.0

    def test_positions_normalized(self) -> None:
        data_map, signal_map, dates = _simple_data_and_signals()
        _, _, pos_df, _ = _align(data_map, signal_map, ["A", "B"])
        row_sums = pos_df.abs().sum(axis=1)
        assert (row_sums <= 1.0 + 1e-10).all()

    def test_signals_clipped(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=5)
        df = pd.DataFrame({"close": [100] * 5, "open": [100] * 5}, index=dates)
        sig = pd.Series([0, 0, 2.0, -3.0, 0.5], index=dates)
        _, _, pos_df, _ = _align({"X": df}, {"X": sig}, ["X"])
        assert pos_df["X"].abs().max() <= 1.0 + 1e-10

    def test_nan_signals_filled_zero(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=5)
        df = pd.DataFrame({"close": [100] * 5, "open": [100] * 5}, index=dates)
        sig = pd.Series([np.nan, 1.0, np.nan, 0.5, np.nan], index=dates)
        _, _, pos_df, _ = _align({"X": df}, {"X": sig}, ["X"])
        assert not pos_df.isna().any().any()

    def test_close_ffill_bfill(self) -> None:
        dates = pd.bdate_range("2025-01-01", periods=5)
        df = pd.DataFrame(
            {"close": [100, np.nan, np.nan, 110, 115], "open": [100] * 5},
            index=dates,
        )
        sig = pd.Series([0, 1, 1, 1, 0], index=dates)
        _, close_df, _, _ = _align({"X": df}, {"X": sig}, ["X"])
        assert not close_df.isna().any().any()

    def test_with_optimizer(self) -> None:
        data_map, signal_map, _ = _simple_data_and_signals()

        def dummy_optimizer(ret, pos, dates_arg):
            return pos * 0.5

        _, _, pos_df, _ = _align(data_map, signal_map, ["A", "B"], optimizer=dummy_optimizer)
        _, _, pos_no_opt, _ = _align(data_map, signal_map, ["A", "B"])
        assert pos_df.abs().sum().sum() <= pos_no_opt.abs().sum().sum() + 1e-10


class TestLoadOptimizer:
    def test_no_optimizer(self) -> None:
        assert _load_optimizer({}) is None
        assert _load_optimizer({"optimizer": ""}) is None

    def test_valid_optimizer(self) -> None:
        opt = _load_optimizer({"optimizer": "risk_parity"})
        assert opt is not None and callable(opt)

    def test_invalid_optimizer_returns_none(self) -> None:
        opt = _load_optimizer({"optimizer": "nonexistent_module_xyz"})
        assert opt is None


class TestModelsCompatibility:
    def test_legacy_position_construction_still_works(self) -> None:
        pos = Position("X", 1, 10.0, pd.Timestamp("2025-01-02"), 5.0)
        assert pos.entry_decision_price is None
        assert pos.entry_slippage_cost == 0.0
        assert pos.signal_time is None

    def test_legacy_trade_record_construction_still_works(self) -> None:
        trade = TradeRecord(
            "X",
            1,
            10.0,
            11.0,
            pd.Timestamp("2025-01-02"),
            pd.Timestamp("2025-01-03"),
            5.0,
            1.0,
            5.0,
            10.0,
            "signal",
            1,
            0.25,
        )
        assert trade.signal_time is None
        assert trade.entry_decision_price is None
        assert trade.exit_decision_price is None
        assert trade.gross_pnl is None
        assert trade.slippage_cost == 0.0
        assert trade.net_pnl is None
        assert trade.holding_days is None


class TestClosePosition:
    def test_profitable_long(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._bar_idx = 5
        engine.positions["000001.SZ"] = Position(
            "000001.SZ", 1, 15.0, pd.Timestamp("2025-01-02"), 1000.0, entry_bar_idx=0,
        )
        engine.capital = 985_000.0
        engine._close_position("000001.SZ", 16.0, pd.Timestamp("2025-01-10"), "signal")

        assert "000001.SZ" not in engine.positions
        assert len(engine.trades) == 1
        t = engine.trades[0]
        assert t.pnl == pytest.approx(1000.0)
        assert t.exit_reason == "signal"
        assert t.holding_bars == 5
        assert t.entry_decision_price == pytest.approx(15.0)
        assert t.exit_decision_price == pytest.approx(16.0)
        assert t.gross_pnl == pytest.approx(1000.0)
        assert t.slippage_cost == pytest.approx(0.0)
        assert t.net_pnl == pytest.approx(1000.0 - t.commission)

    def test_losing_long(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._bar_idx = 3
        engine.positions["600519.SH"] = Position(
            "600519.SH", 1, 1800.0, pd.Timestamp("2025-01-02"), 100.0, entry_bar_idx=0,
        )
        engine.capital = 820_000.0
        engine._close_position("600519.SH", 1750.0, pd.Timestamp("2025-01-06"), "signal")

        t = engine.trades[0]
        assert t.pnl == pytest.approx(-5000.0)
        assert t.direction == 1

    def test_old_close_position_signature_still_works(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        engine._bar_idx = 2
        engine.positions["X"] = Position("X", 1, 10.5, pd.Timestamp("2025-01-02"), 2.0)
        engine.capital = 979.98
        engine._close_position("X", 12.5, pd.Timestamp("2025-01-04"), "signal")
        trade = engine.trades[0]
        assert trade.exit_decision_price == pytest.approx(12.5)
        assert trade.gross_pnl == pytest.approx(4.0)

    def test_close_nonexistent_position_noop(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._close_position("NOPE.SZ", 10.0, pd.Timestamp("2025-01-01"), "signal")
        assert len(engine.trades) == 0

    def test_capital_returned(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine._bar_idx = 1
        engine.positions["000001.SZ"] = Position(
            "000001.SZ", 1, 15.0, pd.Timestamp("2025-01-02"), 1000.0,
        )
        capital_before = 985_000.0
        engine.capital = capital_before
        engine._close_position("000001.SZ", 15.0, pd.Timestamp("2025-01-03"), "signal")
        assert engine.capital > capital_before

    def test_long_trade_accounting_is_correct(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        engine._bar_idx = 3
        engine.positions["LONG"] = Position(
            "LONG",
            1,
            10.5,
            pd.Timestamp("2025-01-02"),
            2.0,
            leverage=1.0,
            entry_bar_idx=0,
            entry_commission=0.02,
            entry_decision_price=10.0,
            entry_slippage_cost=1.0,
            signal_time=pd.Timestamp("2025-01-01"),
        )
        engine.capital = 978.98
        engine._close_position(
            "LONG",
            11.5,
            pd.Timestamp("2025-01-04"),
            "signal",
            exit_decision_price=12.0,
        )
        trade = engine.trades[0]
        assert trade.pnl == pytest.approx(2.0)
        assert trade.gross_pnl == pytest.approx(4.0)
        assert trade.commission == pytest.approx(0.06)
        assert trade.slippage_cost == pytest.approx(2.0)
        assert trade.net_pnl == pytest.approx(1.94)
        assert trade.gross_pnl - trade.commission - trade.slippage_cost == pytest.approx(trade.net_pnl)
        assert trade.slippage_cost > 0
        assert trade.holding_days == 2

    def test_short_trade_accounting_is_correct(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        engine._bar_idx = 4
        engine.positions["SHORT"] = Position(
            "SHORT",
            -1,
            9.5,
            pd.Timestamp("2025-01-02"),
            2.0,
            leverage=1.0,
            entry_bar_idx=1,
            entry_commission=0.02,
            entry_decision_price=10.0,
            entry_slippage_cost=1.0,
            signal_time=pd.Timestamp("2025-01-01"),
        )
        engine.capital = 980.98
        engine._close_position(
            "SHORT",
            8.5,
            pd.Timestamp("2025-01-05"),
            "signal",
            exit_decision_price=8.0,
        )
        trade = engine.trades[0]
        assert trade.pnl == pytest.approx(2.0)
        assert trade.gross_pnl == pytest.approx(4.0)
        assert trade.commission == pytest.approx(0.06)
        assert trade.slippage_cost == pytest.approx(2.0)
        assert trade.net_pnl == pytest.approx(1.94)
        assert trade.gross_pnl - trade.commission - trade.slippage_cost == pytest.approx(trade.net_pnl)
        assert trade.slippage_cost > 0
        assert trade.holding_days == 3

    def test_existing_capital_and_equity_behaviour_remains_unchanged(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        engine.capital = 978.98
        engine.positions["X"] = Position(
            "X",
            1,
            10.5,
            pd.Timestamp("2025-01-02"),
            2.0,
            entry_commission=0.02,
            entry_decision_price=10.0,
        )
        engine._bar_idx = 3
        engine._close_position(
            "X",
            11.5,
            pd.Timestamp("2025-01-04"),
            "signal",
            exit_decision_price=12.0,
        )
        assert engine.capital == pytest.approx(1001.94)


class TestCalcEquity:
    def test_no_positions(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.0]}, index=dates)
        eq = engine._calc_equity(close_df, dates[0])
        assert eq == 1_000_000.0

    def test_with_unrealized_gain(self) -> None:
        engine = ChinaAEngine({"initial_cash": 1_000_000})
        engine.capital = 985_000.0
        engine.positions["X"] = Position("X", 1, 15.0, pd.Timestamp("2025-01-02"), 1000.0)
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-03")])
        close_df = pd.DataFrame({"X": [16.0]}, index=dates)
        eq = engine._calc_equity(close_df, dates[0])
        assert eq == pytest.approx(1_001_000.0)


class TestFillLedger:
    def test_entry_and_exit_create_separate_fills(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")])
        df = pd.DataFrame(
            {"open": [10.0, 12.0], "close": [10.0, 12.0]},
            index=dates,
        )

        engine._rebalance("X", 0.5, df, dates[0], 1_000.0)
        assert len(engine.fills) == 1
        entry = engine.fills[0]
        assert entry.event_type == "entry"
        assert entry.side == "buy"
        assert entry.reason == "signal"
        assert entry.decision_price == pytest.approx(10.0)
        assert entry.fill_price == pytest.approx(10.5)
        assert entry.notional == pytest.approx(abs(entry.quantity) * entry.fill_price)
        assert entry.commission == pytest.approx(entry.quantity * 0.01)

        engine._bar_idx = 1
        engine._rebalance("X", 0.0, df, dates[1], engine._calc_equity(
            pd.DataFrame({"X": [10.0, 12.0]}, index=dates), dates[1]
        ))
        assert len(engine.fills) == 2
        exit_fill = engine.fills[1]
        assert exit_fill.event_type == "exit"
        assert exit_fill.side == "sell"
        assert exit_fill.reason == "signal"
        assert exit_fill.decision_price == pytest.approx(12.0)
        assert exit_fill.fill_price == pytest.approx(11.5)
        assert exit_fill.commission == pytest.approx(exit_fill.quantity * 0.02)
        assert entry.commission != exit_fill.commission

    @pytest.mark.parametrize("target_weight", [0.5, -0.5])
    def test_adverse_entry_slippage_is_positive(self, target_weight: float) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        ts = pd.Timestamp("2025-01-02")
        df = pd.DataFrame({"open": [10.0], "close": [10.0]}, index=[ts])

        engine._rebalance("X", target_weight, df, ts, 1_000.0)

        assert len(engine.fills) == 1
        assert engine.fills[0].slippage_cost > 0.0

    def test_fill_record_is_frozen(self) -> None:
        fill = FillRecord(
            pd.Timestamp("2025-01-02"), "X", "buy", "entry", 1,
            2.0, 10.0, 10.5, 21.0, 0.02, 1.0, "signal",
        )
        with pytest.raises(Exception):
            fill.quantity = 3.0  # type: ignore[misc]


class TestExecutedPositionAccounting:
    def test_weights_and_exposures_use_current_prices_and_equity(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        ts = pd.Timestamp("2025-01-02")
        close_df = pd.DataFrame({"LONG": [20.0], "SHORT": [50.0]}, index=[ts])
        engine.positions = {
            "LONG": Position("LONG", 1, 18.0, ts, 5.0),
            "SHORT": Position("SHORT", -1, 52.0, ts, 2.0),
        }

        engine._record_executed_position_weights(
            ts, close_df, 1_000.0, ["LONG", "SHORT"]
        )
        weights = engine._executed_positions_frame(
            pd.DatetimeIndex([ts]), ["LONG", "SHORT"]
        )
        assert weights.at[ts, "LONG"] == pytest.approx(0.1)
        assert weights.at[ts, "SHORT"] == pytest.approx(-0.1)

        accounting = engine._build_daily_accounting(
            pd.Series([1_000.0], index=[ts]), weights, pd.DatetimeIndex([ts])
        )
        row = accounting.loc[ts]
        assert row["gross_exposure"] == pytest.approx(0.2)
        assert row["net_exposure"] == pytest.approx(0.0)
        assert row["long_exposure"] == pytest.approx(0.1)
        assert row["short_exposure"] == pytest.approx(0.1)

    def test_turnover_first_row_and_weight_changes_are_deterministic(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")])
        weights = pd.DataFrame(
            {"A": [0.6, 0.2], "B": [-0.2, 0.0]},
            index=dates,
        )
        accounting = engine._build_daily_accounting(
            pd.Series([1_000.0, 1_000.0], index=dates), weights, dates
        )

        assert accounting.iloc[0]["one_way_turnover"] == pytest.approx(0.4)
        assert accounting.iloc[1]["one_way_turnover"] == pytest.approx(0.3)

    def test_daily_cost_and_return_reconciliation(self) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")])
        engine.fills.extend([
            FillRecord(dates[1], "A", "buy", "entry", 1, 1.0, 10.0, 10.5,
                       10.5, 2.0, 1.0, "signal"),
            FillRecord(dates[1], "B", "sell", "entry", -1, 1.0, 20.0, 19.5,
                       19.5, 1.0, 0.5, "signal"),
        ])
        equity = pd.Series([1_000.0, 1_010.0], index=dates)
        weights = pd.DataFrame({"A": [0.0, 0.1], "B": [0.0, -0.1]}, index=dates)

        accounting = engine._build_daily_accounting(equity, weights, dates)
        row = accounting.iloc[1]
        assert row["daily_commission"] == pytest.approx(3.0)
        assert row["daily_slippage_cost"] == pytest.approx(1.5)
        assert row["daily_total_cost"] == pytest.approx(4.5)
        assert row["cost_rate"] == pytest.approx(0.0045)
        assert row["net_return"] == pytest.approx(0.01)
        assert row["gross_return"] == pytest.approx(
            row["net_return"] + row["cost_rate"]
        )
        expected_gross_equity = 1_000.0 * (1.0 + accounting.iloc[0]["gross_return"])
        expected_gross_equity *= 1.0 + row["gross_return"]
        assert row["gross_equity"] == pytest.approx(expected_gross_equity)


class TestArtifacts:
    def test_trades_csv_contains_old_and_new_columns(self, tmp_path: Path) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        run_dir = tmp_path / "run"
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")])
        data_map = {
            "X": pd.DataFrame(
                {"open": [10.0, 12.0], "close": [11.0, 11.5]},
                index=dates,
            )
        }
        target_pos = pd.DataFrame({"X": [1.0, 0.0]}, index=dates)
        equity_series = pd.Series([1000.0, 1002.0], index=dates)
        bench_equity = pd.Series([1000.0, 1001.0], index=dates)
        bench_ret = pd.Series([0.0, 0.001], index=dates)

        engine.trades.append(TradeRecord(
            symbol="X",
            direction=1,
            entry_price=10.5,
            exit_price=11.5,
            entry_time=pd.Timestamp("2025-01-02"),
            exit_time=pd.Timestamp("2025-01-04"),
            size=2.0,
            leverage=1.0,
            pnl=2.0,
            pnl_pct=9.5238,
            exit_reason="signal",
            holding_bars=2,
            commission=0.06,
            signal_time=pd.Timestamp("2025-01-01"),
            entry_decision_price=10.0,
            exit_decision_price=12.0,
            gross_pnl=4.0,
            slippage_cost=2.0,
            net_pnl=1.94,
            holding_days=2,
        ))

        artifact_metrics = {"sharpe": 1.0}
        engine._write_artifacts(
            run_dir,
            data_map,
            dates,
            equity_series,
            bench_equity,
            bench_ret,
            target_pos,
            artifact_metrics,
            ["X"],
        )
        assert "mean_hhi" in artifact_metrics
        assert "maximum_largest_absolute_weight" in artifact_metrics

        trades_df = pd.read_csv(run_dir / "artifacts" / "trades.csv")
        expected_columns = {
            "timestamp", "code", "side", "price", "qty", "reason",
            "pnl", "holding_days", "return_pct", "signal_time",
            "decision_price", "fill_price", "gross_pnl", "commission",
            "slippage_cost", "net_pnl",
        }
        assert expected_columns.issubset(set(trades_df.columns))

        entry_row = trades_df.iloc[0]
        exit_row = trades_df.iloc[1]
        assert entry_row["decision_price"] == pytest.approx(10.0)
        assert entry_row["fill_price"] == pytest.approx(10.5)
        assert exit_row["decision_price"] == pytest.approx(12.0)
        assert exit_row["fill_price"] == pytest.approx(11.5)
        assert exit_row["gross_pnl"] == pytest.approx(4.0)
        assert exit_row["commission"] == pytest.approx(0.06)
        assert exit_row["slippage_cost"] == pytest.approx(2.0)
        assert exit_row["net_pnl"] == pytest.approx(1.94)

        artifacts = run_dir / "artifacts"
        for legacy_name in ("equity.csv", "positions.csv", "trades.csv", "metrics.csv"):
            assert (artifacts / legacy_name).is_file()
        for new_name in ("fills.csv", "executed_positions.csv", "daily_accounting.csv"):
            assert (artifacts / new_name).is_file()
        for report_name in (
            "performance_summary.json", "performance_summary.csv",
            "monthly_returns.csv", "drawdown_periods.csv",
            "asset_attribution.csv", "cost_reconciliation.csv",
            "concentration.csv", "performance_report.md",
        ):
            assert (artifacts / report_name).is_file()

        fills_df = pd.read_csv(artifacts / "fills.csv")
        assert fills_df.empty
        assert list(fills_df.columns) == [
            "timestamp", "symbol", "side", "event_type", "direction",
            "quantity", "decision_price", "fill_price", "notional",
            "commission", "slippage_cost", "reason",
        ]

        accounting_df = pd.read_csv(artifacts / "daily_accounting.csv")
        assert set(accounting_df.columns) == {
            "timestamp", "net_return", "gross_return", "daily_commission",
            "daily_slippage_cost", "daily_total_cost", "cost_rate",
            "one_way_turnover", "gross_exposure", "net_exposure",
            "long_exposure", "short_exposure", "equity", "gross_equity",
        }

    def test_fills_csv_serializes_execution_ledger(self, tmp_path: Path) -> None:
        engine = DummyEngine({"initial_cash": 1_000})
        ts = pd.Timestamp("2025-01-02")
        engine.fills.append(FillRecord(
            ts, "X", "buy", "entry", 1, 2.0, 10.0, 10.5,
            21.0, 0.02, 1.0, "signal",
        ))
        dates = pd.DatetimeIndex([ts])
        data_map = {
            "X": pd.DataFrame({"open": [10.0], "close": [10.5]}, index=dates)
        }
        target_pos = pd.DataFrame({"X": [0.0]}, index=dates)
        equity = pd.Series([1_000.0], index=dates)

        engine._write_artifacts(
            tmp_path,
            data_map,
            dates,
            equity,
            equity,
            pd.Series([0.0], index=dates),
            target_pos,
            {},
            ["X"],
        )

        fills_df = pd.read_csv(tmp_path / "artifacts" / "fills.csv")
        assert len(fills_df) == 1
        assert fills_df.iloc[0]["event_type"] == "entry"
        assert fills_df.iloc[0]["commission"] == pytest.approx(0.02)
        assert fills_df.iloc[0]["slippage_cost"] == pytest.approx(1.0)


class TestSafePrice:
    def test_returns_close_price(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.5]}, index=dates)
        assert BaseEngine._safe_price(close_df, dates[0], "X", 10.0) == 15.5

    def test_fallback_on_missing_symbol(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.5]}, index=dates)
        assert BaseEngine._safe_price(close_df, dates[0], "MISSING", 10.0) == 10.0

    def test_fallback_on_missing_timestamp(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [15.5]}, index=dates)
        assert BaseEngine._safe_price(close_df, pd.Timestamp("2025-06-01"), "X", 10.0) == 10.0

    def test_fallback_on_nan(self) -> None:
        dates = pd.DatetimeIndex([pd.Timestamp("2025-01-02")])
        close_df = pd.DataFrame({"X": [np.nan]}, index=dates)
        assert BaseEngine._safe_price(close_df, dates[0], "X", 10.0) == 10.0
