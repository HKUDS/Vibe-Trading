#!/usr/bin/env python3
"""Demo: large-batch Monte Carlo + enhanced validation on synthetic equity.

Run from the ``agent/`` directory (or any cwd with ``agent`` on PYTHONPATH):

    cd agent && python scripts/demo_monte_carlo.py
    cd agent && python scripts/demo_monte_carlo.py --n-paths 100000 --antithetic --method gbm --sampling sobol
    cd agent && python scripts/demo_monte_carlo.py --correlated
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Allow `python scripts/demo_monte_carlo.py` from agent/
_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from backtest.enhanced_validation import (  # noqa: E402
    parameter_sensitivity,
    regime_conditioned_backtest,
    regime_conditional_ic,
    signal_parameter_grid,
    stress_scenarios,
    walk_forward_oos,
)
from backtest.monte_carlo import run_monte_carlo_paths  # noqa: E402
from backtest.risk_metrics import run_risk_metrics  # noqa: E402
from backtest.validation import run_validation  # noqa: E402


def _synthetic_equity(n: int = 504, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, size=n)
    # Mild negative skew crash cluster
    rets[200:205] = -0.03
    equity = 1_000_000.0 * np.cumprod(1.0 + rets)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.Series(equity, index=idx, name="equity")


def _synthetic_prices(n: int = 504, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, size=n)
    px = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(px, index=pd.bdate_range("2023-01-02", periods=n), name="close")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monte Carlo + enhanced backtest demo")
    parser.add_argument("--n-paths", type=int, default=10_000, help="Monte Carlo paths")
    parser.add_argument("--batch-size", type=int, default=5_000, help="Batch size")
    parser.add_argument(
        "--method",
        default="bootstrap",
        choices=["gbm", "bootstrap", "block_bootstrap", "correlated_gbm"],
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--antithetic", action="store_true", help="Antithetic variates (GBM family)")
    parser.add_argument("--n-jobs", type=int, default=1, help="Parallel batch workers")
    parser.add_argument(
        "--sampling",
        default="iid",
        choices=["iid", "sobol", "stratified"],
        help="QMC sampling for GBM family",
    )
    parser.add_argument(
        "--correlated",
        action="store_true",
        help="Shortcut: run correlated_gbm demo portfolio",
    )
    args = parser.parse_args()

    equity = _synthetic_equity()
    prices = _synthetic_prices()
    print(f"Synthetic equity bars={len(equity)} start={equity.iloc[0]:.2f} end={equity.iloc[-1]:.2f}")

    def progress(stage, current, total, message):
        if current is None or total is None:
            print(f"[{stage}] {message}")
        elif current == total or current % max(total // 5, 1) == 0:
            print(f"[{stage}] {current}/{total} — {message}")

    method = "correlated_gbm" if args.correlated else args.method
    t0 = time.perf_counter()
    if method == "correlated_gbm":
        mc = run_monte_carlo_paths(
            method="correlated_gbm",
            n_paths=args.n_paths,
            batch_size=args.batch_size,
            seed=args.seed,
            horizon=126,
            antithetic=args.antithetic or True,
            n_jobs=args.n_jobs,
            sampling=args.sampling,
            asset_mu=[0.0005, 0.0003, 0.0002],
            asset_cov=[
                [1.0e-4, 4.0e-5, 2.0e-5],
                [4.0e-5, 1.2e-4, 3.0e-5],
                [2.0e-5, 3.0e-5, 9.0e-5],
            ],
            asset_weights=[0.5, 0.3, 0.2],
            initial_capital=1_000_000.0,
            progress=progress,
        )
    else:
        mc = run_monte_carlo_paths(
            method=method,
            equity_curve=equity,
            n_paths=args.n_paths,
            batch_size=args.batch_size,
            seed=args.seed,
            antithetic=args.antithetic,
            n_jobs=args.n_jobs,
            sampling=args.sampling,
            progress=progress,
        )
    elapsed = time.perf_counter() - t0
    outcomes = mc["outcomes"]
    print("\n=== Monte Carlo outcomes ===")
    print(json.dumps({
        "method": mc["method"],
        "n_paths": mc["n_paths"],
        "antithetic": mc.get("antithetic"),
        "sampling": mc.get("sampling"),
        "n_jobs": mc.get("n_jobs"),
        "parallel_backend": mc.get("parallel_backend"),
        "elapsed_s": round(elapsed, 3),
        "paths_per_sec": int(args.n_paths / max(elapsed, 1e-9)),
        "ruin_probability": outcomes["ruin_probability"],
        "expected_shortfall_return": outcomes["expected_shortfall_return"],
        "terminal_wealth_percentiles": outcomes["terminal_wealth"]["percentiles"],
        "max_drawdown_percentiles": outcomes["max_drawdown"]["percentiles"],
    }, indent=2))

    print("\n=== Enhanced validation (stress / WF-OOS / sensitivity / regimes / signal grid) ===")
    # Multi-asset returns for correlation-regime axis
    rng = np.random.default_rng(args.seed)
    factor = rng.normal(0, 0.01, len(equity))
    rets_m = pd.DataFrame(
        {
            "A": 0.7 * factor + 0.3 * rng.normal(0, 0.01, len(equity)),
            "B": 0.7 * factor + 0.3 * rng.normal(0, 0.01, len(equity)),
            "C": 0.3 * factor + 0.7 * rng.normal(0, 0.012, len(equity)),
        },
        index=equity.index,
    )
    enhanced = {
        "stress": stress_scenarios(equity),
        "walk_forward_oos": walk_forward_oos(equity, n_windows=4),
        "parameter_sensitivity": parameter_sensitivity(
            equity,
            return_scales=(0.75, 1.0, 1.25),
            vol_scales=(1.0, 1.5),
            cost_drags_bps=(0.0, 10.0),
        ),
        "signal_parameter_grid": signal_parameter_grid(
            prices,
            strategy="ma_crossover",
            param_grid={"fast": [5, 10, 15], "slow": [20, 40, 60]},
            cost_bps=5.0,
            collect_trial_returns=True,
            pbo_n_groups=8,
        ),
        "regime_conditioned": regime_conditioned_backtest(
            equity,
            returns_matrix=rets_m,
            corr_window=40,
            include_trend=True,
            export_regime_labels=True,
        ),
        "risk_metrics": run_risk_metrics(
            equity,
            n_trials=15,
            n_bootstrap=500,
            seed=args.seed,
            include_pbo=True,
            # Will be filled after grid runs — see below
        ),
    }
    # Exact CSCV PBO from the signal grid return matrix
    grid_rets = enhanced["signal_parameter_grid"].get("trial_returns")
    if grid_rets is not None:
        enhanced["risk_metrics"] = run_risk_metrics(
            equity,
            n_trials=int(enhanced["signal_parameter_grid"]["n_combinations"]),
            n_bootstrap=500,
            seed=args.seed,
            include_pbo=True,
            trial_returns=grid_rets,
            pbo_n_groups=8,
        )

    # Mild predictive link in a synthetic cross-section for regime-conditional IC
    n_names = 12
    factor_panel = pd.DataFrame(
        rng.normal(0, 1, size=(len(equity), n_names)),
        index=equity.index,
        columns=[f"S{i}" for i in range(n_names)],
    )
    ret_panel = pd.DataFrame(
        {
            c: 0.05 * factor_panel[c] + rng.normal(0, 0.02, len(equity))
            for c in factor_panel.columns
        },
        index=equity.index,
    )
    enhanced["regime_conditional_ic"] = regime_conditional_ic(
        factor_panel,
        ret_panel,
        regime_result=enhanced["regime_conditioned"],
        axis="vol",
        min_obs=10,
    )

    summary = {
        "worst_stress": enhanced["stress"].get("worst_return_scenario"),
        "oos_consistency": enhanced["walk_forward_oos"].get("consistency_rate"),
        "sensitivity_stability": enhanced["parameter_sensitivity"].get("stability_rate"),
        "signal_grid_stability": enhanced["signal_parameter_grid"].get("stability_rate"),
        "signal_grid_best": enhanced["signal_parameter_grid"].get("best"),
        "cscv_pbo": (enhanced["signal_parameter_grid"].get("cscv_pbo") or {}).get("pbo"),
        "regime_axes": enhanced["regime_conditioned"].get("axes"),
        "regime_label_axes": list((enhanced["regime_conditioned"].get("regime_labels") or {}).keys()),
        "regime_sharpe_spread_vol": enhanced["regime_conditioned"].get("sharpe_spread_high_minus_low"),
        "regime_ic_overall": (enhanced["regime_conditional_ic"].get("overall") or {}).get("mean_ic"),
        "regime_ic_by_vol": {
            k: v.get("mean_ic")
            for k, v in (enhanced["regime_conditional_ic"].get("by_regime") or {}).items()
        },
        "psr": enhanced["risk_metrics"]["probabilistic_sharpe"]["psr"],
        "dsr": enhanced["risk_metrics"]["deflated_sharpe"]["dsr"],
        "expected_max_sharpe": enhanced["risk_metrics"]["deflated_sharpe"]["expected_max_sharpe"],
        "pbo_method": (enhanced["risk_metrics"].get("pbo") or {}).get("method"),
        "pbo": (enhanced["risk_metrics"].get("pbo") or {}).get("pbo"),
    }
    print(json.dumps(summary, indent=2, default=str))

    print("\n=== Dispatcher smoke (config.validation) ===")
    dispatched = run_validation(
        {
            "validation": {
                "monte_carlo_paths": {
                    "method": "gbm",
                    "n_paths": min(2_000, args.n_paths),
                    "batch_size": 1_000,
                    "seed": args.seed,
                    "sampling": "sobol",
                    "antithetic": True,
                },
                "stress": {"seed": args.seed},
                "regime_conditioned": {
                    "include_trend": True,
                    "export_regime_labels": True,
                },
                "signal_parameter_grid": {
                    "strategy": "ma_crossover",
                    "param_grid": {"fast": [10], "slow": [30]},
                    "collect_trial_returns": True,
                },
                "risk_metrics": {
                    "n_trials": 10,
                    "n_bootstrap": 200,
                    "include_pbo": True,
                    "pbo_n_groups": 8,
                },
            }
        },
        equity,
        trades=[],
        initial_capital=float(equity.iloc[0]),
    )
    print("keys:", sorted(dispatched.keys()))
    print("demo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
