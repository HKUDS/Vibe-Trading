"""Large-batch Monte Carlo path simulation for backtest validation.

Complements the trade-order permutation test in ``backtest.validation`` with
vectorized multi-path simulators capable of thousands to millions of paths:

  - ``gbm`` — geometric Brownian motion calibrated from returns (or explicit μ/σ)
  - ``bootstrap`` — i.i.d. historical return resampling
  - ``block_bootstrap`` — stationary block bootstrap (preserves short-run dependence)
  - ``permute`` — delegates to the existing trade PnL permutation test

Designed for batching, progress reporting, and distributional aggregation
(percentiles, ruin probability, expected shortfall, confidence bands).
"""

from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

ProgressCallback = Callable[[str, Optional[int], Optional[int], str], None]

# Sensible defaults for interactive / swarm use.
DEFAULT_N_PATHS = 10_000
DEFAULT_BATCH_SIZE = 5_000
DEFAULT_HORIZON = 252
MAX_PATHS = 5_000_000
# Keep a compact path sample for fan charts; full matrices stay out of JSON.
MAX_FAN_PATHS = 40
MAX_FAN_STEPS = 400


def _emit(
    progress: Optional[ProgressCallback],
    stage: str,
    current: Optional[int],
    total: Optional[int],
    message: str,
) -> None:
    if progress is not None:
        progress(stage, current, total, message)


def _validate_n_paths(n_paths: Any) -> Optional[str]:
    if isinstance(n_paths, bool) or not isinstance(n_paths, Integral) or n_paths < 1:
        return f"n_paths must be >= 1, got {n_paths}"
    if int(n_paths) > MAX_PATHS:
        return f"n_paths must be <= {MAX_PATHS}, got {n_paths}"
    return None


def _validate_seed(seed: Any) -> Optional[str]:
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        return f"seed must be >= 0, got {seed}"
    return None


def _returns_from_equity(equity_curve: pd.Series) -> np.ndarray:
    returns = equity_curve.pct_change().dropna().to_numpy(dtype=float)
    returns = returns[np.isfinite(returns)]
    return returns


def _max_drawdown_paths(equity: np.ndarray) -> np.ndarray:
    """Per-path max drawdown from an (n_paths, n_steps) equity matrix."""
    peak = np.maximum.accumulate(equity, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = (equity - peak) / np.where(peak > 0, peak, 1.0)
    return np.nanmin(dd, axis=1)


def _expected_shortfall(losses: np.ndarray, alpha: float = 0.95) -> float:
    """ES/CVaR on a loss distribution (positive = loss)."""
    if len(losses) == 0:
        return float("nan")
    cutoff = np.quantile(losses, alpha)
    tail = losses[losses >= cutoff]
    if len(tail) == 0:
        return float(cutoff)
    return float(np.mean(tail))


def aggregate_path_outcomes(
    terminal_wealth: np.ndarray,
    max_drawdowns: np.ndarray,
    *,
    initial_capital: float,
    ruin_level: float = 0.5,
    es_alpha: float = 0.95,
    percentile_levels: Sequence[float] = (1, 5, 10, 25, 50, 75, 90, 95, 99),
) -> Dict[str, Any]:
    """Aggregate distributional outcomes across simulated paths."""
    tw = np.asarray(terminal_wealth, dtype=float)
    mdd = np.asarray(max_drawdowns, dtype=float)
    returns = tw / initial_capital - 1.0
    losses = -returns  # positive when wealth falls

    ruin_threshold = initial_capital * float(ruin_level)
    ruin_prob = float(np.mean(tw <= ruin_threshold)) if len(tw) else float("nan")

    pct = {
        f"p{int(p) if float(p).is_integer() else p}": round(float(np.percentile(tw, p)), 4)
        for p in percentile_levels
    }
    ret_pct = {
        f"p{int(p) if float(p).is_integer() else p}": round(float(np.percentile(returns, p)), 6)
        for p in percentile_levels
    }
    dd_pct = {
        f"p{int(p) if float(p).is_integer() else p}": round(float(np.percentile(mdd, p)), 6)
        for p in percentile_levels
    }

    return {
        "n_paths": int(len(tw)),
        "initial_capital": round(float(initial_capital), 4),
        "ruin_level": float(ruin_level),
        "ruin_probability": round(ruin_prob, 6),
        "expected_shortfall_return": round(_expected_shortfall(losses, es_alpha), 6),
        "es_alpha": float(es_alpha),
        "terminal_wealth": {
            "mean": round(float(np.mean(tw)), 4),
            "std": round(float(np.std(tw)), 4),
            "min": round(float(np.min(tw)), 4),
            "max": round(float(np.max(tw)), 4),
            "percentiles": pct,
        },
        "total_return": {
            "mean": round(float(np.mean(returns)), 6),
            "std": round(float(np.std(returns)), 6),
            "percentiles": ret_pct,
            "prob_positive": round(float(np.mean(returns > 0)), 6),
            "prob_loss_gt_10pct": round(float(np.mean(returns < -0.10)), 6),
            "prob_loss_gt_20pct": round(float(np.mean(returns < -0.20)), 6),
        },
        "max_drawdown": {
            "mean": round(float(np.mean(mdd)), 6),
            "std": round(float(np.std(mdd)), 6),
            "worst": round(float(np.min(mdd)), 6),
            "percentiles": dd_pct,
        },
    }


def _fan_chart_payload(
    equity_batch: np.ndarray,
    *,
    initial_capital: float,
) -> Dict[str, Any]:
    """Downsample path matrix into confidence bands + sample paths."""
    n_paths, n_steps = equity_batch.shape
    step_idx = np.unique(np.linspace(0, n_steps - 1, min(n_steps, MAX_FAN_STEPS)).astype(int))
    sample_rows = np.unique(
        np.linspace(0, n_paths - 1, min(MAX_FAN_PATHS, n_paths)).astype(int)
    )
    sliced = equity_batch[:, step_idx]
    return {
        "steps": (step_idx + 1).tolist(),
        "initial_capital": round(float(initial_capital), 2),
        "band_p5": np.round(np.percentile(sliced, 5, axis=0), 2).tolist(),
        "band_p25": np.round(np.percentile(sliced, 25, axis=0), 2).tolist(),
        "band_p50": np.round(np.percentile(sliced, 50, axis=0), 2).tolist(),
        "band_p75": np.round(np.percentile(sliced, 75, axis=0), 2).tolist(),
        "band_p95": np.round(np.percentile(sliced, 95, axis=0), 2).tolist(),
        "samples": np.round(sliced[sample_rows], 2).tolist(),
    }


def _simulate_return_paths(
    returns_matrix: np.ndarray,
    initial_capital: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compound returns → equity paths; return equity, terminal, max DD."""
    # (n_paths, horizon)
    growth = np.cumprod(1.0 + returns_matrix, axis=1)
    equity = initial_capital * growth
    terminal = equity[:, -1]
    mdd = _max_drawdown_paths(equity)
    return equity, terminal, mdd


def _draw_bootstrap_returns(
    hist: np.ndarray,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray:
    idx = rng.integers(0, len(hist), size=(n_paths, horizon))
    return hist[idx]


def _draw_block_bootstrap_returns(
    hist: np.ndarray,
    n_paths: int,
    horizon: int,
    block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    n = len(hist)
    block = max(1, min(int(block_size), n))
    out = np.empty((n_paths, horizon), dtype=float)
    for i in range(n_paths):
        filled = 0
        while filled < horizon:
            start = int(rng.integers(0, n))
            take = min(block, horizon - filled)
            # Wrap around so every start is valid.
            segment = np.take(hist, np.arange(start, start + take) % n)
            out[i, filled : filled + take] = segment
            filled += take
    return out


def _draw_gbm_returns(
    mu: float,
    sigma: float,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
    dt: float = 1.0,
) -> np.ndarray:
    """Lognormal GBM increments as simple returns."""
    z = rng.standard_normal(size=(n_paths, horizon))
    # Exact GBM one-step simple return: exp((μ-σ²/2)dt + σ√dt Z) - 1
    drift = (mu - 0.5 * sigma * sigma) * dt
    diffusion = sigma * math.sqrt(dt) * z
    return np.exp(drift + diffusion) - 1.0


def run_monte_carlo_paths(
    *,
    method: str = "bootstrap",
    equity_curve: Optional[pd.Series] = None,
    returns: Optional[Sequence[float]] = None,
    initial_capital: float = 1_000_000.0,
    n_paths: int = DEFAULT_N_PATHS,
    horizon: Optional[int] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seed: int = 42,
    mu: Optional[float] = None,
    sigma: Optional[float] = None,
    block_size: int = 21,
    ruin_level: float = 0.5,
    es_alpha: float = 0.95,
    keep_fan_chart: bool = True,
    progress: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Run large-batch Monte Carlo path simulations.

    Args:
        method: ``gbm`` | ``bootstrap`` | ``block_bootstrap``.
        equity_curve: Optional equity series used to estimate returns / horizon.
        returns: Optional explicit return series (overrides equity-derived returns).
        initial_capital: Starting wealth.
        n_paths: Number of simulated paths (default 10_000, max 5_000_000).
        horizon: Path length in bars (default: len(returns) or 252).
        batch_size: Paths per vectorized batch (memory control).
        seed: RNG seed.
        mu / sigma: Optional GBM params (annualised daily if estimated from data).
        block_size: Block length for block bootstrap.
        ruin_level: Fraction of initial capital that counts as ruin (default 50%).
        es_alpha: Expected-shortfall confidence level.
        keep_fan_chart: Include downsampled confidence bands.
        progress: Optional ``(stage, current, total, message)`` callback.

    Returns:
        Dict with method metadata, aggregated distributional outcomes, and
        optional fan-chart payload.
    """
    err = _validate_n_paths(n_paths) or _validate_seed(seed)
    if err:
        return {"error": err}

    if isinstance(batch_size, bool) or not isinstance(batch_size, Integral) or batch_size < 1:
        return {"error": f"batch_size must be >= 1, got {batch_size}"}
    if isinstance(ruin_level, bool) or not isinstance(ruin_level, Real) or not 0.0 < ruin_level <= 1.0:
        return {"error": f"ruin_level must be in (0, 1], got {ruin_level}"}
    if isinstance(es_alpha, bool) or not isinstance(es_alpha, Real) or not 0.0 < es_alpha < 1.0:
        return {"error": f"es_alpha must be in (0, 1), got {es_alpha}"}

    method_norm = (method or "").strip().lower()
    if method_norm not in {"gbm", "bootstrap", "block_bootstrap"}:
        return {"error": f"unknown method {method!r}; use gbm|bootstrap|block_bootstrap"}

    if returns is not None:
        hist = np.asarray(list(returns), dtype=float)
        hist = hist[np.isfinite(hist)]
    elif equity_curve is not None and len(equity_curve) >= 2:
        hist = _returns_from_equity(equity_curve)
        if initial_capital == 1_000_000.0:
            # Prefer the actual starting equity when available.
            first = float(equity_curve.iloc[0])
            if math.isfinite(first) and first > 0:
                initial_capital = first
    else:
        return {"error": "need equity_curve or returns"}

    if len(hist) < 5:
        return {"error": "need at least 5 return observations"}

    if horizon is None:
        horizon = len(hist) if equity_curve is not None else DEFAULT_HORIZON
    if isinstance(horizon, bool) or not isinstance(horizon, Integral) or horizon < 2:
        return {"error": f"horizon must be >= 2, got {horizon}"}
    horizon = int(horizon)
    n_paths = int(n_paths)
    batch_size = int(min(int(batch_size), n_paths))

    # Calibrate GBM from sample if not provided.
    sample_mu = float(np.mean(hist))
    sample_sigma = float(np.std(hist))
    if method_norm == "gbm":
        use_mu = float(mu) if mu is not None else sample_mu
        use_sigma = float(sigma) if sigma is not None else sample_sigma
        if not math.isfinite(use_sigma) or use_sigma < 0:
            return {"error": f"sigma must be finite and >= 0, got {use_sigma}"}
    else:
        use_mu = sample_mu
        use_sigma = sample_sigma

    rng = np.random.default_rng(int(seed))
    terminals: List[np.ndarray] = []
    drawdowns: List[np.ndarray] = []
    fan_source: Optional[np.ndarray] = None
    fan_budget = min(MAX_FAN_PATHS * 3, n_paths)  # oversample then downsample

    _emit(progress, "simulate", 0, n_paths, f"starting {method_norm} Monte Carlo")
    done = 0
    while done < n_paths:
        this_batch = min(batch_size, n_paths - done)
        if method_norm == "bootstrap":
            rets = _draw_bootstrap_returns(hist, this_batch, horizon, rng)
        elif method_norm == "block_bootstrap":
            rets = _draw_block_bootstrap_returns(hist, this_batch, horizon, block_size, rng)
        else:
            rets = _draw_gbm_returns(use_mu, use_sigma, this_batch, horizon, rng)

        equity, terminal, mdd = _simulate_return_paths(rets, float(initial_capital))
        terminals.append(terminal)
        drawdowns.append(mdd)

        if keep_fan_chart and fan_source is None:
            take = min(fan_budget, this_batch)
            fan_source = equity[:take].copy()
        elif keep_fan_chart and fan_source is not None and fan_source.shape[0] < fan_budget:
            need = fan_budget - fan_source.shape[0]
            fan_source = np.vstack([fan_source, equity[:need]])

        done += this_batch
        _emit(progress, "simulate", done, n_paths, f"completed {done}/{n_paths} paths")

    terminal_wealth = np.concatenate(terminals)
    max_drawdowns = np.concatenate(drawdowns)
    _emit(progress, "aggregate", n_paths, n_paths, "aggregating distributional outcomes")

    result: Dict[str, Any] = {
        "method": method_norm,
        "n_paths": n_paths,
        "horizon": horizon,
        "batch_size": batch_size,
        "seed": int(seed),
        "calibration": {
            "sample_mu": round(sample_mu, 8),
            "sample_sigma": round(sample_sigma, 8),
            "mu": round(use_mu, 8),
            "sigma": round(use_sigma, 8),
            "n_history": int(len(hist)),
            "block_size": int(block_size) if method_norm == "block_bootstrap" else None,
        },
        "outcomes": aggregate_path_outcomes(
            terminal_wealth,
            max_drawdowns,
            initial_capital=float(initial_capital),
            ruin_level=float(ruin_level),
            es_alpha=float(es_alpha),
        ),
    }
    if keep_fan_chart and fan_source is not None:
        result["equity_paths"] = _fan_chart_payload(
            fan_source, initial_capital=float(initial_capital)
        )
    _emit(progress, "done", n_paths, n_paths, "Monte Carlo complete")
    return result


def run_monte_carlo_from_config(
    config: Dict[str, Any],
    equity_curve: pd.Series,
    trades: Optional[list] = None,
    initial_capital: float = 1_000_000.0,
    progress: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Dispatch Monte Carlo from a ``validation.monte_carlo_paths`` config block.

    Config keys (all optional except when method requires them):
      method, n_paths, horizon, batch_size, seed, mu, sigma, block_size,
      ruin_level, es_alpha, keep_fan_chart
    """
    cfg = config if isinstance(config, dict) else {}
    method = str(cfg.get("method", "bootstrap")).lower()

    if method == "permute":
        from backtest.validation import monte_carlo_test

        if not trades:
            return {"error": "permute method requires trades"}
        return monte_carlo_test(
            trades,
            initial_capital,
            n_simulations=int(cfg.get("n_paths", cfg.get("n_simulations", DEFAULT_N_PATHS))),
            seed=int(cfg.get("seed", 42)),
        )

    return run_monte_carlo_paths(
        method=method,
        equity_curve=equity_curve,
        initial_capital=initial_capital,
        n_paths=int(cfg.get("n_paths", DEFAULT_N_PATHS)),
        horizon=cfg.get("horizon"),
        batch_size=int(cfg.get("batch_size", DEFAULT_BATCH_SIZE)),
        seed=int(cfg.get("seed", 42)),
        mu=cfg.get("mu"),
        sigma=cfg.get("sigma"),
        block_size=int(cfg.get("block_size", 21)),
        ruin_level=float(cfg.get("ruin_level", 0.5)),
        es_alpha=float(cfg.get("es_alpha", 0.95)),
        keep_fan_chart=bool(cfg.get("keep_fan_chart", True)),
        progress=progress,
    )
