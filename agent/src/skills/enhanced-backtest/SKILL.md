---
name: enhanced-backtest
description: "Enhanced backtest validation: stress, WF-OOS, post-hoc + signal/SignalEngine param grids, multi-axis regimes, regime-conditional IC, CSCV PBO (exact/subsample), PSR/DSR, Monte Carlo path hooks."
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
| `parameter_sensitivity` | Post-hoc grid over return scale / vol scale / cost drag |
| `signal_parameter_grid` | **True** signal re-runs (MA / breakout / RSI / MACD / vol-target …) |
| `regime_conditioned` | Vol + trend (+ optional correlation-fused) splits; optional `export_regime_labels` |
| `regime_conditional_ic` | Spearman IC overall + per-regime (needs `factor_df` / `return_df` + labels) |
| `risk_metrics` | PSR, DSR, bootstrap CI, CSCV PBO (`trial_returns`) or approx |
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
  "signal_parameter_grid": {
    "strategy": "ma_crossover",
    "param_grid": {"fast": [5, 10, 15], "slow": [20, 40, 60]},
    "cost_bps": 5,
    "collect_trial_returns": true,
    "use_signal_engine": true,
    "pbo_n_groups": 8
  },
  "regime_conditioned": {
    "vol_window": 21,
    "high_vol_percentile": 70,
    "include_trend": true,
    "trend_window": 63,
    "export_regime_labels": true
  },
  "regime_conditional_ic": {
    "axis": "vol",
    "min_obs": 20
  },
  "risk_metrics": {
    "n_trials": 20,
    "n_bootstrap": 1000,
    "include_pbo": true,
    "pbo_n_groups": 8,
    "pbo_max_combinations": 12870
  },
  "monte_carlo_paths": {
    "method": "gbm",
    "n_paths": 10000,
    "sampling": "sobol",
    "antithetic": true
  }
}
```

### Signal / SignalEngine grid knobs

- Builtins: `ma_crossover`, `breakout`, `threshold_momentum`, `rsi_mean_reversion`,
  `macd_crossover`, `vol_target_momentum`
- `collect_trial_returns: true` → attaches `(T, N)` matrix + `cscv_pbo`
- `use_signal_engine: true` or `module_path: "…/signal_engine.py"` → calls
  `SignalEngine.generate(data_map)` per param cell (runner-like vertical slice)
- `module_path` must sit under `run_dir` / `allow_roots`; source is AST-scanned
  (blocks OS/network/`eval`/`exec` style imports) before load
- When `risk_metrics.include_pbo` is set and the grid collected `trial_returns`,
  the dispatcher feeds that matrix into CSCV PBO automatically

### CSCV PBO (exact vs random subsample)

- `pbo_n_groups` even, typically 8–16 for exact CSCV (`method=cscv_exact`)
- When `C(n_groups, n/2) > pbo_max_combinations` (default 12_870 = C(16,8)),
  typically `n_groups > 16`, CSCV uses a reproducible random combination
  subsample (`method=cscv_random_subsample`, seed from `risk_metrics.seed`)

### Regime labels → factor_analysis / regime-conditional IC

With `export_regime_labels: true`, results include date→label maps. Convert via
`regime_labels_to_frame(result)` and join onto a factor panel before calling
`factor_analysis`.

For a lightweight IC-by-regime table without layered NAV, call
`regime_conditional_ic(factor_df, return_df, regime_result=...)` or set
`config.validation.regime_conditional_ic` (reuses `regime_conditioned` labels
when present; still requires `factor_df` / `return_df` in that config block).

## Interpretation checklist

1. **Stress** — Identify worst return / drawdown scenario; size risk for that case.
2. **Walk-forward OOS** — Mean Sharpe degradation IS→OOS; consistency_rate of profitable OOS folds.
3. **Parameter sensitivity** — Post-hoc `stability_rate`; inspect `worst` grid cell.
4. **Signal parameter grid** — True re-runs; prefer high `stability_rate`; check `cscv_pbo`.
5. **Regime-conditioned** — Check vol, trend, vol×trend cross, and fused/defused if available.
6. **Regime-conditional IC** — Compare mean IC / ICIR across high_vol vs low_vol (or trend).
7. **Risk metrics** — PSR near 1 supports edge; DSR falls as `n_trials` rises; CSCV `pbo` high ⇒ selection overfitting.
8. **Monte Carlo paths** — Prefer `sampling=sobol`; ruin probability and ES before sizing live capital.

## Modules

- `backtest.enhanced_validation`
- `backtest.risk_metrics`
- `backtest.monte_carlo`
- `backtest.validation.run_validation` (dispatcher)
