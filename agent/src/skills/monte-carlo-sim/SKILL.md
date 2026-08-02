---
name: monte-carlo-sim
description: "Large-batch Monte Carlo path simulation: GBM, bootstrap, block bootstrap; ruin probability, expected shortfall, percentile bands."
category: analysis
---

# Monte Carlo Path Simulation

## Overview

Use the `monte_carlo` tool (or `config.validation.monte_carlo_paths`) for
**thousands to millions** of simulated equity paths. This is distinct from the
trade-order **permutation** test (`validation.monte_carlo`), which shuffles
realized trade PnLs to get a Sharpe p-value.

## Methods

| Method | When to use |
|--------|-------------|
| `bootstrap` (default) | Resample historical strategy/asset returns i.i.d. |
| `block_bootstrap` | Preserve short-run autocorrelation (set `block_size`, default 21) |
| `gbm` | Parametric geometric Brownian motion (`mu`/`sigma` optional; else calibrated) |
| `permute` | Only via `monte_carlo_paths.method=permute` — delegates to trade shuffle test |

## Defaults

- `n_paths`: **10_000** (cap **5_000_000**)
- `batch_size`: **5_000** (vectorized batches; lower if memory-constrained)
- `horizon`: length of history, else **252** bars
- `ruin_level`: **0.5** (50% of initial capital)
- `es_alpha`: **0.95** expected shortfall on return losses

## Tool usage

```text
monte_carlo(
  run_dir="<run_dir>",
  method="bootstrap",
  n_paths=100000,
  batch_size=10000,
  seed=42
)
```

Or with raw returns (no run dir):

```text
monte_carlo(returns=[...], n_paths=50000, method="gbm", mu=0.0004, sigma=0.012)
```

## Config hook (post-backtest)

```json
"validation": {
  "monte_carlo": {"n_simulations": 1000},
  "monte_carlo_paths": {
    "method": "block_bootstrap",
    "n_paths": 100000,
    "batch_size": 10000,
    "block_size": 21,
    "ruin_level": 0.5,
    "es_alpha": 0.95
  }
}
```

## Outputs to report

1. Terminal-wealth percentiles (p1 / p5 / p50 / p95 / p99)
2. Ruin probability at `ruin_level`
3. Expected shortfall (CVaR) of returns
4. Max-drawdown distribution (mean / worst / percentiles)
5. Confidence bands (`equity_paths`) for fan charts

## Standalone demo

```bash
cd agent && python scripts/demo_monte_carlo.py
```
