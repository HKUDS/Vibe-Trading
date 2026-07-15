"""Shared backtest metrics, extracted from daily_portfolio.py for reuse.

Provides annualisation helpers, trade statistics, and full metric calculation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.models import FillRecord, OrderRecord, TradeRecord

# ─── Annualisation factor mapping ───

# mootdx (A-share) and futu (HK + A-share) are equity sources, so they mirror
# the tushare/akshare column: 252 trading days and a 240-minute session. HK
# sessions are marginally longer (~330 min) — an approximation in line with the
# rest of this annualisation table; the key fix is that intraday mootdx/futu no
# longer fall back to the bars_per_day=1 default, which mis-annualised vol/Sharpe.
_TRADING_DAYS = {"tushare": 252, "yfinance": 252, "okx": 365, "akshare": 252, "ccxt": 365, "mootdx": 252, "futu": 252}
_BARS_PER_DAY = {
    "1m":  {"tushare": 240, "okx": 1440, "yfinance": 390, "akshare": 240, "ccxt": 1440, "mootdx": 240, "futu": 240},
    "5m":  {"tushare": 48,  "okx": 288,  "yfinance": 78,  "akshare": 48,  "ccxt": 288,  "mootdx": 48,  "futu": 48},
    "15m": {"tushare": 16,  "okx": 96,   "yfinance": 26,  "akshare": 16,  "ccxt": 96,   "mootdx": 16,  "futu": 16},
    "30m": {"tushare": 8,   "okx": 48,   "yfinance": 13,  "akshare": 8,   "ccxt": 48,   "mootdx": 8,   "futu": 8},
    "1H":  {"tushare": 4,   "okx": 24,   "yfinance": 7,   "akshare": 4,   "ccxt": 24,   "mootdx": 4,   "futu": 4},
    "4H":  {"tushare": 1,   "okx": 6,    "yfinance": 2,   "akshare": 1,   "ccxt": 6,    "mootdx": 1,   "futu": 1},
    "1D":  {"tushare": 1,   "okx": 1,    "yfinance": 1,   "akshare": 1,   "ccxt": 1,    "mootdx": 1,   "futu": 1},
}


def calc_bars_per_year(interval: str = "1D", source: str = "tushare") -> int:
    """Number of bars per year for annualisation.

    Args:
        interval: Bar size (1m / 5m / 15m / 30m / 1H / 4H / 1D).
        source: Data source (tushare / yfinance / okx).

    Returns:
        Bars per year.
    """
    trading_days = _TRADING_DAYS.get(source, 252)
    bars_per_day = _BARS_PER_DAY.get(interval, {}).get(source, 1)
    return trading_days * bars_per_day


def win_rate_and_stats(trades: List[TradeRecord]) -> Dict[str, float]:
    """Win rate and P&L statistics from completed trades.

    Args:
        trades: Completed round-trip trades.

    Returns:
        Dict with win_rate, profit_loss_ratio, max_consecutive_loss,
        avg_holding_bars, profit_factor.
    """
    if not trades:
        return {
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "max_consecutive_loss": 0,
            "avg_holding_bars": 0.0,
            "profit_factor": 0.0,
        }

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]

    win_rate = len(wins) / len(trades)

    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = abs(float(np.mean(losses))) if losses else 1e-10
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 1e-10 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 1e-10
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-10 else 0.0

    max_consec = 0
    cur_consec = 0
    for t in trades:
        if t.pnl < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    hold_bars = [t.holding_bars for t in trades if t.holding_bars > 0]
    avg_holding = float(np.mean(hold_bars)) if hold_bars else 0.0

    return {
        "win_rate": win_rate,
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "max_consecutive_loss": max_consec,
        "avg_holding_bars": round(avg_holding, 1),
        "profit_factor": round(profit_factor, 4),
    }


def by_symbol_stats(trades: List[TradeRecord]) -> Dict[str, Dict[str, Any]]:
    """Per-symbol trade statistics.

    Args:
        trades: Completed round-trip trades.

    Returns:
        {symbol: {count, win_rate, total_pnl, avg_pnl}}.
    """
    groups: Dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.symbol, []).append(t)

    result = {}
    for sym, sym_trades in groups.items():
        pnls = [t.pnl for t in sym_trades]
        wins = [p for p in pnls if p > 0]
        result[sym] = {
            "count": len(sym_trades),
            "win_rate": round(len(wins) / len(sym_trades), 4) if sym_trades else 0.0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(float(np.mean(pnls)), 2) if pnls else 0.0,
        }
    return result


def by_exit_reason_stats(trades: List[TradeRecord]) -> Dict[str, Dict[str, Any]]:
    """Per-exit-reason trade statistics.

    Args:
        trades: Completed round-trip trades.

    Returns:
        {reason: {count, total_pnl}}.
    """
    groups: Dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.exit_reason, []).append(t)

    result = {}
    for reason, reason_trades in groups.items():
        pnls = [t.pnl for t in reason_trades]
        result[reason] = {
            "count": len(reason_trades),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def calc_turnover_series(positions: pd.DataFrame) -> pd.Series:
    """Per-bar weight-implied portfolio turnover from a position frame.

    Turnover for a bar is ``0.5 * sum_i |w_{t,i} - w_{t-1,i}|``, so a full
    rotation from one asset to another counts as 1.0 (matching the
    ``turnover_aware`` optimizer's convention). The first bar's turnover is
    ``0.5 * sum_i |w_{0,i}|``, treating the initial allocation as entry from
    cash. Turnover is measured on the weight frame the caller supplies. It
    does not know whether the execution engine filled, rounded, or rejected
    those target positions.

    Args:
        positions: Position-weight matrix (index=timestamp, columns=codes).

    Returns:
        Per-bar turnover series indexed like ``positions``; empty when the
        input is empty.
    """
    if positions is None or positions.empty:
        return pd.Series(dtype=float)
    filled = positions.fillna(0.0)
    prev = filled.shift(1).fillna(0.0)
    return 0.5 * (filled - prev).abs().sum(axis=1)


def calc_execution_metrics(
    executed_positions: pd.DataFrame,
    fills: List[FillRecord],
    observation_count: int,
    bars_per_year: Optional[int] = 252,
    orders: Optional[List[OrderRecord]] = None,
) -> Dict[str, float]:
    """Calculate scalar cost, turnover, and exposure metrics from executions.

    Turnover and exposure are based on actual executed weights, not target
    weights. Annualized turnover scales the observed one-way turnover by the
    number of observations and the effective bars-per-year value.
    """
    positions = (
        executed_positions.fillna(0.0)
        if executed_positions is not None
        else pd.DataFrame()
    )
    turnover = calc_turnover_series(positions)
    total_turnover = float(turnover.sum()) if not turnover.empty else 0.0

    n_obs = max(int(observation_count), 0)
    if bars_per_year is None:
        if n_obs > 1 and isinstance(positions.index, pd.DatetimeIndex):
            elapsed_days = max((positions.index[-1] - positions.index[0]).days, 0)
            years = elapsed_days / 365.25 if elapsed_days > 0 else 0.0
            effective_bpy = n_obs / years if years > 0 else float(n_obs)
        else:
            effective_bpy = float(n_obs)
    else:
        effective_bpy = max(float(bars_per_year), 0.0)
    annualized_turnover = (
        total_turnover * effective_bpy / n_obs if n_obs > 0 else 0.0
    )

    total_commission = float(sum(fill.commission for fill in fills))
    total_slippage = float(sum(fill.slippage_cost for fill in fills))
    order_records = orders or []
    total_requested = float(sum(order.requested_quantity for order in order_records))
    total_filled = float(sum(order.filled_quantity for order in order_records))
    total_cancelled = float(sum(order.cancelled_quantity for order in order_records))
    total_unfilled = float(sum(
        max(order.requested_quantity - order.filled_quantity, 0.0)
        for order in order_records
    ))
    fills_by_order: Dict[str, int] = {}
    fill_quantity_by_order: Dict[str, float] = {}
    for fill in fills:
        if fill.order_id:
            fills_by_order[fill.order_id] = fills_by_order.get(fill.order_id, 0) + 1
            fill_quantity_by_order[fill.order_id] = (
                fill_quantity_by_order.get(fill.order_id, 0.0)
                + abs(float(fill.quantity))
            )
    partial_fill_orders = sum(
        order.filled_quantity > 0
        and (
            fills_by_order.get(order.order_id, 0) > 1
            or order.filled_quantity + 1e-9 < order.requested_quantity
        )
        for order in order_records
    )

    order_ids = {order.order_id for order in order_records}
    unlinked_fills = sum(not bool(fill.order_id) for fill in fills)
    orphan_fills = sum(
        bool(fill.order_id) and fill.order_id not in order_ids for fill in fills
    )
    fill_quantity_mismatches = 0
    lifecycle_violations = 0
    for order in order_records:
        tolerance = max(1e-9, order.requested_quantity * 1e-9)
        recorded_fill_quantity = fill_quantity_by_order.get(order.order_id, 0.0)
        if abs(recorded_fill_quantity - order.filled_quantity) > tolerance:
            fill_quantity_mismatches += 1

        lifecycle_total = (
            order.filled_quantity
            + float(order.remaining_quantity or 0.0)
            + order.cancelled_quantity
        )
        lifecycle_valid = (
            abs(order.requested_quantity - lifecycle_total) <= tolerance
        )
        if order.status == "filled":
            lifecycle_valid = lifecycle_valid and (
                float(order.remaining_quantity or 0.0) <= tolerance
                and order.cancelled_quantity <= tolerance
            )
        elif order.status in {"cancelled", "expired", "rejected"}:
            lifecycle_valid = lifecycle_valid and (
                float(order.remaining_quantity or 0.0) <= tolerance
            )
        else:
            lifecycle_valid = lifecycle_valid and (
                float(order.remaining_quantity or 0.0) > tolerance
            )
        if not lifecycle_valid:
            lifecycle_violations += 1

    limit_price_violations = 0
    execution_before_eligibility = 0
    for fill in fills:
        tolerance = max(1e-9, abs(float(fill.fill_price)) * 1e-9)
        if fill.order_type == "limit" and fill.limit_price is not None:
            limit_price = float(fill.limit_price)
            if (
                (fill.side == "buy" and fill.fill_price > limit_price + tolerance)
                or (fill.side == "sell" and fill.fill_price < limit_price - tolerance)
            ):
                limit_price_violations += 1
        if (
            fill.eligible_bar_index is not None
            and fill.execution_bar_index is not None
        ):
            if fill.execution_bar_index < fill.eligible_bar_index:
                execution_before_eligibility += 1
        elif fill.eligible_time is not None:
            if pd.Timestamp(fill.timestamp) < pd.Timestamp(fill.eligible_time):
                execution_before_eligibility += 1

    volume_constrained_orders = sum(
        bool(order.volume_constrained) for order in order_records
    )
    volume_constraint_events = sum(
        max(int(order.volume_constrained_bars), 0) for order in order_records
    )
    exempt_volume_fills = sum(
        bool(fill.volume_limit_exempt) for fill in fills
    )
    participation_fill_quantity = float(sum(
        abs(float(fill.quantity))
        for fill in fills
        if fill.participation_rate is not None and not fill.volume_limit_exempt
    ))

    # A bar can contain more than one fill (for example, an exit followed by
    # a reversal entry). Validate the cap against their aggregate quantity,
    # not each fill independently.
    volume_by_bar: Dict[tuple[pd.Timestamp, str], Dict[str, float]] = {}
    for fill in fills:
        if fill.participation_rate is None or fill.volume_limit_exempt:
            continue
        key = (pd.Timestamp(fill.timestamp), fill.symbol)
        bucket = volume_by_bar.setdefault(key, {
            "quantity": 0.0,
            "bar_volume": 0.0,
            "capacity": 0.0,
        })
        bucket["quantity"] += abs(float(fill.quantity))
        if fill.bar_volume is not None:
            bucket["bar_volume"] = max(float(fill.bar_volume), 0.0)
        if fill.bar_volume_capacity is not None:
            bucket["capacity"] = max(float(fill.bar_volume_capacity), 0.0)

    observed_participation = []
    volume_limit_violations = 0
    for bucket in volume_by_bar.values():
        quantity = bucket["quantity"]
        bar_volume = bucket["bar_volume"]
        capacity = bucket["capacity"]
        if bar_volume > 0.0:
            observed_participation.append(quantity / bar_volume)
        tolerance = max(1e-9, capacity * 1e-9)
        if quantity > capacity + tolerance:
            volume_limit_violations += 1

    if positions.empty:
        gross_exposure = pd.Series(dtype=float)
        net_exposure = pd.Series(dtype=float)
        active_positions = pd.Series(dtype=float)
    else:
        gross_exposure = positions.abs().sum(axis=1)
        net_exposure = positions.sum(axis=1)
        active_positions = positions.ne(0.0).sum(axis=1)

    return {
        "total_commission": total_commission,
        "total_slippage_cost": total_slippage,
        "total_trading_cost": total_commission + total_slippage,
        "order_count": float(len(order_records)),
        "filled_order_count": float(sum(
            order.status == "filled" for order in order_records
        )),
        "cancelled_order_count": float(sum(
            order.status == "cancelled" for order in order_records
        )),
        "expired_order_count": float(sum(
            order.status == "expired" for order in order_records
        )),
        "rejected_order_count": float(sum(
            order.status == "rejected" for order in order_records
        )),
        "market_order_count": float(sum(
            order.order_type == "market" for order in order_records
        )),
        "limit_order_count": float(sum(
            order.order_type == "limit" for order in order_records
        )),
        "ioc_order_count": float(sum(
            order.time_in_force == "IOC" for order in order_records
        )),
        "fok_order_count": float(sum(
            order.time_in_force == "FOK" for order in order_records
        )),
        "deferred_order_count": float(sum(
            order.deferred_bars > 0 for order in order_records
        )),
        "total_deferred_bars": float(sum(
            order.deferred_bars for order in order_records
        )),
        "total_execution_attempts": float(sum(
            order.attempt_count for order in order_records
        )),
        "total_unfilled_eligible_bars": float(sum(
            order.unfilled_eligible_bars for order in order_records
        )),
        "limit_fill_count": float(sum(
            fill.order_type == "limit" for fill in fills
        )),
        "limit_price_violation_count": float(limit_price_violations),
        "execution_before_eligibility_count": float(
            execution_before_eligibility
        ),
        "unlinked_fill_count": float(unlinked_fills),
        "orphan_fill_count": float(orphan_fills),
        "fill_quantity_mismatch_count": float(fill_quantity_mismatches),
        "order_lifecycle_violation_count": float(lifecycle_violations),
        "partial_fill_order_count": float(partial_fill_orders),
        "volume_constrained_order_count": float(volume_constrained_orders),
        "volume_constraint_event_count": float(volume_constraint_events),
        "volume_limit_exempt_fill_count": float(exempt_volume_fills),
        "volume_participation_fill_quantity": participation_fill_quantity,
        "max_observed_volume_participation": (
            float(max(observed_participation)) if observed_participation else 0.0
        ),
        "mean_observed_volume_participation": (
            float(np.mean(observed_participation))
            if observed_participation else 0.0
        ),
        "volume_limit_violation_count": float(volume_limit_violations),
        "total_requested_quantity": total_requested,
        "total_filled_quantity": total_filled,
        "total_cancelled_quantity": total_cancelled,
        "total_unfilled_quantity": total_unfilled,
        "fill_ratio": total_filled / total_requested if total_requested > 0 else 0.0,
        "total_one_way_turnover": total_turnover,
        "annualized_one_way_turnover": float(annualized_turnover),
        "mean_gross_exposure": (
            float(gross_exposure.mean()) if not gross_exposure.empty else 0.0
        ),
        "maximum_gross_exposure": (
            float(gross_exposure.max()) if not gross_exposure.empty else 0.0
        ),
        "mean_net_exposure": (
            float(net_exposure.mean()) if not net_exposure.empty else 0.0
        ),
        "mean_active_positions": (
            float(active_positions.mean()) if not active_positions.empty else 0.0
        ),
    }


def calc_metrics(
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    initial_cash: float,
    bars_per_year: Optional[int] = 252,
    bench_ret: Optional[pd.Series] = None,
    positions: Optional[pd.DataFrame] = None,
    turnover_series: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Full set of performance metrics.

    Args:
        equity_curve: Equity time series (index=timestamp, values=equity).
        trades: Completed round-trip trades.
        initial_cash: Starting capital.
        bars_per_year: Bars per year for annualisation. None = auto-detect
            from equity curve dates (calendar-day method, for cross-market).
        bench_ret: Benchmark per-bar return series (optional).
        positions: Position-weight frame used as a backward-compatible
            turnover fallback when ``turnover_series`` is not supplied.
        turnover_series: Actual per-bar execution turnover (optional). When
            supplied, it takes precedence over position-implied turnover.

    Returns:
        Metrics dictionary (compatible with daily_portfolio format).
    """
    if len(equity_curve) == 0:
        return _empty_metrics(initial_cash)

    n = len(equity_curve)

    # Calendar-day annualization for cross-market (bars_per_year=None)
    if bars_per_year is None:
        first, last = equity_curve.index[0], equity_curve.index[-1]
        calendar_days = (last - first).days
        years = calendar_days / 365.25 if calendar_days > 0 else 1.0
        bpy = int(n / years) if years > 0 else 252
    else:
        bpy = bars_per_year

    port_ret = equity_curve.pct_change().fillna(0.0)

    total_ret = float(equity_curve.iloc[-1] / initial_cash - 1)
    # A leveraged/short book can end at or below zero equity (``total_ret <= -1``).
    # ``(1 + total_ret) ** fractional`` would then raise a negative base to a
    # fractional power, which Python evaluates to a ``complex`` and crashes the
    # subsequent ``float(...)``. A total wipeout annualises to -100%.
    growth = 1 + total_ret
    if growth <= 0:
        ann_ret = -1.0
    else:
        ann_ret = float(growth ** (bpy / max(n, 1)) - 1)
    # ``Series.std()`` uses ddof=1, so a single-observation return series
    # (e.g. a one-bar backtest) yields NaN and poisons the Sharpe ratio.
    # Guard the small sample the same way ``downside_std`` is guarded below.
    vol = float(port_ret.std()) if len(port_ret) > 1 else 0.0
    sharpe = float(port_ret.mean() / (vol + 1e-10) * np.sqrt(bpy))

    # Drawdown
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak.replace(0, 1)
    max_dd = float(dd.min())

    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-10 else 0.0

    # Sortino
    downside = port_ret[port_ret < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else 1e-10
    sortino = float(port_ret.mean() / (downside_std + 1e-10) * np.sqrt(bpy))

    trade_stats = win_rate_and_stats(trades)

    # Prefer execution-derived turnover; retain the position-frame fallback
    # for external callers of calc_metrics that do not have fill records.
    turnover_values = (
        turnover_series.reindex(equity_curve.index).fillna(0.0).clip(lower=0.0)
        if turnover_series is not None
        else calc_turnover_series(positions)
        if positions is not None
        else pd.Series(dtype=float)
    )
    avg_turnover = float(turnover_values.mean()) if len(turnover_values) > 0 else 0.0
    total_turnover = float(turnover_values.sum()) if len(turnover_values) > 0 else 0.0

    # Benchmark comparison
    bench_return = 0.0
    excess = 0.0
    ir = 0.0
    if bench_ret is not None and len(bench_ret) > 0:
        bench_return = float((1 + bench_ret).prod() - 1)
        excess = total_ret - bench_return
        active_ret = port_ret - bench_ret.reindex(port_ret.index).fillna(0.0)
        # Same ddof=1 small-sample guard as ``vol`` / ``downside_std`` so the
        # information ratio stays finite for a single-observation series.
        active_std = float(active_ret.std()) if len(active_ret) > 1 else 0.0
        ir = float(active_ret.mean() / (active_std + 1e-10) * np.sqrt(bpy))

    return {
        "final_value": float(equity_curve.iloc[-1]),
        "total_return": total_ret,
        "annual_return": ann_ret,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "win_rate": trade_stats["win_rate"],
        "profit_loss_ratio": trade_stats["profit_loss_ratio"],
        "profit_factor": trade_stats["profit_factor"],
        "max_consecutive_loss": trade_stats["max_consecutive_loss"],
        "avg_holding_days": trade_stats["avg_holding_bars"],
        "trade_count": len(trades),
        "benchmark_return": round(bench_return, 6),
        "excess_return": round(excess, 6),
        "information_ratio": round(ir, 4),
        "avg_turnover": round(avg_turnover, 6),
        "total_turnover": round(total_turnover, 6),
    }


def _empty_metrics(initial_cash: float) -> Dict[str, Any]:
    """Return zero-valued metrics when no data is available."""
    return {
        "final_value": initial_cash,
        "total_return": 0, "annual_return": 0, "max_drawdown": 0,
        "sharpe": 0, "calmar": 0, "sortino": 0,
        "win_rate": 0, "profit_loss_ratio": 0, "profit_factor": 0,
        "max_consecutive_loss": 0, "avg_holding_days": 0, "trade_count": 0,
        "benchmark_return": 0, "excess_return": 0, "information_ratio": 0,
        "avg_turnover": 0.0, "total_turnover": 0.0,
    }
