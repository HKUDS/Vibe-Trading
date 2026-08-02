"""Large-batch Monte Carlo path simulation for backtest validation.

Complements the trade-order permutation test in ``backtest.validation`` with
vectorized multi-path simulators capable of thousands to millions of paths:

  - ``gbm`` — geometric Brownian motion calibrated from returns (or explicit μ/σ)
  - ``bootstrap`` — i.i.d. historical return resampling
  - ``block_bootstrap`` — stationary block bootstrap (preserves short-run dependence)
  - ``correlated_gbm`` — multi-asset correlated GBM → portfolio paths
  - ``permute`` — delegates to the existing trade PnL permutation test

Supports antithetic variates (GBM family), Sobol / stratified QMC sampling for
GBM variance reduction, batched vectorization, optional threaded or process
parallelism (``n_jobs``; ProcessPool for GIL-bound block bootstrap), progress
reporting, and distributional aggregation (percentiles, ruin probability,
expected shortfall, confidence bands).
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
# Cap Sobol dimension to keep QMC tractable; beyond this fall back to LHS per batch.
MAX_SOBOL_DIM = 512


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
        f"p{int(p) if float(p).is_integer() else p}": round(float(np.percentile(tw, p)), 4) for p in percentile_levels
    }
    ret_pct = {
        f"p{int(p) if float(p).is_integer() else p}": round(float(np.percentile(returns, p)), 6)
        for p in percentile_levels
    }
    dd_pct = {
        f"p{int(p) if float(p).is_integer() else p}": round(float(np.percentile(mdd, p)), 6) for p in percentile_levels
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
    sample_rows = np.unique(np.linspace(0, n_paths - 1, min(MAX_FAN_PATHS, n_paths)).astype(int))
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
    """Vectorized stationary block bootstrap of historical returns.

    Draws all block starts up front, then gathers wrapped segments in one
    advanced-index operation (no Python per-path fill loop).
    """
    n = len(hist)
    block = max(1, min(int(block_size), n))
    n_blocks = int(math.ceil(int(horizon) / block))
    # (n_paths, n_blocks) start indices into hist
    starts = rng.integers(0, n, size=(int(n_paths), n_blocks))
    offsets = np.arange(block, dtype=np.int64)
    # (n_paths, n_blocks, block) → wrap-around indices
    idx = (starts[..., None].astype(np.int64) + offsets[None, None, :]) % n
    flat = hist[idx.reshape(int(n_paths), -1)]
    return flat[:, : int(horizon)]


def _block_bootstrap_batch_worker(
    hist: np.ndarray,
    n_paths: int,
    horizon: int,
    block_size: int,
    seed: int,
) -> np.ndarray:
    """Module-level worker for ProcessPool block-bootstrap batches."""
    rng = np.random.default_rng(int(seed))
    return _draw_block_bootstrap_returns(hist, n_paths, horizon, block_size, rng)


def _uniforms_to_normals(u: np.ndarray) -> np.ndarray:
    """Inverse-CDF map (0,1) → N(0,1) via erfinv (no scipy.stats required)."""
    from scipy.special import erfinv

    u = np.clip(np.asarray(u, dtype=float), 1e-12, 1.0 - 1e-12)
    return np.sqrt(2.0) * erfinv(2.0 * u - 1.0)


def _qmc_normal_matrix(
    n_paths: int,
    horizon: int,
    seed: int,
    *,
    method: str = "sobol",
) -> np.ndarray:
    """Draw (n_paths, horizon) standard normals via Sobol or Latin Hypercube."""
    from scipy.stats import qmc

    dim = int(horizon)
    n = int(n_paths)
    method_norm = method.lower()

    if method_norm == "sobol" and dim <= MAX_SOBOL_DIM:
        # Power-of-two friendly: generate next power of 2 then truncate.
        eng = qmc.Sobol(d=dim, scramble=True, seed=int(seed))
        m = max(1, math.ceil(math.log2(max(n, 2))))
        # Sobol.random(n) warns unless n is a power of 2; use random_base2.
        raw = eng.random_base2(m)
        u = raw[:n]
    else:
        # Stratified / LHS (also used when Sobol dim is too large).
        eng = qmc.LatinHypercube(d=dim, seed=int(seed))
        u = eng.random(n)
    return _uniforms_to_normals(u)


def _draw_gbm_returns(
    mu: float,
    sigma: float,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
    dt: float = 1.0,
    antithetic: bool = False,
    sampling: str = "iid",
    qmc_seed: Optional[int] = None,
) -> np.ndarray:
    """Lognormal GBM increments as simple returns.

    ``sampling``:
      - ``iid`` — standard normals (default)
      - ``sobol`` — scrambled Sobol QMC → normals (fallback to LHS if dim huge)
      - ``stratified`` — Latin Hypercube sampling → normals

    When ``antithetic`` is True with ``iid``, pair Z with −Z. With QMC,
    antithetic is applied after the QMC draw (pair and truncate).
    """
    sampling_norm = (sampling or "iid").strip().lower()
    if sampling_norm not in {"iid", "sobol", "stratified"}:
        raise ValueError(f"unknown sampling {sampling!r}; use iid|sobol|stratified")

    if sampling_norm == "iid":
        if antithetic:
            half = (n_paths + 1) // 2
            z_half = rng.standard_normal(size=(half, horizon))
            z = np.vstack([z_half, -z_half])[:n_paths]
        else:
            z = rng.standard_normal(size=(n_paths, horizon))
    else:
        seed_q = int(qmc_seed) if qmc_seed is not None else 0
        if antithetic:
            half = (n_paths + 1) // 2
            z_half = _qmc_normal_matrix(half, horizon, seed_q, method=sampling_norm)
            z = np.vstack([z_half, -z_half])[:n_paths]
        else:
            z = _qmc_normal_matrix(n_paths, horizon, seed_q, method=sampling_norm)

    # Exact GBM one-step simple return: exp((μ-σ²/2)dt + σ√dt Z) - 1
    drift = (mu - 0.5 * sigma * sigma) * dt
    diffusion = sigma * math.sqrt(dt) * z
    return np.exp(drift + diffusion) - 1.0


def _draw_correlated_gbm_portfolio_returns(
    mu: np.ndarray,
    cov: np.ndarray,
    weights: np.ndarray,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
    dt: float = 1.0,
    antithetic: bool = False,
    sampling: str = "iid",
    qmc_seed: Optional[int] = None,
) -> np.ndarray:
    """Multi-asset correlated GBM → portfolio simple-return paths.

    ``mu`` shape (n_assets,), ``cov`` (n_assets, n_assets), ``weights`` (n_assets,).
    Each step draws correlated log-returns, converts to simple returns per asset,
    then forms the weighted portfolio simple return.
    """
    mu = np.asarray(mu, dtype=float).reshape(-1)
    cov = np.asarray(cov, dtype=float)
    weights = np.asarray(weights, dtype=float).reshape(-1)
    n_assets = len(mu)
    if cov.shape != (n_assets, n_assets):
        raise ValueError(f"cov shape {cov.shape} != ({n_assets}, {n_assets})")
    if len(weights) != n_assets:
        raise ValueError("weights length must match mu")
    w_sum = float(np.sum(weights))
    if not math.isfinite(w_sum) or abs(w_sum) < 1e-15:
        raise ValueError("weights must sum to a non-zero finite value")
    weights = weights / w_sum

    # Symmetrise + jitter for numerical PSD, then Cholesky.
    sym = 0.5 * (cov + cov.T)
    try:
        chol = np.linalg.cholesky(sym)
    except np.linalg.LinAlgError:
        eigvals, eigvecs = np.linalg.eigh(sym)
        eigvals = np.clip(eigvals, 1e-12, None)
        chol = eigvecs @ np.diag(np.sqrt(eigvals))

    sampling_norm = (sampling or "iid").strip().lower()
    flat_dim = horizon * n_assets

    if sampling_norm == "iid":
        if antithetic:
            half = (n_paths + 1) // 2
            z_half = rng.standard_normal(size=(half, horizon, n_assets))
            z = np.concatenate([z_half, -z_half], axis=0)[:n_paths]
        else:
            z = rng.standard_normal(size=(n_paths, horizon, n_assets))
    else:
        seed_q = int(qmc_seed) if qmc_seed is not None else 0
        n_draw = (n_paths + 1) // 2 if antithetic else n_paths
        # Flatten time×asset into QMC dimensions; reshape after.
        z_flat = _qmc_normal_matrix(n_draw, flat_dim, seed_q, method=sampling_norm)
        z_half = z_flat.reshape(n_draw, horizon, n_assets)
        if antithetic:
            z = np.concatenate([z_half, -z_half], axis=0)[:n_paths]
        else:
            z = z_half

    # Correlated shocks: Z @ Lᵀ
    shock = z @ chol.T  # (n_paths, horizon, n_assets)
    drift = (mu - 0.5 * np.diag(sym)) * dt  # (n_assets,)
    # Asset simple returns
    asset_rets = np.exp(drift.reshape(1, 1, -1) + math.sqrt(dt) * shock) - 1.0
    # Portfolio simple return ≈ w·r (rebalanced each bar)
    return asset_rets @ weights


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
    antithetic: bool = False,
    n_jobs: int = 1,
    sampling: str = "iid",
    parallel_backend: str = "auto",
    # Multi-asset correlated GBM (method="correlated_gbm")
    asset_mu: Optional[Sequence[float]] = None,
    asset_cov: Optional[Sequence[Sequence[float]]] = None,
    asset_weights: Optional[Sequence[float]] = None,
    progress: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Run large-batch Monte Carlo path simulations.

    Args:
        method: ``gbm`` | ``bootstrap`` | ``block_bootstrap`` | ``correlated_gbm``.
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
        antithetic: Use antithetic variates for GBM / correlated_gbm (variance reduction).
        n_jobs: Parallel batch workers (1 = sequential).
        sampling: ``iid`` | ``sobol`` | ``stratified`` for GBM family QMC VR.
        parallel_backend: ``auto`` | ``thread`` | ``process``. Auto uses process
            pools for GIL-bound ``block_bootstrap`` when ``n_jobs>1``.
        asset_mu / asset_cov / asset_weights: Required for ``correlated_gbm``.
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
    if isinstance(n_jobs, bool) or not isinstance(n_jobs, Integral) or n_jobs < 1:
        return {"error": f"n_jobs must be >= 1, got {n_jobs}"}

    sampling_norm = (sampling or "iid").strip().lower()
    if sampling_norm not in {"iid", "sobol", "stratified"}:
        return {"error": f"unknown sampling {sampling!r}; use iid|sobol|stratified"}

    backend_norm = (parallel_backend or "auto").strip().lower()
    if backend_norm not in {"auto", "thread", "process"}:
        return {"error": f"unknown parallel_backend {parallel_backend!r}"}

    method_norm = (method or "").strip().lower()
    if method_norm not in {"gbm", "bootstrap", "block_bootstrap", "correlated_gbm"}:
        return {"error": (f"unknown method {method!r}; use gbm|bootstrap|block_bootstrap|correlated_gbm")}

    hist: Optional[np.ndarray] = None
    if method_norm != "correlated_gbm":
        if returns is not None:
            hist = np.asarray(list(returns), dtype=float)
            hist = hist[np.isfinite(hist)]
        elif equity_curve is not None and len(equity_curve) >= 2:
            hist = _returns_from_equity(equity_curve)
            if initial_capital == 1_000_000.0:
                first = float(equity_curve.iloc[0])
                if math.isfinite(first) and first > 0:
                    initial_capital = first
        else:
            return {"error": "need equity_curve or returns"}

        if hist is None or len(hist) < 5:
            return {"error": "need at least 5 return observations"}
    else:
        if asset_mu is None or asset_cov is None:
            return {"error": "correlated_gbm requires asset_mu and asset_cov"}
        if equity_curve is not None and initial_capital == 1_000_000.0:
            first = float(equity_curve.iloc[0])
            if math.isfinite(first) and first > 0:
                initial_capital = first

    if horizon is None:
        if hist is not None and equity_curve is not None:
            horizon = len(hist)
        else:
            horizon = DEFAULT_HORIZON
    if isinstance(horizon, bool) or not isinstance(horizon, Integral) or horizon < 2:
        return {"error": f"horizon must be >= 2, got {horizon}"}
    horizon = int(horizon)
    n_paths = int(n_paths)
    batch_size = int(min(int(batch_size), n_paths))
    n_jobs = int(n_jobs)

    # Calibrate GBM from sample if not provided.
    if hist is not None:
        sample_mu = float(np.mean(hist))
        sample_sigma = float(np.std(hist))
    else:
        sample_mu = float("nan")
        sample_sigma = float("nan")

    if method_norm == "gbm":
        use_mu = float(mu) if mu is not None else sample_mu
        use_sigma = float(sigma) if sigma is not None else sample_sigma
        if not math.isfinite(use_sigma) or use_sigma < 0:
            return {"error": f"sigma must be finite and >= 0, got {use_sigma}"}
    elif method_norm == "correlated_gbm":
        use_mu = float(mu) if mu is not None else 0.0
        use_sigma = float(sigma) if sigma is not None else 0.0
        try:
            mu_vec = np.asarray(list(asset_mu), dtype=float)  # type: ignore[arg-type]
            cov_mat = np.asarray(asset_cov, dtype=float)
            if asset_weights is None:
                w_vec = np.ones(len(mu_vec), dtype=float) / len(mu_vec)
            else:
                w_vec = np.asarray(list(asset_weights), dtype=float)
            # Dry-run validation
            _ = _draw_correlated_gbm_portfolio_returns(mu_vec, cov_mat, w_vec, 2, 2, np.random.default_rng(0))
        except (TypeError, ValueError) as exc:
            return {"error": f"correlated_gbm inputs invalid: {exc}"}
    else:
        use_mu = sample_mu
        use_sigma = sample_sigma

    # QMC only applies to GBM family; ignore silently for bootstrap methods.
    effective_sampling = sampling_norm if method_norm in {"gbm", "correlated_gbm"} else "iid"

    def _batch_returns(batch_n: int, batch_seed: int) -> np.ndarray:
        local_rng = np.random.default_rng(int(batch_seed))
        if method_norm == "bootstrap":
            assert hist is not None
            return _draw_bootstrap_returns(hist, batch_n, horizon, local_rng)
        if method_norm == "block_bootstrap":
            assert hist is not None
            return _draw_block_bootstrap_returns(hist, batch_n, horizon, block_size, local_rng)
        if method_norm == "correlated_gbm":
            return _draw_correlated_gbm_portfolio_returns(
                mu_vec,
                cov_mat,
                w_vec,
                batch_n,
                horizon,
                local_rng,
                antithetic=antithetic,
                sampling=effective_sampling,
                qmc_seed=batch_seed,
            )
        return _draw_gbm_returns(
            use_mu,
            use_sigma,
            batch_n,
            horizon,
            local_rng,
            antithetic=antithetic,
            sampling=effective_sampling,
            qmc_seed=batch_seed,
        )

    # Pre-split into batches with independent seeds for optional parallelism.
    batch_specs: List[tuple[int, int, int]] = []  # (offset, size, seed)
    offset = 0
    batch_i = 0
    while offset < n_paths:
        size = min(batch_size, n_paths - offset)
        batch_specs.append((offset, size, int(seed) + 1_000_003 * batch_i))
        offset += size
        batch_i += 1

    terminals: List[np.ndarray] = []
    drawdowns: List[np.ndarray] = []
    fan_source: Optional[np.ndarray] = None
    fan_budget = min(MAX_FAN_PATHS * 3, n_paths)

    # Choose parallel backend.
    use_process = False
    if n_jobs > 1 and len(batch_specs) > 1:
        if backend_norm == "process":
            use_process = True
        elif backend_norm == "auto" and method_norm == "block_bootstrap":
            use_process = True

    _emit(progress, "simulate", 0, n_paths, f"starting {method_norm} Monte Carlo")

    def _run_one(spec: tuple[int, int, int]) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
        off, size, bseed = spec
        rets = _batch_returns(size, bseed)
        equity, terminal, mdd = _simulate_return_paths(rets, float(initial_capital))
        return off, equity, terminal, mdd

    def _accumulate(off: int, equity: np.ndarray, terminal: np.ndarray, mdd: np.ndarray) -> None:
        nonlocal fan_source
        terminals.append(terminal)
        drawdowns.append(mdd)
        if keep_fan_chart and fan_source is None:
            take = min(fan_budget, equity.shape[0])
            fan_source = equity[:take].copy()
        elif keep_fan_chart and fan_source is not None and fan_source.shape[0] < fan_budget:
            need = fan_budget - fan_source.shape[0]
            fan_source = np.vstack([fan_source, equity[:need]])

    if n_jobs == 1 or len(batch_specs) == 1:
        done = 0
        for spec in batch_specs:
            off, equity, terminal, mdd = _run_one(spec)
            _accumulate(off, equity, terminal, mdd)
            done += spec[1]
            _emit(progress, "simulate", done, n_paths, f"completed {done}/{n_paths} paths")
    elif use_process and method_norm == "block_bootstrap":
        # Process pool for GIL-bound Python block-bootstrap loops.
        from concurrent.futures import ProcessPoolExecutor, as_completed

        assert hist is not None
        workers = min(int(n_jobs), len(batch_specs))
        ordered: Dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {}
            for spec in batch_specs:
                off, size, bseed = spec
                fut = pool.submit(
                    _block_bootstrap_batch_worker,
                    hist,
                    size,
                    horizon,
                    int(block_size),
                    bseed,
                )
                futs[fut] = off
            done = 0
            for fut in as_completed(futs):
                off = futs[fut]
                rets = fut.result()
                equity, terminal, mdd = _simulate_return_paths(rets, float(initial_capital))
                ordered[off] = (equity, terminal, mdd)
                done += equity.shape[0]
                _emit(progress, "simulate", done, n_paths, f"completed {done}/{n_paths} paths")
        for off in sorted(ordered):
            equity, terminal, mdd = ordered[off]
            _accumulate(off, equity, terminal, mdd)
    else:
        # Thread pool: numpy releases the GIL on large BLAS/ufunc work.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        workers = min(int(n_jobs), len(batch_specs))
        ordered = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one, spec): spec[0] for spec in batch_specs}
            done = 0
            for fut in as_completed(futs):
                off, equity, terminal, mdd = fut.result()
                ordered[off] = (equity, terminal, mdd)
                done += equity.shape[0]
                _emit(progress, "simulate", done, n_paths, f"completed {done}/{n_paths} paths")
        for off in sorted(ordered):
            equity, terminal, mdd = ordered[off]
            _accumulate(off, equity, terminal, mdd)

    terminal_wealth = np.concatenate(terminals)
    max_drawdowns = np.concatenate(drawdowns)
    _emit(progress, "aggregate", n_paths, n_paths, "aggregating distributional outcomes")

    used_backend = (
        "sequential"
        if n_jobs == 1 or len(batch_specs) == 1
        else ("process" if use_process and method_norm == "block_bootstrap" else "thread")
    )

    result: Dict[str, Any] = {
        "method": method_norm,
        "n_paths": n_paths,
        "horizon": horizon,
        "batch_size": batch_size,
        "seed": int(seed),
        "antithetic": bool(antithetic) and method_norm in {"gbm", "correlated_gbm"},
        "sampling": effective_sampling,
        "n_jobs": n_jobs,
        "parallel_backend": used_backend,
        "calibration": {
            "sample_mu": round(sample_mu, 8) if math.isfinite(sample_mu) else None,
            "sample_sigma": round(sample_sigma, 8) if math.isfinite(sample_sigma) else None,
            "mu": round(use_mu, 8),
            "sigma": round(use_sigma, 8),
            "n_history": int(len(hist)) if hist is not None else None,
            "block_size": int(block_size) if method_norm == "block_bootstrap" else None,
            "n_assets": int(len(mu_vec)) if method_norm == "correlated_gbm" else None,
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
        result["equity_paths"] = _fan_chart_payload(fan_source, initial_capital=float(initial_capital))
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
      ruin_level, es_alpha, keep_fan_chart, antithetic, n_jobs, sampling,
      parallel_backend, asset_mu, asset_cov, asset_weights
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
        antithetic=bool(cfg.get("antithetic", False)),
        n_jobs=int(cfg.get("n_jobs", 1)),
        sampling=str(cfg.get("sampling", "iid")),
        parallel_backend=str(cfg.get("parallel_backend", "auto")),
        asset_mu=cfg.get("asset_mu"),
        asset_cov=cfg.get("asset_cov"),
        asset_weights=cfg.get("asset_weights"),
        progress=progress,
    )
