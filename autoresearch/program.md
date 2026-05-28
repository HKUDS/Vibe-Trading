# ztrade Karpathy-Style Autoresearch Program

You are driving a long-running quant research loop in the style of
Karpathy/autoresearch.

## Objective

Improve the ztrade v47 strategy family under a fixed, code-owned judge.
The first research surface is v47 parameter tuning only.

## Loop

1. Read every file in the Required Context section before changing anything.
2. If this is a fresh workspace, run the baseline/default v47 evaluation first
   before proposing any parameter change.
3. Think with the local Alpha Zoo context and the swarm proposal request.
4. Mutate exactly one allowed candidate surface:
   `autoresearch/mutable/v47_params.json`.
5. Run the fixed ztrade autoresearch evaluator through the Required Evaluator
   Invocation section. Do not invent another backtest or scoring path.
6. Let the evaluator append `results.tsv` and refresh `latest_state.json`.
7. Keep the candidate only when the evaluator returns KEEP and all required
   gates pass. Otherwise discard or revise in the next iteration.
8. NEVER STOP after a single iteration. Continue proposing, evaluating, and
   keeping/discarding until a human explicitly stops the session, a hard blocker
   repeats, or a configured loop limit is reached.

## Required Context

Before each iteration, read these project-level files:

- `autoresearch/program.md`
- `autoresearch/evaluator_contract.md`
- `autoresearch/results.tsv` if present; otherwise create it from
  `autoresearch/results.template.tsv`
- `autoresearch/latest_state.json` if present; otherwise create it from
  `autoresearch/latest_state.template.json`
- `autoresearch/best/v47_params.json`
- `autoresearch/mutable/v47_params.json`
- `autoresearch/context/alpha_zoo_context.json`
- `autoresearch/proposals/swarm_proposal_request.json`

Every iteration must also inspect these code-owned judge files before proposing
or evaluating a candidate:

- `agent/src/ztrade_autoresearch/protocol.py`
- `agent/src/ztrade_autoresearch/evaluator.py`
- `agent/src/ztrade_autoresearch/runner.py`
- `agent/src/tools/ztrade_autoresearch_tool.py`

## Required Evaluator Invocation

Use the existing ztrade autoresearch evaluator only. The normal CSV command is:

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="agent/runs/ztrade_autoresearch_${RUN_ID}"
export RUN_DIR
mkdir -p "$RUN_DIR/logs"
PYTHONPATH=agent uv run python - <<'PY' > "$RUN_DIR/logs/autoresearch_stdout.log" 2> "$RUN_DIR/logs/autoresearch_stderr.log"
import os
from pathlib import Path
from src.ztrade_autoresearch.runner import run_ztrade_csv_research

run_ztrade_csv_research(
    Path(os.environ["RUN_DIR"]),
    data_dir="/Users/wdblink/Code/my_repo/ztrade/data",
    max_iterations=1,
    max_symbols=200,
    use_mutable_candidate=True,
)
PY
```

For baseline-first sanity on a fresh workspace, do not mutate params. Run the
same evaluator with static search disabled after baseline:

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="agent/runs/ztrade_autoresearch_baseline_${RUN_ID}"
export RUN_DIR
mkdir -p "$RUN_DIR/logs"
PYTHONPATH=agent uv run python - <<'PY' > "$RUN_DIR/logs/autoresearch_stdout.log" 2> "$RUN_DIR/logs/autoresearch_stderr.log"
import os
from pathlib import Path
from src.ztrade_autoresearch.runner import run_ztrade_csv_research

run_ztrade_csv_research(
    Path(os.environ["RUN_DIR"]),
    data_dir="/Users/wdblink/Code/my_repo/ztrade/data",
    max_iterations=0,
    max_symbols=200,
    use_mutable_candidate=False,
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

## Baseline First

Before the first parameter mutation in a new research run, evaluate the default
v47 baseline using the baseline-first command above. This run should produce
baseline rows and no candidate verdict. Do not treat an empty `results.tsv` as
evidence that parameter search should start immediately.

## Git Advance/Revert Discipline

Each candidate iteration must be recoverable:

1. Start from a clean or understood worktree.
2. Record the current commit hash and mutable params before editing.
3. Edit only `autoresearch/mutable/v47_params.json`.
4. Run the required evaluator.
5. If verdict is KEEP, update `autoresearch/best/v47_params.json` and commit
   the kept candidate with a message that includes the evaluator score.
6. If verdict is DISCARD/BLOCKED, revert `autoresearch/mutable/v47_params.json`
   to the previous best candidate. Do not commit discarded params.

Do not use destructive repository-wide commands. Revert only the mutable
candidate file unless a human explicitly requests broader reset behavior.

## Logging

Every evaluator invocation must write stdout and stderr under that run's
`logs/` directory. Do not stream full backtest output into the chat context.
Summarize the verdict, score, failed gates, and run directory instead.

## Timeouts and Crashes

If an evaluator run exceeds 90 minutes, stop that run, mark the candidate
BLOCKED in notes, inspect stderr, and continue with a simpler candidate. If the
run crashes, first check whether the crash is caused by the candidate params. A
small candidate-surface fix is allowed; evaluator/protocol/backtest fixes are
not allowed during the research loop.

## Simplicity Criterion

Prefer simpler changes when scores are similar. A small return or win-rate
improvement is not enough if it requires a wider mutable surface, opaque factor
addition, or fragile one-window behavior.

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
