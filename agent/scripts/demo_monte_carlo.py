#!/usr/bin/env python3
"""Demo: large-batch Monte Carlo + enhanced validation on synthetic equity.

Run from the ``agent/`` directory (or any cwd with ``agent`` on PYTHONPATH):

    cd agent && python scripts/demo_monte_carlo.py
    cd agent && python scripts/demo_monte_carlo.py --n-paths 100000
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
    stress_scenarios,
    walk_forward_oos,
)
from backtest.monte_carlo import run_monte_carlo_paths  # noqa: E402
from backtest.validation import run_validation  # noqa: E402


def _synthetic_equity(n: int = 504, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, size=n)
    # Mild negative skew crash cluster
    rets[200:205] = -0.03
    equity = 1_000_000.0 * np.cumprod(1.0 + rets)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.Series(equity, index=idx, name="equity")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monte Carlo + enhanced backtest demo")
    parser.add_argument("--n-paths", type=int, default=10_000, help="Monte Carlo paths")
    parser.add_argument("--batch-size", type=int, default=5_000, help="Batch size")
    parser.add_argument("--method", default="bootstrap", choices=["gbm", "bootstrap", "block_bootstrap"])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    equity = _synthetic_equity()
    print(f"Synthetic equity bars={len(equity)} start={equity.iloc[0]:.2f} end={equity.iloc[-1]:.2f}")

    def progress(stage, current, total, message):
        if current is None or total is None:
            print(f"[{stage}] {message}")
        elif current == total or current % max(total // 5, 1) == 0:
            print(f"[{stage}] {current}/{total} — {message}")

    t0 = time.perf_counter()
    mc = run_monte_carlo_paths(
        method=args.method,
        equity_curve=equity,
        n_paths=args.n_paths,
        batch_size=args.batch_size,
        seed=args.seed,
        progress=progress,
    )
    elapsed = time.perf_counter() - t0
    outcomes = mc["outcomes"]
    print("\n=== Monte Carlo outcomes ===")
    print(json.dumps({
        "method": mc["method"],
        "n_paths": mc["n_paths"],
        "elapsed_s": round(elapsed, 3),
        "paths_per_sec": int(args.n_paths / max(elapsed, 1e-9)),
        "ruin_probability": outcomes["ruin_probability"],
        "expected_shortfall_return": outcomes["expected_shortfall_return"],
        "terminal_wealth_percentiles": outcomes["terminal_wealth"]["percentiles"],
        "max_drawdown_percentiles": outcomes["max_drawdown"]["percentiles"],
    }, indent=2))

    print("\n=== Enhanced validation (stress / WF-OOS / sensitivity / regime) ===")
    enhanced = {
        "stress": stress_scenarios(equity),
        "walk_forward_oos": walk_forward_oos(equity, n_windows=4),
        "parameter_sensitivity": parameter_sensitivity(
            equity,
            return_scales=(0.75, 1.0, 1.25),
            vol_scales=(1.0, 1.5),
            cost_drags_bps=(0.0, 10.0),
        ),
        "regime_conditioned": regime_conditioned_backtest(equity),
    }
    summary = {
        "worst_stress": enhanced["stress"].get("worst_return_scenario"),
        "oos_consistency": enhanced["walk_forward_oos"].get("consistency_rate"),
        "sensitivity_stability": enhanced["parameter_sensitivity"].get("stability_rate"),
        "regime_sharpe_spread": enhanced["regime_conditioned"].get("sharpe_spread_high_minus_low"),
    }
    print(json.dumps(summary, indent=2))

    print("\n=== Dispatcher smoke (config.validation) ===")
    dispatched = run_validation(
        {
            "validation": {
                "monte_carlo_paths": {
                    "method": "gbm",
                    "n_paths": min(2_000, args.n_paths),
                    "batch_size": 1_000,
                    "seed": args.seed,
                },
                "stress": {"seed": args.seed},
                "regime_conditioned": {},
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
