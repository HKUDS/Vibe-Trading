#!/usr/bin/env python3
"""Demo: risk overlay + HFT cost stack vs unconstrained high-turnover book.

Shows risk-adjusted score ↑ and drawdown / ruin ↓ under bar-proxy costs
(spread + impact + adverse selection). Not exchange co-lo / LOB.

Run from the ``agent/`` directory:

    cd agent && python scripts/demo_risk_overlay_hft.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from backtest.enhanced_validation import (  # noqa: E402
    signal_parameter_grid,
    stress_scenarios,
)
from backtest.hft_config_gate import (  # noqa: E402
    compare_grid_vs_risk_gated,
    inject_risk_first_defaults,
    validate_risk_first_config,
)
from backtest.hft_costs import default_hft_cost_model  # noqa: E402
from backtest.monte_carlo import run_monte_carlo_paths  # noqa: E402
from backtest.risk_metrics import rank_trials_risk_adjusted  # noqa: E402
from backtest.risk_overlay import (  # noqa: E402
    RiskOverlayConfig,
    apply_risk_overlay,
    overlay_ab_comparison,
    simulate_strategy_pnl,
)


def _synthetic_hft_book(
    n_bars: int = 2_000,
    n_names: int = 3,
    seed: int = 11,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """High-turnover long/short weights on noisy mean-reverting returns."""
    rng = np.random.default_rng(seed)
    idx = pd.RangeIndex(n_bars)
    # Mean-reverting microstructure-like returns with crash cluster.
    noise = rng.normal(0.0, 0.0035, size=(n_bars, n_names))
    # Mild AR(1) mean reversion so a constrained book can keep edge.
    rets = np.zeros_like(noise)
    for t in range(1, n_bars):
        rets[t] = -0.25 * rets[t - 1] + noise[t]
    rets[800:820] -= 0.012  # adverse-selection / inventory blow-up window
    rets[1500:1510] -= 0.015
    returns = pd.DataFrame(rets, index=idx, columns=[f"S{i}" for i in range(n_names)])
    # Aggressive book with a stronger mean-reversion tilt — unconstrained
    # overtrades; overlay + HFT costs should improve risk-adjusted score.
    signal = -np.sign(returns.shift(1).fillna(0.0).to_numpy())
    flip_noise = np.sign(rng.normal(size=(n_bars, n_names)))
    raw = 0.7 * signal + 0.3 * flip_noise
    gross = 1.2 + 1.2 * (rng.random(n_bars) > 0.6)
    raw = raw * (gross[:, None] / max(n_names, 1))
    raw[:, 0] *= 2.2  # concentration that overlay will clip
    positions = pd.DataFrame(raw, index=idx, columns=returns.columns)
    close = (1.0 + returns).cumprod() * 100.0
    # Open ≈ prior close with small gap noise (next-bar-open proxy).
    open_ = close.shift(1).fillna(close.iloc[0]) * (1.0 + rng.normal(0.0, 0.0005, size=close.shape))
    open_ = pd.DataFrame(open_.to_numpy(), index=idx, columns=returns.columns)
    return positions, returns, close, open_


def main() -> int:
    parser = argparse.ArgumentParser(description="Risk overlay HFT-proxy demo")
    parser.add_argument("--n-bars", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--n-paths", type=int, default=5_000)
    args = parser.parse_args()

    positions, returns, close, open_ = _synthetic_hft_book(n_bars=args.n_bars, seed=args.seed)
    overlay = RiskOverlayConfig(
        enabled=True,
        vol_target=0.15,
        vol_lookback=30,
        max_gross_leverage=1.0,
        max_net_exposure=0.35,
        max_name_weight=0.4,
        max_turnover=0.25,
        max_drawdown_kill=0.08,
        kill_cooldown_bars=10,
        kill_reset_drawdown=0.03,
        stop_loss=0.05,
        ohlc_stop=True,
        inventory_mean_reversion=0.2,
        partial_fill_rate=0.65,
        next_bar_open_slippage_bps=4.0,
        max_name_vol=0.55,
        name_vol_lookback=25,
        max_portfolio_cvar=0.03,
        cvar_lookback=40,
        bars_per_year=252 * 78,  # ~5m bars / trading year proxy (not co-lo)
    )
    costs = default_hft_cost_model(aggressive=True)

    # Synthetic OHLC for richer stop proxy evidence.
    high = close * (1.0 + 0.002)
    low = close.copy()
    low.iloc[800:820] = close.iloc[800:820] * 0.94  # wick through stop

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
        positions,
        returns,
        config=overlay,
        close=close,
        open_=open_,
        high=high,
        low=low,
    )
    adj_eq = simulate_strategy_pnl(adj, returns, hft_costs=costs, initial_capital=1_000_000.0)

    mc_base = run_monte_carlo_paths(
        method="bootstrap",
        n_paths=args.n_paths,
        equity_curve=base_eq,
        seed=args.seed,
        ruin_level=0.5,
    )
    mc_adj = run_monte_carlo_paths(
        method="bootstrap",
        n_paths=args.n_paths,
        equity_curve=adj_eq,
        seed=args.seed,
        ruin_level=0.5,
    )

    # Risk-adjusted ranking on a small signal grid (synthetic prices).
    px = close.iloc[:, 0]
    grid = signal_parameter_grid(
        px,
        strategy="rsi_mean_reversion",
        collect_trial_returns=True,
        cost_bps=10.0,
        risk_ranking={
            "objective": "sharpe_dd_penalty",
            "max_dd_limit": 0.25,
            "min_psr": 0.4,
            "dd_penalty": 2.0,
        },
    )
    ranking = grid.get("risk_adjusted_ranking")
    if ranking is None and grid.get("trial_returns") is not None:
        ranking = rank_trials_risk_adjusted(
            grid["trial_returns"],
            max_dd_limit=0.25,
            min_psr=0.4,
        )

    grid_compare = None
    if grid.get("trial_returns") is not None:
        grid_compare = compare_grid_vs_risk_gated(
            grid["trial_returns"],
            max_dd_limit=0.25,
            min_psr=0.0,
        )

    stress = stress_scenarios(adj_eq, seed=args.seed)

    # Config gate example (what strategy-generate / hft-risk-alpha must emit).
    sample_cfg = inject_risk_first_defaults(
        {"interval": "1m", "codes": ["DEMO"], "source": "auto"},
        short_horizon=True,
    )
    gate = validate_risk_first_config(sample_cfg, require_hft_costs=True)

    out = {
        "note": (
            "Bar/tick-proxy risk overlay + HFT cost stack demo — not exchange co-lo. "
            "Compares unconstrained high-turnover weights vs risk_overlay under "
            "spread+impact+adverse-selection costs. Live engine fills apply the same "
            "HFT haircut + impact drag when config.hft_costs is set."
        ),
        "ab_comparison": ab,
        "overlay_diag_summary": {
            "kill_events": overlay_diag.get("kill_events"),
            "stop_events": overlay_diag.get("stop_events"),
            "ohlc_stop_events": overlay_diag.get("ohlc_stop_events"),
            "cvar_scales": overlay_diag.get("cvar_scales"),
        },
        "monte_carlo": {
            "baseline_ruin": mc_base.get("outcomes", {}).get("ruin_probability"),
            "overlay_ruin": mc_adj.get("outcomes", {}).get("ruin_probability"),
            "baseline_es": mc_base.get("outcomes", {}).get("expected_shortfall_return"),
            "overlay_es": mc_adj.get("outcomes", {}).get("expected_shortfall_return"),
            "baseline_mdd_p5": (mc_base.get("outcomes", {}).get("max_drawdown", {}).get("percentiles", {}).get("p5")),
            "overlay_mdd_p5": (mc_adj.get("outcomes", {}).get("max_drawdown", {}).get("percentiles", {}).get("p5")),
        },
        "grid_ranking_summary": {
            "n_accepted": (ranking or {}).get("n_accepted"),
            "n_rejected": (ranking or {}).get("n_rejected"),
            "best": (ranking or {}).get("best"),
        },
        "grid_vs_risk_gated": grid_compare,
        "config_gate_ok": gate.get("ok"),
        "stress_worst_dd": stress.get("worst_dd_scenario"),
        "stress_n_scenarios": stress.get("n_scenarios"),
        "limits": (
            "No LOB, queue priority, or nanosecond latency. "
            "partial_fill_rate / next_bar_open_slippage_bps / ohlc_stop / "
            "max_adv_participation are bar proxies. Runner auto-enforces "
            "risk-first defaults for 1s/minute/HFT-tagged configs."
        ),
    }
    print(json.dumps(out, indent=2, default=str))

    # Soft proof: overlay should improve risk-adjusted score and not worsen |max_dd|.
    imp = ab.get("improvement", {})
    if abs(ab["overlay"]["max_drawdown"]) > abs(ab["baseline"]["max_drawdown"]) + 1e-9:
        print(
            "[warn] overlay |max_dd| not better than baseline on this seed "
            f"(base={ab['baseline']['max_drawdown']}, "
            f"overlay={ab['overlay']['max_drawdown']})",
            file=sys.stderr,
        )
    if float(imp.get("risk_adjusted_score_delta", 0.0)) < 0:
        print(
            f"[warn] risk_adjusted_score_delta < 0 on this seed (delta={imp.get('risk_adjusted_score_delta')})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
