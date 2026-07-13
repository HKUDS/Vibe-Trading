"""Deterministic tests for shared Phase 3 performance reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.models import FillRecord, TradeRecord
from backtest.reporting import (
    ATTRIBUTION_COLUMNS,
    CONCENTRATION_COLUMNS,
    DD_COLUMNS,
    MONTHLY_COLUMNS,
    build_asset_attribution,
    build_concentration,
    build_cost_reconciliation,
    build_monthly_returns,
    build_performance_summary,
    build_reporting_outputs,
    concentration_metrics,
    analyze_drawdowns,
    write_reporting_outputs,
)


def _trade(
    symbol: str,
    gross_pnl: float,
    commission: float,
    slippage_cost: float,
    net_pnl: float,
    pnl_pct: float = 1.0,
    holding_days: int = 2,
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        direction=1,
        entry_price=10.0,
        exit_price=11.0,
        entry_time=pd.Timestamp("2025-01-02"),
        exit_time=pd.Timestamp("2025-01-04"),
        size=1.0,
        leverage=1.0,
        pnl=gross_pnl - slippage_cost,
        pnl_pct=pnl_pct,
        exit_reason="signal",
        holding_bars=holding_days,
        commission=commission,
        gross_pnl=gross_pnl,
        slippage_cost=slippage_cost,
        net_pnl=net_pnl,
        holding_days=holding_days,
    )


def _fill(
    timestamp: pd.Timestamp,
    symbol: str,
    commission: float,
    slippage: float,
) -> FillRecord:
    return FillRecord(
        timestamp=timestamp,
        symbol=symbol,
        side="buy",
        event_type="entry",
        direction=1,
        quantity=1.0,
        decision_price=10.0,
        fill_price=10.5,
        notional=10.5,
        commission=commission,
        slippage_cost=slippage,
        reason="signal",
    )


def _daily_accounting() -> pd.DataFrame:
    dates = pd.DatetimeIndex([
        pd.Timestamp("2025-01-30"),
        pd.Timestamp("2025-01-31"),
        pd.Timestamp("2025-02-03"),
    ])
    return pd.DataFrame({
        "net_return": [0.10, -0.10, 0.05],
        "gross_return": [0.11, -0.09, 0.06],
        "daily_commission": [1.0, 2.0, 3.0],
        "daily_slippage_cost": [0.5, 1.0, 1.5],
        "daily_total_cost": [1.5, 3.0, 4.5],
        "cost_rate": [0.0015, 0.003, 0.0045],
        "one_way_turnover": [0.2, 0.3, 0.4],
        "gross_exposure": [0.5, 0.7, 0.6],
        "net_exposure": [0.5, 0.3, 0.2],
        "long_exposure": [0.5, 0.5, 0.4],
        "short_exposure": [0.0, 0.2, 0.2],
        "equity": [1100.0, 990.0, 1039.5],
        "gross_equity": [1110.0, 1010.1, 1070.706],
    }, index=dates)


class TestMonthlyReturns:
    def test_compounds_partial_months_and_aggregates_accounting(self) -> None:
        monthly = build_monthly_returns(_daily_accounting())

        assert list(monthly["month"]) == ["2025-01", "2025-02"]
        january = monthly.iloc[0]
        assert january["net_return"] == pytest.approx((1.10 * 0.90) - 1.0)
        assert january["gross_return"] == pytest.approx((1.11 * 0.91) - 1.0)
        assert january["total_commission"] == pytest.approx(3.0)
        assert january["total_slippage_cost"] == pytest.approx(1.5)
        assert january["total_trading_cost"] == pytest.approx(4.5)
        assert january["one_way_turnover"] == pytest.approx(0.5)
        assert january["average_gross_exposure"] == pytest.approx(0.6)
        assert january["ending_equity"] == pytest.approx(990.0)

    def test_empty_monthly_output_has_headers(self) -> None:
        monthly = build_monthly_returns(pd.DataFrame())
        assert monthly.empty
        assert list(monthly.columns) == MONTHLY_COLUMNS


class TestDrawdowns:
    def test_recovered_drawdown(self) -> None:
        dates = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-05"])
        periods = analyze_drawdowns(pd.Series([100.0, 90.0, 110.0], index=dates))

        assert len(periods) == 1
        row = periods.iloc[0]
        assert row["depth"] == pytest.approx(-0.10)
        assert row["duration_days"] == 4
        assert row["recovery_days"] == 3
        assert bool(row["recovered"]) is True
        assert pd.Timestamp(row["trough_timestamp"]) == dates[1]

    def test_unrecovered_drawdown(self) -> None:
        dates = pd.to_datetime(["2025-01-01", "2025-01-03", "2025-01-06"])
        periods = analyze_drawdowns(pd.Series([100.0, 95.0, 90.0], index=dates))

        row = periods.iloc[0]
        assert row["depth"] == pytest.approx(-0.10)
        assert row["duration_days"] == 5
        assert bool(row["recovered"]) is False
        assert pd.isna(row["recovery_timestamp"])
        assert pd.isna(row["recovery_days"])

    def test_flat_equity_has_no_drawdown(self) -> None:
        dates = pd.date_range("2025-01-01", periods=3)
        periods = analyze_drawdowns(pd.Series([100.0, 100.0, 100.0], index=dates))
        assert periods.empty
        assert list(periods.columns) == DD_COLUMNS


class TestAssetAttribution:
    def test_groups_symbols_and_reconciles_values(self) -> None:
        trades = [
            _trade("A", 10.0, 1.0, 2.0, 7.0, pnl_pct=4.0),
            _trade("A", -1.0, 1.0, 1.0, -3.0, pnl_pct=-2.0),
            _trade("B", 4.0, 1.0, 1.0, 2.0, pnl_pct=1.0),
        ]
        attribution = build_asset_attribution(trades)

        a = attribution.set_index("symbol").loc["A"]
        assert a["trade_count"] == 2
        assert a["winning_trades"] == 1
        assert a["losing_trades"] == 1
        assert a["gross_pnl"] == pytest.approx(9.0)
        assert a["commission"] == pytest.approx(2.0)
        assert a["slippage_cost"] == pytest.approx(3.0)
        assert a["net_pnl"] == pytest.approx(4.0)
        assert a["contribution_to_total_net_pnl"] == pytest.approx(4.0 / 6.0)
        assert attribution["net_pnl"].sum() == pytest.approx(
            sum(trade.net_pnl for trade in trades if trade.net_pnl is not None)
        )

    def test_zero_trade_attribution_has_headers_only(self) -> None:
        attribution = build_asset_attribution([])
        assert attribution.empty
        assert list(attribution.columns) == ATTRIBUTION_COLUMNS


class TestCostReconciliation:
    def test_exact_reconciliation(self) -> None:
        trade = _trade("A", 10.0, 1.0, 1.0, 8.0)
        fills = [_fill(pd.Timestamp("2025-01-02"), "A", 1.0, 1.0)]
        result = build_cost_reconciliation([trade], fills, 8.0, 1_000.0).iloc[0]
        assert result["reconciliation_status"] == "reconciled"
        assert result["difference"] == pytest.approx(0.0)
        assert result["commission_difference"] == pytest.approx(0.0)
        assert result["slippage_difference"] == pytest.approx(0.0)
        assert result["expected_ending_equity"] == pytest.approx(1_008.0)

    def test_difference_within_tolerance(self) -> None:
        trade = _trade("A", 10.0, 1.0, 1.0, 8.0)
        fills = [_fill(pd.Timestamp("2025-01-02"), "A", 1.0, 1.0)]
        result = build_cost_reconciliation(
            [trade], fills, 8.00000001, 1_000_000.0
        ).iloc[0]
        assert result["reconciliation_status"] == "difference_within_tolerance"

    def test_meaningful_difference_is_unreconciled(self) -> None:
        trade = _trade("A", 10.0, 1.0, 1.0, 8.0)
        fills = [_fill(pd.Timestamp("2025-01-02"), "A", 1.0, 1.0)]
        result = build_cost_reconciliation(
            [trade], fills, 20.0, 1_000.0
        ).iloc[0]
        assert result["reconciliation_status"] == "unreconciled"
        assert "funding" in result["difference_explanation"]

    def test_fill_trade_cost_mismatch_is_unreconciled(self) -> None:
        trade = _trade("A", 10.0, 1.0, 1.0, 8.0)
        fills = [_fill(pd.Timestamp("2025-01-02"), "A", 2.0, 3.0)]
        result = build_cost_reconciliation(
            [trade], fills, 8.0, 1_000.0
        ).iloc[0]

        assert result["reconciliation_status"] == "unreconciled"
        assert result["commission_difference"] == pytest.approx(1.0)
        assert result["slippage_difference"] == pytest.approx(2.0)

    def test_flat_zero_trade_run_is_not_applicable(self) -> None:
        result = build_cost_reconciliation([], [], 0.0, 1_000.0).iloc[0]
        assert result["reconciliation_status"] == "not_applicable"


class TestConcentration:
    def test_hhi_top_weights_and_zero_row(self) -> None:
        dates = pd.date_range("2025-01-01", periods=2)
        positions = pd.DataFrame({
            "A": [0.5, 0.0], "B": [-0.25, 0.0],
            "C": [0.1, 0.0], "D": [0.05, 0.0],
        }, index=dates)
        concentration = build_concentration(positions)

        first = concentration.iloc[0]
        assert first["active_positions"] == 4
        assert first["largest_absolute_weight"] == pytest.approx(0.5)
        assert first["top_3_absolute_weight"] == pytest.approx(0.85)
        assert first["hhi"] == pytest.approx(0.325)
        assert first["gross_exposure"] == pytest.approx(0.9)
        assert first["net_exposure"] == pytest.approx(0.4)
        assert concentration.iloc[1]["hhi"] == pytest.approx(0.0)
        assert concentration.iloc[1]["largest_absolute_weight"] == pytest.approx(0.0)

        scalars = concentration_metrics(concentration)
        assert scalars["mean_hhi"] == pytest.approx(0.1625)
        assert scalars["maximum_hhi"] == pytest.approx(0.325)

    def test_empty_concentration_has_headers(self) -> None:
        concentration = build_concentration(pd.DataFrame())
        assert concentration.empty
        assert list(concentration.columns) == CONCENTRATION_COLUMNS


class TestPerformanceSummaryAndArtifacts:
    def test_summary_reconciles_equity_costs_and_drawdown(self) -> None:
        daily = _daily_accounting()
        drawdowns = analyze_drawdowns(daily["equity"])
        metrics = {
            "total_commission": 6.0,
            "total_slippage_cost": 3.0,
            "total_trading_cost": 9.0,
            "total_one_way_turnover": 0.9,
            "annualized_one_way_turnover": 75.6,
            "mean_gross_exposure": 0.6,
            "maximum_gross_exposure": 0.7,
            "mean_net_exposure": 1.0 / 3.0,
            "mean_active_positions": 1.5,
            "win_rate": 0.5,
        }
        trades = [_trade("A", 10.0, 1.0, 1.0, 8.0)]
        summary = build_performance_summary(
            daily, trades, metrics, 1_000.0, 252, drawdowns
        )

        assert summary["starting_capital"] == pytest.approx(1_000.0)
        assert summary["ending_capital"] == pytest.approx(1_039.5)
        assert summary["gross_ending_capital"] == pytest.approx(1_070.706)
        assert summary["net_profit"] == pytest.approx(39.5)
        assert summary["net_total_return"] == pytest.approx(0.0395)
        assert summary["gross_total_return"] == pytest.approx(0.070706)
        assert summary["total_trading_cost"] == pytest.approx(9.0)
        assert summary["maximum_drawdown"] == pytest.approx(-0.10)
        assert summary["maximum_drawdown_duration_days"] == 4

    def test_zero_trade_flat_equity_is_safe(self) -> None:
        dates = pd.date_range("2025-01-01", periods=2)
        daily = _daily_accounting().iloc[:2].copy()
        daily.index = dates
        daily.loc[:, "net_return"] = 0.0
        daily.loc[:, "gross_return"] = 0.0
        daily.loc[:, "equity"] = 1_000.0
        daily.loc[:, "gross_equity"] = 1_000.0
        summary = build_performance_summary(
            daily, [], {}, 1_000.0, 252, analyze_drawdowns(daily["equity"])
        )
        assert summary["net_profit"] == pytest.approx(0.0)
        assert summary["trade_count"] == 0
        assert summary["maximum_drawdown"] == pytest.approx(0.0)
        assert summary["sharpe_ratio"] == pytest.approx(0.0)

    def test_all_reporting_artifacts_are_written_and_consistent(self, tmp_path: Path) -> None:
        daily = _daily_accounting()
        positions = pd.DataFrame(
            {"A": [0.5, 0.4, 0.0], "B": [0.0, -0.2, 0.0]},
            index=daily.index,
        )
        trades = [_trade("A", 10.0, 1.0, 1.0, 8.0)]
        fills = [_fill(daily.index[0], "A", 1.0, 1.0)]
        outputs = build_reporting_outputs(
            daily, positions, trades, fills,
            {"total_commission": 1.0, "total_slippage_cost": 1.0,
             "total_trading_cost": 2.0, "win_rate": 1.0},
            1_000.0, 252,
        )
        write_reporting_outputs(tmp_path, outputs)

        expected = {
            "performance_summary.json", "performance_summary.csv",
            "monthly_returns.csv", "drawdown_periods.csv",
            "asset_attribution.csv", "cost_reconciliation.csv",
            "concentration.csv", "performance_report.md",
        }
        assert expected == {path.name for path in tmp_path.iterdir()}
        summary = json.loads((tmp_path / "performance_summary.json").read_text())
        summary_csv = pd.read_csv(tmp_path / "performance_summary.csv").iloc[0]
        report = (tmp_path / "performance_report.md").read_text()
        assert summary["ending_capital"] == pytest.approx(summary_csv["ending_capital"])
        assert summary["total_commission"] == pytest.approx(1.0)
        assert summary["total_slippage_cost"] == pytest.approx(1.0)
        assert summary["total_trading_cost"] == pytest.approx(2.0)
        assert f"Ending capital: {summary['ending_capital']:,.2f}" in report
        assert "Historical backtest results do not guarantee future profit." in report
