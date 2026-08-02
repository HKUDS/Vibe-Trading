"""Advanced risk / overfitting metrics for backtest validation.

Implements:
  - Probabilistic Sharpe Ratio (PSR) — Bailey & López de Prado (2012)
  - Deflated Sharpe Ratio (DSR) — Bailey & López de Prado (2014)
  - Bootstrap Sharpe CI (thin wrapper reusing validation.bootstrap_sharpe_ci)
  - Exact CSCV Probability of Backtest Overfitting (PBO) on per-trial return
    matrices — Bailey & López de Prado (2014)
  - Approximate PBO when only a vector of trial Sharpes is available
  - Risk-adjusted trial ranking with max-DD / PSR / CVaR gates

These are descriptive research diagnostics — not trading signals.
"""

from __future__ import annotations

import itertools
import math
from numbers import Integral
from typing import Any, Dict, Optional, Sequence, Union

import numpy as np
import pandas as pd


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (stdlib; avoids scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _sample_moments(returns: np.ndarray) -> Dict[str, float]:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return {"n": float(n), "mean": float("nan"), "std": float("nan"), "skew": 0.0, "kurtosis": 3.0}
    mean = float(np.mean(r))
    std = float(np.std(r, ddof=1)) if n > 1 else 0.0
    if std < 1e-15:
        return {"n": float(n), "mean": mean, "std": std, "skew": 0.0, "kurtosis": 3.0}
    z = (r - mean) / std
    skew = float(np.mean(z**3))
    # Pearson kurtosis (normal = 3)
    kurtosis = float(np.mean(z**4))
    return {"n": float(n), "mean": mean, "std": std, "skew": skew, "kurtosis": kurtosis}


def observed_sharpe(returns: np.ndarray, bars_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    std = float(np.std(r, ddof=1))
    return float(np.mean(r) / (std + 1e-15) * math.sqrt(bars_per_year))


def probabilistic_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sharpe_benchmark: float = 0.0,
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """PSR: P(true SR > SR*) under non-normal returns (Bailey & LdP 2012).

    ``sharpe`` / ``sharpe_benchmark`` are annualised; they are converted to
    per-bar Sharpes for the sampling-variance formula.
    """
    if isinstance(n_obs, bool) or not isinstance(n_obs, Integral) or n_obs < 2:
        return {"error": f"n_obs must be >= 2, got {n_obs}"}
    if not math.isfinite(float(sharpe)):
        return {"error": f"sharpe must be finite, got {sharpe}"}

    # Convert annualised → per-bar for the asymptotic variance.
    scale = math.sqrt(max(int(bars_per_year), 1))
    sr = float(sharpe) / scale
    sr_star = float(sharpe_benchmark) / scale
    n = int(n_obs)
    g3 = float(skew)
    g4 = float(kurtosis)

    # σ̂(SR) ≈ sqrt( (1 - γ3·SR + (γ4-1)/4 · SR²) / (n-1) )
    inside = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr
    inside = max(inside, 1e-12)
    se = math.sqrt(inside / max(n - 1, 1))
    z = (sr - sr_star) / se
    psr = _norm_cdf(z)
    return {
        "observed_sharpe": round(float(sharpe), 6),
        "benchmark_sharpe": round(float(sharpe_benchmark), 6),
        "n_obs": n,
        "skew": round(g3, 6),
        "kurtosis": round(g4, 6),
        "psr": round(float(psr), 6),
        "z_stat": round(float(z), 6),
        "se_per_bar_sharpe": round(float(se), 8),
        "bars_per_year": int(bars_per_year),
    }


def expected_max_sharpe(
    n_trials: int,
    *,
    variance_of_sharpe: float = 1.0,
) -> float:
    """Expected maximum Sharpe under n independent trials (Euler-Mascheroni approx).

    E[max SR] ≈ σ · ((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)))
    with γ ≈ 0.5772156649. For N=1 returns 0.
    """
    if isinstance(n_trials, bool) or not isinstance(n_trials, Integral) or n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return 0.0

    def _ppf(p: float) -> float:
        """Approximate standard-normal quantile (Abramowitz & Stegun 26.2.23)."""
        p = min(max(float(p), 1e-12), 1.0 - 1e-12)
        if p < 0.5:
            return -_ppf(1.0 - p)
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        # Rational approximation; then 2 Newton polish steps on Φ.
        x = t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (
            1.0 + 1.330274 * t + 0.189269 * t * t + 0.001308 * t * t * t
        )
        for _ in range(2):
            fx = _norm_cdf(x) - p
            dens = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
            x -= fx / max(dens, 1e-15)
        return x

    gamma = 0.5772156649
    n = float(n_trials)
    emax = (1.0 - gamma) * _ppf(1.0 - 1.0 / n) + gamma * _ppf(1.0 - 1.0 / (n * math.e))
    return float(math.sqrt(max(float(variance_of_sharpe), 0.0)) * emax)


def deflated_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    n_trials: int,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    bars_per_year: int = 252,
    variance_of_sharpe: Optional[float] = None,
) -> Dict[str, Any]:
    """DSR: PSR against the expected maximum Sharpe given multiple trials."""
    if isinstance(n_trials, bool) or not isinstance(n_trials, Integral) or n_trials < 1:
        return {"error": f"n_trials must be >= 1, got {n_trials}"}

    # Default variance of the Sharpe estimator under normality (annualised SR var ≈ bars/n).
    if variance_of_sharpe is None:
        variance_of_sharpe = float(bars_per_year) / max(int(n_obs), 1)

    try:
        sr0 = expected_max_sharpe(int(n_trials), variance_of_sharpe=float(variance_of_sharpe))
    except ValueError as exc:
        return {"error": str(exc)}

    psr = probabilistic_sharpe_ratio(
        sharpe,
        n_obs,
        skew=skew,
        kurtosis=kurtosis,
        sharpe_benchmark=sr0,
        bars_per_year=bars_per_year,
    )
    if "error" in psr:
        return psr
    return {
        "observed_sharpe": psr["observed_sharpe"],
        "n_obs": int(n_obs),
        "n_trials": int(n_trials),
        "expected_max_sharpe": round(float(sr0), 6),
        "variance_of_sharpe": round(float(variance_of_sharpe), 8),
        "dsr": psr["psr"],
        "z_stat": psr["z_stat"],
        "skew": psr["skew"],
        "kurtosis": psr["kurtosis"],
        "bars_per_year": int(bars_per_year),
    }


def _per_column_sharpe(rets: np.ndarray, bars_per_year: int) -> np.ndarray:
    """Sharpe for each column of a (T, N) return matrix."""
    t, n = rets.shape
    if t < 2:
        return np.zeros(n, dtype=float)
    mean = np.nanmean(rets, axis=0)
    std = np.nanstd(rets, axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = mean / (std + 1e-15) * math.sqrt(max(int(bars_per_year), 1))
    return np.where(np.isfinite(sr), sr, 0.0)


def _relative_rank(values: np.ndarray, index: int) -> float:
    """Relative rank in (0, 1]: fraction of peers with strictly worse score + ties/2."""
    v = float(values[index])
    n = len(values)
    if n <= 1:
        return 1.0
    worse = float(np.sum(values < v))
    ties = float(np.sum(values == v))
    # Mid-rank of the selected item among ties, normalised to (0, 1].
    rank = worse + 0.5 * (ties + 1.0)
    return float(rank / n)


def _sample_cscv_is_groups(
    n_groups: int,
    half: int,
    n_sample: int,
    rng: np.random.Generator,
) -> list[tuple[int, ...]]:
    """Draw ``n_sample`` unique IS group tuples without materialising C(n, k)."""
    seen: set[tuple[int, ...]] = set()
    # Hard cap attempts so pathological seeds cannot spin forever.
    max_attempts = max(n_sample * 40, n_sample + 100)
    attempts = 0
    while len(seen) < n_sample and attempts < max_attempts:
        attempts += 1
        chosen = tuple(sorted(int(x) for x in rng.choice(n_groups, size=half, replace=False)))
        seen.add(chosen)
    return list(seen)


def cscv_probability_of_backtest_overfitting(
    trial_returns: Union[np.ndarray, Sequence[Sequence[float]], pd.DataFrame],
    *,
    n_groups: int = 16,
    bars_per_year: int = 252,
    max_combinations: int = 12_870,
    seed: int = 42,
) -> Dict[str, Any]:
    """CSCV PBO on a per-trial return matrix (Bailey & López de Prado 2014).

    ``trial_returns`` shape ``(T, N)`` — T synchronized return observations across
    N strategy/parameter trials (columns). Observations are partitioned into
    ``n_groups`` contiguous blocks; every combination of ``n_groups/2`` blocks
    forms an IS set (complement = OOS). For each combination the IS-best trial
    is scored by its OOS relative rank ``λ``; PBO is the fraction with ``λ < 0.5``.

    When ``C(n_groups, n_groups/2)`` exceeds ``max_combinations`` (typical for
    ``n_groups > 16`` with the default cap of 12_870 = C(16,8)), a reproducible
    random subsample of combinations is used (``method=cscv_random_subsample``)
    so CSCV stays tractable.

    Also reports the logit-average estimator used in the paper:
    ``pbo_logit = Φ̄(mean logit(λ))``.
    """
    if isinstance(trial_returns, pd.DataFrame):
        mat = trial_returns.to_numpy(dtype=float)
    else:
        mat = np.asarray(trial_returns, dtype=float)
    if mat.ndim != 2:
        return {"error": f"trial_returns must be 2-D (T, N), got shape {mat.shape}"}
    t_obs, n_trials = mat.shape
    if n_trials < 2:
        return {"error": f"need at least 2 trials, got {n_trials}"}
    if isinstance(n_groups, bool) or not isinstance(n_groups, Integral) or n_groups < 2 or int(n_groups) % 2 != 0:
        return {"error": f"n_groups must be an even integer >= 2, got {n_groups}"}
    n_groups = int(n_groups)
    if t_obs < n_groups * 2:
        return {"error": (f"need at least {n_groups * 2} return rows for n_groups={n_groups}, got {t_obs}")}
    if isinstance(max_combinations, bool) or not isinstance(max_combinations, Integral) or max_combinations < 1:
        return {"error": f"max_combinations must be >= 1, got {max_combinations}"}
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        return {"error": f"seed must be >= 0, got {seed}"}

    # Truncate to a multiple of n_groups (drop leftover rows at the end).
    usable = (t_obs // n_groups) * n_groups
    mat = mat[:usable]
    t_obs = usable
    block = t_obs // n_groups
    half = n_groups // 2

    n_combos_full = math.comb(n_groups, half)
    subsampled = n_combos_full > int(max_combinations)
    if subsampled:
        rng = np.random.default_rng(int(seed))
        is_group_list = _sample_cscv_is_groups(n_groups, half, int(max_combinations), rng)
        method = "cscv_random_subsample"
        note = (
            f"Random CSCV subsample of {len(is_group_list)} / {n_combos_full} "
            f"IS combinations (n_groups={n_groups} exceeds exact enumeration "
            f"cap max_combinations={int(max_combinations)}; seed={int(seed)})."
        )
    else:
        is_group_list = list(itertools.combinations(range(n_groups), half))
        method = "cscv_exact"
        note = (
            "Exact combinatorial symmetric cross-validation PBO on the "
            "(T, N) trial return matrix (Bailey & López de Prado 2014)."
        )

    group_slices = [slice(g * block, (g + 1) * block) for g in range(n_groups)]
    underperform = 0
    logits: list[float] = []
    lambdas: list[float] = []

    for is_groups in is_group_list:
        is_set = set(is_groups)
        is_idx = np.concatenate([np.arange(group_slices[g].start, group_slices[g].stop) for g in is_groups])
        oos_groups = [g for g in range(n_groups) if g not in is_set]
        oos_idx = np.concatenate([np.arange(group_slices[g].start, group_slices[g].stop) for g in oos_groups])
        is_sr = _per_column_sharpe(mat[is_idx], bars_per_year)
        oos_sr = _per_column_sharpe(mat[oos_idx], bars_per_year)
        best = int(np.argmax(is_sr))
        lam = _relative_rank(oos_sr, best)
        # Avoid logit singularities at 0/1.
        lam_clip = min(max(lam, 1e-6), 1.0 - 1e-6)
        logits.append(math.log(lam_clip / (1.0 - lam_clip)))
        lambdas.append(lam)
        if lam < 0.5:
            underperform += 1

    n_c = len(lambdas)
    pbo = underperform / float(n_c) if n_c else float("nan")
    mean_logit = float(np.mean(logits)) if logits else 0.0
    # Φ̄(x) = 1 - Φ(x)
    pbo_logit = 1.0 - _norm_cdf(mean_logit)

    out: Dict[str, Any] = {
        "pbo": round(float(pbo), 6),
        "pbo_logit": round(float(pbo_logit), 6),
        "mean_lambda": round(float(np.mean(lambdas)), 6) if lambdas else float("nan"),
        "mean_logit_lambda": round(mean_logit, 6),
        "n_trials": int(n_trials),
        "n_obs": int(t_obs),
        "n_groups": int(n_groups),
        "block_size": int(block),
        "n_combinations": int(n_c),
        "n_combinations_full": int(n_combos_full),
        "method": method,
        "note": note,
    }
    if subsampled:
        out["max_combinations"] = int(max_combinations)
        out["seed"] = int(seed)
        out["subsampled"] = True
    return out


def probability_of_backtest_overfitting(
    trial_sharpes: Sequence[float],
    *,
    n_splits: int = 8,
    seed: int = 42,
) -> Dict[str, Any]:
    """CSCV-style PBO approximation on a vector of trial Sharpes.

    Prefer :func:`cscv_probability_of_backtest_overfitting` when a full
    ``(T, N)`` per-trial return matrix is available. This fallback randomly
    partitions the Sharpe vector into IS/OOS halves over ``n_splits`` draws.
    """
    arr = np.asarray(list(trial_sharpes), dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 4:
        return {"error": "need at least 4 finite trial_sharpes for PBO approximation"}
    if isinstance(n_splits, bool) or not isinstance(n_splits, Integral) or n_splits < 1:
        return {"error": f"n_splits must be >= 1, got {n_splits}"}
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        return {"error": f"seed must be >= 0, got {seed}"}

    rng = np.random.default_rng(int(seed))
    n = len(arr)
    half = n // 2
    if half < 2:
        return {"error": "need at least 4 trials so each half has >= 2"}

    underperform = 0
    for _ in range(int(n_splits)):
        idx = rng.permutation(n)
        is_s = arr[idx[:half]]
        oos_s = arr[idx[half : half * 2]]
        best_is_pos = int(np.argmax(is_s))
        oos_of_best = oos_s[min(best_is_pos, len(oos_s) - 1)]
        if oos_of_best < float(np.median(oos_s)):
            underperform += 1

    pbo = underperform / float(n_splits)
    return {
        "pbo": round(float(pbo), 6),
        "n_trials": int(n),
        "n_splits": int(n_splits),
        "method": "cscv_sharpe_vector_approx",
        "note": (
            "Approximate PBO from trial Sharpe vector; supply trial_returns "
            "(T×N matrix) for exact CSCV via cscv_probability_of_backtest_overfitting."
        ),
    }


def expected_shortfall(
    returns: np.ndarray,
    *,
    alpha: float = 0.95,
) -> float:
    """CVaR / ES on a return series (positive = loss magnitude)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 5:
        return float("nan")
    if not (0.5 < float(alpha) < 1.0):
        raise ValueError(f"alpha must be in (0.5, 1), got {alpha}")
    losses = -r
    cutoff = float(np.quantile(losses, float(alpha)))
    tail = losses[losses >= cutoff]
    if len(tail) == 0:
        return cutoff
    return float(np.mean(tail))


def _sortino(returns: np.ndarray, bars_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    downside = r[r < 0.0]
    dd = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    return float(np.mean(r) / (dd + 1e-15) * math.sqrt(max(int(bars_per_year), 1)))


def _calmar(returns: np.ndarray, bars_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1.0)
    mdd = float(np.min(dd))
    ann = float(np.mean(r) * max(int(bars_per_year), 1))
    return float(ann / (abs(mdd) + 1e-15))


def _max_drawdown_from_returns(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1.0)
    return float(np.min(dd))


def score_trial_risk_adjusted(
    returns: np.ndarray,
    *,
    bars_per_year: int = 252,
    objective: str = "sharpe_dd_penalty",
    max_dd_limit: float = 0.20,
    min_psr: float = 0.5,
    max_cvar: Optional[float] = None,
    cvar_alpha: float = 0.95,
    dd_penalty: float = 2.0,
    n_trials: int = 1,
) -> Dict[str, Any]:
    """Score one trial with risk gates + risk-adjusted objective.

    Objectives:
      - ``sharpe`` — raw annualised Sharpe
      - ``sortino`` — Sortino
      - ``calmar`` — Calmar
      - ``sharpe_dd_penalty`` — Sharpe − dd_penalty × |max_dd|  (default)
      - ``psr`` — probabilistic Sharpe vs 0

    Hard rejects (``accepted=False``) when:
      - |max_dd| > max_dd_limit
      - PSR < min_psr
      - CVaR > max_cvar (when max_cvar set; CVaR is positive loss)
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 5:
        return {"accepted": False, "reason": "insufficient_observations", "score": float("-inf")}

    sharpe = observed_sharpe(r, bars_per_year)
    moments = _sample_moments(r)
    psr = probabilistic_sharpe_ratio(
        sharpe,
        int(moments["n"]),
        skew=float(moments["skew"]),
        kurtosis=float(moments["kurtosis"]),
        bars_per_year=bars_per_year,
    )
    mdd = _max_drawdown_from_returns(r)
    cvar = expected_shortfall(r, alpha=cvar_alpha)
    sortino = _sortino(r, bars_per_year)
    calmar = _calmar(r, bars_per_year)

    reject_reasons: list[str] = []
    if abs(mdd) > float(max_dd_limit) + 1e-12:
        reject_reasons.append(f"max_dd={mdd:.4f} exceeds limit={max_dd_limit}")
    psr_val = float(psr.get("psr", 0.0)) if "psr" in psr else 0.0
    if psr_val < float(min_psr):
        reject_reasons.append(f"psr={psr_val:.4f} below min_psr={min_psr}")
    if max_cvar is not None and np.isfinite(cvar) and cvar > float(max_cvar):
        reject_reasons.append(f"cvar={cvar:.4f} exceeds max_cvar={max_cvar}")

    obj = (objective or "sharpe_dd_penalty").strip().lower().replace("-", "_")
    # Reject return-only objectives — risk-first ranking must use a risk-aware score.
    _return_only = {
        "return",
        "returns",
        "total_return",
        "raw_return",
        "pnl",
        "profit",
        "cumret",
        "cumulative_return",
        "mean_return",
        "expected_return",
    }
    if obj in _return_only:
        return {
            "accepted": False,
            "reason": f"return_only_objective_rejected:{obj}",
            "reject_reasons": [f"objective={obj} is return-only"],
            "score": float("-inf"),
            "objective": obj,
        }

    if obj == "sharpe":
        score = sharpe
    elif obj == "sortino":
        score = sortino
    elif obj == "calmar":
        score = calmar
    elif obj == "psr":
        score = psr_val
    else:
        # Default / unknown → sharpe with drawdown penalty (never raw return).
        obj = "sharpe_dd_penalty" if obj not in {"sharpe_dd_penalty"} else obj
        score = sharpe - float(dd_penalty) * abs(mdd)

    dsr = deflated_sharpe_ratio(
        sharpe,
        int(moments["n"]),
        int(n_trials),
        skew=float(moments["skew"]),
        kurtosis=float(moments["kurtosis"]),
        bars_per_year=bars_per_year,
    )

    return {
        "accepted": len(reject_reasons) == 0,
        "reject_reasons": reject_reasons,
        "score": round(float(score), 6),
        "objective": obj,
        "sharpe": round(float(sharpe), 6),
        "sortino": round(float(sortino), 6),
        "calmar": round(float(calmar), 6),
        "max_dd": round(float(mdd), 6),
        "cvar": round(float(cvar), 6) if np.isfinite(cvar) else None,
        "psr": round(psr_val, 6),
        "dsr": dsr.get("dsr"),
        "n_obs": int(moments["n"]),
    }


def rank_trials_risk_adjusted(
    trial_returns: Union[np.ndarray, Sequence[Sequence[float]], pd.DataFrame],
    *,
    bars_per_year: int = 252,
    objective: str = "sharpe_dd_penalty",
    max_dd_limit: float = 0.20,
    min_psr: float = 0.5,
    max_cvar: Optional[float] = None,
    cvar_alpha: float = 0.95,
    dd_penalty: float = 2.0,
    labels: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Rank / reject a (T, N) trial return matrix with risk-adjusted scores.

    Prefer this over raw Sharpe max when selecting alphas under risk budgets.
    """
    if isinstance(trial_returns, pd.DataFrame):
        mat = trial_returns.to_numpy(dtype=float)
        col_labels: list[Any] = list(labels) if labels is not None else list(trial_returns.columns)
    else:
        mat = np.asarray(trial_returns, dtype=float)
        col_labels = list(labels) if labels is not None else list(range(mat.shape[1] if mat.ndim == 2 else 0))

    if mat.ndim != 2:
        return {"error": f"trial_returns must be 2-D (T, N), got shape {mat.shape}"}
    t_obs, n_trials = mat.shape
    if n_trials < 1:
        return {"error": "need at least 1 trial"}

    scored: list[Dict[str, Any]] = []
    for j in range(n_trials):
        row = score_trial_risk_adjusted(
            mat[:, j],
            bars_per_year=bars_per_year,
            objective=objective,
            max_dd_limit=max_dd_limit,
            min_psr=min_psr,
            max_cvar=max_cvar,
            cvar_alpha=cvar_alpha,
            dd_penalty=dd_penalty,
            n_trials=n_trials,
        )
        row["trial_index"] = int(j)
        row["label"] = col_labels[j] if j < len(col_labels) else j
        scored.append(row)

    accepted = [s for s in scored if s["accepted"]]
    rejected = [s for s in scored if not s["accepted"]]
    ranking = sorted(accepted, key=lambda s: float(s["score"]), reverse=True)
    best = ranking[0] if ranking else None

    return {
        "n_trials": int(n_trials),
        "n_obs": int(t_obs),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "objective": objective,
        "gates": {
            "max_dd_limit": float(max_dd_limit),
            "min_psr": float(min_psr),
            "max_cvar": float(max_cvar) if max_cvar is not None else None,
            "cvar_alpha": float(cvar_alpha),
            "dd_penalty": float(dd_penalty),
        },
        "best": best,
        "ranking": ranking,
        "rejected": rejected,
        "all_scores": scored,
        "note": (
            "Risk-first ranking: reject high-DD / low-PSR / high-CVaR trials, "
            "then sort survivors by the chosen risk-adjusted objective "
            "(default Sharpe with drawdown penalty)."
        ),
    }


def run_risk_metrics(
    equity_curve: pd.Series,
    *,
    bars_per_year: int = 252,
    n_trials: int = 1,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
    skew: Optional[float] = None,
    kurtosis: Optional[float] = None,
    include_pbo: bool = False,
    trial_sharpes: Optional[Sequence[float]] = None,
    trial_returns: Optional[Union[np.ndarray, Sequence[Sequence[float]], pd.DataFrame]] = None,
    pbo_n_groups: int = 16,
    pbo_max_combinations: int = 12_870,
) -> Dict[str, Any]:
    """Bundle PSR / DSR / bootstrap CI (+ optional PBO) for an equity curve.

    When ``include_pbo`` is True:
      - prefer ``trial_returns`` (T×N) → CSCV PBO (exact, or random subsample
        when ``C(n_groups, n/2)`` exceeds ``pbo_max_combinations``)
      - else ``trial_sharpes`` → Sharpe-vector approximation
    """
    if len(equity_curve) < 5:
        return {"error": "need at least 5 equity observations"}
    if isinstance(n_trials, bool) or not isinstance(n_trials, Integral) or n_trials < 1:
        return {"error": f"n_trials must be >= 1, got {n_trials}"}

    returns = equity_curve.pct_change().dropna().to_numpy(dtype=float)
    moments = _sample_moments(returns)
    use_skew = float(skew) if skew is not None else float(moments["skew"])
    use_kurt = float(kurtosis) if kurtosis is not None else float(moments["kurtosis"])
    sharpe = observed_sharpe(returns, bars_per_year)
    n_obs = int(moments["n"])

    psr = probabilistic_sharpe_ratio(
        sharpe,
        n_obs,
        skew=use_skew,
        kurtosis=use_kurt,
        sharpe_benchmark=0.0,
        bars_per_year=bars_per_year,
    )
    dsr = deflated_sharpe_ratio(
        sharpe,
        n_obs,
        int(n_trials),
        skew=use_skew,
        kurtosis=use_kurt,
        bars_per_year=bars_per_year,
    )

    from backtest.validation import bootstrap_sharpe_ci

    boot = bootstrap_sharpe_ci(
        equity_curve,
        n_bootstrap=int(n_bootstrap),
        confidence=float(confidence),
        bars_per_year=bars_per_year,
        seed=int(seed),
    )
    # Drop bulky samples from the bundle unless tiny.
    if isinstance(boot, dict) and "sharpe_samples" in boot and int(n_bootstrap) > 500:
        boot = {k: v for k, v in boot.items() if k != "sharpe_samples"}

    out: Dict[str, Any] = {
        "observed_sharpe": round(sharpe, 6),
        "moments": {
            "n_obs": n_obs,
            "skew": round(use_skew, 6),
            "kurtosis": round(use_kurt, 6),
            "mean_return": round(float(moments["mean"]), 8),
            "std_return": round(float(moments["std"]), 8),
        },
        "probabilistic_sharpe": psr,
        "deflated_sharpe": dsr,
        "bootstrap_sharpe_ci": boot,
        "n_trials": int(n_trials),
    }

    if include_pbo:
        if trial_returns is not None:
            out["pbo"] = cscv_probability_of_backtest_overfitting(
                trial_returns,
                n_groups=int(pbo_n_groups),
                bars_per_year=bars_per_year,
                max_combinations=int(pbo_max_combinations),
                seed=int(seed),
            )
        elif trial_sharpes is not None:
            out["pbo"] = probability_of_backtest_overfitting(list(trial_sharpes), seed=int(seed))
        else:
            out["pbo"] = {
                "error": ("include_pbo=True requires trial_returns (T×N matrix) or trial_sharpes (list)"),
            }

    return out
