---
name: enhanced-backtest
description: "Enhanced backtest validation: stress scenarios, walk-forward OOS, parameter sensitivity, regime-conditioned splits, Monte Carlo path hooks."
category: analysis
---

# Enhanced Backtest Validation

## Overview

Beyond the classic Monte Carlo permutation / Bootstrap / Walk-Forward trio,
enable richer checks under `config.validation`:

| Key | Purpose |
|-----|---------|
| `stress` | Shock and vol-spike scenarios on the equity path |
| `walk_forward_oos` | Rolling/expanding IS vs OOS folds with degradation stats |
| `parameter_sensitivity` | Grid over return scale / vol scale / cost drag |
| `regime_conditioned` | High-vol vs low-vol performance split |
| `monte_carlo_paths` | Large-batch path simulation (see `monte-carlo-sim` skill) |

## Example config

```json
"validation": {
  "monte_carlo": {"n_simulations": 1000},
  "bootstrap": {"n_bootstrap": 1000, "confidence": 0.95},
  "walk_forward": {"n_windows": 5},
  "walk_forward_oos": {"n_windows": 5, "train_ratio": 0.7, "mode": "rolling"},
  "stress": {"seed": 42},
  "parameter_sensitivity": {
    "return_scales": [0.5, 1.0, 1.5],
    "vol_scales": [1.0, 1.5, 2.0],
    "cost_drags_bps": [0, 10, 25]
  },
  "regime_conditioned": {"vol_window": 21, "high_vol_percentile": 70},
  "monte_carlo_paths": {"method": "bootstrap", "n_paths": 10000}
}
```

## Interpretation checklist

1. **Stress** — Identify worst return / drawdown scenario; size risk for that case.
2. **Walk-forward OOS** — Mean Sharpe degradation IS→OOS; consistency_rate of profitable OOS folds.
3. **Parameter sensitivity** — `stability_rate` near 1.0 implies robustness; inspect `worst` grid cell.
4. **Regime-conditioned** — Prefer strategies that do not collapse entirely in high-vol regimes.
5. **Monte Carlo paths** — Ruin probability and ES before sizing live capital.

## Modules

- `backtest.enhanced_validation`
- `backtest.monte_carlo`
- `backtest.validation.run_validation` (dispatcher)
