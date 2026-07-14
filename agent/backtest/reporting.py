"""Reusable performance-reporting builders for normal backtest runs."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.models import FillRecord, OrderRecord, TradeRecord
from backtest.metrics import calc_execution_metrics


MONTHLY_COLUMNS = [
    "month", "net_return", "gross_return", "total_commission",
    "total_slippage_cost", "total_trading_cost", "one_way_turnover",
    "average_gross_exposure", "ending_equity", "gross_ending_equity",
]
DD_COLUMNS = [
    "drawdown_id", "peak_timestamp", "trough_timestamp",
    "recovery_timestamp", "depth", "duration_days", "recovery_days",
    "recovered",
]
ATTRIBUTION_COLUMNS = [
    "symbol", "trade_count", "winning_trades", "losing_trades", "win_rate",
    "gross_pnl", "commission", "slippage_cost", "net_pnl",
    "average_net_pnl", "average_return_pct", "average_holding_days",
    "contribution_to_total_net_pnl",
]
RECONCILIATION_COLUMNS = [
    "gross_completed_trade_pnl", "execution_price_pnl", "total_commission",
    "total_slippage_cost", "completed_trade_net_pnl",
    "trade_total_commission", "fill_total_commission", "commission_difference",
    "trade_total_slippage_cost", "fill_total_slippage_cost", "slippage_difference",
    "realized_gross_pnl", "unrealized_gross_pnl", "expected_ending_equity",
    "final_capital", "open_position_count", "equity_derived_net_profit",
    "difference", "final_capital_difference", "tolerance",
    "reconciliation_status", "difference_explanation",
]
CONCENTRATION_COLUMNS = [
    "timestamp", "active_positions", "largest_absolute_weight",
    "top_3_absolute_weight", "hhi", "gross_exposure", "net_exposure",
]


def _finite(value: Any, default: float = 0.0) -> float:
    """Return a finite float suitable for CSV and strict JSON output."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _effective_bars_per_year(
    index: pd.Index,
    bars_per_year: Optional[int],
) -> float:
    if bars_per_year is not None:
        return max(_finite(bars_per_year), 0.0)
    if len(index) <= 1 or not isinstance(index, pd.DatetimeIndex):
        return float(max(len(index), 1))
    elapsed_days = max((index[-1] - index[0]).days, 0)
    years = elapsed_days / 365.25 if elapsed_days > 0 else 0.0
    return len(index) / years if years > 0 else float(len(index))


def _annualized_return(
    starting_capital: float,
    ending_capital: float,
    observations: int,
    bars_per_year: float,
) -> float:
    if starting_capital <= 0 or ending_capital <= 0 or observations <= 0:
        return 0.0
    result = (ending_capital / starting_capital) ** (bars_per_year / observations) - 1.0
    return _finite(result)


def analyze_drawdowns(equity: pd.Series) -> pd.DataFrame:
    """Detect distinct peak-to-recovery drawdown episodes."""
    if equity is None or equity.empty:
        return pd.DataFrame(columns=DD_COLUMNS)

    series = equity.dropna().astype(float).sort_index()
    if series.empty:
        return pd.DataFrame(columns=DD_COLUMNS)

    peak_value = float(series.iloc[0])
    peak_timestamp = pd.Timestamp(series.index[0])
    in_drawdown = False
    trough_value = peak_value
    trough_timestamp = peak_timestamp
    rows: List[Dict[str, Any]] = []

    for raw_timestamp, raw_value in series.iloc[1:].items():
        timestamp = pd.Timestamp(raw_timestamp)
        value = float(raw_value)
        if value >= peak_value:
            if in_drawdown:
                rows.append({
                    "drawdown_id": len(rows) + 1,
                    "peak_timestamp": peak_timestamp,
                    "trough_timestamp": trough_timestamp,
                    "recovery_timestamp": timestamp,
                    "depth": trough_value / peak_value - 1.0 if peak_value else 0.0,
                    "duration_days": max((timestamp - peak_timestamp).days, 0),
                    "recovery_days": max((timestamp - trough_timestamp).days, 0),
                    "recovered": True,
                })
                in_drawdown = False
            peak_value = value
            peak_timestamp = timestamp
            trough_value = value
            trough_timestamp = timestamp
        else:
            if not in_drawdown:
                in_drawdown = True
                trough_value = value
                trough_timestamp = timestamp
            elif value < trough_value:
                trough_value = value
                trough_timestamp = timestamp

    if in_drawdown:
        final_timestamp = pd.Timestamp(series.index[-1])
        rows.append({
            "drawdown_id": len(rows) + 1,
            "peak_timestamp": peak_timestamp,
            "trough_timestamp": trough_timestamp,
            "recovery_timestamp": pd.NaT,
            "depth": trough_value / peak_value - 1.0 if peak_value else 0.0,
            "duration_days": max((final_timestamp - peak_timestamp).days, 0),
            "recovery_days": np.nan,
            "recovered": False,
        })

    return pd.DataFrame(rows, columns=DD_COLUMNS)


def build_monthly_returns(daily_accounting: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily accounting into chronologically ordered months."""
    if daily_accounting is None or daily_accounting.empty:
        return pd.DataFrame(columns=MONTHLY_COLUMNS)

    daily = daily_accounting.copy()
    daily.index = pd.to_datetime(daily.index)
    daily = daily.sort_index()
    rows: List[Dict[str, Any]] = []
    for period, group in daily.groupby(daily.index.to_period("M"), sort=True):
        rows.append({
            "month": str(period),
            "net_return": _finite((1.0 + group["net_return"]).prod() - 1.0),
            "gross_return": _finite((1.0 + group["gross_return"]).prod() - 1.0),
            "total_commission": _finite(group["daily_commission"].sum()),
            "total_slippage_cost": _finite(group["daily_slippage_cost"].sum()),
            "total_trading_cost": _finite(group["daily_total_cost"].sum()),
            "one_way_turnover": _finite(group["one_way_turnover"].sum()),
            "average_gross_exposure": _finite(group["gross_exposure"].mean()),
            "ending_equity": _finite(group["equity"].iloc[-1]),
            "gross_ending_equity": _finite(group["gross_equity"].iloc[-1]),
        })
    return pd.DataFrame(rows, columns=MONTHLY_COLUMNS)


def build_asset_attribution(trades: List[TradeRecord]) -> pd.DataFrame:
    """Build completed-round-trip attribution grouped by engine symbol."""
    if not trades:
        return pd.DataFrame(columns=ATTRIBUTION_COLUMNS)

    grouped: Dict[str, List[TradeRecord]] = {}
    for trade in trades:
        grouped.setdefault(trade.symbol, []).append(trade)

    trade_net_values = []
    for trade in trades:
        gross = trade.gross_pnl if trade.gross_pnl is not None else trade.pnl + trade.slippage_cost
        net = trade.net_pnl if trade.net_pnl is not None else gross - trade.commission - trade.slippage_cost
        trade_net_values.append(_finite(net))
    total_net_pnl = sum(trade_net_values)

    rows: List[Dict[str, Any]] = []
    for symbol in sorted(grouped):
        symbol_trades = grouped[symbol]
        gross_values = []
        net_values = []
        holding_values = []
        for trade in symbol_trades:
            gross = trade.gross_pnl if trade.gross_pnl is not None else trade.pnl + trade.slippage_cost
            net = trade.net_pnl if trade.net_pnl is not None else gross - trade.commission - trade.slippage_cost
            gross_values.append(_finite(gross))
            net_values.append(_finite(net))
            holding_values.append(_finite(
                trade.holding_days if trade.holding_days is not None else trade.holding_bars
            ))
        symbol_net = sum(net_values)
        winning = sum(value > 0 for value in net_values)
        losing = sum(value < 0 for value in net_values)
        rows.append({
            "symbol": symbol,
            "trade_count": len(symbol_trades),
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": winning / len(symbol_trades) if symbol_trades else 0.0,
            "gross_pnl": sum(gross_values),
            "commission": sum(_finite(trade.commission) for trade in symbol_trades),
            "slippage_cost": sum(_finite(trade.slippage_cost) for trade in symbol_trades),
            "net_pnl": symbol_net,
            "average_net_pnl": float(np.mean(net_values)) if net_values else 0.0,
            "average_return_pct": float(np.mean([
                _finite(trade.pnl_pct) for trade in symbol_trades
            ])) if symbol_trades else 0.0,
            "average_holding_days": float(np.mean(holding_values)) if holding_values else 0.0,
            "contribution_to_total_net_pnl": (
                symbol_net / total_net_pnl if abs(total_net_pnl) > 1e-12 else 0.0
            ),
        })
    return pd.DataFrame(rows, columns=ATTRIBUTION_COLUMNS)


def build_cost_reconciliation(
    trades: List[TradeRecord],
    fills: List[FillRecord],
    equity_derived_net_profit: float,
    starting_capital: float,
    final_capital: Optional[float] = None,
    final_unrealized_pnl: float = 0.0,
    open_position_count: int = 0,
) -> pd.DataFrame:
    """Reconcile fills, completed trades, and canonical terminal equity."""
    gross_trade_pnl = sum(_finite(
        trade.gross_pnl if trade.gross_pnl is not None else trade.pnl + trade.slippage_cost
    ) for trade in trades)
    execution_pnl = sum(_finite(trade.pnl) for trade in trades)
    completed_net = sum(_finite(
        trade.net_pnl if trade.net_pnl is not None
        else (trade.gross_pnl if trade.gross_pnl is not None else trade.pnl + trade.slippage_cost)
        - trade.commission - trade.slippage_cost
    ) for trade in trades)
    trade_commission = sum(_finite(trade.commission) for trade in trades)
    trade_slippage = sum(_finite(trade.slippage_cost) for trade in trades)
    fill_commission = sum(_finite(fill.commission) for fill in fills)
    fill_slippage = sum(_finite(fill.slippage_cost) for fill in fills)
    equity_profit = _finite(equity_derived_net_profit)
    difference = equity_profit - completed_net
    unrealized = _finite(final_unrealized_pnl)
    actual_ending_equity = _finite(starting_capital) + equity_profit
    expected_ending_equity = _finite(starting_capital) + completed_net + unrealized
    terminal_capital = (
        actual_ending_equity if final_capital is None else _finite(final_capital)
    )
    commission_difference = fill_commission - trade_commission
    slippage_difference = fill_slippage - trade_slippage
    final_capital_difference = terminal_capital - actual_ending_equity
    scale = max(
        abs(starting_capital), abs(actual_ending_equity), abs(completed_net),
        abs(fill_commission), abs(fill_slippage), 1.0,
    )
    exact_tolerance = max(1e-12, np.finfo(float).eps * 10.0 * scale)
    tolerance = max(1e-10, np.finfo(float).eps * 100.0 * scale)
    differences = [
        difference,
        commission_difference,
        slippage_difference,
        final_capital_difference,
        unrealized,
    ]

    if (
        not trades and not fills and abs(equity_profit) <= tolerance
        and int(open_position_count) == 0
    ):
        status = "not_applicable"
    elif int(open_position_count) == 0 and all(
        abs(value) <= exact_tolerance for value in differences
    ):
        status = "reconciled"
    elif int(open_position_count) == 0 and all(
        abs(value) <= tolerance for value in differences
    ):
        status = "difference_within_tolerance"
    else:
        status = "unreconciled"

    explanation = (
        "Differences may reflect open or unrealised positions, funding, forced "
        "closes, or engine-specific cash flows not represented by completed trades."
    )
    row = {
        "gross_completed_trade_pnl": gross_trade_pnl,
        "execution_price_pnl": execution_pnl,
        "total_commission": fill_commission,
        "total_slippage_cost": fill_slippage,
        "completed_trade_net_pnl": completed_net,
        "trade_total_commission": trade_commission,
        "fill_total_commission": fill_commission,
        "commission_difference": commission_difference,
        "trade_total_slippage_cost": trade_slippage,
        "fill_total_slippage_cost": fill_slippage,
        "slippage_difference": slippage_difference,
        "realized_gross_pnl": gross_trade_pnl,
        "unrealized_gross_pnl": unrealized,
        "expected_ending_equity": expected_ending_equity,
        "final_capital": terminal_capital,
        "open_position_count": int(open_position_count),
        "equity_derived_net_profit": equity_profit,
        "difference": difference,
        "final_capital_difference": final_capital_difference,
        "tolerance": tolerance,
        "reconciliation_status": status,
        "difference_explanation": explanation,
    }
    return pd.DataFrame([row], columns=RECONCILIATION_COLUMNS)


def build_concentration(executed_positions: pd.DataFrame) -> pd.DataFrame:
    """Calculate concentration from actual executed weights only."""
    if executed_positions is None or executed_positions.empty:
        return pd.DataFrame(columns=CONCENTRATION_COLUMNS)

    positions = executed_positions.fillna(0.0).astype(float).sort_index()
    rows: List[Dict[str, Any]] = []
    for timestamp, row in positions.iterrows():
        absolute = row.abs().sort_values(ascending=False)
        rows.append({
            "timestamp": pd.Timestamp(timestamp),
            "active_positions": int(row.ne(0.0).sum()),
            "largest_absolute_weight": _finite(absolute.iloc[0]) if len(absolute) else 0.0,
            "top_3_absolute_weight": _finite(absolute.iloc[:3].sum()),
            "hhi": _finite((absolute ** 2).sum()),
            "gross_exposure": _finite(absolute.sum()),
            "net_exposure": _finite(row.sum()),
        })
    return pd.DataFrame(rows, columns=CONCENTRATION_COLUMNS)


def concentration_metrics(concentration: pd.DataFrame) -> Dict[str, float]:
    if concentration is None or concentration.empty:
        return {
            "mean_hhi": 0.0,
            "maximum_hhi": 0.0,
            "mean_largest_absolute_weight": 0.0,
            "maximum_largest_absolute_weight": 0.0,
        }
    return {
        "mean_hhi": _finite(concentration["hhi"].mean()),
        "maximum_hhi": _finite(concentration["hhi"].max()),
        "mean_largest_absolute_weight": _finite(
            concentration["largest_absolute_weight"].mean()
        ),
        "maximum_largest_absolute_weight": _finite(
            concentration["largest_absolute_weight"].max()
        ),
    }


def build_performance_summary(
    daily_accounting: pd.DataFrame,
    trades: List[TradeRecord],
    scalar_metrics: Dict[str, Any],
    starting_capital: float,
    bars_per_year: Optional[int],
    drawdowns: pd.DataFrame,
) -> Dict[str, Any]:
    """Build a strict-JSON-safe performance summary."""
    starting = _finite(starting_capital)
    if daily_accounting is None or daily_accounting.empty:
        ending = starting
        gross_ending = starting
        net_returns = pd.Series(dtype=float)
        index = pd.DatetimeIndex([])
    else:
        ending = _finite(daily_accounting["equity"].iloc[-1], starting)
        gross_ending = _finite(daily_accounting["gross_equity"].iloc[-1], starting)
        net_returns = daily_accounting["net_return"].fillna(0.0).astype(float)
        index = pd.DatetimeIndex(daily_accounting.index)

    n = len(net_returns)
    bpy = _effective_bars_per_year(index, bars_per_year)
    volatility = _finite(net_returns.std()) if n > 1 else 0.0
    annualized_volatility = volatility * math.sqrt(bpy) if bpy > 0 else 0.0
    sharpe = (
        _finite(net_returns.mean()) / volatility * math.sqrt(bpy)
        if volatility > 1e-12 and bpy > 0 else 0.0
    )
    downside = net_returns[net_returns < 0]
    downside_std = _finite(downside.std()) if len(downside) > 1 else 0.0
    sortino = (
        _finite(net_returns.mean()) / downside_std * math.sqrt(bpy)
        if downside_std > 1e-12 and bpy > 0 else 0.0
    )
    equity = (
        daily_accounting["equity"].astype(float)
        if daily_accounting is not None and not daily_accounting.empty
        else pd.Series(dtype=float)
    )
    if equity.empty:
        maximum_drawdown = 0.0
    else:
        maximum_drawdown = _finite(
            ((equity - equity.cummax()) / equity.cummax().replace(0, np.nan)).min()
        )
    max_duration = (
        int(drawdowns["duration_days"].max()) if not drawdowns.empty else 0
    )
    holding_days = [
        _finite(trade.holding_days if trade.holding_days is not None else trade.holding_bars)
        for trade in trades
    ]
    net_total_return = ending / starting - 1.0 if abs(starting) > 1e-12 else 0.0
    gross_total_return = gross_ending / starting - 1.0 if abs(starting) > 1e-12 else 0.0
    total_cost = _finite(scalar_metrics.get("total_trading_cost", 0.0))

    summary = {
        "starting_capital": starting,
        "ending_capital": ending,
        "gross_ending_capital": gross_ending,
        "net_profit": ending - starting,
        "gross_profit": gross_ending - starting,
        "net_total_return": _finite(net_total_return),
        "gross_total_return": _finite(gross_total_return),
        "annualized_net_return": _annualized_return(starting, ending, n, bpy),
        "annualized_gross_return": _annualized_return(starting, gross_ending, n, bpy),
        "annualized_volatility": _finite(annualized_volatility),
        "sharpe_ratio": _finite(sharpe),
        "sortino_ratio": _finite(sortino),
        "maximum_drawdown": maximum_drawdown,
        "maximum_drawdown_duration_days": max_duration,
        "total_commission": _finite(scalar_metrics.get("total_commission", 0.0)),
        "total_slippage_cost": _finite(scalar_metrics.get("total_slippage_cost", 0.0)),
        "total_trading_cost": total_cost,
        "order_count": int(_finite(scalar_metrics.get("order_count", 0.0))),
        "filled_order_count": int(_finite(
            scalar_metrics.get("filled_order_count", 0.0)
        )),
        "cancelled_order_count": int(_finite(
            scalar_metrics.get("cancelled_order_count", 0.0)
        )),
        "partial_fill_order_count": int(_finite(
            scalar_metrics.get("partial_fill_order_count", 0.0)
        )),
        "total_requested_quantity": _finite(
            scalar_metrics.get("total_requested_quantity", 0.0)
        ),
        "total_filled_quantity": _finite(
            scalar_metrics.get("total_filled_quantity", 0.0)
        ),
        "total_cancelled_quantity": _finite(
            scalar_metrics.get("total_cancelled_quantity", 0.0)
        ),
        "total_unfilled_quantity": _finite(
            scalar_metrics.get("total_unfilled_quantity", 0.0)
        ),
        "fill_ratio": _finite(scalar_metrics.get("fill_ratio", 0.0)),
        "trading_cost_as_pct_starting_capital": (
            total_cost / starting if abs(starting) > 1e-12 else 0.0
        ),
        "total_one_way_turnover": _finite(scalar_metrics.get("total_one_way_turnover", 0.0)),
        "annualized_one_way_turnover": _finite(
            scalar_metrics.get("annualized_one_way_turnover", 0.0)
        ),
        "mean_gross_exposure": _finite(scalar_metrics.get("mean_gross_exposure", 0.0)),
        "maximum_gross_exposure": _finite(
            scalar_metrics.get("maximum_gross_exposure", 0.0)
        ),
        "mean_net_exposure": _finite(scalar_metrics.get("mean_net_exposure", 0.0)),
        "mean_active_positions": _finite(
            scalar_metrics.get("mean_active_positions", 0.0)
        ),
        "trade_count": len(trades),
        "win_rate": _finite(scalar_metrics.get("win_rate", 0.0)),
        "average_holding_days": float(np.mean(holding_days)) if holding_days else 0.0,
        "gross_values_method": (
            "Cost-reconciled from net returns; not independently resimulated without costs."
        ),
    }
    return {key: (_finite(value) if isinstance(value, (float, np.floating)) else value)
            for key, value in summary.items()}


def render_performance_report(
    summary: Dict[str, Any],
    monthly: pd.DataFrame,
    attribution: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> str:
    """Render deterministic, factual Markdown without recommendations."""
    net_profit = _finite(summary.get("net_profit", 0.0))
    result_label = "Profit" if net_profit > 0 else ("Loss" if net_profit < 0 else "Flat")
    lines = [
        "# Performance Report",
        "",
        "Gross figures are cost-reconciled estimates, not an independently resimulated no-cost run.",
        "",
        "## Summary",
        "",
        f"- Starting capital: {_finite(summary.get('starting_capital')):,.2f}",
        f"- Ending capital: {_finite(summary.get('ending_capital')):,.2f}",
        f"- Net result: {result_label} ({net_profit:,.2f})",
        f"- Net return: {_finite(summary.get('net_total_return')):.2%}",
        f"- Gross return: {_finite(summary.get('gross_total_return')):.2%}",
        f"- Commission: {_finite(summary.get('total_commission')):,.2f}",
        f"- Slippage cost: {_finite(summary.get('total_slippage_cost')):,.2f}",
        f"- Total trading costs: {_finite(summary.get('total_trading_cost')):,.2f}",
        f"- Order fill ratio: {_finite(summary.get('fill_ratio')):.2%}",
        f"- Partially filled orders: {int(summary.get('partial_fill_order_count', 0))}",
        f"- Cancelled orders: {int(summary.get('cancelled_order_count', 0))}",
        f"- Unfilled quantity: {_finite(summary.get('total_unfilled_quantity')):,.6f}",
        f"- Maximum drawdown: {_finite(summary.get('maximum_drawdown')):.2%}",
        f"- Maximum drawdown duration: {int(summary.get('maximum_drawdown_duration_days', 0))} days",
        f"- Total one-way turnover: {_finite(summary.get('total_one_way_turnover')):.4f}",
        f"- Mean gross exposure: {_finite(summary.get('mean_gross_exposure')):.2%}",
        f"- Mean net exposure: {_finite(summary.get('mean_net_exposure')):.2%}",
        f"- Trade count: {int(summary.get('trade_count', 0))}",
        f"- Win rate: {_finite(summary.get('win_rate')):.2%}",
        "",
        "## Attribution",
        "",
    ]
    if attribution.empty:
        lines.extend(["- Best contributing asset: N/A", "- Worst contributing asset: N/A"])
    else:
        best = attribution.loc[attribution["net_pnl"].idxmax()]
        worst = attribution.loc[attribution["net_pnl"].idxmin()]
        lines.extend([
            f"- Best contributing asset: {best['symbol']} ({_finite(best['net_pnl']):,.2f})",
            f"- Worst contributing asset: {worst['symbol']} ({_finite(worst['net_pnl']):,.2f})",
        ])

    lines.extend(["", "## Monthly Performance", ""])
    if monthly.empty:
        lines.extend(["- Best month: N/A", "- Worst month: N/A"])
    else:
        best_month = monthly.loc[monthly["net_return"].idxmax()]
        worst_month = monthly.loc[monthly["net_return"].idxmin()]
        lines.extend([
            f"- Best month: {best_month['month']} ({_finite(best_month['net_return']):.2%})",
            f"- Worst month: {worst_month['month']} ({_finite(worst_month['net_return']):.2%})",
        ])

    status = (
        str(reconciliation.iloc[0]["reconciliation_status"])
        if not reconciliation.empty else "not_applicable"
    )
    lines.extend([
        "",
        "## Cost Reconciliation",
        "",
        f"- Status: {status}",
        "- Differences may reflect open or unrealised positions, funding, forced closes, or engine-specific cash flows.",
        "",
        "## Warning",
        "",
        "Historical backtest results do not guarantee future profit.",
        "",
    ])
    return "\n".join(lines)


def build_reporting_outputs(
    daily_accounting: pd.DataFrame,
    executed_positions: pd.DataFrame,
    trades: List[TradeRecord],
    fills: List[FillRecord],
    scalar_metrics: Dict[str, Any],
    starting_capital: float,
    bars_per_year: Optional[int],
    orders: Optional[List[OrderRecord]] = None,
    final_capital: Optional[float] = None,
    final_unrealized_pnl: float = 0.0,
    open_position_count: int = 0,
) -> Dict[str, Any]:
    """Build all machine-readable and human-readable reporting outputs."""
    equity = (
        daily_accounting["equity"]
        if daily_accounting is not None and "equity" in daily_accounting else pd.Series(dtype=float)
    )
    drawdowns = analyze_drawdowns(equity)
    monthly = build_monthly_returns(daily_accounting)
    attribution = build_asset_attribution(trades)
    concentration = build_concentration(executed_positions)
    concentration_scalars = concentration_metrics(concentration)
    enriched_metrics = dict(scalar_metrics)
    enriched_metrics.update(calc_execution_metrics(
        executed_positions,
        fills,
        observation_count=len(daily_accounting) if daily_accounting is not None else 0,
        bars_per_year=bars_per_year,
        orders=orders,
    ))
    enriched_metrics.update(concentration_scalars)
    ending = _finite(equity.iloc[-1], starting_capital) if not equity.empty else starting_capital
    reconciliation = build_cost_reconciliation(
        trades,
        fills,
        ending - starting_capital,
        starting_capital,
        final_capital=final_capital,
        final_unrealized_pnl=final_unrealized_pnl,
        open_position_count=open_position_count,
    )
    summary = build_performance_summary(
        daily_accounting, trades, enriched_metrics, starting_capital,
        bars_per_year, drawdowns,
    )
    report = render_performance_report(summary, monthly, attribution, reconciliation)
    return {
        "performance_summary": summary,
        "monthly_returns": monthly,
        "drawdown_periods": drawdowns,
        "asset_attribution": attribution,
        "cost_reconciliation": reconciliation,
        "concentration": concentration,
        "concentration_metrics": concentration_scalars,
        "performance_report": report,
    }


def write_reporting_outputs(out: Path, outputs: Dict[str, Any]) -> None:
    """Write the Phase 3 reporting artifact set."""
    out.mkdir(parents=True, exist_ok=True)
    summary = outputs["performance_summary"]
    (out / "performance_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame([summary]).to_csv(out / "performance_summary.csv", index=False)
    outputs["monthly_returns"].to_csv(out / "monthly_returns.csv", index=False)
    outputs["drawdown_periods"].to_csv(out / "drawdown_periods.csv", index=False)
    outputs["asset_attribution"].to_csv(out / "asset_attribution.csv", index=False)
    outputs["cost_reconciliation"].to_csv(out / "cost_reconciliation.csv", index=False)
    outputs["concentration"].to_csv(out / "concentration.csv", index=False)
    (out / "performance_report.md").write_text(
        outputs["performance_report"], encoding="utf-8"
    )
