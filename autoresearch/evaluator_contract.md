# ztrade Autoresearch Evaluator Contract

This file is the agent-readable contract for the fixed judge. The executable
source of truth remains the Python code listed below.

## Authoritative Code

- Protocol, windows, baseline, and gates:
  `agent/src/ztrade_autoresearch/protocol.py`
- KEEP/DISCARD decision logic:
  `agent/src/ztrade_autoresearch/evaluator.py`
- Backtest execution and artifact writing:
  `agent/src/ztrade_autoresearch/runner.py`
- Tool wrapper:
  `agent/src/tools/ztrade_autoresearch_tool.py`

## Current Judge

The evaluator compares one candidate against `ztrade_v47_baseline` on paired
windows. It computes return delta, drawdown delta, loss-window count, trade
retention, positive-return concentration, and minimum trade count. A candidate
is KEEP only if every gate passes.

Alternate scoring paths are forbidden. Do not compute your own KEEP/DISCARD
outside `agent/src/ztrade_autoresearch/evaluator.py`.

## Required Mutable Input

The only editable candidate input for V1 is:

`autoresearch/mutable/v47_params.json`

It must contain existing v47 parameter keys only. Bounds are enforced by
`agent/src/ztrade_autoresearch/research_loop.py`.

## Required Proposal Input

Read this file before proposing the next experiment:

`autoresearch/proposals/swarm_proposal_request.json`

Swarm and Alpha Zoo can propose hypotheses. They cannot decide KEEP/DISCARD,
edit evaluator code, or expand the official mutable surface directly.

## Required Output

Each evaluator run writes normal run artifacts under `agent/runs/...` and
updates project-level runtime state:

- `autoresearch/results.tsv` is append-only experiment history.
- `autoresearch/latest_state.json` is refreshed to the latest evaluator state.

These files are runtime outputs and should not be committed. The tracked
templates are:

- `autoresearch/results.template.tsv`
- `autoresearch/latest_state.template.json`

Do not hand-edit evaluator results.
