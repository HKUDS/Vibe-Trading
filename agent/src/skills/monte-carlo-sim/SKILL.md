---
name: monte-carlo-sim
description: "Large-batch Monte Carlo path simulation: GBM, bootstrap, block bootstrap, correlated multi-asset GBM; antithetic / Sobol / stratified VR; process-pool block bootstrap; ruin / ES / percentile bands."
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
| `correlated_gbm` | Multi-asset correlated GBM → portfolio path (`asset_mu`, `asset_cov`, `asset_weights`) |
| `permute` | Only via `monte_carlo_paths.method=permute` — delegates to trade shuffle test |

## Variance reduction & scale

- `antithetic=true` — pairs Z with −Z for `gbm` / `correlated_gbm`
- `sampling=sobol` — scrambled Sobol QMC → normals (GBM family; falls back to LHS if dim huge)
- `sampling=stratified` — Latin Hypercube sampling → normals
- `n_jobs>1` — batch parallelism (`thread` for vectorized methods; `process` auto for `block_bootstrap`)
- `parallel_backend` — `auto` | `thread` | `process`
- `batch_size` — keep memory bounded at 1e5–1e6+ paths (default 5000)

## Defaults

- `n_paths`: **10_000** (cap **5_000_000**)
- `batch_size`: **5_000**
- `horizon`: length of history, else **252** bars
- `ruin_level`: **0.5** (50% of initial capital)
- `es_alpha`: **0.95** expected shortfall on return losses
- `sampling`: prefer **sobol** for GBM family research (tool default remains `iid`)
- `antithetic`: prefer **true** for GBM / correlated_gbm
- `block_bootstrap`: vectorized path construction; `n_jobs>1` → process pool by default

## Tool usage

```text
monte_carlo(
  run_dir="<run_dir>",
  method="gbm",
  n_paths=100000,
  batch_size=10000,
  sampling="sobol",
  antithetic=true,
  n_jobs=4,
  seed=42
)
```

Correlated multi-asset:

```text
monte_carlo(
  method="correlated_gbm",
  n_paths=20000,
  horizon=252,
  sampling="stratified",
  antithetic=true,
  asset_mu=[0.0004, 0.0003],
  asset_cov=[[0.0001, 0.00005], [0.00005, 0.00012]],
  asset_weights=[0.6, 0.4],
  initial_capital=1000000
)
```

Block bootstrap with process pool:

```text
monte_carlo(
  method="block_bootstrap",
  n_paths=50000,
  block_size=21,
  n_jobs=4,
  parallel_backend="process"
)
```

## Config hook (post-backtest)

```json
"validation": {
  "monte_carlo": {"n_simulations": 1000},
  "monte_carlo_paths": {
    "method": "gbm",
    "n_paths": 100000,
    "batch_size": 10000,
    "sampling": "sobol",
    "antithetic": true,
    "n_jobs": 2,
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
6. Whether antithetic / sampling / n_jobs / parallel_backend were used

## Standalone demo

```bash
cd agent && python scripts/demo_monte_carlo.py
cd agent && python scripts/demo_monte_carlo.py --n-paths 100000 --antithetic --method gbm --sampling sobol
cd agent && python scripts/demo_monte_carlo.py --method block_bootstrap --n-jobs 2
```
