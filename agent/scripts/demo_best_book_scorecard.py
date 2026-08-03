#!/usr/bin/env python3
"""End-to-end "best book" scorecard: HFT-proxy strategy → overlay + replace costs
→ risk_adjusted_ranking + CSCV/PSR/DSR → MC ruin/ES.

Prints a clear human-readable scorecard comparing unconstrained vs risk-first
books. Bar/tick proxy only — not exchange co-lo / LOB.

Run from the ``agent/`` directory:

    cd agent && python scripts/demo_best_book_scorecard.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from backtest.enhanced_validation import (  # noqa: E402
    signal_parameter_grid,
    stress_scenarios,
    walk_forward_risk_gated,
)
from backtest.hft_config_gate import (  # noqa: E402
    compare_grid_vs_risk_gated,
    inject_risk_first_defaults,
    validate_risk_first_config,
)
from backtest.hft_costs import HftCostModel  # noqa: E402
from backtest.monte_carlo import run_monte_carlo_paths  # noqa: E402
from backtest.risk_metrics import (  # noqa: E402
    cscv_probability_of_backtest_overfitting,
    rank_trials_risk_adjusted,
    run_risk_metrics,
)
from backtest.risk_overlay import (  # noqa: E402
    RiskOverlayConfig,
    apply_risk_overlay,
    overlay_ab_comparison,
    simulate_strategy_pnl,
)


def _synthetic_hft_book(
    n_bars: int = 2_400,
    n_names: int = 4,
    seed: int = 17,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.RangeIndex(n_bars)
    # Correlated microstructure-like returns with crash clusters.
    common = rng.normal(0.0, 0.0025, size=n_bars)
    noise = rng.normal(0.0, 0.0025, size=(n_bars, n_names))
    rets = np.zeros_like(noise)
    for t in range(1, n_bars):
        rets[t] = -0.2 * rets[t - 1] + 0.55 * common[t] + noise[t]
    rets[700:730] -= 0.01
    rets[1600:1625] -= 0.014
    cols = [f"S{i}" for i in range(n_names)]
    returns = pd.DataFrame(rets, index=idx, columns=cols)
    signal = -np.sign(returns.shift(1).fillna(0.0).to_numpy())
    flip = np.sign(rng.normal(size=(n_bars, n_names)))
    raw = 0.65 * signal + 0.35 * flip
    gross = 1.3 + 1.1 * (rng.random(n_bars) > 0.55)
    raw = raw * (gross[:, None] / max(n_names, 1))
    raw[:, 0] *= 2.0
    raw[:, 1] *= 1.8  # correlated concentration for cluster caps
    positions = pd.DataFrame(raw, index=idx, columns=cols)
    close = (1.0 + returns).cumprod() * 100.0
    open_ = close.shift(1).fillna(close.iloc[0]) * (
        1.0 + rng.normal(0.0, 0.0004, size=close.shape)
    )
    open_ = pd.DataFrame(open_.to_numpy(), index=idx, columns=cols)
    high = close * (1.0 + 0.0015)
    low = close.copy()
    low.iloc[700:730] = close.iloc[700:730] * 0.93
    return positions, returns, close, open_, high, low


def _fmt_pct(x: float) -> str:
    return f"{100.0 * float(x):+.2f}%"


def _fmt_num(x: Any, digits: int = 4) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return str(x)


def _print_scorecard(card: Dict[str, Any]) -> None:
    ab = card["ab_comparison"]
    base, ov = ab["baseline"], ab["overlay"]
    imp = ab["improvement"]
    mc = card["monte_carlo"]
    print()
    print("=" * 72)
    print(" BEST BOOK SCORECARD  (bar/tick proxy — not co-lo / LOB)")
    print("=" * 72)
    print(f"{'Metric':<28} {'Unconstrained':>14} {'Risk-first':>14} {'Delta':>12}")
    print("-" * 72)
    rows = [
        ("Total return", base["total_return"], ov["total_return"], ov["total_return"] - base["total_return"]),
        ("Max drawdown", base["max_drawdown"], ov["max_drawdown"], imp["drawdown_reduction"]),
        ("Risk-adj score", base["risk_adjusted_score"], ov["risk_adjusted_score"], imp["risk_adjusted_score_delta"]),
        ("Ruin proxy", base["ruin_proxy"], ov["ruin_proxy"], imp["ruin_reduction"]),
        ("Sharpe", base["sharpe"], ov["sharpe"], imp["sharpe_delta"]),
    ]
    for name, a, b, d in rows:
        if "drawdown" in name.lower() or "ruin" in name.lower() or "return" in name.lower():
            print(f"{name:<28} {_fmt_pct(a):>14} {_fmt_pct(b):>14} {_fmt_num(d):>12}")
        else:
            print(f"{name:<28} {_fmt_num(a):>14} {_fmt_num(b):>14} {_fmt_num(d):>12}")
    print("-" * 72)
    print(
        f"MC ruin (boot)              {_fmt_num(mc['baseline_ruin']):>14} "
        f"{_fmt_num(mc['overlay_ruin']):>14} "
        f"{_fmt_num(mc['baseline_ruin'] - mc['overlay_ruin']):>12}"
    )
    print(
        f"MC ES return (boot)         {_fmt_num(mc['baseline_es']):>14} "
        f"{_fmt_num(mc['overlay_es']):>14}"
    )
    if mc.get("overlay_sobol_ruin") is not None:
        print(
            f"MC ruin (Sobol GBM)         {'—':>14} "
            f"{_fmt_num(mc['overlay_sobol_ruin']):>14}"
        )
    print("-" * 72)
    rk = card.get("grid_ranking_summary") or {}
    print(
        f"Grid risk-ranking           accepted={rk.get('n_accepted')}  "
        f"rejected={rk.get('n_rejected')}"
    )
    best = rk.get("best") or {}
    if best:
        print(
            f"  best trial                idx={best.get('trial_index')}  "
            f"score={_fmt_num(best.get('score'))}  "
            f"psr={_fmt_num(best.get('psr'))}  dsr={_fmt_num(best.get('dsr'))}"
        )
    pbo = card.get("cscv_pbo") or {}
    if "pbo" in pbo:
        print(f"CSCV PBO                    {_fmt_num(pbo.get('pbo'))}  method={pbo.get('method')}")
    wf = card.get("walk_forward_risk_gated") or {}
    if wf:
        print(
            f"WF risk-gated               pass_rate={_fmt_num(wf.get('pass_rate'))}  "
            f"passed={wf.get('passed')}"
        )
    gate = card.get("config_gate") or {}
    print(f"Config gate ok              {gate.get('ok')}  (replace + ranking + overlay)")
    print("-" * 72)
    verdict_bits = []
    if imp.get("drawdown_reduction", 0) >= 0:
        verdict_bits.append("risk↓")
    if imp.get("risk_adjusted_score_delta", 0) >= 0:
        verdict_bits.append("risk-adj↑")
    if mc["overlay_ruin"] <= mc["baseline_ruin"] + 1e-12:
        verdict_bits.append("ruin↓")
    print("Verdict: " + (", ".join(verdict_bits) if verdict_bits else "mixed on this seed"))
    print(card["limits"])
    print("=" * 72)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Best-book risk-first scorecard")
    parser.add_argument("--n-bars", type=int, default=2_400)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--n-paths", type=int, default=4_000)
    parser.add_argument("--json", action="store_true", help="Also dump full JSON payload")
    args = parser.parse_args()

    positions, returns, close, open_, high, low = _synthetic_hft_book(
        n_bars=args.n_bars, seed=args.seed
    )
    overlay = RiskOverlayConfig(
        enabled=True,
        vol_target=0.14,
        vol_lookback=25,
        vol_governor_lookback=80,
        vol_governor_spike_ratio=1.4,
        max_gross_leverage=1.0,
        max_net_exposure=0.35,
        max_name_weight=0.35,
        max_corr_cluster_gross=0.55,
        corr_cluster_threshold=0.6,
        corr_lookback=40,
        max_turnover=0.22,
        turnover_cost_feedback=0.0015,
        turnover_cost_bps=12.0,
        max_drawdown_kill=0.08,
        kill_cooldown_bars=10,
        kill_reset_drawdown=0.03,
        stop_loss=0.05,
        ohlc_stop=True,
        inventory_mean_reversion=0.2,
        partial_fill_rate=0.65,
        next_bar_open_slippage_bps=4.0,
        max_name_vol=0.55,
        max_portfolio_cvar=0.03,
        cvar_lookback=40,
        bars_per_year=252 * 78,
    )
    costs = HftCostModel(
        spread_bps=5.0,
        impact_coeff=15.0,
        impact_power=0.5,
        adverse_selection_bps=4.0,
        participation_cap=0.4,
        max_adv_participation=0.15,
        fill_slippage_mode="replace",
        adv_fallback_notional=5_000_000.0,
    )

    ab = overlay_ab_comparison(
        positions,
        returns,
        overlay=overlay,
        close=close,
        open_=open_,
        high=high,
        low=low,
        hft_costs=costs,
        initial_capital=1_000_000.0,
    )

    base_eq = simulate_strategy_pnl(positions, returns, hft_costs=costs, initial_capital=1_000_000.0)
    adj, overlay_diag = apply_risk_overlay(
        positions, returns, config=overlay, close=close, open_=open_, high=high, low=low
    )
    adj_eq = simulate_strategy_pnl(adj, returns, hft_costs=costs, initial_capital=1_000_000.0)

    mc_base = run_monte_carlo_paths(
        method="bootstrap", n_paths=args.n_paths, equity_curve=base_eq, seed=args.seed, ruin_level=0.5
    )
    mc_adj = run_monte_carlo_paths(
        method="bootstrap", n_paths=args.n_paths, equity_curve=adj_eq, seed=args.seed, ruin_level=0.5
    )
    # Sobol GBM on overlay book for low-discrepancy tail estimate.
    rets_adj = adj_eq.pct_change().dropna()
    mu = float(rets_adj.mean())
    sigma = float(rets_adj.std(ddof=1)) if len(rets_adj) > 2 else 0.01
    mc_sobol = run_monte_carlo_paths(
        method="gbm",
        n_paths=min(args.n_paths, 5_000),
        horizon=min(252, max(60, len(rets_adj))),
        mu=mu,
        sigma=max(sigma, 1e-6),
        sampling="sobol",
        antithetic=True,
        seed=args.seed,
        ruin_level=0.5,
        initial_capital=float(adj_eq.iloc[0]),
    )

    px = close.iloc[:, 0]
    grid = signal_parameter_grid(
        px,
        strategy="rsi_mean_reversion",
        collect_trial_returns=True,
        cost_bps=10.0,
        risk_ranking={
            "objective": "sharpe_dd_penalty",
            "max_dd_limit": 0.30,
            "min_psr": 0.35,
            "min_dsr": 0.25,
            "fragile_fold_std": 2.0,
            "dd_penalty": 2.0,
        },
    )
    ranking = grid.get("risk_adjusted_ranking")
    trial_rets = grid.get("trial_returns")
    pbo = None
    if trial_rets is not None:
        mat = np.asarray(trial_rets, dtype=float)
        if mat.ndim == 2 and mat.shape[1] >= 2 and mat.shape[0] >= 32:
            pbo = cscv_probability_of_backtest_overfitting(mat, n_groups=8, bars_per_year=252)
        if ranking is None:
            ranking = rank_trials_risk_adjusted(mat, max_dd_limit=0.30, min_psr=0.35, min_dsr=0.25)

    grid_compare = None
    if trial_rets is not None:
        grid_compare = compare_grid_vs_risk_gated(trial_rets, max_dd_limit=0.30, min_psr=0.0)

    wf = walk_forward_risk_gated(
        adj_eq,
        n_windows=4,
        max_dd_limit=0.35,
        min_psr=0.0,
        min_dsr=0.0,
    )
    stress = stress_scenarios(adj_eq, seed=args.seed)
    risk_bundle = run_risk_metrics(adj_eq, n_trials=max(2, (ranking or {}).get("n_trials", 8)), include_pbo=False)

    sample_cfg = inject_risk_first_defaults(
        {"interval": "1m", "codes": ["DEMO"], "source": "auto", "tags": ["hft"]},
        short_horizon=True,
    )
    gate = validate_risk_first_config(sample_cfg, require_hft_costs=True)

    card = {
        "ab_comparison": ab,
        "overlay_diag_summary": {
            "kill_events": overlay_diag.get("kill_events"),
            "corr_cluster_clips": overlay_diag.get("corr_cluster_clips"),
            "vol_governor_scales": overlay_diag.get("vol_governor_scales"),
            "turnover_cost_clips": overlay_diag.get("turnover_cost_clips"),
            "cvar_scales": overlay_diag.get("cvar_scales"),
        },
        "monte_carlo": {
            "baseline_ruin": mc_base.get("outcomes", {}).get("ruin_probability"),
            "overlay_ruin": mc_adj.get("outcomes", {}).get("ruin_probability"),
            "baseline_es": mc_base.get("outcomes", {}).get("expected_shortfall_return"),
            "overlay_es": mc_adj.get("outcomes", {}).get("expected_shortfall_return"),
            "overlay_sobol_ruin": mc_sobol.get("outcomes", {}).get("ruin_probability"),
            "overlay_sobol_es": mc_sobol.get("outcomes", {}).get("expected_shortfall_return"),
        },
        "grid_ranking_summary": {
            "n_accepted": (ranking or {}).get("n_accepted"),
            "n_rejected": (ranking or {}).get("n_rejected"),
            "best": (ranking or {}).get("best"),
            "gates": (ranking or {}).get("gates"),
        },
        "grid_vs_risk_gated": grid_compare,
        "cscv_pbo": pbo,
        "walk_forward_risk_gated": {
            "pass_rate": wf.get("pass_rate"),
            "passed": wf.get("passed"),
            "n_folds_passed": wf.get("n_folds_passed"),
            "n_folds_failed": wf.get("n_folds_failed"),
        },
        "risk_metrics": {
            "psr": (risk_bundle.get("probabilistic_sharpe") or {}).get("psr"),
            "dsr": (risk_bundle.get("deflated_sharpe") or {}).get("dsr"),
        },
        "config_gate": {"ok": gate.get("ok"), "errors": gate.get("errors"), "warnings": gate.get("warnings")},
        "stress_worst_dd": stress.get("worst_dd_scenario"),
        "stress_has_adv": any(
            s.get("name") == "adv_participation_stress" for s in stress.get("scenarios", [])
        ),
        "limits": (
            "No LOB, queue priority, or nanosecond latency. "
            "Corr-cluster / vol-governor / turnover-cost-feedback / ADV are bar proxies."
        ),
    }

    _print_scorecard(card)
    if args.json:
        print(json.dumps(card, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
