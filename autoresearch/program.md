# ztrade Karpathy-Style Autoresearch Program

You are driving a long-running quant research loop in the style of
Karpathy/autoresearch.

## Objective

Improve the ztrade v47 strategy family under a fixed, code-owned judge.
The first research surface is v47 parameter tuning only.

## Loop

1. Read this file, `results.tsv`, `latest_state.json`, and the current best
   parameters before changing anything.
2. Think with the local Alpha Zoo context and the swarm proposal request.
3. Mutate exactly one allowed candidate surface:
   `autoresearch/mutable/v47_params.json`.
4. Run the fixed ztrade autoresearch evaluator.
5. Append or refresh `results.tsv` from evaluator output.
6. Keep the candidate only when the evaluator returns KEEP and all required
   gates pass. Otherwise discard or revise in the next iteration.

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
