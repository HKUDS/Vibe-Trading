"""Enhanced backtest validation beyond the core Monte Carlo / bootstrap / WF trio.

Provides:
  - stress_scenarios — apply historical-style shocks to the equity return path
  - walk_forward_oos — rolling/expanding in-sample vs out-of-sample splits
  - walk_forward_risk_gated — WF OOS folds fail-closed on DD/PSR/DSR/CVaR gates
  - parameter_sensitivity — post-hoc robustness grid over return/vol/cost knobs
  - signal_parameter_grid — true signal-engine style param re-runs on a price series
  - signal_engine_param_grid — SignalEngine.generate() vertical slice over params
  - regime_conditioned — vol + trend (+ optional correlation-fused) regime splits
    with optional regime_labels export for factor_analysis hooks
  - regime_conditional_ic — Spearman IC overall + per-regime (uses export_regime_labels)

Hooked from ``backtest.validation.run_validation`` when the matching keys appear
under ``config["validation"]``.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import math
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from backtest.models import TradeRecord

# signal_fn(prices, **params) -> position series in {-1, 0, 1} (or continuous weight)
SignalFn = Callable[..., pd.Series]
# engine_factory(**params) -> object with .generate(data_map) -> Dict[str, Series]
EngineFactory = Callable[..., Any]

# Modules / builtins blocked when AST-scanning a run_dir SignalEngine re-exec.
_SIGNAL_ENGINE_FORBIDDEN_IMPORTS = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "ctypes",
        "shutil",
        "sys",
        "builtins",
        "importlib",
        "pathlib",
        "pickle",
        "marshal",
        "multiprocessing",
        "concurrent",
        "asyncio",
        "http",
        "urllib",
        "requests",
        "ftplib",
        "telnetlib",
        "webbrowser",
        "pty",
        "fcntl",
        "resource",
        "signal",
        "tempfile",
        "glob",
        "code",
        "codeop",
    }
)
_SIGNAL_ENGINE_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"})


def _sharpe(returns: np.ndarray, bars_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    std = float(np.std(returns))
    return float(np.mean(returns) / (std + 1e-10) * math.sqrt(bars_per_year))


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, 1)
    return float(dd.min())


def _window_metrics(equity: pd.Series, bars_per_year: int = 252) -> Dict[str, float]:
    if len(equity) < 2 or float(equity.iloc[0]) <= 0:
        return {"return": 0.0, "sharpe": 0.0, "max_dd": 0.0}
    ret = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    rets = equity.pct_change().dropna().to_numpy(dtype=float)
    return {
        "return": round(ret, 6),
        "sharpe": round(_sharpe(rets, bars_per_year), 4),
        "max_dd": round(_max_drawdown(equity), 6),
    }


# ─── Stress scenarios ───


_DEFAULT_STRESS: List[Dict[str, Any]] = [
    {"name": "flash_crash_10pct", "shock_return": -0.10, "spread_bars": 1},
    {"name": "correction_20pct", "shock_return": -0.20, "spread_bars": 5},
    {"name": "bear_market_40pct", "shock_return": -0.40, "spread_bars": 60},
    {"name": "vol_spike_2x", "vol_multiplier": 2.0},
    {"name": "vol_spike_3x", "vol_multiplier": 3.0},
    {"name": "liquidity_crunch", "shock_return": -0.08, "vol_multiplier": 1.5, "spread_bars": 3},
    # HFT / short-horizon bar-proxy stresses (not co-lo latency simulation)
    {
        "name": "adverse_selection_burst",
        "shock_return": -0.03,
        "vol_multiplier": 1.8,
        "spread_bars": 2,
        "note": "Proxy for informed-flow toxicity: short sharp adverse move + vol",
    },
    {
        "name": "latency_slippage_tax",
        "cost_drag_bps": 25.0,
        "note": "Proxy for delayed fills: extra cost drag on every bar return",
    },
    {
        "name": "adv_participation_stress",
        "cost_drag_bps": 40.0,
        "vol_multiplier": 1.4,
        "note": (
            "Proxy for eating through ADV: higher participation → impact + "
            "vol spike (bar-level; not LOB depth)"
        ),
    },
]


def stress_scenarios(
    equity_curve: pd.Series,
    scenarios: Optional[Sequence[Dict[str, Any]]] = None,
    bars_per_year: int = 252,
    seed: int = 42,
) -> Dict[str, Any]:
    """Apply shock / vol-stress scenarios to an equity curve and recompute metrics.

    Each scenario may specify:
      - shock_return: total multiplicative return shock applied over spread_bars
      - spread_bars: bars over which the shock is distributed (default 1)
      - vol_multiplier: scale residual returns around their mean
      - start_frac: where in [0,1] to place the shock (default mid-sample)
      - cost_drag_bps: subtract a constant per-bar cost (latency / slippage proxy)
    """
    if len(equity_curve) < 5:
        return {"error": "need at least 5 equity observations"}
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        return {"error": f"seed must be >= 0, got {seed}"}

    base = _window_metrics(equity_curve, bars_per_year)
    returns = equity_curve.pct_change().dropna().to_numpy(dtype=float)
    scenarios = list(scenarios) if scenarios else list(_DEFAULT_STRESS)
    results = []
    rng = np.random.default_rng(int(seed))

    for raw in scenarios:
        if not isinstance(raw, dict) or "name" not in raw:
            continue
        name = str(raw["name"])
        shocked = returns.copy()
        vol_mult = float(raw.get("vol_multiplier", 1.0))
        if vol_mult != 1.0:
            mu = float(np.mean(shocked))
            shocked = mu + (shocked - mu) * vol_mult

        shock_ret = raw.get("shock_return")
        if shock_ret is not None:
            shock_ret = float(shock_ret)
            spread = int(raw.get("spread_bars", 1))
            spread = max(1, min(spread, len(shocked)))
            start_frac = float(raw.get("start_frac", 0.5))
            start_frac = min(max(start_frac, 0.0), 0.95)
            start = int(start_frac * (len(shocked) - spread))
            # Convert total shock into per-bar simple returns: (1+R)^(1/n) - 1
            per_bar = (1.0 + shock_ret) ** (1.0 / spread) - 1.0
            shocked[start : start + spread] = per_bar

        # Optional noise so identical configs remain reproducible via seed.
        if raw.get("add_noise"):
            noise = float(raw["add_noise"])
            shocked = shocked + rng.normal(0.0, abs(noise), size=len(shocked))

        # Latency / adverse-selection cost tax (bps per bar on returns).
        cost_drag_bps = raw.get("cost_drag_bps")
        if cost_drag_bps is not None:
            shocked = shocked - abs(float(cost_drag_bps)) / 10_000.0

        start_eq = float(equity_curve.iloc[0])
        path = start_eq * np.cumprod(1.0 + shocked)
        idx = equity_curve.index[1 : len(path) + 1]
        stressed_eq = pd.Series(path, index=idx)
        metrics = _window_metrics(stressed_eq, bars_per_year)
        results.append(
            {
                "name": name,
                "shock_return": raw.get("shock_return"),
                "vol_multiplier": vol_mult,
                "cost_drag_bps": cost_drag_bps,
                "metrics": metrics,
                "delta_return": round(metrics["return"] - base["return"], 6),
                "delta_sharpe": round(metrics["sharpe"] - base["sharpe"], 4),
                "delta_max_dd": round(metrics["max_dd"] - base["max_dd"], 6),
            }
        )

    return {
        "baseline": base,
        "n_scenarios": len(results),
        "scenarios": results,
        "worst_return_scenario": min(results, key=lambda r: r["metrics"]["return"])["name"] if results else None,
        "worst_dd_scenario": min(results, key=lambda r: r["metrics"]["max_dd"])["name"] if results else None,
    }


# ─── Walk-forward OOS ───


def walk_forward_oos(
    equity_curve: pd.Series,
    trades: Optional[List[TradeRecord]] = None,
    n_windows: int = 5,
    train_ratio: float = 0.7,
    mode: str = "rolling",
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Rolling or expanding walk-forward with explicit IS / OOS splits.

    Unlike the simple non-overlapping window splitter, each fold reports
    in-sample and out-of-sample metrics so the IS→OOS degradation is visible.
    """
    trades = trades or []
    if isinstance(n_windows, bool) or not isinstance(n_windows, Integral) or n_windows < 1:
        return {"error": f"n_windows must be >= 1, got {n_windows}"}
    if isinstance(train_ratio, bool) or not isinstance(train_ratio, Real) or not 0.1 <= float(train_ratio) <= 0.9:
        return {"error": f"train_ratio must be in [0.1, 0.9], got {train_ratio}"}
    mode_norm = (mode or "rolling").strip().lower()
    if mode_norm not in {"rolling", "expanding"}:
        return {"error": f"mode must be rolling|expanding, got {mode}"}
    if len(equity_curve) < n_windows * 4:
        return {"error": f"need at least {n_windows * 4} bars for {n_windows} OOS windows"}

    n = len(equity_curve)
    # Reserve the last (1 - overlap) portion for successive OOS folds.
    oos_span = max(n // (n_windows + 1), 2)
    folds = []
    for i in range(int(n_windows)):
        oos_end = n - (int(n_windows) - 1 - i) * oos_span
        oos_start = oos_end - oos_span
        if oos_start < 4:
            continue
        if mode_norm == "expanding":
            is_start = 0
        else:
            is_len = max(int(oos_span * float(train_ratio) / (1.0 - float(train_ratio))), 4)
            is_start = max(0, oos_start - is_len)
        is_end = oos_start
        if is_end - is_start < 2:
            continue

        is_eq = equity_curve.iloc[is_start:is_end]
        oos_eq = equity_curve.iloc[oos_start:oos_end]
        is_m = _window_metrics(is_eq, bars_per_year)
        oos_m = _window_metrics(oos_eq, bars_per_year)

        is_start_ts = equity_curve.index[is_start]
        is_end_ts = equity_curve.index[is_end - 1]
        oos_start_ts = equity_curve.index[oos_start]
        oos_end_ts = equity_curve.index[oos_end - 1]

        def _ts(x: Any) -> str:
            return str(x.date()) if hasattr(x, "date") else str(x)

        is_trades = [t for t in trades if is_start_ts <= t.entry_time <= is_end_ts]
        oos_trades = [t for t in trades if oos_start_ts <= t.entry_time <= oos_end_ts]

        folds.append(
            {
                "fold": i + 1,
                "mode": mode_norm,
                "is": {
                    "start": _ts(is_start_ts),
                    "end": _ts(is_end_ts),
                    "bars": int(len(is_eq)),
                    "trades": len(is_trades),
                    **is_m,
                },
                "oos": {
                    "start": _ts(oos_start_ts),
                    "end": _ts(oos_end_ts),
                    "bars": int(len(oos_eq)),
                    "trades": len(oos_trades),
                    **oos_m,
                },
                "sharpe_degradation": round(is_m["sharpe"] - oos_m["sharpe"], 4),
                "return_degradation": round(is_m["return"] - oos_m["return"], 6),
            }
        )

    if not folds:
        return {"error": "unable to form walk-forward OOS folds with given parameters"}

    oos_sharpes = [f["oos"]["sharpe"] for f in folds]
    oos_returns = [f["oos"]["return"] for f in folds]
    degradations = [f["sharpe_degradation"] for f in folds]
    return {
        "n_windows": len(folds),
        "mode": mode_norm,
        "train_ratio": float(train_ratio),
        "folds": folds,
        "oos_sharpe_mean": round(float(np.mean(oos_sharpes)), 4),
        "oos_sharpe_std": round(float(np.std(oos_sharpes)), 4),
        "oos_return_mean": round(float(np.mean(oos_returns)), 6),
        "oos_profitable_folds": int(sum(1 for r in oos_returns if r > 0)),
        "mean_sharpe_degradation": round(float(np.mean(degradations)), 4),
        "consistency_rate": round(float(sum(1 for r in oos_returns if r > 0) / len(folds)), 4),
    }


def walk_forward_risk_gated(
    equity_curve: pd.Series,
    trades: Optional[List[TradeRecord]] = None,
    *,
    n_windows: int = 5,
    train_ratio: float = 0.7,
    mode: str = "rolling",
    bars_per_year: int = 252,
    max_dd_limit: float = 0.20,
    min_psr: float = 0.5,
    min_dsr: Optional[float] = None,
    max_cvar: Optional[float] = None,
    max_oos_dd: Optional[float] = None,
    max_sharpe_degradation: Optional[float] = None,
) -> Dict[str, Any]:
    """Walk-forward OOS combined with risk gates on each OOS fold.

    A fold *passes* when OOS |max_dd| / PSR / DSR / CVaR clear the gates
    (and optional degradation / OOS-DD caps). Strategies that look fine
    in-sample but blow OOS risk budgets fail closed.
    """
    base = walk_forward_oos(
        equity_curve,
        trades,
        n_windows=n_windows,
        train_ratio=train_ratio,
        mode=mode,
        bars_per_year=bars_per_year,
    )
    if "error" in base:
        return base

    from backtest.risk_metrics import score_trial_risk_adjusted

    # Recompute OOS slices with the same geometry as walk_forward_oos.
    n = len(equity_curve)
    oos_span = max(n // (int(n_windows) + 1), 2)
    mode_norm = (mode or "rolling").strip().lower()
    oos_dd_lim = float(max_oos_dd) if max_oos_dd is not None else float(max_dd_limit)

    gated_folds: List[Dict[str, Any]] = []
    n_pass = 0
    for fold in base.get("folds", []):
        i = int(fold.get("fold", 1)) - 1
        oos_end = n - (int(n_windows) - 1 - i) * oos_span
        oos_start = oos_end - oos_span
        oos_eq = equity_curve.iloc[max(0, oos_start) : min(n, oos_end)]
        rets = oos_eq.pct_change().dropna().to_numpy(dtype=float)
        scored = score_trial_risk_adjusted(
            rets,
            bars_per_year=bars_per_year,
            max_dd_limit=oos_dd_lim,
            min_psr=min_psr,
            min_dsr=min_dsr,
            max_cvar=max_cvar,
            n_trials=max(1, int(n_windows)),
        )
        deg = float(fold.get("sharpe_degradation", 0.0))
        deg_fail = (
            max_sharpe_degradation is not None
            and deg > float(max_sharpe_degradation) + 1e-12
        )
        passed = bool(scored.get("accepted")) and not deg_fail
        if passed:
            n_pass += 1
        gated_folds.append(
            {
                "fold": fold.get("fold"),
                "mode": mode_norm,
                "oos_metrics": fold.get("oos"),
                "sharpe_degradation": fold.get("sharpe_degradation"),
                "risk_score": {
                    k: scored.get(k)
                    for k in (
                        "accepted",
                        "score",
                        "sharpe",
                        "max_dd",
                        "psr",
                        "dsr",
                        "cvar",
                        "reject_reasons",
                    )
                },
                "passed": passed,
                "degradation_fail": deg_fail,
            }
        )

    n_folds = len(gated_folds)
    return {
        **base,
        "risk_gates": {
            "max_dd_limit": float(max_dd_limit),
            "max_oos_dd": oos_dd_lim,
            "min_psr": float(min_psr),
            "min_dsr": float(min_dsr) if min_dsr is not None else None,
            "max_cvar": float(max_cvar) if max_cvar is not None else None,
            "max_sharpe_degradation": (
                float(max_sharpe_degradation) if max_sharpe_degradation is not None else None
            ),
        },
        "gated_folds": gated_folds,
        "n_folds_passed": n_pass,
        "n_folds_failed": n_folds - n_pass,
        "pass_rate": round(n_pass / n_folds, 4) if n_folds else 0.0,
        "passed": n_pass == n_folds and n_folds > 0,
        "note": (
            "Walk-forward OOS folds gated by risk_adjusted score (DD/PSR/DSR/CVaR). "
            "Fail closed when any fold breaches risk budgets."
        ),
    }


# ─── Parameter sensitivity / robustness ───


def parameter_sensitivity(
    equity_curve: pd.Series,
    *,
    return_scales: Sequence[float] = (0.5, 0.75, 1.0, 1.25, 1.5),
    vol_scales: Sequence[float] = (0.75, 1.0, 1.25, 1.5, 2.0),
    cost_drags_bps: Sequence[float] = (0.0, 5.0, 10.0, 25.0, 50.0),
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Probe robustness by scaling returns, volatility, and per-bar cost drag.

    This is a post-hoc sensitivity layer on the realized equity path — useful
    when re-running the full signal engine over a parameter grid is expensive.
    Positive scales amplify edge; cost_drags_bps subtracts basis points per bar.
    """
    if len(equity_curve) < 5:
        return {"error": "need at least 5 equity observations"}

    returns = equity_curve.pct_change().dropna().to_numpy(dtype=float)
    start_eq = float(equity_curve.iloc[0])
    baseline = _window_metrics(equity_curve, bars_per_year)
    grid = []

    for rs in return_scales:
        for vs in vol_scales:
            for cost in cost_drags_bps:
                mu = float(np.mean(returns))
                centered = returns - mu
                adjusted = mu * float(rs) + centered * float(vs)
                adjusted = adjusted - (float(cost) / 10_000.0)
                path = start_eq * np.cumprod(1.0 + adjusted)
                eq = pd.Series(path, index=equity_curve.index[1 : len(path) + 1])
                metrics = _window_metrics(eq, bars_per_year)
                grid.append(
                    {
                        "return_scale": float(rs),
                        "vol_scale": float(vs),
                        "cost_drag_bps": float(cost),
                        **metrics,
                    }
                )

    sharpes = np.array([g["sharpe"] for g in grid], dtype=float)
    # Stability: fraction of grid points that keep Sharpe within 50% of baseline
    # (or stay non-negative when baseline Sharpe is near zero).
    base_s = baseline["sharpe"]
    if abs(base_s) < 1e-6:
        stable = float(np.mean(sharpes >= -0.1))
    else:
        stable = float(np.mean(np.abs(sharpes - base_s) <= 0.5 * abs(base_s)))

    best = max(grid, key=lambda g: g["sharpe"]) if grid else None
    worst = min(grid, key=lambda g: g["sharpe"]) if grid else None
    return {
        "baseline": baseline,
        "n_combinations": len(grid),
        "grid": grid,
        "sharpe_mean": round(float(np.mean(sharpes)), 4) if len(sharpes) else None,
        "sharpe_std": round(float(np.std(sharpes)), 4) if len(sharpes) else None,
        "sharpe_min": round(float(np.min(sharpes)), 4) if len(sharpes) else None,
        "sharpe_max": round(float(np.max(sharpes)), 4) if len(sharpes) else None,
        "stability_rate": round(stable, 4),
        "best": best,
        "worst": worst,
    }


# ─── Regime-conditioned backtests ───


def _count_trades_in_mask(trades: List[TradeRecord], mask: pd.Series) -> int:
    t_count = 0
    for t in trades:
        ts = t.entry_time
        if ts in mask.index and bool(mask.loc[ts]):
            t_count += 1
            continue
        if hasattr(ts, "normalize") and hasattr(mask.index, "normalize"):
            day = ts.normalize()
            matches = mask.index[mask.index.normalize() == day]
            if len(matches) and bool(mask.loc[matches[0]]):
                t_count += 1
    return t_count


def _regime_slice_metrics(
    equity_curve: pd.Series,
    rets: pd.Series,
    mask: pd.Series,
    label: str,
    trades: List[TradeRecord],
    bars_per_year: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Rebuild a contiguous equity path from regime returns only."""
    regime_rets = rets[mask].dropna()
    if len(regime_rets) < 2:
        out: Dict[str, Any] = {
            "label": label,
            "bars": int(mask.sum()) if mask.dtype == bool or mask.dtype == np.bool_ else int(len(regime_rets)),
            "error": "insufficient bars",
        }
        if extra:
            out.update(extra)
        return out
    start = float(equity_curve.iloc[0])
    path = start * np.cumprod(1.0 + regime_rets.to_numpy(dtype=float))
    eq = pd.Series(path, index=regime_rets.index)
    metrics = _window_metrics(eq, bars_per_year)
    result = {
        "label": label,
        "bars": int(mask.fillna(False).sum()),
        "trades": _count_trades_in_mask(trades, mask.fillna(False)),
        **metrics,
    }
    if extra:
        result.update(extra)
    return result


def _trend_masks(
    equity_curve: pd.Series,
    *,
    trend_window: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Causal trend labels from SMA slope of equity (up / down / flat)."""
    sma = equity_curve.rolling(int(trend_window), min_periods=max(2, trend_window // 2)).mean()
    slope = sma.diff()
    # Flat band: |slope| below median absolute non-nan slope * 0.25.
    abs_slope = slope.abs()
    band = float(abs_slope.dropna().median() or 0.0) * 0.25
    up = (slope > band) & slope.notna()
    down = (slope < -band) & slope.notna()
    flat = slope.notna() & ~up & ~down
    return up, down, flat


def _correlation_fused_mask(
    returns_matrix: pd.DataFrame,
    equity_index: pd.Index,
    *,
    corr_window: int = 60,
    edge_threshold: float = 0.5,
    smooth_window: int = 5,
    enter_threshold: float = 0.65,
    exit_threshold: float = 0.45,
) -> tuple[Optional[pd.Series], Optional[Dict[str, Any]]]:
    """Map correlation-regime FUSED state onto the equity index.

    Uses ``backtest.regime`` edge-density + hysteresis. Returns (fused_mask, meta)
    or (None, error_dict) when inputs are insufficient.
    """
    if returns_matrix is None or not isinstance(returns_matrix, pd.DataFrame):
        return None, {"error": "returns_matrix must be a DataFrame"}
    if returns_matrix.shape[1] < 2:
        return None, {"error": "returns_matrix needs >= 2 columns for correlation regimes"}
    if len(returns_matrix) < int(corr_window) + 5:
        return None, {"error": f"returns_matrix needs >= {int(corr_window) + 5} bars"}

    from backtest.regime import compute_edge_density, detect_regimes

    try:
        density = compute_edge_density(
            returns_matrix.astype(float),
            corr_window=int(corr_window),
            edge_threshold=float(edge_threshold),
        )
        regimes = detect_regimes(
            density,
            smooth_window=int(smooth_window),
            enter_threshold=float(enter_threshold),
            exit_threshold=float(exit_threshold),
        )
    except ValueError as exc:
        return None, {"error": str(exc)}

    fused = regimes["fused"].astype(bool)
    # Align to equity index (inner join on overlapping timestamps / normalized days).
    aligned = fused.reindex(equity_index)
    if aligned.isna().all() and hasattr(equity_index, "normalize"):
        fused_day = fused.copy()
        fused_day.index = fused_day.index.normalize()
        day_index = equity_index.normalize()
        aligned = pd.Series(
            [bool(fused_day.get(d, False)) if d in fused_day.index else False for d in day_index],
            index=equity_index,
        )
    else:
        aligned = aligned.fillna(False).astype(bool)

    meta = {
        "corr_window": int(corr_window),
        "edge_threshold": float(edge_threshold),
        "smooth_window": int(smooth_window),
        "enter_threshold": float(enter_threshold),
        "exit_threshold": float(exit_threshold),
        "fused_bars": int(aligned.sum()),
        "n_assets": int(returns_matrix.shape[1]),
    }
    return aligned, meta


def regime_conditioned_backtest(
    equity_curve: pd.Series,
    trades: Optional[List[TradeRecord]] = None,
    *,
    vol_window: int = 21,
    high_vol_percentile: float = 70.0,
    bars_per_year: int = 252,
    include_trend: bool = True,
    trend_window: int = 63,
    returns_matrix: Optional[pd.DataFrame] = None,
    corr_window: int = 60,
    edge_threshold: float = 0.5,
    smooth_window: int = 5,
    enter_threshold: float = 0.65,
    exit_threshold: float = 0.45,
    export_regime_labels: bool = False,
) -> Dict[str, Any]:
    """Split performance across vol, optional trend, and optional correlation regimes.

    Always reports high_vol / low_vol. When ``include_trend`` is True, also reports
    uptrend / downtrend / sideways and the 2×2 vol×trend cross. When a multi-asset
    ``returns_matrix`` is supplied, integrates correlation-regime FUSED/DEFUSED
    states from ``backtest.regime`` onto the equity timeline.

    When ``export_regime_labels`` is True, adds a ``regime_labels`` dict of
    date→label series (vol / trend / correlation) suitable for merging into
    factor_analysis panels or writing as a CSV sidecar.
    """
    trades = trades or []
    need = max(int(vol_window), int(trend_window) if include_trend else 0) + 5
    if len(equity_curve) < need:
        return {"error": f"need at least {need} bars"}
    if isinstance(vol_window, bool) or not isinstance(vol_window, Integral) or vol_window < 2:
        return {"error": f"vol_window must be >= 2, got {vol_window}"}
    if (
        isinstance(high_vol_percentile, bool)
        or not isinstance(high_vol_percentile, Real)
        or not 50.0 <= float(high_vol_percentile) <= 95.0
    ):
        return {"error": f"high_vol_percentile must be in [50, 95], got {high_vol_percentile}"}
    if include_trend and (isinstance(trend_window, bool) or not isinstance(trend_window, Integral) or trend_window < 2):
        return {"error": f"trend_window must be >= 2, got {trend_window}"}

    rets = equity_curve.pct_change()
    rolling_vol = rets.rolling(int(vol_window)).std()
    threshold = float(rolling_vol.quantile(float(high_vol_percentile) / 100.0))
    high_mask = rolling_vol >= threshold
    low_mask = (~high_mask) & rolling_vol.notna()

    high = _regime_slice_metrics(
        equity_curve,
        rets,
        high_mask.fillna(False),
        "high_vol",
        trades,
        bars_per_year,
        extra={"vol_threshold": round(threshold, 8)},
    )
    low = _regime_slice_metrics(
        equity_curve,
        rets,
        low_mask.fillna(False),
        "low_vol",
        trades,
        bars_per_year,
        extra={"vol_threshold": round(threshold, 8)},
    )
    overall = _window_metrics(equity_curve, bars_per_year)

    regimes: Dict[str, Any] = {"high_vol": high, "low_vol": low}
    result: Dict[str, Any] = {
        "vol_window": int(vol_window),
        "high_vol_percentile": float(high_vol_percentile),
        "vol_threshold": round(threshold, 8),
        "overall": overall,
        "regimes": regimes,
        "sharpe_spread_high_minus_low": round(float(high.get("sharpe", 0.0)) - float(low.get("sharpe", 0.0)), 4),
        "axes": ["vol"],
    }

    label_cols: Dict[str, pd.Series] = {}
    if export_regime_labels:
        vol_lab = pd.Series("unknown", index=equity_curve.index, dtype=object)
        vol_lab = vol_lab.mask(high_mask.fillna(False), "high_vol")
        vol_lab = vol_lab.mask(low_mask.fillna(False), "low_vol")
        label_cols["vol"] = vol_lab

    if include_trend:
        up, down, flat = _trend_masks(equity_curve, trend_window=int(trend_window))
        regimes["uptrend"] = _regime_slice_metrics(equity_curve, rets, up, "uptrend", trades, bars_per_year)
        regimes["downtrend"] = _regime_slice_metrics(equity_curve, rets, down, "downtrend", trades, bars_per_year)
        regimes["sideways"] = _regime_slice_metrics(equity_curve, rets, flat, "sideways", trades, bars_per_year)
        # Vol × trend cross (4 cells that usually have enough bars).
        cross = {}
        for v_label, v_mask in (("high_vol", high_mask.fillna(False)), ("low_vol", low_mask.fillna(False))):
            for t_label, t_mask in (("uptrend", up), ("downtrend", down)):
                label = f"{v_label}_{t_label}"
                cross[label] = _regime_slice_metrics(
                    equity_curve,
                    rets,
                    v_mask & t_mask,
                    label,
                    trades,
                    bars_per_year,
                )
        result["vol_trend_cross"] = cross
        result["trend_window"] = int(trend_window)
        result["axes"] = list(result["axes"]) + ["trend"]
        result["sharpe_spread_up_minus_down"] = round(
            float(regimes["uptrend"].get("sharpe", 0.0)) - float(regimes["downtrend"].get("sharpe", 0.0)),
            4,
        )
        if export_regime_labels:
            trend_lab = pd.Series("sideways", index=equity_curve.index, dtype=object)
            trend_lab = trend_lab.mask(up, "uptrend")
            trend_lab = trend_lab.mask(down, "downtrend")
            label_cols["trend"] = trend_lab

    if returns_matrix is not None:
        fused_mask, corr_meta = _correlation_fused_mask(
            returns_matrix,
            equity_curve.index,
            corr_window=corr_window,
            edge_threshold=edge_threshold,
            smooth_window=smooth_window,
            enter_threshold=enter_threshold,
            exit_threshold=exit_threshold,
        )
        if fused_mask is None:
            result["correlation_regime"] = corr_meta
        else:
            fused = _regime_slice_metrics(equity_curve, rets, fused_mask, "fused", trades, bars_per_year)
            defused = _regime_slice_metrics(equity_curve, rets, ~fused_mask, "defused", trades, bars_per_year)
            regimes["fused"] = fused
            regimes["defused"] = defused
            result["correlation_regime"] = {
                **(corr_meta or {}),
                "sharpe_spread_fused_minus_defused": round(
                    float(fused.get("sharpe", 0.0)) - float(defused.get("sharpe", 0.0)), 4
                ),
            }
            result["axes"] = list(result["axes"]) + ["correlation"]
            if export_regime_labels:
                corr_lab = pd.Series("defused", index=equity_curve.index, dtype=object)
                corr_lab = corr_lab.mask(fused_mask, "fused")
                label_cols["correlation"] = corr_lab

    if export_regime_labels and label_cols:
        # Compact JSON-friendly payload + note for factor_analysis merge.
        result["regime_labels"] = {axis: {str(k): str(v) for k, v in ser.items()} for axis, ser in label_cols.items()}
        result["regime_labels_note"] = (
            "Date→label maps for vol/trend/correlation axes; merge onto a "
            "factor panel (as columns) before calling factor_analysis, or write "
            "via regime_labels_to_frame()."
        )

    return result


def regime_labels_to_frame(regime_result: Dict[str, Any]) -> pd.DataFrame:
    """Convert ``regime_conditioned_backtest(... export_regime_labels=True)`` labels to a DataFrame.

    Useful as a sidecar for ``factor_analysis`` (join on date index).
    """
    labels = regime_result.get("regime_labels") if isinstance(regime_result, dict) else None
    if not isinstance(labels, dict) or not labels:
        return pd.DataFrame()
    cols = {}
    for axis, mapping in labels.items():
        if isinstance(mapping, dict):
            cols[axis] = pd.Series(mapping)
    if not cols:
        return pd.DataFrame()
    frame = pd.DataFrame(cols)
    try:
        frame.index = pd.to_datetime(frame.index)
    except (TypeError, ValueError):
        pass
    return frame.sort_index()


def _ic_summary(ic: pd.Series, *, min_obs: int) -> Dict[str, Any]:
    """Mean IC / ICIR / hit-rate summary for an IC series."""
    s = ic.dropna().astype(float) if isinstance(ic, pd.Series) else pd.Series(dtype=float)
    n = int(len(s))
    if n < int(min_obs):
        return {
            "n_obs": n,
            "mean_ic": None,
            "icir": None,
            "hit_rate": None,
            "insufficient_obs": True,
        }
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if n > 1 else float("nan")
    icir = mean / (std + 1e-15) * math.sqrt(max(n, 1)) if n > 1 else float("nan")
    hit = float((s > 0).mean())
    return {
        "n_obs": n,
        "mean_ic": round(mean, 6),
        "ic_std": round(std, 6) if math.isfinite(std) else None,
        "icir": round(float(icir), 6) if math.isfinite(icir) else None,
        "hit_rate": round(hit, 6),
        "insufficient_obs": False,
    }


def regime_conditional_ic(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    *,
    regime_result: Optional[Dict[str, Any]] = None,
    regime_labels: Optional[pd.DataFrame] = None,
    axis: str = "vol",
    min_obs: int = 20,
) -> Dict[str, Any]:
    """Spearman IC overall and split by regime labels (factor_analysis hook).

    Supply either:
      - ``regime_result`` from ``regime_conditioned_backtest(..., export_regime_labels=True)``
      - or a ``regime_labels`` DataFrame (e.g. from ``regime_labels_to_frame``)

    Computes daily IC via ``factor_analysis_core.compute_ic_series``, then
    summarises mean IC / ICIR / hit-rate overall and per label on ``axis``.
    """
    if not isinstance(factor_df, pd.DataFrame) or factor_df.empty:
        return {"error": "factor_df must be a non-empty DataFrame"}
    if not isinstance(return_df, pd.DataFrame) or return_df.empty:
        return {"error": "return_df must be a non-empty DataFrame"}
    if isinstance(min_obs, bool) or not isinstance(min_obs, Integral) or min_obs < 1:
        return {"error": f"min_obs must be >= 1, got {min_obs}"}

    if regime_labels is None:
        if not isinstance(regime_result, dict):
            return {"error": ("provide regime_result (export_regime_labels=True) or regime_labels DataFrame")}
        regime_labels = regime_labels_to_frame(regime_result)
    if not isinstance(regime_labels, pd.DataFrame) or regime_labels.empty:
        return {"error": "regime_labels is empty; enable export_regime_labels"}

    axis_key = str(axis)
    if axis_key not in regime_labels.columns:
        return {"error": (f"axis {axis_key!r} not in regime_labels columns {list(regime_labels.columns)}")}

    try:
        from src.factors.factor_analysis_core import compute_ic_series
    except ImportError:
        try:
            from factors.factor_analysis_core import compute_ic_series  # type: ignore
        except ImportError as exc:
            return {"error": f"factor_analysis_core unavailable: {exc}"}

    # Align date indices to timestamps when possible.
    factor_df = factor_df.copy()
    return_df = return_df.copy()
    labels = regime_labels.copy()
    try:
        factor_df.index = pd.to_datetime(factor_df.index)
        return_df.index = pd.to_datetime(return_df.index)
        labels.index = pd.to_datetime(labels.index)
    except (TypeError, ValueError):
        pass

    ic = compute_ic_series(factor_df, return_df)
    if ic.empty:
        return {"error": "compute_ic_series returned empty IC (check panel overlap)"}

    axis_labels = labels[axis_key].reindex(ic.index)
    overall = _ic_summary(ic, min_obs=int(min_obs))

    by_regime: Dict[str, Any] = {}
    for label, idx in axis_labels.groupby(axis_labels).groups.items():
        if label is None or (isinstance(label, float) and math.isnan(label)):
            continue
        by_regime[str(label)] = _ic_summary(ic.loc[idx], min_obs=int(min_obs))

    # Spread between the two most common regimes when available (e.g. high_vol − low_vol).
    spread = None
    if len(by_regime) >= 2:
        ranked = sorted(
            ((k, v) for k, v in by_regime.items() if not v.get("insufficient_obs") and v.get("mean_ic") is not None),
            key=lambda kv: kv[1]["n_obs"],
            reverse=True,
        )
        if len(ranked) >= 2:
            a, b = ranked[0], ranked[1]
            spread = {
                "a": a[0],
                "b": b[0],
                "mean_ic_a_minus_b": round(float(a[1]["mean_ic"]) - float(b[1]["mean_ic"]), 6),
            }

    return {
        "axis": axis_key,
        "overall": overall,
        "by_regime": by_regime,
        "ic_spread": spread,
        "n_ic_dates": int(len(ic)),
        "note": (
            "Regime-conditional Spearman IC using export_regime_labels / "
            "regime_labels_to_frame; join labels onto the factor panel date index "
            "before calling factor_analysis for full layered NAV diagnostics."
        ),
    }


# ─── True signal-parameter grid (re-run signals, not post-hoc equity scaling) ───


def _ma_crossover_signal(prices: pd.Series, fast: int = 10, slow: int = 30) -> pd.Series:
    fast_i, slow_i = int(fast), int(slow)
    if fast_i < 1 or slow_i < 2 or fast_i >= slow_i:
        return pd.Series(0.0, index=prices.index)
    f = prices.rolling(fast_i).mean()
    s = prices.rolling(slow_i).mean()
    pos = (f > s).astype(float)
    return pos.fillna(0.0)


def _breakout_signal(prices: pd.Series, lookback: int = 20, exit_lookback: int = 10) -> pd.Series:
    lb = max(2, int(lookback))
    ex = max(1, int(exit_lookback))
    hi = prices.rolling(lb).max().shift(1)
    lo = prices.rolling(ex).min().shift(1)
    pos = pd.Series(0.0, index=prices.index)
    long = False
    for i in range(len(prices)):
        px = float(prices.iloc[i])
        if not long and np.isfinite(hi.iloc[i]) and px >= float(hi.iloc[i]):
            long = True
        elif long and np.isfinite(lo.iloc[i]) and px <= float(lo.iloc[i]):
            long = False
        pos.iloc[i] = 1.0 if long else 0.0
    return pos


def _threshold_momentum_signal(prices: pd.Series, lookback: int = 21, entry_z: float = 0.5) -> pd.Series:
    lb = max(2, int(lookback))
    rets = prices.pct_change(lb)
    mu = rets.rolling(lb * 2, min_periods=lb).mean()
    sd = rets.rolling(lb * 2, min_periods=lb).std()
    z = (rets - mu) / (sd + 1e-12)
    return (z > float(entry_z)).astype(float).fillna(0.0)


def _rsi_mean_reversion_signal(
    prices: pd.Series,
    period: int = 14,
    lower: float = 30.0,
    upper: float = 70.0,
) -> pd.Series:
    """Long when RSI exits oversold; flat when overbought (classic MR band)."""
    p = max(2, int(period))
    delta = prices.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / p, min_periods=p).mean()
    avg_loss = loss.ewm(alpha=1.0 / p, min_periods=p).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    pos = pd.Series(0.0, index=prices.index)
    long = False
    lo, hi = float(lower), float(upper)
    for i in range(len(rsi)):
        v = float(rsi.iloc[i]) if np.isfinite(rsi.iloc[i]) else 50.0
        if not long and v <= lo:
            long = True
        elif long and v >= hi:
            long = False
        pos.iloc[i] = 1.0 if long else 0.0
    return pos


def _macd_crossover_signal(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.Series:
    f, s, sig = max(1, int(fast)), max(2, int(slow)), max(1, int(signal))
    if f >= s:
        return pd.Series(0.0, index=prices.index)
    ema_f = prices.ewm(span=f, adjust=False).mean()
    ema_s = prices.ewm(span=s, adjust=False).mean()
    macd = ema_f - ema_s
    macd_sig = macd.ewm(span=sig, adjust=False).mean()
    return (macd > macd_sig).astype(float).fillna(0.0)


def _vol_target_momentum_signal(
    prices: pd.Series,
    lookback: int = 21,
    vol_lookback: int = 21,
    target_vol: float = 0.15,
    bars_per_year: int = 252,
) -> pd.Series:
    """Sign of lookback momentum, scaled so realized vol ≈ target_vol."""
    lb = max(2, int(lookback))
    vl = max(2, int(vol_lookback))
    mom = np.sign(prices.pct_change(lb)).fillna(0.0)
    rets = prices.pct_change().fillna(0.0)
    realized = rets.rolling(vl).std() * math.sqrt(max(int(bars_per_year), 1))
    scale = float(target_vol) / (realized + 1e-8)
    scale = scale.clip(upper=3.0).fillna(0.0)
    return (mom * scale).fillna(0.0)


_BUILTIN_SIGNALS: Dict[str, SignalFn] = {
    "ma_crossover": _ma_crossover_signal,
    "breakout": _breakout_signal,
    "threshold_momentum": _threshold_momentum_signal,
    "rsi_mean_reversion": _rsi_mean_reversion_signal,
    "macd_crossover": _macd_crossover_signal,
    "vol_target_momentum": _vol_target_momentum_signal,
}

_DEFAULT_PARAM_GRIDS: Dict[str, Dict[str, Sequence[Any]]] = {
    "ma_crossover": {"fast": (5, 10, 15), "slow": (20, 40, 60)},
    "breakout": {"lookback": (10, 20, 40), "exit_lookback": (5, 10, 20)},
    "threshold_momentum": {"lookback": (10, 21, 42), "entry_z": (0.0, 0.5, 1.0)},
    "rsi_mean_reversion": {"period": (7, 14, 21), "lower": (25.0, 30.0), "upper": (70.0, 75.0)},
    "macd_crossover": {"fast": (8, 12), "slow": (21, 26), "signal": (5, 9)},
    "vol_target_momentum": {
        "lookback": (10, 21, 42),
        "vol_lookback": (21,),
        "target_vol": (0.10, 0.15, 0.20),
    },
}


def _positions_to_equity(
    prices: pd.Series,
    positions: pd.Series,
    *,
    initial_capital: float,
    cost_bps: float,
) -> pd.Series:
    """Long/flat (or signed) next-bar returns with turnover costs."""
    px = prices.astype(float)
    pos = positions.reindex(px.index).fillna(0.0).astype(float)
    # Trade at close → earn next bar return.
    asset_ret = px.pct_change().fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strat_ret = held * asset_ret - cost
    equity = float(initial_capital) * np.cumprod(1.0 + strat_ret.to_numpy(dtype=float))
    return pd.Series(equity, index=px.index)


def _positions_to_strategy_returns(
    prices: pd.Series,
    positions: pd.Series,
    *,
    cost_bps: float,
) -> pd.Series:
    px = prices.astype(float)
    pos = positions.reindex(px.index).fillna(0.0).astype(float)
    asset_ret = px.pct_change().fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    return held * asset_ret - cost


def _expand_param_grid(param_grid: Dict[str, Sequence[Any]]) -> List[Dict[str, Any]]:
    keys = list(param_grid.keys())
    if not keys:
        return [{}]
    values = [list(param_grid[k]) for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _normalize_param_value(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v)
    return v


def _score_grid_cells(
    cells: List[Dict[str, Any]],
    *,
    strategy_label: str,
    grid_spec: Dict[str, Sequence[Any]],
    cost_bps: float,
    trial_return_cols: Optional[List[np.ndarray]] = None,
    pbo_n_groups: int = 8,
    risk_ranking: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not cells:
        return {"error": "no grid cells evaluated"}

    sharpes = np.array([c["sharpe"] for c in cells], dtype=float)
    best = max(cells, key=lambda c: c["sharpe"])
    worst = min(cells, key=lambda c: c["sharpe"])
    med = float(np.median(sharpes))
    if abs(med) < 1e-6:
        stable = float(np.mean(sharpes >= -0.1))
    else:
        stable = float(np.mean(np.abs(sharpes - med) <= 0.5 * abs(med)))

    out: Dict[str, Any] = {
        "strategy": strategy_label,
        "n_combinations": len(cells),
        "cost_bps": float(cost_bps),
        "param_grid": {k: list(v) for k, v in grid_spec.items()},
        "grid": cells,
        "sharpe_mean": round(float(np.mean(sharpes)), 4),
        "sharpe_std": round(float(np.std(sharpes)), 4),
        "sharpe_min": round(float(np.min(sharpes)), 4),
        "sharpe_max": round(float(np.max(sharpes)), 4),
        "stability_rate": round(stable, 4),
        "best": best,
        "worst": worst,
        "note": (
            "True signal re-runs on the supplied price series — not post-hoc "
            "equity-path scaling (see parameter_sensitivity for that)."
        ),
    }

    if trial_return_cols is not None and len(trial_return_cols) >= 2:
        # Align lengths (drop leading bars where any trial is NaN-padded differently).
        min_len = min(len(c) for c in trial_return_cols)
        mat = np.column_stack([c[-min_len:] for c in trial_return_cols])
        out["trial_returns_shape"] = [int(mat.shape[0]), int(mat.shape[1])]
        # Keep compact list-of-lists for JSON configs / CSCV (caller may drop).
        out["trial_returns"] = np.round(mat, 10).tolist()
        try:
            from backtest.risk_metrics import cscv_probability_of_backtest_overfitting

            # Prefer smaller n_groups when T is modest.
            t_rows = mat.shape[0]
            groups = int(pbo_n_groups)
            while groups > 2 and t_rows < groups * 2:
                groups //= 2
            if groups % 2 == 1:
                groups = max(2, groups - 1)
            pbo = cscv_probability_of_backtest_overfitting(mat, n_groups=groups, bars_per_year=252)
            out["cscv_pbo"] = pbo
        except Exception as exc:  # pragma: no cover — defensive
            out["cscv_pbo"] = {"error": str(exc)}

        # Risk-adjusted ranking / hard gates (prefer over raw Sharpe max).
        try:
            from backtest.risk_metrics import rank_trials_risk_adjusted

            rk_cfg = risk_ranking if isinstance(risk_ranking, dict) else {}
            labels = [c.get("params", i) for i, c in enumerate(cells)]
            ranking = rank_trials_risk_adjusted(
                mat,
                bars_per_year=252,
                objective=str(rk_cfg.get("objective", "sharpe_dd_penalty")),
                max_dd_limit=float(rk_cfg.get("max_dd_limit", 0.20)),
                min_psr=float(rk_cfg.get("min_psr", 0.5)),
                min_dsr=(float(rk_cfg["min_dsr"]) if rk_cfg.get("min_dsr") is not None else None),
                max_cvar=(float(rk_cfg["max_cvar"]) if rk_cfg.get("max_cvar") is not None else None),
                cvar_alpha=float(rk_cfg.get("cvar_alpha", 0.95)),
                dd_penalty=float(rk_cfg.get("dd_penalty", 2.0)),
                labels=labels,
                fragile_fold_std=(
                    float(rk_cfg["fragile_fold_std"])
                    if rk_cfg.get("fragile_fold_std") is not None
                    else None
                ),
                fragile_n_folds=int(rk_cfg.get("fragile_n_folds", 4)),
            )
            out["risk_adjusted_ranking"] = {
                k: ranking[k]
                for k in (
                    "n_trials",
                    "n_accepted",
                    "n_rejected",
                    "objective",
                    "gates",
                    "best",
                    "ranking",
                    "rejected",
                    "note",
                )
                if k in ranking
            }
            # Prefer risk-gated best when any trial survives.
            if ranking.get("best") is not None:
                best_idx = int(ranking["best"]["trial_index"])
                if 0 <= best_idx < len(cells):
                    out["best_risk_adjusted"] = cells[best_idx]
                    out["best_risk_adjusted_score"] = ranking["best"]
        except Exception as exc:  # pragma: no cover — defensive
            out["risk_adjusted_ranking"] = {"error": str(exc)}

    return out


def signal_parameter_grid(
    prices: pd.Series,
    *,
    strategy: str = "ma_crossover",
    param_grid: Optional[Dict[str, Sequence[Any]]] = None,
    signal_fn: Optional[SignalFn] = None,
    bars_per_year: int = 252,
    cost_bps: float = 0.0,
    initial_capital: float = 1_000_000.0,
    max_combinations: int = 500,
    collect_trial_returns: bool = False,
    pbo_n_groups: int = 8,
    risk_ranking: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Re-run a signal function across a parameter grid and score each cell.

    Unlike :func:`parameter_sensitivity` (post-hoc equity-path scaling), this
    regenerates positions from ``prices`` for every parameter combination — a
    true signal-engine sensitivity vertical slice for common strategies and
    custom callables.

    Built-in ``strategy`` names: ``ma_crossover``, ``breakout``,
    ``threshold_momentum``, ``rsi_mean_reversion``, ``macd_crossover``,
    ``vol_target_momentum``. Pass ``signal_fn`` to override.

    When ``collect_trial_returns`` is True, attaches a ``(T, N)`` trial return
    matrix, CSCV PBO, and risk-adjusted ranking (max-DD / PSR / CVaR gates).
    """
    if not isinstance(prices, pd.Series) or len(prices) < 10:
        return {"error": "need a price Series with at least 10 observations"}
    if isinstance(cost_bps, bool) or not isinstance(cost_bps, Real) or cost_bps < 0:
        return {"error": f"cost_bps must be >= 0, got {cost_bps}"}
    if isinstance(max_combinations, bool) or not isinstance(max_combinations, Integral) or max_combinations < 1:
        return {"error": f"max_combinations must be >= 1, got {max_combinations}"}

    strategy_norm = (strategy or "ma_crossover").strip().lower()
    fn = signal_fn or _BUILTIN_SIGNALS.get(strategy_norm)
    if fn is None:
        return {"error": (f"unknown strategy {strategy!r}; use {sorted(_BUILTIN_SIGNALS)} or pass signal_fn")}

    grid_spec = param_grid or _DEFAULT_PARAM_GRIDS.get(strategy_norm, {})
    if not isinstance(grid_spec, dict):
        return {"error": "param_grid must be a dict of name -> sequence"}
    combos = _expand_param_grid(grid_spec)
    # Drop structurally invalid MA / MACD cells (fast >= slow) before the cap check.
    if strategy_norm in {"ma_crossover", "macd_crossover"} and signal_fn is None:
        combos = [p for p in combos if int(p.get("fast", 0)) < int(p.get("slow", 10**9))]
    if len(combos) > int(max_combinations):
        return {"error": (f"param_grid expands to {len(combos)} combinations; cap is {int(max_combinations)}")}
    if not combos:
        return {"error": "param_grid produced no valid combinations"}

    cells: List[Dict[str, Any]] = []
    trial_cols: List[np.ndarray] = []
    for params in combos:
        try:
            positions = fn(prices, **params)
        except TypeError as exc:
            return {"error": f"signal_fn rejected params {params}: {exc}"}
        if not isinstance(positions, pd.Series):
            return {"error": "signal_fn must return a pandas Series of positions"}
        eq = _positions_to_equity(
            prices,
            positions,
            initial_capital=float(initial_capital),
            cost_bps=float(cost_bps),
        )
        metrics = _window_metrics(eq, bars_per_year)
        turnover = float(positions.diff().abs().fillna(positions.abs()).mean())
        cells.append(
            {
                "params": {k: _normalize_param_value(v) for k, v in params.items()},
                "turnover_mean": round(turnover, 6),
                **metrics,
            }
        )
        if collect_trial_returns:
            strat_rets = _positions_to_strategy_returns(prices, positions, cost_bps=float(cost_bps))
            trial_cols.append(strat_rets.to_numpy(dtype=float))

    return _score_grid_cells(
        cells,
        strategy_label=strategy_norm if signal_fn is None else "custom",
        grid_spec=grid_spec,
        cost_bps=float(cost_bps),
        trial_return_cols=trial_cols if collect_trial_returns else None,
        pbo_n_groups=int(pbo_n_groups),
        risk_ranking=risk_ranking,
    )


def _prices_to_ohlcv_map(prices: pd.Series, symbol: str = "ASSET") -> Dict[str, pd.DataFrame]:
    close = prices.astype(float)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1.0,
        },
        index=prices.index,
    )
    return {symbol: df}


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _ast_scan_signal_engine_source(source: str) -> Optional[str]:
    """Return an error string if ``source`` uses blocked imports/calls; else None."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"syntax error in signal engine: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".", 1)[0]
                if root in _SIGNAL_ENGINE_FORBIDDEN_IMPORTS:
                    return f"forbidden import in SignalEngine module: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".", 1)[0] if mod else ""
            if root in _SIGNAL_ENGINE_FORBIDDEN_IMPORTS:
                return f"forbidden import in SignalEngine module: {mod or '.'}"
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _SIGNAL_ENGINE_FORBIDDEN_CALLS:
                return f"forbidden call in SignalEngine module: {name}()"
    return None


def _resolve_safe_signal_engine_path(
    module_path: Union[str, Path],
    *,
    allow_roots: Optional[Sequence[Union[str, Path]]] = None,
    run_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Resolve ``module_path`` and require it to sit under an allow-listed root."""
    path = Path(module_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"signal engine module not found: {path}")
    if path.suffix.lower() != ".py":
        raise ValueError(f"signal engine module must be a .py file, got {path.suffix!r}")

    roots: List[Path] = []
    if run_dir is not None:
        roots.append(Path(run_dir).expanduser().resolve())
    if allow_roots:
        roots.extend(Path(r).expanduser().resolve() for r in allow_roots)
    if not roots:
        # Default: cwd + common research artifact locations under cwd.
        roots.append(Path.cwd().resolve())

    if not any(_is_under_root(path, root) for root in roots):
        raise PermissionError(
            f"signal engine path {path} is outside allow_roots {[str(r) for r in roots]} (pass run_dir / allow_roots)"
        )
    return path


def _load_signal_engine_class(
    module_path: Union[str, Path],
    *,
    allow_roots: Optional[Sequence[Union[str, Path]]] = None,
    run_dir: Optional[Union[str, Path]] = None,
) -> type:
    path = _resolve_safe_signal_engine_path(module_path, allow_roots=allow_roots, run_dir=run_dir)
    source = path.read_text(encoding="utf-8")
    scan_err = _ast_scan_signal_engine_source(source)
    if scan_err:
        raise PermissionError(scan_err)

    spec = importlib.util.spec_from_file_location("_vt_signal_engine_grid", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, "SignalEngine", None)
    if cls is None:
        raise AttributeError(f"SignalEngine class not found in {path}")
    return cls


class _BuiltinEngineAdapter:
    """Wrap a builtin signal fn so it looks like SignalEngine.generate(data_map)."""

    def __init__(self, strategy: str, **params: Any) -> None:
        fn = _BUILTIN_SIGNALS.get(strategy)
        if fn is None:
            raise ValueError(f"unknown builtin strategy {strategy!r}")
        self._fn = fn
        self._params = params

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        out: Dict[str, pd.Series] = {}
        for sym, df in data_map.items():
            if "close" in df.columns:
                close = df["close"]
            else:
                close = df.iloc[:, 0]
            out[sym] = self._fn(close.astype(float), **self._params)
        return out


def signal_engine_param_grid(
    prices: pd.Series,
    *,
    param_grid: Dict[str, Sequence[Any]],
    engine_factory: Optional[EngineFactory] = None,
    module_path: Optional[Union[str, Path]] = None,
    strategy: Optional[str] = None,
    symbol: str = "ASSET",
    bars_per_year: int = 252,
    cost_bps: float = 0.0,
    initial_capital: float = 1_000_000.0,
    max_combinations: int = 200,
    collect_trial_returns: bool = True,
    pbo_n_groups: int = 8,
    risk_ranking: Optional[Dict[str, Any]] = None,
    run_dir: Optional[Union[str, Path]] = None,
    allow_roots: Optional[Sequence[Union[str, Path]]] = None,
) -> Dict[str, Any]:
    """Vertical slice: re-instantiate SignalEngine-like objects across a param grid.

    Provide one of:
      - ``engine_factory(**params)`` returning an object with ``.generate(data_map)``
      - ``module_path`` to a ``signal_engine.py`` defining ``class SignalEngine``
        (path must sit under ``run_dir`` / ``allow_roots``; source is AST-scanned
        to reject OS/network/exec style imports before ``exec_module``)
      - ``strategy`` builtin name (uses :class:`_BuiltinEngineAdapter`)

    Each cell calls ``generate`` on a synthetic OHLCV ``data_map`` built from
    ``prices``, converts the first symbol's signal to positions, and scores
    equity — closer to a real runner re-exec than bare signal callables.
    """
    if not isinstance(prices, pd.Series) or len(prices) < 10:
        return {"error": "need a price Series with at least 10 observations"}
    if not isinstance(param_grid, dict) or not param_grid:
        return {"error": "param_grid must be a non-empty dict"}
    if isinstance(max_combinations, bool) or not isinstance(max_combinations, Integral) or max_combinations < 1:
        return {"error": f"max_combinations must be >= 1, got {max_combinations}"}

    sources = sum(x is not None for x in (engine_factory, module_path, strategy))
    if sources != 1:
        return {
            "error": "provide exactly one of engine_factory, module_path, or strategy",
        }

    engine_cls: Optional[type] = None
    if module_path is not None:
        try:
            engine_cls = _load_signal_engine_class(module_path, allow_roots=allow_roots, run_dir=run_dir)
        except (OSError, ImportError, AttributeError, PermissionError, ValueError) as exc:
            return {"error": f"failed to load SignalEngine: {exc}"}

    strategy_norm = (strategy or "").strip().lower() if strategy else None
    if strategy_norm and strategy_norm not in _BUILTIN_SIGNALS:
        return {"error": f"unknown strategy {strategy!r}; use {sorted(_BUILTIN_SIGNALS)}"}

    combos = _expand_param_grid(param_grid)
    if strategy_norm in {"ma_crossover", "macd_crossover"}:
        combos = [p for p in combos if int(p.get("fast", 0)) < int(p.get("slow", 10**9))]
    if len(combos) > int(max_combinations):
        return {"error": (f"param_grid expands to {len(combos)} combinations; cap is {int(max_combinations)}")}
    if not combos:
        return {"error": "param_grid produced no valid combinations"}

    data_map = _prices_to_ohlcv_map(prices, symbol=symbol)
    cells: List[Dict[str, Any]] = []
    trial_cols: List[np.ndarray] = []

    for params in combos:
        try:
            if engine_factory is not None:
                engine = engine_factory(**params)
            elif engine_cls is not None:
                engine = engine_cls(**params)
            else:
                assert strategy_norm is not None
                engine = _BuiltinEngineAdapter(strategy_norm, **params)
            raw = engine.generate(data_map)
        except Exception as exc:
            return {"error": f"SignalEngine generate failed for {params}: {exc}"}

        if not isinstance(raw, dict) or not raw:
            return {"error": "SignalEngine.generate() must return a non-empty Dict[str, Series]"}
        first_key = symbol if symbol in raw else next(iter(raw))
        positions = raw[first_key]
        if not isinstance(positions, pd.Series):
            return {"error": f"signal for {first_key!r} must be a Series"}

        eq = _positions_to_equity(
            prices,
            positions,
            initial_capital=float(initial_capital),
            cost_bps=float(cost_bps),
        )
        metrics = _window_metrics(eq, bars_per_year)
        turnover = float(positions.diff().abs().fillna(positions.abs()).mean())
        cells.append(
            {
                "params": {k: _normalize_param_value(v) for k, v in params.items()},
                "turnover_mean": round(turnover, 6),
                **metrics,
            }
        )
        if collect_trial_returns:
            trial_cols.append(
                _positions_to_strategy_returns(prices, positions, cost_bps=float(cost_bps)).to_numpy(dtype=float)
            )

    if strategy_norm:
        label = f"signal_engine:{strategy_norm}"
    elif module_path is not None:
        label = f"signal_engine:{Path(module_path).name}"
    else:
        label = "signal_engine:custom"

    out = _score_grid_cells(
        cells,
        strategy_label=label,
        grid_spec=param_grid,
        cost_bps=float(cost_bps),
        trial_return_cols=trial_cols if collect_trial_returns else None,
        pbo_n_groups=int(pbo_n_groups),
        risk_ranking=risk_ranking,
    )
    out["interface"] = "SignalEngine.generate"
    out["symbol"] = symbol
    if module_path is not None:
        out["module_path_security"] = "allow_roots+ast_scan"
    return out


def run_enhanced_validation(
    config: Dict[str, Any],
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Run enhanced validators declared under ``config`` (already the validation sub-dict keys)."""
    results: Dict[str, Any] = {}

    if "stress" in config:
        s_cfg = config["stress"] if isinstance(config["stress"], dict) else {}
        results["stress"] = stress_scenarios(
            equity_curve,
            scenarios=s_cfg.get("scenarios"),
            bars_per_year=bars_per_year,
            seed=int(s_cfg.get("seed", 42)),
        )

    if "walk_forward_oos" in config:
        wf_cfg = config["walk_forward_oos"] if isinstance(config["walk_forward_oos"], dict) else {}
        results["walk_forward_oos"] = walk_forward_oos(
            equity_curve,
            trades,
            n_windows=int(wf_cfg.get("n_windows", 5)),
            train_ratio=float(wf_cfg.get("train_ratio", 0.7)),
            mode=str(wf_cfg.get("mode", "rolling")),
            bars_per_year=bars_per_year,
        )

    if "walk_forward_risk_gated" in config:
        wfg = (
            config["walk_forward_risk_gated"]
            if isinstance(config["walk_forward_risk_gated"], dict)
            else {}
        )
        results["walk_forward_risk_gated"] = walk_forward_risk_gated(
            equity_curve,
            trades,
            n_windows=int(wfg.get("n_windows", 5)),
            train_ratio=float(wfg.get("train_ratio", 0.7)),
            mode=str(wfg.get("mode", "rolling")),
            bars_per_year=bars_per_year,
            max_dd_limit=float(wfg.get("max_dd_limit", 0.20)),
            min_psr=float(wfg.get("min_psr", 0.5)),
            min_dsr=(float(wfg["min_dsr"]) if wfg.get("min_dsr") is not None else None),
            max_cvar=(float(wfg["max_cvar"]) if wfg.get("max_cvar") is not None else None),
            max_oos_dd=(float(wfg["max_oos_dd"]) if wfg.get("max_oos_dd") is not None else None),
            max_sharpe_degradation=(
                float(wfg["max_sharpe_degradation"])
                if wfg.get("max_sharpe_degradation") is not None
                else None
            ),
        )

    if "parameter_sensitivity" in config:
        p_cfg = config["parameter_sensitivity"] if isinstance(config["parameter_sensitivity"], dict) else {}
        results["parameter_sensitivity"] = parameter_sensitivity(
            equity_curve,
            return_scales=p_cfg.get("return_scales", (0.5, 0.75, 1.0, 1.25, 1.5)),
            vol_scales=p_cfg.get("vol_scales", (0.75, 1.0, 1.25, 1.5, 2.0)),
            cost_drags_bps=p_cfg.get("cost_drags_bps", (0.0, 5.0, 10.0, 25.0, 50.0)),
            bars_per_year=bars_per_year,
        )

    if "regime_conditioned" in config:
        r_cfg = config["regime_conditioned"] if isinstance(config["regime_conditioned"], dict) else {}
        returns_matrix = r_cfg.get("returns_matrix")
        if isinstance(returns_matrix, dict):
            returns_matrix = pd.DataFrame(returns_matrix)
        results["regime_conditioned"] = regime_conditioned_backtest(
            equity_curve,
            trades,
            vol_window=int(r_cfg.get("vol_window", 21)),
            high_vol_percentile=float(r_cfg.get("high_vol_percentile", 70.0)),
            bars_per_year=bars_per_year,
            include_trend=bool(r_cfg.get("include_trend", True)),
            trend_window=int(r_cfg.get("trend_window", 63)),
            returns_matrix=returns_matrix,
            corr_window=int(r_cfg.get("corr_window", 60)),
            edge_threshold=float(r_cfg.get("edge_threshold", 0.5)),
            smooth_window=int(r_cfg.get("smooth_window", 5)),
            enter_threshold=float(r_cfg.get("enter_threshold", 0.65)),
            exit_threshold=float(r_cfg.get("exit_threshold", 0.45)),
            export_regime_labels=bool(r_cfg.get("export_regime_labels", False)),
        )

    if "signal_parameter_grid" in config:
        g_cfg = config["signal_parameter_grid"] if isinstance(config["signal_parameter_grid"], dict) else {}
        prices = g_cfg.get("prices")
        if prices is None:
            # Fall back to equity curve as a proxy price series for demos.
            prices = equity_curve
        elif isinstance(prices, dict):
            prices = pd.Series(prices)
        elif isinstance(prices, list):
            prices = pd.Series(prices)

        # Prefer SignalEngine vertical slice when module_path / use_signal_engine set.
        if g_cfg.get("module_path") or g_cfg.get("use_signal_engine"):
            results["signal_parameter_grid"] = signal_engine_param_grid(
                prices,
                param_grid=g_cfg.get("param_grid")
                or _DEFAULT_PARAM_GRIDS.get(str(g_cfg.get("strategy", "ma_crossover")), {}),
                module_path=g_cfg.get("module_path"),
                strategy=(None if g_cfg.get("module_path") else str(g_cfg.get("strategy", "ma_crossover"))),
                symbol=str(g_cfg.get("symbol", "ASSET")),
                bars_per_year=bars_per_year,
                cost_bps=float(g_cfg.get("cost_bps", 0.0)),
                initial_capital=float(g_cfg.get("initial_capital", float(equity_curve.iloc[0]))),
                collect_trial_returns=bool(g_cfg.get("collect_trial_returns", True)),
                pbo_n_groups=int(g_cfg.get("pbo_n_groups", 8)),
                risk_ranking=g_cfg.get("risk_ranking"),
                run_dir=g_cfg.get("run_dir"),
                allow_roots=g_cfg.get("allow_roots"),
            )
        else:
            results["signal_parameter_grid"] = signal_parameter_grid(
                prices,
                strategy=str(g_cfg.get("strategy", "ma_crossover")),
                param_grid=g_cfg.get("param_grid"),
                bars_per_year=bars_per_year,
                cost_bps=float(g_cfg.get("cost_bps", 0.0)),
                initial_capital=float(g_cfg.get("initial_capital", float(equity_curve.iloc[0]))),
                collect_trial_returns=bool(g_cfg.get("collect_trial_returns", False)),
                pbo_n_groups=int(g_cfg.get("pbo_n_groups", 8)),
                risk_ranking=g_cfg.get("risk_ranking"),
            )

    if "regime_conditional_ic" in config:
        ic_cfg = config["regime_conditional_ic"] if isinstance(config["regime_conditional_ic"], dict) else {}
        factor_df = ic_cfg.get("factor_df")
        return_df = ic_cfg.get("return_df")
        if isinstance(factor_df, dict):
            factor_df = pd.DataFrame(factor_df)
        if isinstance(return_df, dict):
            return_df = pd.DataFrame(return_df)
        regime_src = ic_cfg.get("regime_result") or results.get("regime_conditioned")
        if not isinstance(factor_df, pd.DataFrame) or not isinstance(return_df, pd.DataFrame):
            results["regime_conditional_ic"] = {
                "error": "regime_conditional_ic requires factor_df and return_df",
            }
        else:
            results["regime_conditional_ic"] = regime_conditional_ic(
                factor_df,
                return_df,
                regime_result=regime_src if isinstance(regime_src, dict) else None,
                axis=str(ic_cfg.get("axis", "vol")),
                min_obs=int(ic_cfg.get("min_obs", 20)),
            )

    return results
