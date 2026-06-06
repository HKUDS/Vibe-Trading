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
- Karpathy-style runs use the repo-level `autoresearch/program.md` as the loop
  contract and `autoresearch/mutable/v47_params.json` as the first editable
  surface.
- Swarm and Alpha Zoo may participate in the Think/proposal step, but only as
  read-only analysis context. KEEP/DISCARD remains the fixed evaluator's job.

## Starting Point

The initial strategy is the ztrade `v47_weak_guard_62_70` profile, currently
recorded in ztrade as `DEFAULT_V3_PROFILE`.

## Tool

Use the `ztrade_autoresearch` tool for the deterministic synthetic smoke:

```json
{
  "run_dir": "agent/runs/ztrade_autoresearch_smoke",
  "candidate_iterations": 4
}
```

The smoke loop uses deterministic synthetic A-share OHLCV data to verify the
Vibe-Trading scaffolding before connecting live Tushare data.

For the Karpathy-faithful loop shape, set `use_mutable_candidate: true`.
The tool initializes the repo-level workspace by default:

- `autoresearch/program.md`
- `autoresearch/mutable/v47_params.json`
- `autoresearch/context/alpha_zoo_context.json`
- `autoresearch/proposals/swarm_proposal_request.json`
- `autoresearch/results.tsv`
- `autoresearch/latest_state.json`

The coding agent should edit only `autoresearch/mutable/v47_params.json`, rerun
the fixed evaluator, then keep or discard based on the evaluator verdict.
Each `run_dir` remains only the fixed evaluator output directory. Pass
`workspace_dir` only for tests or intentionally isolated research workspaces.

Use local ztrade CSV history with:

```json
{
  "run_dir": "agent/runs/ztrade_autoresearch_csv",
  "mode": "ztrade_csv",
  "data_dir": "/Users/wdblink/Code/my_repo/ztrade/data",
  "candidate_iterations": 4,
  "max_symbols": 200
}
```

The CSV mode uses a 180-day indicator warmup and blocks signals before each
evaluation window starts.

## Promotion: Local Paper Simulation

After a candidate has passed the fixed evaluator and is written to
`autoresearch/best/v47_params.json`, use `ztrade_paper_sim` to promote it into
a broker-free live-like run directory:

```json
{
  "run_dir": "agent/runs/ztrade_paper_demo",
  "mode": "ztrade_csv",
  "data_dir": "/Users/wdblink/Code/my_repo/ztrade/data",
  "max_symbols": 200
}
```

The tool writes:

- `config.json`
- `code/signal_engine.py`
- `artifacts/equity.csv`
- `artifacts/positions.csv`
- `artifacts/trades.csv`
- `artifacts/paper_state.json`
- `run_card.json`

This is a local paper account only. It never connects to a broker, order
gateway, vn.py gateway, or live account. Use `vnpy-export` separately when a
human explicitly wants a vn.py CTA template for external deployment review.
