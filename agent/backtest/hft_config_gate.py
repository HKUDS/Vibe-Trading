"""Hard gates for risk-first / HFT-proxy strategy configs.

Skills ``strategy-generate`` and ``hft-risk-alpha`` must emit configs that
include an active ``risk_overlay`` and ``validation.risk_adjusted_ranking``.
Return-only objectives are rejected.

The runner / ``BaseEngine`` auto-injects defaults and asserts for short-horizon
intervals (``1s`` / minute bars) and HFT-tagged configs so return-only setups
fail closed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set

# Objectives that optimize raw PnL / return without a risk adjustment.
_RETURN_ONLY = frozenset(
    {
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
)

# Allowed risk-adjusted objectives for ranking / selection.
ALLOWED_RISK_OBJECTIVES = frozenset(
    {
        "sharpe",
        "sortino",
        "calmar",
        "sharpe_dd_penalty",
        "psr",
    }
)

# Intervals that imply high-turnover / short-horizon research.
SHORT_HORIZON_INTERVALS = frozenset(
    {
        "1s",
        "5s",
        "10s",
        "15s",
        "30s",
        "1m",
        "2m",
        "3m",
        "5m",
        "10m",
        "15m",
        "30m",
        "60m",
        "1h",
    }
)

_HFT_TAG_TOKENS = frozenset(
    {
        "hft",
        "short_horizon",
        "short-horizon",
        "high_turnover",
        "high-turnover",
        "intraday",
        "scalp",
        "market_making",
        "market-making",
    }
)

_REQUIRED_OVERLAY_KEYS = (
    "max_drawdown_kill",
    "max_gross_leverage",
)


def is_return_only_objective(objective: Any) -> bool:
    if objective is None:
        return False
    text = str(objective).strip().lower().replace("-", "_").replace(" ", "_")
    return text in _RETURN_ONLY


def _tag_tokens(config: Mapping[str, Any]) -> Set[str]:
    """Collect free-form tags / style labels from common config keys."""
    tokens: Set[str] = set()
    for key in ("tags", "style", "strategy_style", "desk", "preset", "category"):
        raw = config.get(key)
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            parts = [str(x) for x in raw]
        else:
            parts = [str(raw)]
        for part in parts:
            for tok in part.lower().replace("-", "_").replace(",", " ").split():
                if tok:
                    tokens.add(tok)
                    tokens.add(tok.replace("_", "-"))
    # Boolean / string flags.
    for key in ("hft", "short_horizon", "high_turnover"):
        val = config.get(key)
        if val is True or str(val).strip().lower() in {"1", "true", "yes", "on"}:
            tokens.add(key.replace("_", "-"))
            tokens.add(key)
    return tokens


def is_short_horizon_config(config: Mapping[str, Any]) -> bool:
    """True when interval / tags imply HFT-proxy / short-horizon research."""
    if not isinstance(config, Mapping):
        return False
    interval = str(config.get("interval") or "").strip().lower()
    if interval in SHORT_HORIZON_INTERVALS:
        return True
    tokens = _tag_tokens(config)
    if tokens & _HFT_TAG_TOKENS:
        return True
    # Explicit hft_costs request also opts into the risk-first path.
    costs = config.get("hft_costs")
    if isinstance(costs, Mapping) and costs.get("enabled", True) is not False:
        if costs not in ({},):
            return True
    return False


def requires_hft_costs(config: Mapping[str, Any]) -> bool:
    """Minute / sub-minute / explicitly HFT-tagged configs need the cost stack."""
    interval = str(config.get("interval") or "").strip().lower()
    if interval in {"1s", "5s", "10s", "15s", "30s", "1m", "2m", "3m", "5m", "15m", "30m"}:
        return True
    tokens = _tag_tokens(config)
    return bool(tokens & {"hft", "high_turnover", "high-turnover", "scalp", "market_making", "market-making"})


def validate_risk_first_config(
    config: Mapping[str, Any],
    *,
    require_overlay: bool = True,
    require_ranking: bool = True,
    require_hft_costs: bool = False,
) -> Dict[str, Any]:
    """Validate that a config is risk-first (not return-only).

    Returns a dict with ``ok`` (bool), ``errors`` (list[str]), ``warnings``.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(config, Mapping):
        return {"ok": False, "errors": ["config must be a mapping"], "warnings": []}

    # ── risk_overlay ──
    overlay = config.get("risk_overlay")
    if require_overlay:
        if overlay in (None, {}, False):
            errors.append("risk_overlay is required for risk-first / HFT-proxy configs")
        elif not isinstance(overlay, Mapping):
            errors.append("risk_overlay must be a mapping")
        elif overlay.get("enabled", True) is False:
            errors.append("risk_overlay.enabled must not be false")
        else:
            for key in _REQUIRED_OVERLAY_KEYS:
                if overlay.get(key) is None:
                    errors.append(f"risk_overlay.{key} is required")
            # Soft nudges for short-horizon realism.
            if overlay.get("inventory_mean_reversion") is None:
                warnings.append("risk_overlay.inventory_mean_reversion recommended for short-horizon books")
            if overlay.get("max_turnover") is None:
                warnings.append("risk_overlay.max_turnover recommended for high-turnover books")

    # ── risk_adjusted_ranking ──
    validation = config.get("validation")
    ranking: Any = None
    if isinstance(validation, Mapping):
        ranking = validation.get("risk_adjusted_ranking")
        grid = validation.get("signal_parameter_grid")
        if isinstance(grid, Mapping):
            rk = grid.get("risk_ranking")
            if rk is not None and ranking is None:
                ranking = rk
                warnings.append("using signal_parameter_grid.risk_ranking as risk_adjusted_ranking proxy")

    if require_ranking:
        if ranking in (None, {}, False):
            errors.append("validation.risk_adjusted_ranking (or signal_parameter_grid.risk_ranking) is required")
        elif not isinstance(ranking, Mapping):
            errors.append("risk_adjusted_ranking must be a mapping")
        else:
            obj = ranking.get("objective", "sharpe_dd_penalty")
            if is_return_only_objective(obj):
                errors.append(f"objective={obj!r} is return-only; use one of {sorted(ALLOWED_RISK_OBJECTIVES)}")
            elif str(obj).strip().lower() not in ALLOWED_RISK_OBJECTIVES:
                errors.append(f"objective={obj!r} not allowed; use one of {sorted(ALLOWED_RISK_OBJECTIVES)}")
            if ranking.get("max_dd_limit") is None:
                errors.append("risk_adjusted_ranking.max_dd_limit is required")

    # Explicit top-level objective fields sometimes used by agents.
    for key in ("objective", "optimize", "selection_objective"):
        if key in config and is_return_only_objective(config.get(key)):
            errors.append(f"config.{key}={config.get(key)!r} is return-only — rejected")

    # ── hft_costs (optional hard require) ──
    costs = config.get("hft_costs")
    if require_hft_costs:
        if costs in (None, {}, False):
            errors.append("hft_costs is required for high-turnover HFT-proxy configs")
        elif isinstance(costs, Mapping) and costs.get("enabled", True) is False:
            errors.append("hft_costs.enabled must not be false")
        elif isinstance(costs, Mapping):
            mode = str(costs.get("fill_slippage_mode", "additive")).strip().lower()
            if mode != "replace":
                errors.append(
                    "hft_costs.fill_slippage_mode must be 'replace' for HFT-proxy "
                    "configs (avoids double-counting native slippage)"
                )
    elif costs in (None, {}, False):
        interval = str(config.get("interval") or "").lower()
        if interval in {"1m", "5m", "15m", "30m"}:
            warnings.append(
                "hft_costs recommended for minute-bar high-turnover configs (spread+impact+adverse selection)"
            )
    elif isinstance(costs, Mapping):
        mode = str(costs.get("fill_slippage_mode", "additive")).strip().lower()
        if mode != "replace":
            warnings.append(
                "hft_costs.fill_slippage_mode='replace' recommended to avoid double-counting"
            )

    # ── Monte Carlo sampling quality (short-horizon / when MC present) ──
    validation = config.get("validation") if isinstance(config.get("validation"), Mapping) else {}
    mc = validation.get("monte_carlo_paths") if isinstance(validation, Mapping) else None
    if isinstance(mc, Mapping) and mc:
        method = str(mc.get("method", "bootstrap")).strip().lower()
        sampling = str(mc.get("sampling", "")).strip().lower()
        if method in {"gbm", "correlated_gbm"} and sampling not in {"sobol", "stratified"}:
            if require_hft_costs or is_short_horizon_config(config):
                errors.append(
                    "validation.monte_carlo_paths.sampling must be 'sobol' or 'stratified' "
                    "for short-horizon GBM MC (got {!r})".format(sampling or "unset")
                )
            else:
                warnings.append(
                    "monte_carlo_paths.sampling=sobol (or stratified) recommended for GBM family"
                )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def assert_risk_first_config(
    config: Mapping[str, Any],
    **kwargs: Any,
) -> None:
    """Raise ``ValueError`` if config fails risk-first gates."""
    result = validate_risk_first_config(config, **kwargs)
    if not result["ok"]:
        raise ValueError("; ".join(result["errors"]))


def enforce_risk_first_config(
    config: Mapping[str, Any],
    *,
    inject: bool = True,
) -> Dict[str, Any]:
    """Inject risk-first defaults (optional) then assert for short-horizon configs.

    Daily / non-HFT configs are returned unchanged. Short-horizon / HFT-tagged
    configs fail closed on return-only objectives after defaults are filled.
    """
    out: Dict[str, Any] = dict(config)
    if not is_short_horizon_config(out):
        return out
    short = True
    need_costs = requires_hft_costs(out)
    if inject:
        out = inject_risk_first_defaults(out, short_horizon=short)
    assert_risk_first_config(out, require_hft_costs=need_costs)
    out["_risk_first_enforced"] = True
    return out


def inject_risk_first_defaults(
    config: Mapping[str, Any],
    *,
    short_horizon: bool = True,
) -> Dict[str, Any]:
    """Return a shallow-copied config with risk-first defaults filled in.

    Does not overwrite existing numeric knobs; only fills missing sections.
    For short-horizon books, coerces ``hft_costs.fill_slippage_mode`` to
    ``replace`` and injects Sobol MC + risk-gated walk-forward hooks.
    """
    out: Dict[str, Any] = dict(config)

    if out.get("risk_overlay") in (None, {}, False):
        out["risk_overlay"] = {
            "enabled": True,
            "vol_target": 0.12,
            "vol_lookback": 20,
            "vol_governor_lookback": 60,
            "vol_governor_spike_ratio": 1.5,
            "max_gross_leverage": 1.0,
            "max_net_exposure": 0.4,
            "max_name_weight": 0.25,
            "max_corr_cluster_gross": 0.6,
            "corr_cluster_threshold": 0.75,
            "max_turnover": 0.3,
            "turnover_cost_feedback": 0.002,
            "turnover_cost_bps": 10.0,
            "max_drawdown_kill": 0.10,
            "kill_cooldown_bars": 5,
            "kill_reset_drawdown": 0.03,
            "stop_loss": 0.04,
            "ohlc_stop": True if short_horizon else False,
            "inventory_mean_reversion": 0.15,
            "partial_fill_rate": 0.7 if short_horizon else None,
            "max_portfolio_cvar": 0.035,
            "cvar_lookback": 40,
        }
        # Drop None keys for cleanliness.
        out["risk_overlay"] = {k: v for k, v in out["risk_overlay"].items() if v is not None}

    validation = dict(out.get("validation") or {}) if isinstance(out.get("validation"), Mapping) else {}
    if validation.get("risk_adjusted_ranking") in (None, {}, False):
        validation["risk_adjusted_ranking"] = {
            "objective": "sharpe_dd_penalty",
            "max_dd_limit": 0.15,
            "min_psr": 0.55,
            "min_dsr": 0.45,
            "max_cvar": 0.04,
            "dd_penalty": 2.0,
            "fragile_fold_std": 1.5,
            "fragile_n_folds": 4,
        }
    else:
        # Fill missing DSR / fragile gates without overwriting user values.
        rk = dict(validation["risk_adjusted_ranking"])
        rk.setdefault("min_dsr", 0.45)
        rk.setdefault("fragile_fold_std", 1.5)
        validation["risk_adjusted_ranking"] = rk
    if "stress" not in validation:
        validation["stress"] = {}
    if short_horizon and validation.get("monte_carlo_paths") in (None, {}, False):
        validation["monte_carlo_paths"] = {
            "method": "gbm",
            "n_paths": 10_000,
            "sampling": "sobol",
            "antithetic": True,
        }
    elif isinstance(validation.get("monte_carlo_paths"), Mapping):
        mc = dict(validation["monte_carlo_paths"])
        method = str(mc.get("method", "bootstrap")).strip().lower()
        if short_horizon and method in {"gbm", "correlated_gbm"}:
            mc.setdefault("sampling", "sobol")
            mc.setdefault("antithetic", True)
        validation["monte_carlo_paths"] = mc
    if short_horizon and validation.get("walk_forward_risk_gated") in (None, {}, False):
        validation["walk_forward_risk_gated"] = {
            "n_windows": 5,
            "max_dd_limit": 0.15,
            "min_psr": 0.5,
            "min_dsr": 0.4,
        }
    out["validation"] = validation

    if short_horizon and out.get("hft_costs") in (None, {}, False):
        out["hft_costs"] = {
            "enabled": True,
            "spread_bps": 2.0,
            "impact_coeff": 8.0,
            "impact_power": 0.5,
            "adverse_selection_bps": 1.5,
            "participation_cap": 0.5,
            "max_adv_participation": 0.2,
            "adv_lookback": 20,
            # Prefer replace so injected HFT stack does not double-count native slippage.
            "fill_slippage_mode": "replace",
            # Soft ADV when loaders omit volume/amount (still a bar proxy).
            "adv_fallback_notional": 5_000_000.0,
        }
    elif short_horizon and isinstance(out.get("hft_costs"), Mapping):
        costs = dict(out["hft_costs"])
        # Fill missing mode only — do not silently overwrite an explicit
        # ``additive`` choice (research A/B); fail-closed gate still rejects
        # additive when ``require_hft_costs`` is True.
        if not costs.get("fill_slippage_mode"):
            costs["fill_slippage_mode"] = "replace"
        costs.setdefault("adv_fallback_notional", 5_000_000.0)
        out["hft_costs"] = costs

    return out


def compare_grid_vs_risk_gated(
    trial_returns: Any,
    *,
    max_dd_limit: float = 0.15,
    min_psr: float = 0.0,
    max_cvar: Optional[float] = None,
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Compare unconstrained return-max pick vs risk-gated ranking.

    Used by demos/tests: the risk-gated survivor should dominate on
    |max_dd| / CVaR (not necessarily raw return).
    """
    import numpy as np

    from backtest.risk_metrics import (
        expected_shortfall,
        rank_trials_risk_adjusted,
    )

    mat = np.asarray(trial_returns, dtype=float)
    if mat.ndim != 2 or mat.shape[1] < 2:
        return {"error": "need 2-D trial_returns with >= 2 trials"}

    # Unconstrained: pick max cumulative return.
    cum = np.prod(1.0 + np.nan_to_num(mat, nan=0.0), axis=0) - 1.0
    unc_idx = int(np.argmax(cum))

    ranked = rank_trials_risk_adjusted(
        mat,
        bars_per_year=bars_per_year,
        objective="sharpe_dd_penalty",
        max_dd_limit=max_dd_limit,
        min_psr=min_psr,
        max_cvar=max_cvar,
        dd_penalty=2.0,
    )
    best = ranked.get("best")
    if best is None:
        return {
            "unconstrained_index": unc_idx,
            "risk_gated_index": None,
            "n_accepted": ranked.get("n_accepted", 0),
            "n_rejected": ranked.get("n_rejected", 0),
            "note": "all trials rejected by risk gates",
            "ranked": ranked,
        }

    gate_idx = int(best["trial_index"])

    def _stats(col: int) -> Dict[str, float]:
        r = mat[:, col]
        r = r[np.isfinite(r)]
        eq = np.cumprod(1.0 + r)
        peak = np.maximum.accumulate(eq)
        dd = float(np.min((eq - peak) / np.where(peak > 0, peak, 1.0)))
        return {
            "total_return": float(eq[-1] / eq[0] - 1.0) if len(eq) else 0.0,
            "max_dd": dd,
            "cvar": float(expected_shortfall(r)),
        }

    unc = _stats(unc_idx)
    gated = _stats(gate_idx)
    return {
        "unconstrained_index": unc_idx,
        "risk_gated_index": gate_idx,
        "unconstrained": unc,
        "risk_gated": gated,
        "risk_gated_better_dd": abs(gated["max_dd"]) <= abs(unc["max_dd"]) + 1e-12,
        "risk_gated_better_cvar": gated["cvar"] <= unc["cvar"] + 1e-12,
        "n_accepted": ranked.get("n_accepted"),
        "n_rejected": ranked.get("n_rejected"),
        "ranked_best": best,
    }
