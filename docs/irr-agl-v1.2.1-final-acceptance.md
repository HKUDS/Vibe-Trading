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

## Phase 10.1 Post-416/420 Security Compatibility Gate

Status: PASS

Branch: `phase/121-10a-post416-420-security-compat`

Phase 10 base commit before Phase 10.1: `5a9964f`

Base branch: `phase/121-10-hardening-packaging`

Audit generation state before final commit: dirty by design with Phase 10.1 changes uncommitted. Final Phase 10.1 commit hash is reported in the PR handoff after commit. `main` and `integration` were not modified, merged, tagged, rebased, amended, or deleted.

Compatibility matrix summary:

- Total #416/#420/local audit items: 13
- PRESENT_SAME_OR_STRONGER: 1
- PATCHED_WITH_TEST: 12
- NOT_APPLICABLE_WITH_PROOF: 0
- BLOCKED_RELEASE: 0
- NEEDS_FOLLOWUP_NON_BLOCKING: 0
- P0/P1 blockers: 0

Documents added:

- `docs/irr-agl-v1.2.1-post416-420-security-compat.md`
- `docs/irr-agl-v1.2.1-security-static-audit.md`
- `docs/irr-agl-v1.2.1-redteam-test-report.md`
- `docs/irr-agl-v1.2.1-security-standards-map.md`

Security findings:

| id | severity | status | files | tests | notes |
|---|---|---|---|---|---|
| B1 | P0 | PATCHED_WITH_TEST | `agent/src/governance/runtime.py` | `test_governance_redteam_boundary.py` | `get()` returns governed proxy; R4/R5 counters zero |
| B2 | P0 | PATCHED_WITH_TEST | `agent/src/governance/runtime.py` | `test_public_inner_attribute_is_not_available` | Public `.inner` unavailable |
| B3 | P0 | PATCHED_WITH_TEST | `agent/src/governance/runtime.py` | `test_state_provider_p40_security.py` | Forged runtime state denied |
| C1 | P1 | PATCHED_WITH_TEST | `agent/src/agent/loop.py` | `test_agent_loop_policy_denied_payload.py` | Malformed deny payload does not allow execution |
| C2-M3 | P1 | PATCHED_WITH_TEST | `agent/src/reliability/data/circuit_breaker.py` | `test_circuit_breaker_concurrency.py` | Atomic failure increments and connection close verified |
| M1 | P1 | PATCHED_WITH_TEST | `agent/src/research_protocol/ledger.py` | `test_trial_ledger_retry_lifecycle.py` | Retry sleep does not hold connection |
| M2 | P0 | PATCHED_WITH_TEST | `agent/src/research_card/api.py`, API routes | `test_research_card_api_security.py` | Traversal returns safe not-found/no leak |
| LIVE-CONNECTOR | P0 | PATCHED_WITH_TEST | `agent/src/api/live_routes.py` | `test_live_connector_route_governance.py` | Submit/cancel pass through governance before adapter |
| REDACTION | P0/P1 | PATCHED_WITH_TEST | backend redaction and frontend research panels | backend and frontend security tests | Display/export/API redaction verified |
| ROUTE-COVERAGE | P1 | PATCHED_WITH_TEST | API/MCP/CLI/session/scheduler/swarm | `test_route_governance_coverage.py` | Real entrypoints covered |

Tests run:

```text
pytest agent/tests/governance/test_governance_redteam_boundary.py -v
Result: 10 passed

pytest agent/tests/governance/test_state_provider_p40_security.py -v
Result: 10 passed

pytest agent/tests/governance/test_live_connector_route_governance.py -v
Result: 7 passed

pytest agent/tests/governance/test_route_governance_coverage.py -v
Result: 10 passed

pytest agent/tests/research_card/test_research_card_api_security.py -v
Result: 8 passed, 5 warnings

pytest agent/tests/reliability/test_circuit_breaker_concurrency.py -v
Result: 5 passed

pytest agent/tests/research_protocol/test_trial_ledger_retry_lifecycle.py -v
Result: 4 passed

pytest agent/tests/security/test_v121_post416_420_security_regression.py -v
Result: 10 passed, 4 warnings

pytest agent/tests/test_agent_loop_policy_denied_payload.py -v
Result: 2 passed

pytest agent/tests/governance/ -q
Result: 48 passed

pytest agent/tests/reliability/ -q
Result: 44 passed, 5 warnings

pytest agent/tests/research_protocol/ -q
Result: 12 passed

pytest agent/tests/research_card/ -q
Result: 12 passed, 5 warnings

pytest agent/tests/quant/ -q
Result: 17 passed

pytest agent/tests/evals/surface_matrix/ -q
Result: 18 passed

pytest agent/tests/demos/ -q
Result: 6 passed

pytest agent/tests/test_schema_migration_v121.py -q
Result: 6 passed, 1 warning

pytest agent/tests/security/ -q
Result: 15 passed, 4 warnings

pytest agent/tests/performance/test_irr_agl_v121_perf_smoke.py -q
Result: 3 passed

cd frontend && npx vitest run src/components/research/__tests__/ResearchPanels.security.test.tsx --reporter=verbose
Result: 1 file passed, 8 tests passed

cd frontend && npx vitest run src/api/__tests__/researchApi.security.test.ts --reporter=verbose
Result: 1 file passed, 4 tests passed

cd frontend && npx vitest run --reporter=verbose
Result: 29 files passed, 256 tests passed

cd frontend && npm run build
Result: passed; existing Vite chunk-size warning

pytest --tb=short -q --ignore=agent/tests/e2e_backtest
Result: 4896 passed, 6 skipped, 139 warnings in 262.32s

git diff --check
Result: passed with line-ending warnings only

ruff check agent/src/governance/runtime.py agent/src/api/live_routes.py agent/src/api/runs_routes.py agent/src/reliability/redaction.py agent/src/research_protocol/ledger.py agent/src/swarm/worker.py agent/tests/governance/test_governance_redteam_boundary.py agent/tests/governance/test_live_connector_route_governance.py agent/tests/governance/test_route_governance_coverage.py agent/tests/governance/test_state_provider_p40_security.py agent/tests/reliability/test_circuit_breaker_concurrency.py agent/tests/research_card/test_research_card_api_security.py agent/tests/research_protocol/test_trial_ledger_retry_lifecycle.py agent/tests/security/test_v121_post416_420_security_regression.py agent/tests/test_agent_loop_policy_denied_payload.py
Result: All checks passed

ruff check agent/src agent/tests
Result: failed with 281 pre-existing repo-wide lint findings outside Phase 10.1 touched files
```

Static audit:

- Required static searches were run and classified in `docs/irr-agl-v1.2.1-security-static-audit.md`.
- Search counts: inner 34, ToolRegistry 31, get-execute 0, runtime state 77, adapter/live 559, eval/exec/import 198, subprocess/env 150, path 1230, frontend HTML 10, skip/TODO 199.
- No unclassified P0/P1 suspicious finding remains.

Residual risks:

| id | severity | status | reason | follow-up |
|---|---|---|---|---|
| R-ruff-backlog | P2 | NEEDS_FOLLOWUP_NON_BLOCKING | Full repo lint has legacy findings unrelated to Phase 10.1 touched files | Separate lint-hardening branch |
| R-vite-chunks | P2 | NEEDS_FOLLOWUP_NON_BLOCKING | Frontend build emits existing large-chunk warning | Separate frontend bundle-splitting pass |

Rollback:

```bash
git checkout phase/121-10a-post416-420-security-compat
git restore --source=HEAD --staged --worktree .
git clean -fd
```

If a commit is created for Phase 10.1, roll it back with:

```bash
git revert <phase-10.1-commit>
```
