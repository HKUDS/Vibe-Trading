# IRR-AGL v1.2.1 Final Acceptance

## Scope

This document closes the v1.2.1 hardening stack through Phase 10: migration fixtures, security regression, performance smoke tests, docs, and packaging. It does not merge or delete phase branches.

## 22-item Definition of Done

- [x] 1. R4/R5 deny path is guarded by Deny Barrier with `inner_tool_executed=False`.
- [x] 2. DecisionRecorder no longer relies on raise-then-write semantics.
- [x] 3. `decision_id`, artifact ID, trace event ID, and ledger hash are separated.
- [x] 4. Evidence writes are idempotent for policy decision artifacts.
- [x] 5. Evidence write failure does not downgrade high-risk deny to allow.
- [x] 6. EvidenceOutbox records partial evidence fallback.
- [x] 7. EvidenceVerifier rebuilds degraded reports when index is missing.
- [x] 8. ClaimSet exists and scorecard gates avoid regex-only prose parsing.
- [x] 9. MethodologyFactSet feeds scorecard predicates.
- [x] 10. Hard failures and conclusion caps expose rule IDs, reason codes, explanations, and evidence refs.
- [x] 11. Registered protocol blocks missing or unconfirmed inferred core fields.
- [x] 12. Protocol provenance metadata does not affect protocol hash.
- [x] 13. OpenAPI snapshots and frontend fixtures cover read-only evidence endpoints.
- [x] 14. Research Card/API/UI hard failures and decision IDs are exact-match tested.
- [x] 15. Surface behavior matrix covers 10 safety scenarios.
- [x] 16. Route-level governance coverage proves real entrypoints are wrapped.
- [x] 17. Three demos use production builders/verifiers and do not hand-write final evidence.
- [x] 18. Old v1.1/v1.2 artifacts, cards, scorecards, and protocols are readable.
- [x] 19. Trace/artifact/card/API/UI fixtures are covered by no-secret regression.
- [x] 20. README quickstart, MCP schema, live safety, and local no-fallback regressions are preserved.
- [x] 21. Performance smoke tests cover DecisionRecorder, EvidenceVerifier, and ClaimSet extraction.
- [x] 22. Final acceptance docs include tests, rollback, known limitations, non-goals, and PR summary.

## Test Commands

Phase 10 targeted commands:

```bash
pytest agent/tests/test_schema_migration_v121.py -q
pytest agent/tests/security/ -q
pytest agent/tests/performance/test_irr_agl_v121_perf_smoke.py -q
```

Final sweep commands:

```bash
pytest agent/tests/governance/ -q
pytest agent/tests/reliability/ -q
pytest agent/tests/research_protocol/ -q
pytest agent/tests/research_card/ -q
pytest agent/tests/quant/ -q
pytest agent/tests/evals/surface_matrix/ -q
pytest agent/tests/demos/ -q
pytest agent/tests/test_schema_migration_v121.py -q
pytest agent/tests/security/ -q
pytest agent/tests/performance/test_irr_agl_v121_perf_smoke.py -q
cd frontend && npx vitest run --reporter=verbose && npm run build
pytest --tb=short -q --ignore=agent/tests/e2e_backtest
```

Actual final command outputs:

- `pytest agent/tests/governance/ -q`: 11 passed.
- `pytest agent/tests/reliability/ -q`: 39 passed, 5 warnings.
- `pytest agent/tests/research_protocol/ -q`: 8 passed.
- `pytest agent/tests/research_card/ -q`: 4 passed, 1 warning.
- `pytest agent/tests/quant/ -q`: 17 passed.
- `pytest agent/tests/evals/surface_matrix/ -q`: 18 passed.
- `pytest agent/tests/demos/ -q`: 6 passed.
- `pytest agent/tests/test_schema_migration_v121.py -q`: 6 passed, 1 warning.
- `pytest agent/tests/security/ -q`: 5 passed.
- `pytest agent/tests/performance/test_irr_agl_v121_perf_smoke.py -q`: 3 passed.
- `cd frontend && npx vitest run --reporter=verbose`: 27 test files passed, 244 tests passed.
- `cd frontend && npm run build`: passed; Vite reported the existing chunk-size warning.
- `pytest --tb=short -q --ignore=agent/tests/e2e_backtest`: 4824 passed, 6 skipped, 135 warnings in 172.98s.

## Demo Outputs

The Phase 8 dry-run commands emit JSON summaries for:

- future data trap
- overfit best trial trap
- remote shell / live write trap

The expected snapshots live under `agent/examples/irr_agl_demos/*/expected_output.json`.

## Known Limitations

- Quant diagnostics are readiness summaries only, not production diagnostics.
- No full IC decay, optimizer, portfolio constructor, or live-trading expansion is included.
- Phase branches are pushed for review; no automatic merge, tag, or branch deletion is performed.

## Rollback

Rollback Phase 10 with:

```bash
git revert <phase-10-commit>
```

Earlier phase commits remain separately revertible because each phase is stacked and independently committed.

## Non-Goals

- No new write APIs.
- No live broker execution.
- No real LLM calls in CI.
- No external market-data dependency for demos or regression tests.

## PR Summary

Base: `integration/irr-agl-v1.2.1-hardening`

Compare: `phase/121-10-hardening-packaging`

Title: `Phase 10: Security, Migration, Performance & Final Packaging`

Summary: adds migration fixtures, security regression, performance smoke tests, final docs, and final acceptance evidence for the v1.2.1 closeout.
