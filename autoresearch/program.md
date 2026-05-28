# ztrade Karpathy-Style Autoresearch Program

You are driving a long-running quant research loop in the style of
Karpathy/autoresearch.

## Objective

Improve the ztrade v47 strategy family under a fixed, code-owned judge.
The first research surface is v47 parameter tuning only.

## Loop

1. Read every file in the Required Context section before changing anything.
2. Think with the local Alpha Zoo context and the swarm proposal request.
3. Mutate exactly one allowed candidate surface:
   `autoresearch/mutable/v47_params.json`.
4. Run the fixed ztrade autoresearch evaluator through the Required Evaluator
   Invocation section. Do not invent another backtest or scoring path.
5. Let the evaluator append or refresh `results.tsv` and `latest_state.json`.
6. Keep the candidate only when the evaluator returns KEEP and all required
   gates pass. Otherwise discard or revise in the next iteration.

## Required Context

Before each iteration, read these project-level files:

- `autoresearch/program.md`
- `autoresearch/evaluator_contract.md`
- `autoresearch/results.tsv`
- `autoresearch/latest_state.json`
- `autoresearch/best/v47_params.json`
- `autoresearch/mutable/v47_params.json`
- `autoresearch/context/alpha_zoo_context.json`
- `autoresearch/proposals/swarm_proposal_request.json`

Then inspect these code-owned judge files when evaluator behavior is relevant:

- `agent/src/ztrade_autoresearch/protocol.py`
- `agent/src/ztrade_autoresearch/evaluator.py`
- `agent/src/ztrade_autoresearch/runner.py`
- `agent/src/tools/ztrade_autoresearch_tool.py`

## Required Evaluator Invocation

Use the existing ztrade autoresearch evaluator only. The normal CSV command is:

```bash
PYTHONPATH=agent uv run python - <<'PY'
from pathlib import Path
from src.ztrade_autoresearch.runner import run_ztrade_csv_research

run_ztrade_csv_research(
    Path("agent/runs") / "ztrade_autoresearch_<iteration_id>",
    data_dir="/Users/wdblink/Code/my_repo/ztrade/data",
    max_iterations=1,
    max_symbols=200,
    use_mutable_candidate=True,
)
PY
```

The tool-equivalent invocation is `ztrade_autoresearch` with:

```json
{
  "mode": "ztrade_csv",
  "data_dir": "/Users/wdblink/Code/my_repo/ztrade/data",
  "max_iterations": 1,
  "max_symbols": 200,
  "use_mutable_candidate": true
}
```

## Immutable Judge

Do not modify data loaders, data windows, benchmark rows, evaluator gates,
backtest execution, cost/slippage/T+1 assumptions, run-card hashing, or frozen
test rules during a research run.

## Proposal Layer

Swarm agents and Alpha Zoo are inside the Think step:

- Swarm may analyze history, explain failure modes, challenge overfitting, and
  propose one next experiment.
- Alpha Zoo is the explainable idea library for factors and factor families.
- Neither swarm nor Alpha Zoo may decide KEEP/DISCARD.
- Neither may directly expand the official search space.

Search-space expansion is allowed only as a written proposal after repeated
plateau evidence under v47 parameter tuning. The proposal must be evaluated by
a separate human or code-review step before becoming mutable surface.

## Current Allowed Surface

Only `autoresearch/mutable/v47_params.json` may be edited by the loop.
All keys must be existing v47 parameter keys and must stay within the
machine-checked bounds in the project code.
