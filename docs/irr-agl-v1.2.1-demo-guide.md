# IRR-AGL v1.2.1 Demo Guide

The deterministic demos prove rejection and evidence closure behavior without real LLM calls, brokers, shell execution, or external market data.

## Future Data Trap

Run:

```bash
python agent/examples/irr_agl_demos/future_data_trap/runner.py --dry-run
```

Proves that a point-in-time violation triggers `pit_violation_hard_fail` and forces `ResearchCard.conclusion_level=not_reliable`.

## Overfit Best Trial Trap

Run:

```bash
python agent/examples/irr_agl_demos/overfit_best_trial_trap/runner.py --dry-run
```

Proves that the selected trial is visible beside all 8 trial events, with trial count carried into methodology facts and the Research Card.

## Remote Shell / Live Write Trap

Run:

```bash
python agent/examples/irr_agl_demos/remote_shell_live_write_trap/runner.py --dry-run
```

Proves that observe/warn mode still denies R5 shell and R4 trade-write tools before execution, and that the same decision IDs appear across trace, artifact, index, API, and card.

## Verification

Each runner calls production builders or verifier paths. The `expected_output.json` files are compact expectation snapshots, not hand-written final ResearchCard, Scorecard, or EvidenceClosureReport artifacts.
