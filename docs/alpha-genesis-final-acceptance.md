# Alpha Genesis Final Acceptance

## Phase Checklist

- Phase 0: current-main baseline and scope lock completed.
- Phase 1: alpha quality scorecard completed.
- Phase 2: trial ledger and data snapshot manifest completed.
- Phase 3: DSL-constrained alpha foundry core completed.
- Phase 4: A-share liquidity/reversal case completed.
- Phase 5: novelty, crowding, and synergy scorer completed.
- Phase 6: alpha quality decision layer completed.
- Phase 7: frozen forward tracking completed.
- Phase 8: read-only reports/API surface completed.
- Phase 9: deterministic demos and final package completed.

## Tests Run

- `pytest agent/tests/alpha_genesis_demos -q` -> 7 passed.
- `pytest agent/tests/alpha_foundry/reports agent/tests/security/test_alpha_genesis_redaction.py agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py -q` -> 4 passed.
- `pytest agent/tests/alpha_foundry/forward -q` -> 9 passed.
- `pytest agent/tests/alpha_quality -q` -> 29 passed.
- `pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q` -> 915 passed, 5 skipped, 12 warnings.

## Evidence Artifacts

- Demo package: `agent/examples/alpha_genesis_demos/`
- Demo tests: `agent/tests/alpha_genesis_demos/`
- Read-only reports: `agent/src/alpha_foundry/reports/`
- Forward tracking: `agent/src/alpha_foundry/forward/`
- Decision layer: `agent/src/alpha_quality/decision/`

## Deliberately Out Of Scope

- No live trading write path.
- No production-ready alpha claim.
- No POST/PUT/PATCH/DELETE Alpha Genesis API.
- No premium data dependency.

## PR Summary

Alpha Genesis adds a current-main-compatible, read-only, evidence-bound factor
research pipeline with deterministic scorecards, trial history, bounded formula
generation, novelty/synergy checks, adversarial quality decisions, frozen
forward tracking, redacted reports, and flagship demos.

Remote PR publication is deferred to the repository owner.
