# Research Lab

Open **Analysis → Research Lab** (`/research-lab`). The Web UI, CLI, authenticated
REST API and Agent/MCP `research_lab` tool execute the same persisted jobs.
For this checkout, activate the project environment with `source .venv/bin/activate`,
or invoke `./.venv/bin/vibe-trading` directly. An old console script in another
Python environment uses that environment’s dependencies.

Costs and parameter studies reuse a completed backtest's exported inputs and
strategy. No model, live broker or price-provider call is part of a study.

## Reusable inputs and execution costs

Run a backtest first, then select its saved run. Its run-card manifest must
still match the strategy and every exported OHLCV snapshot. A changed or
missing file is refused; rerun that backtest to create a new baseline.

```bash
vibe-trading research-lab costs RUN_ID --fee-multipliers 1 2 3 --slippage-bps 0 5 --json
```

Each scenario actually reruns the ordinary market engine against the same
hash-verified data. The multiplier applies once to execution commissions and
transaction taxes, including minimum fees. Funding and borrow charges stay as
configured. Additional adverse slippage is applied before the venue's normal
slippage and tick rounding. Options support commission scenarios but reject
additional option slippage until that execution model exists. A break-even is
reported only as an observed sign-change bracket between measured scenarios;
position sizing can make the relationship nonlinear. There are at most 20
scenarios per request.

## Train, select, freeze, test

```bash
vibe-trading research-lab walk-forward RUN_ID \
  --parameter fast=10,20 --parameter slow=40,60 \
  --train-bars 252 --test-bars 63 --holdout-bars 63 --max-folds 4 \
  --objective sharpe --training rolling --json
```

The strategy's `SignalEngine.__init__` accepts these named scalar parameters.
The Web form discovers literal defaults and saved constructor parameters.
The bounded grid has at most 12 candidates and 12 folds. Training uses either
a rolling window or all prior observations; it selects only on training
Sharpe or return, with input-order tie breaking. The selection and plan are
written and hashed before testing. Both the supplied data map and trial-local snapshot files are truncated
before the strategy runs, so neither supplies later prices to a training trial. Prior prices remain
available for indicator warmup while execution begins at the evaluated window.

Every test starts flat and pays the engine's entry and liquidation costs.
OOS returns are compounded across test windows, including each first bar.
The optional final holdout is excluded from every earlier training and test
window. It receives its own last training-only selection and is reported
separately from validation OOS returns. A fold limit may leave unused bars;
the report names them. This isolates parameter selection; it does not certify
that arbitrary user strategy code is causal within each provided window.
Options-portfolio selection is currently refused explicitly.

The older backtest validation output `walk_forward` remains compatible but is
labelled **Window consistency** in Web: it splits an existing equity curve,
includes the preceding boundary equity in each later window, and is not a
train-and-test parameter study. CLI revalidation uses the same correction.

## Factor source and history contracts

```bash
vibe-trading research-lab audit --json
vibe-trading research-lab audit --alpha-id gtja191_149 --json
```

The audit checks every registered factor against a reviewed source fingerprint,
minimum history and initialization policy, then executes deterministic synthetic
panels. Nested complete windows, recursive seeds, explicit partial coverage
and conditional samples are distinct. This is implementation verification,
not a claim of profitable factors or full published-formula equivalence.

Long GTJA windows are restored for 25/26/33/39/45/56/61/64/74/75/77/91/92/98.
Alpha149 fits the last **252 selected benchmark-down returns**, without
zero-filling up days. Alpha27/30 use geometric WMA weights; Alpha30 requires
observed MKT/SMB/HML panels and uses real multifactor residuals. All bundled
minimum histories are reconciled before the registry excludes the initial
ineligible prefix. Missing bars do not reset a recursive statistic's state.
The original report and operator interpretations are linked in the zoo's
[provenance note](../agent/src/factors/zoo/gtja191/LICENSE.md).

## Saved task replay

```bash
vibe-trading research-lab cases --json
vibe-trading research-lab replay /path/to/saved-run --case research.window_boundary.v1 --json
vibe-trading research-lab replay --bindings /path/to/bindings.json --json
```

There are 20 financial task cases alongside the existing identity case. Each
case owns its original prompt, expected measurements, execution restrictions,
provider-usage budget and elapsed-time bound. Run those prompts through the
normal Agent first, then evaluate the saved artifacts. The verifier itself
never runs a model, fetches prices, or rewrites a prompt to fit a case.
`bindings.json` is an array of `case_id`, `run_dir`, optional `trace_dir` objects;
each task must have its own corresponding saved run. Web evaluates a selected
saved run and task, displaying every verdict and coverage gap.

Numeric expectations read bounded JSON fields or CSV rows. Missing
measurements or timestamps stay `NOT_EVALUABLE`; malformed evidence is
`INVALID_ARTIFACT`. Wrong numbers, changed prompts, forbidden calls and exceeded
budgets fail. Synthetic pass/fail fixtures test the verifier; they are never
reported as live Agent performance. See the [harness schema](../agent/evals/harness/README.md).

## API and saved reports

- `GET /api/research-lab/catalog`: available runs, parameters and task prompts.
- `POST /api/research-lab/jobs`: `{ "action": "cost_sensitivity|walk_forward|factor_audit|replay", "request": {...} }`.
- `GET /api/research-lab/jobs/{id}`: durable status, progress, request and result.
- `GET /api/research-lab/jobs/{id}/report`: completed JSON report.

All routes use application authentication; submission uses settings-write
protection. The API admits two simultaneous workers. Saved jobs live under the
configured runs directory, and Web's `?job=...` URL recovers a report after a
reload. An exited worker is shown as interrupted rather than running forever.
CLI `research-lab show JOB_ID --json` reads the same result. Exit codes are
0 for completion/pass, 1 for execution/evaluation failure, and 2 for an invalid
request or incomplete evaluation. Agent results link the complete JSON when
tables exceed the tool output budget.
