# ztrade Karpathy-Style Autoresearch Program

You are driving a long-running quant research loop in the style of
Karpathy/autoresearch.

## Objective

Improve the ztrade v47 strategy family under a fixed, code-owned judge.
The active research surface includes v47 parameter tuning, candidate-only
indicator composition from the project Alpha Zoo/indicator library, and
regime-aware position sizing that can differ between bull and bear-like states.
Leverage is no longer an allowed candidate mechanism; every future mutable
candidate must keep `allow_leverage=false`.

## Loop

1. Read every file in the Required Context section before changing anything.
2. If this is a fresh workspace, run the baseline/default v47 evaluation first
   before proposing any parameter change.
3. Think with the local Alpha Zoo context and the swarm proposal request. Before
   editing params, write the candidate hypothesis, expected improvement,
   expected cost, and failure criteria in the iteration report draft.
4. Mutate exactly one allowed candidate surface:
   `autoresearch/mutable/v47_params.json`.
5. Run the fixed ztrade autoresearch evaluator through the Required Evaluator
   Invocation section. Do not invent another backtest or scoring path.
6. Let the evaluator append `results.tsv` and refresh `latest_state.json`.
7. Write the required iteration report described in the Iteration Report
   Contract below.
8. Keep the candidate only when the evaluator returns KEEP and all required
   gates pass. Otherwise discard or revise in the next iteration.
9. NEVER STOP after a single iteration or one small batch. Continue proposing,
   evaluating, and keeping/discarding until the Session Budget and Stop
   Contract below permits a response to the human.

## Session Budget and Stop Contract

Historical warning: `max_iterations` is not the autoresearch session loop
budget. Treat this file as the only authority for iteration semantics. Code and
tool calls use `candidate_iterations` for the per-invocation evaluator count.

Default agent session budget:

- Continue candidate iterations after the baseline until one of the allowed stop
  conditions below is true.
- Tool limits, elapsed time, context pressure, or model uncertainty about future
  context are not stop conditions and are not reasons to send a final response.
  They only trigger the Context Packaging and Memory Recovery protocol below;
  after writing the continuation package, continue the next candidate iteration
  whenever the host still permits tool use.
- Send only brief progress updates during the loop. Do not summarize and stop
  merely because several candidates were DISCARD.

Allowed stop conditions, and only these:

- A human explicitly asks to stop, pause, or summarize only.
- In the fixed historical backtest windows, the current candidate achieves both
  of these evaluator-supported metrics:
  - total-trade weighted average win rate is greater than `50%`;
  - annualized return is greater than `30%`.

Use the evaluator artifacts for this decision. The preferred diagnostics are
`candidate_trade_weighted_win_rate` and `candidate_mean_annual_return_pct` from
the current candidate verdict. If those fields are unavailable, compute the
weighted win rate from candidate window rows as
`sum(candidate_win_rate * candidate_trade_count) / sum(candidate_trade_count)`,
and clearly label the annualized-return source used. Do not stop based on
unweighted window win-rate averages, a single lucky window, or a KEEP verdict
alone.

All other outcomes, including repeated DISCARD verdicts, KEEP without the two
performance targets, hard blockers, and completed batches, are continuation
signals unless a human explicitly stops the session. After a DISCARD, restore
`autoresearch/mutable/v47_params.json` to the current best/default params,
analyze the failed gates, choose a smaller or more orthogonal next mutation, and
immediately run the next evaluator invocation.

User constraint as of 2026-05-31: future iterations must not use leverage. Any
candidate with `allow_leverage=true` is invalid even if it meets stop metrics.

## Context Packaging and Memory Recovery

Context management is part of the loop, not a loop-ending event.

When context pressure, elapsed-time pressure, or a likely model handoff is
detected, write or refresh this local continuation package before the next
candidate mutation:

`autoresearch/context/continuation_state.md`

The continuation package must contain:

- current branch and commit hash;
- current best commit or best params source;
- current `autoresearch/best/v47_params.json` summary;
- current `autoresearch/mutable/v47_params.json` summary and any diff from best;
- latest result row and iteration id from `autoresearch/results.tsv`;
- latest report path under `autoresearch/reports/`;
- latest evaluator run directory;
- current stop metrics:
  `candidate_trade_weighted_win_rate`, `candidate_mean_annual_return_pct`, and
  `stop_target_met`;
- last three to five candidate outcomes and the lesson from each;
- next candidate proposal, exact param mutation, and rationale;
- unresolved blockers or data/runtime concerns;
- exact continuation command or evaluator invocation to run next.

The next candidate proposal must be a concrete next parameter experiment that
can be executed immediately within the current mutable surface. It must name
the iteration number or candidate id, the exact single parameter change, the
baseline value, the candidate value, and the evaluator command/run-report path
to use next. Do not write vague continuation language such as "future loops
should", "consider instrumentation", "after a new plan", or "choose a parameter
later" in this field. If instrumentation or search-space expansion seems
necessary, record it under unresolved concerns, but still provide the next
allowed parameter experiment for the current loop.

After writing the continuation package, continue the loop. Do not present the
package as a final answer unless the human explicitly asks to stop, pause, or
summarize only.

On any resumed session or context transition, reconstruct local memory before
proposing new params. Read, in this order when present:

- `autoresearch/context/continuation_state.md`;
- the latest five files under `autoresearch/reports/`;
- `autoresearch/results.tsv`;
- `autoresearch/latest_state.json`;
- `autoresearch/best/v47_params.json`;
- `autoresearch/mutable/v47_params.json`;
- `git log --oneline -10`;
- `git status --short`.

If those files are insufficient, reconstruct state from run artifacts under
`agent/runs/` and the report history. Ask the human only when the local memory
cannot identify the current best params, the last completed evaluator result, or
the safe next command.

## Required Context

Before each iteration, read these project-level files:

- `autoresearch/program.md`
- `autoresearch/evaluator_contract.md`
- `autoresearch/results.tsv` if present; otherwise create it from
  `autoresearch/results.template.tsv`
- `autoresearch/latest_state.json` if present; otherwise create it from
  `autoresearch/latest_state.template.json`
- `autoresearch/loop_config.json`
- `autoresearch/context/continuation_state.md` if present
- `autoresearch/reports/` if present
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
    candidate_iterations=1,
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
    candidate_iterations=0,
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
  "candidate_iterations": 1,
  "max_symbols": 200,
  "use_mutable_candidate": true
}
```

## Baseline First

Before the first parameter mutation in a new research run, evaluate the default
v47 baseline using the baseline-first command above. This run should produce
baseline rows and no candidate verdict. Do not treat an empty `results.tsv` as
evidence that parameter search should start immediately.

## Candidate Protocol Freeze

Before each candidate evaluator invocation, freeze the candidate protocol in the
iteration report draft:

- hypothesis and expected source of return improvement;
- expected cost or failure mode;
- exact params before/after the mutation;
- baseline params source;
- fixed evaluator command and run directory;
- frozen historical window list or the protocol artifact that contains it;
- gates and stop targets in force for this iteration.

Do not edit the candidate question, windows, gates, or evaluator command after
seeing results. If the hypothesis changes, start a new iteration.

## Result Reuse and Force-Rerun Rules

Normal autoresearch candidate evaluations must run the evaluator, not reuse old
candidate results. Baseline/reference artifacts may be reused only when all of
these are unchanged:

- frozen windows;
- baseline params;
- data snapshot;
- backtest engine, candidate strategy code, evaluator code, and protocol code;
- transaction costs, slippage, T+1, warmup, and execution assumptions.

Any change to shared evaluator/backtest logic, data, cost assumptions, window
definitions, or strategy parameter parsing forces a fresh baseline and fresh
candidate run before KEEP, stop-target, or promotion claims may be made. A run
that reuses stale artifacts may only be labeled exploratory.

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

## Iteration Report Contract

After every candidate evaluator invocation, write one Markdown report under:

`autoresearch/reports/iteration_<N>_<candidate_id>.md`

Create `autoresearch/reports/` if it does not exist. The report is runtime
research memory, not a committed protocol file.

Each report must contain:

1. Swarm analysis report:
   - `factor_librarian`: Alpha Zoo or factor-family context considered.
   - `v47_researcher`: why this idea maps to the current v47 parameter,
     indicator-composition, or regime-sizing surface.
   - `regime_analyst`: expected behavior in bull and bear windows.
   - `overfit_skeptic`: overfit, leakage, and one-window-luck objections.
   - `proposal_writer`: the exact experiment proposal that was evaluated.
2. Strategy modification summary:
   - previous params source (`best` or current mutable baseline).
   - exact parameter diff for this candidate.
   - rationale for every changed key.
   - whether the candidate was KEEP, DISCARD, or BLOCKED.
3. Historical backtest-window results:
   - Use evaluator artifacts from the current run directory, preferably
     `summary.json`, `metrics_rows.json`, `experiments.jsonl`, and
     `run_status.json`.
   - Include run completeness: `completed`, `total_jobs`, `failed`, and any
     failed job error summaries. If any job is missing, failed, or timed out, the
     iteration is `BLOCKED` or exploratory and cannot be used for KEEP or stop
     target claims.
   - Include a table with one row per frozen CSV historical window:
     `window_id`, `regime`, `start`, `end`, `baseline_return_pct`,
     `candidate_return_pct`, `return_delta_pct`, `candidate_annual_return_pct`,
     `candidate_win_rate`, `candidate_trade_count`, and
     `candidate_max_drawdown_pct`.
   - Include total/aggregate candidate return and baseline return when the
     evaluator artifact provides them. If only per-window rows are available,
     compute and label arithmetic `sum_return_pct` and `avg_return_pct`; do not
     present these as portfolio-compounded returns.
4. Verdict diagnostics:
   - evaluator score, failed gates, return delta, drawdown delta, trade
     retention, concentration, candidate trade count,
     `candidate_trade_weighted_win_rate`, `candidate_mean_annual_return_pct`,
     fixed-window loss ratio, bear-window return delta, bear-window loss ratio,
     bear-window drawdown delta, and whether the two-part stop target is met.
5. Next-iteration plan:
   - if DISCARD/BLOCKED, explain the smaller or more orthogonal mutation to try
     next.
   - if KEEP, explain what changed in `best` and the next conservative follow-up.
6. Anti-pattern and residual-risk checklist:
   - confirm no post-result window/gate changes;
   - confirm only one candidate idea changed, or explain why the change remains
     attributable;
   - confirm improvements are not dominated by one window or one abnormal trade;
   - confirm trade count did not collapse without offsetting return/drawdown
     improvement;
   - note data freshness, live/backtest parity, costs/slippage/T+1, warmup, and
     signal-date/buy-date leakage risks.

Also output a short chat summary for the human after each iteration. The chat
summary must point to the report path and include only the candidate id, verdict,
score, total/aggregate return line, and next action.

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

## Promotion and Veto Gates

The evaluator decides KEEP/DISCARD, but the iteration report must distinguish
research status:

- `KEEP`: fixed evaluator gates pass for the mutable candidate.
- `DISCARD`: fixed evaluator gates fail and the candidate should be reverted.
- `BLOCKED`: evaluator coverage, job completion, data, or command execution is
  incomplete.
- `Exploratory only`: results are informative but cannot support KEEP,
  stop-target, or live/default promotion claims.

Runbook-derived gates include:

- complete paired-window coverage;
- aggregate return delta against baseline;
- average drawdown worsening not above protocol threshold;
- total trade retention;
- improvement concentration not dominated by one window;
- fixed-window loss ratio within protocol threshold;
- bear-window return delta, loss ratio, and drawdown veto checks;
- simplicity and live/backtest parity review.

Fixed historical windows are diagnostic and veto surfaces. A candidate cannot be
declared successful merely because one short event window wins. Bear-window veto
failures, incomplete run status, or stale reused artifacts prevent promotion
claims even when aggregate score is positive.

## Independent Review

Before treating a KEEP as promotable beyond `autoresearch/best/`, an independent
review pass must inspect protocol freeze, run completeness, evaluator artifacts,
failed windows, parameter complexity, and residual risks. Critical findings must
be written into the iteration report and resolved before any live/default
promotion proposal.

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
plateau evidence under v47 parameter tuning and candidate-only indicator
composition. The proposal must be evaluated by
a separate human or code-review step before becoming mutable surface.

## Common Anti-Patterns

- Running only the latest market segment and declaring victory.
- Adding or removing windows after seeing results.
- Combining multiple unrelated parameter ideas so attribution is impossible.
- Ignoring trade-count collapse because win rate improved.
- Treating a KEEP verdict as a stop condition without the explicit stop-target
  metrics.
- Saving only a final chat summary without preserving protocol, raw artifacts,
  run status, and iteration report.

## Current Allowed Surface

Only `autoresearch/mutable/v47_params.json` may be edited by the loop.
All keys must be strategy parameters declared in the project code and must stay
within the machine-checked bounds. The current allowed expansion includes
project-indicator controls such as `alpha_qlib_roc10_*` and regime-aware
position sizing controls such as `regime_position_sizing_enable`,
`bull_position_weight`, and `bear_position_weight`.
