"""Enhanced backtest validation beyond the core Monte Carlo / bootstrap / WF trio.

Provides:
  - stress_scenarios — apply historical-style shocks to the equity return path
  - walk_forward_oos — rolling/expanding in-sample vs out-of-sample splits
  - parameter_sensitivity — robustness grid over return-scaling / vol / cost knobs
  - regime_conditioned — metrics conditioned on high/low volatility regimes

Hooked from ``backtest.validation.run_validation`` when the matching keys appear
under ``config["validation"]``.
"""

from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from backtest.models import TradeRecord


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
        "worst_return_scenario": min(results, key=lambda r: r["metrics"]["return"])["name"]
        if results
        else None,
        "worst_dd_scenario": min(results, key=lambda r: r["metrics"]["max_dd"])["name"]
        if results
        else None,
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
    if (
        isinstance(train_ratio, bool)
        or not isinstance(train_ratio, Real)
        or not 0.1 <= float(train_ratio) <= 0.9
    ):
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

        is_trades = [
            t for t in trades if is_start_ts <= t.entry_time <= is_end_ts
        ]
        oos_trades = [
            t for t in trades if oos_start_ts <= t.entry_time <= oos_end_ts
        ]

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
        "consistency_rate": round(
            float(sum(1 for r in oos_returns if r > 0) / len(folds)), 4
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


def regime_conditioned_backtest(
    equity_curve: pd.Series,
    trades: Optional[List[TradeRecord]] = None,
    *,
    vol_window: int = 21,
    high_vol_percentile: float = 70.0,
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Split performance into high-vol vs low-vol regimes via rolling volatility."""
    trades = trades or []
    if len(equity_curve) < vol_window + 5:
        return {"error": f"need at least {vol_window + 5} bars"}
    if isinstance(vol_window, bool) or not isinstance(vol_window, Integral) or vol_window < 2:
        return {"error": f"vol_window must be >= 2, got {vol_window}"}
    if (
        isinstance(high_vol_percentile, bool)
        or not isinstance(high_vol_percentile, Real)
        or not 50.0 <= float(high_vol_percentile) <= 95.0
    ):
        return {"error": f"high_vol_percentile must be in [50, 95], got {high_vol_percentile}"}

    rets = equity_curve.pct_change()
    rolling_vol = rets.rolling(int(vol_window)).std()
    threshold = float(rolling_vol.quantile(float(high_vol_percentile) / 100.0))
    high_mask = rolling_vol >= threshold
    low_mask = (~high_mask) & rolling_vol.notna()

    def _regime_slice(mask: pd.Series, label: str) -> Dict[str, Any]:
        # Rebuild a contiguous equity path from regime returns only.
        regime_rets = rets[mask].dropna()
        if len(regime_rets) < 2:
            return {"label": label, "bars": int(len(regime_rets)), "error": "insufficient bars"}
        start = float(equity_curve.iloc[0])
        path = start * np.cumprod(1.0 + regime_rets.to_numpy(dtype=float))
        eq = pd.Series(path, index=regime_rets.index)
        metrics = _window_metrics(eq, bars_per_year)
        # Count trades whose entry timestamp falls on a high/low bar.
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
        return {
            "label": label,
            "bars": int(mask.sum()),
            "trades": t_count,
            "vol_threshold": round(threshold, 8),
            **metrics,
        }

    high = _regime_slice(high_mask.fillna(False), "high_vol")
    low = _regime_slice(low_mask.fillna(False), "low_vol")
    overall = _window_metrics(equity_curve, bars_per_year)

    return {
        "vol_window": int(vol_window),
        "high_vol_percentile": float(high_vol_percentile),
        "vol_threshold": round(threshold, 8),
        "overall": overall,
        "regimes": {"high_vol": high, "low_vol": low},
        "sharpe_spread_high_minus_low": round(
            float(high.get("sharpe", 0.0)) - float(low.get("sharpe", 0.0)), 4
        ),
    }


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

    if "parameter_sensitivity" in config:
        p_cfg = (
            config["parameter_sensitivity"]
            if isinstance(config["parameter_sensitivity"], dict)
            else {}
        )
        results["parameter_sensitivity"] = parameter_sensitivity(
            equity_curve,
            return_scales=p_cfg.get("return_scales", (0.5, 0.75, 1.0, 1.25, 1.5)),
            vol_scales=p_cfg.get("vol_scales", (0.75, 1.0, 1.25, 1.5, 2.0)),
            cost_drags_bps=p_cfg.get("cost_drags_bps", (0.0, 5.0, 10.0, 25.0, 50.0)),
            bars_per_year=bars_per_year,
        )

    if "regime_conditioned" in config:
        r_cfg = (
            config["regime_conditioned"]
            if isinstance(config["regime_conditioned"], dict)
            else {}
        )
        results["regime_conditioned"] = regime_conditioned_backtest(
            equity_curve,
            trades,
            vol_window=int(r_cfg.get("vol_window", 21)),
            high_vol_percentile=float(r_cfg.get("high_vol_percentile", 70.0)),
            bars_per_year=bars_per_year,
        )

    return results
