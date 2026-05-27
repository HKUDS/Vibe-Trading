---
name: ztrade-autoresearch
description: Run a bounded ztrade V47-style autoresearch loop on Vibe-Trading backtest scaffolding.
---

# ztrade Autoresearch

This skill is for ztrade strategy research, not live trading.

## Boundary

- Agent may propose candidate changes only inside the candidate strategy surface.
- Agent must not modify the evaluator, data windows, search space, or backtest engine during a run.
- Candidate code must use standard library plus existing project dependencies only.
- The loop produces research evidence and run cards. It does not promote live profiles.

## Starting Point

The initial strategy is the ztrade `v47_weak_guard_62_70` profile, currently
recorded in ztrade as `DEFAULT_V3_PROFILE`.

## Tool

Use the `ztrade_autoresearch` tool for the deterministic synthetic smoke:

```json
{
  "run_dir": "agent/runs/ztrade_autoresearch_smoke",
  "max_iterations": 4
}
```

The smoke loop uses deterministic synthetic A-share OHLCV data to verify the
Vibe-Trading scaffolding before connecting live Tushare data.

Use local ztrade CSV history with:

```json
{
  "run_dir": "agent/runs/ztrade_autoresearch_csv",
  "mode": "ztrade_csv",
  "data_dir": "/Users/wdblink/Code/my_repo/ztrade/data",
  "max_iterations": 4,
  "max_symbols": 200
}
```

The CSV mode uses a 180-day indicator warmup and blocks signals before each
evaluation window starts.
