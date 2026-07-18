"""Shared backtest metrics, extracted from daily_portfolio.py for reuse.

Provides annualisation helpers, trade statistics, and full metric calculation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.models import TradeRecord

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


def calc_trade_turnover_series(
    trades: List[TradeRecord],
    equity_curve: pd.Series,
) -> pd.Series:
    """Per-bar turnover from actual entry and exit allocations.

    Each filled leg contributes its margin-equivalent traded value. Dividing
    gross traded value by twice the portfolio equity preserves the existing
    convention: entering a 100% allocation counts as 0.5 and rotating a 100%
    allocation between two assets counts as 1.0.

    Args:
        trades: Completed trades carrying actual entry/exit margin values.
        equity_curve: Portfolio equity used to normalize traded values.

    Returns:
        Per-bar realized turnover aligned to ``equity_curve``. Bars without
        fills are zero and remain part of the average-turnover denominator.
    """
    if equity_curve is None or equity_curve.empty:
        return pd.Series(dtype=float)

    traded_margin = pd.Series(0.0, index=equity_curve.index, dtype=float)
    for trade in trades:
        for timestamp, margin in (
            (trade.entry_time, trade.entry_margin),
            (trade.exit_time, trade.exit_margin),
        ):
            try:
                margin_value = float(margin)
            except (TypeError, ValueError):
                continue
            if (
                timestamp in traded_margin.index
                and np.isfinite(margin_value)
                and margin_value > 0
            ):
                traded_margin.loc[timestamp] += margin_value

    denominator = 2.0 * equity_curve.abs().replace(0.0, np.nan)
    return (traded_margin / denominator).replace([np.inf, -np.inf], np.nan).fillna(0.0)


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
