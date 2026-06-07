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

Evaluator KEEP is a necessary condition for promotion, not a sufficient one.
After KEEP, the candidate must pass Post-KEEP Agent Review before
`autoresearch/best/v47_params.json` may be updated.

CSV evaluation windows are the frozen bull/bear windows generated in
`agent/src/ztrade_autoresearch/protocol.py` from the user-defined bull intervals
between `2023-12-28` and `2026-05-27`; all non-bull dates in that span are bear
windows. Do not edit these windows during autoresearch.

Alternate scoring paths are forbidden. Do not compute your own KEEP/DISCARD
outside `agent/src/ztrade_autoresearch/evaluator.py`.

Advisory reviewers (`factor_validator` and `backtest_reviewer`, defined in
`agent/src/swarm/presets/factor_research_committee.yaml`) may not compute or
override evaluator verdicts. They may veto promotion after an evaluator KEEP
through the Post-KEEP Agent Review described in `autoresearch/program.md`.

## Required Mutable Input

The only editable candidate input for the active run is:

`autoresearch/mutable/v47_params.json`

It must contain strategy parameter keys declared by
`agent/src/ztrade_autoresearch/protocol.py`, including current v47 parameters,
candidate-only Alpha Zoo indicator controls, and regime-aware position sizing
controls. Bounds are enforced by `agent/src/ztrade_autoresearch/research_loop.py`.

## Required Proposal Input

Read this file before proposing the next experiment:

`autoresearch/proposals/swarm_proposal_request.json`

Swarm and Alpha Zoo can propose hypotheses. They cannot decide KEEP/DISCARD,
edit evaluator code, or expand the official mutable surface directly.

Search-space expansion proposals must include the verdicts of both
`factor_validator` and `backtest_reviewer` under
`autoresearch/proposals/advisory_verdicts/`. Both reviewers must return
`recommend` for the expansion to enter the mutable surface; if either returns
`improve` or `reject`, the proposal is archived and the loop returns to
current best strategy parameter tuning. See
`autoresearch/program.md#search-space-expansion-review` for the trigger
condition.

## Required Post-KEEP Review

When the evaluator returns KEEP, the iteration report must include the review
outputs from:

- `factor_validator`: statistical/factor validity review, including IC/ICIR,
  grouped monotonicity where available, decay, robustness, multiple-testing
  risk, and overfitting warnings.
- `backtest_reviewer`: backtest credibility review, including bias checks,
  sample-size/parameter-count risk, transaction cost realism, stress behavior,
  and live-like feasibility.

Each reviewer must return `PASS`, `VETO`, or `NEEDS_MORE_EVIDENCE`.
`VETO` and `NEEDS_MORE_EVIDENCE` block promotion but do not rewrite the fixed
evaluator's KEEP verdict.

## Required Output

Each evaluator run writes normal run artifacts under `agent/runs/...` and
updates project-level runtime state:

- `autoresearch/results.tsv` is append-only experiment history.
- `autoresearch/latest_state.json` is refreshed to the latest evaluator state.
- `autoresearch/reports/iteration_<N>_<candidate_id>.md` records each
  iteration's swarm analysis, strategy diff, per-window historical returns,
  aggregate return, verdict diagnostics, post-KEEP review when applicable, and
  next-iteration plan.

Loop completion may be claimed only when a human asks to stop/pause/summarize,
or when the current candidate's evaluator diagnostics show both
`candidate_trade_weighted_win_rate > 0.50` and
`candidate_mean_annual_return_pct > 30.0`.

Leverage is forbidden for future mutable candidates. `allow_leverage` must stay
`false`; any leveraged result is archive-only evidence and cannot satisfy the
active stop contract.

Runbook-derived promotion/veto diagnostics are also part of the fixed judge:
paired-window coverage, fixed-window loss ratio, bear-window return delta,
bear-window loss ratio, bear-window drawdown delta, trade retention, and
improvement concentration. Incomplete `run_status.json` or stale reused
artifacts cannot support KEEP, stop-target, or promotion claims.

Promotion additionally fails when either post-KEEP reviewer returns `VETO` or
`NEEDS_MORE_EVIDENCE`.

These files are runtime outputs and should not be committed. The tracked
templates are:

- `autoresearch/results.template.tsv`
- `autoresearch/latest_state.template.json`

Do not hand-edit evaluator results.
