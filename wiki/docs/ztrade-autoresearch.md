# ztrade Auto Research Adapter

This fork branch adds a bounded ztrade strategy-research loop on top of
Vibe-Trading backtest primitives. The agent is used for strategy research only:
it proposes and evaluates strategy-code candidates, then records evidence. It is
not a live per-trade decision maker.

## Current Starting Point

- Source strategy: ztrade `v47_weak_guard_62_70`.
- Source evidence: the local ztrade project records it as `DEFAULT_V3_PROFILE`.
- Adapter implementation: `agent/src/ztrade_autoresearch/candidate_strategy.py`.
- Baseline id: `ztrade_v47_baseline`.

The current adapter ports the V47 research semantics into Vibe's signal-engine
surface: recent reversal setup, volume confirmation, trend-line confirmation,
weekly short-line confirmation, and early-failure exits with market-breadth
guards.

## Fixed Research Boundary

- Candidate changes are constrained to the candidate strategy surface.
- Candidate helper functions are allowed only in the candidate strategy file.
- New dependencies are forbidden; only standard library and existing project
  dependencies are allowed.
- The evaluator, search space, rolling windows, protocol, and backtest engine
  are fixed during a run.
- Outputs are evidence artifacts, not live profile promotion.

## Implemented Components

- `agent/src/ztrade_autoresearch/protocol.py`: frozen baseline parameters,
  candidate search space, rolling synthetic windows, and gates.
- `agent/src/ztrade_autoresearch/evaluator.py`: paired-window evaluator and
  gate verdicts.
- `agent/src/ztrade_autoresearch/runner.py`: deterministic offline smoke loop
  using Vibe's `ChinaAEngine`.
- `agent/src/tools/ztrade_autoresearch_tool.py`: Vibe tool-registry entry.
- `agent/src/skills/ztrade-autoresearch/SKILL.md`: agent-facing operating
  boundary.
- `agent/tests/test_ztrade_autoresearch.py`: focused regression tests.

## Run Commands

Run tests:

```bash
uv run --with pytest python -m pytest agent/tests/test_ztrade_autoresearch.py -q
```

Run the deterministic 4-candidate smoke loop:

```bash
PYTHONPATH=agent uv run python - <<'PY'
from pathlib import Path
import json
from src.ztrade_autoresearch.runner import run_synthetic_research

summary = run_synthetic_research(
    Path("/tmp/vibe_ztrade_autoresearch_full_20260526_clean"),
    max_iterations=4,
)
print(json.dumps(summary["best_candidate"], ensure_ascii=False, indent=2))
PY
```

The runner writes:

- `protocol.json`
- `metrics_rows.json`
- `experiments.jsonl`
- `summary.json`
- Vibe run cards under `<run_dir>/<candidate>/<window>/`

Run against the current ztrade local CSV history:

```bash
PYTHONPATH=agent uv run python - <<'PY'
from pathlib import Path
import json
from src.ztrade_autoresearch.runner import run_ztrade_csv_research

summary = run_ztrade_csv_research(
    Path("/tmp/vibe_ztrade_csv_autoresearch_20260526_m200_warmup"),
    data_dir="/Users/wdblink/Code/my_repo/ztrade/data",
    max_iterations=4,
    max_symbols=200,
)
print(json.dumps(summary["best_candidate"], ensure_ascii=False, indent=2))
PY
```

CSV mode uses each evaluation window plus a 180-day historical warmup for
indicators. Candidate signals are forced to zero before the actual evaluation
window starts, so the warmup does not create pre-window entries.

## Latest Smoke Result

The 2026-05-26 deterministic smoke run completed four candidate iterations.
All candidates were discarded by the fixed gates:

- `candidate_volume_110`: failed return delta, loss-window, and concentration gates.
- `candidate_volume_135`: failed return delta and trade-retention gates.
- `candidate_window_10`: failed concentration gate.
- `candidate_early_loss_050`: failed concentration gate.

This is a valid initial outcome: the evaluator kept the baseline rather than
promoting an under-evidenced candidate.

## Latest ztrade CSV Result

The 2026-05-26 local CSV run used:

- Data directory: `/Users/wdblink/Code/my_repo/ztrade/data`
- Window count: 14
- Max symbols per window: 200
- Candidate iterations: 4
- Baseline trades: 82

All candidates were discarded by the fixed gates:

- `candidate_volume_110`: higher trade count but failed return delta and
  loss-window gates.
- `candidate_volume_135`: failed return delta, loss-window, trade-retention,
  and concentration gates.
- `candidate_window_10`: behavior was identical to baseline and failed the
  concentration gate.
- `candidate_early_loss_050`: behavior was identical to baseline and failed the
  concentration gate.

No candidate was promoted; the fixed evaluator kept `ztrade_v47_baseline`.

## Next Integration Step

The current run uses deterministic synthetic A-share data to prove the
Vibe-Trading harness. The next step is connecting the adapter to the real data
universe used by ztrade, then adding a parity check between ztrade's original
V47 backtest metrics and the Vibe adapter's metrics before trusting real
strategy promotion.
