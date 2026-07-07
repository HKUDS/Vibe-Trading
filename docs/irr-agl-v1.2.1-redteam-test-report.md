# IRR-AGL v1.2.1 Phase 10.1 Red-Team Test Report

This report records local offensive regression tests for the post-416/420 compatibility gate. Tests used only fake tools, fake adapters, local test clients, temporary directories, and deterministic fixtures. No real shell execution, broker calls, LLM calls, market-data pulls, or external scans were used.

## Targeted Security Commands

| command | result |
|---|---|
| `pytest agent/tests/governance/test_governance_redteam_boundary.py -v` | 10 passed |
| `pytest agent/tests/governance/test_state_provider_p40_security.py -v` | 10 passed |
| `pytest agent/tests/governance/test_live_connector_route_governance.py -v` | 7 passed |
| `pytest agent/tests/governance/test_route_governance_coverage.py -v` | 10 passed |
| `pytest agent/tests/research_card/test_research_card_api_security.py -v` | 8 passed, 5 warnings |
| `pytest agent/tests/reliability/test_circuit_breaker_concurrency.py -v` | 5 passed |
| `pytest agent/tests/research_protocol/test_trial_ledger_retry_lifecycle.py -v` | 4 passed |
| `pytest agent/tests/security/test_v121_post416_420_security_regression.py -v` | 10 passed, 4 warnings |
| `pytest agent/tests/test_agent_loop_policy_denied_payload.py -v` | 2 passed |
| `cd frontend && npx vitest run src/components/research/__tests__/ResearchPanels.security.test.tsx --reporter=verbose` | 1 file passed, 8 tests passed |
| `cd frontend && npx vitest run src/api/__tests__/researchApi.security.test.ts --reporter=verbose` | 1 file passed, 4 tests passed |

## Suite Commands

| command | result |
|---|---|
| `pytest agent/tests/governance/ -q` | 48 passed |
| `pytest agent/tests/reliability/ -q` | 44 passed, 5 warnings |
| `pytest agent/tests/research_protocol/ -q` | 12 passed |
| `pytest agent/tests/research_card/ -q` | 12 passed, 5 warnings |
| `pytest agent/tests/quant/ -q` | 17 passed |
| `pytest agent/tests/evals/surface_matrix/ -q` | 18 passed |
| `pytest agent/tests/demos/ -q` | 6 passed |
| `pytest agent/tests/test_schema_migration_v121.py -q` | 6 passed, 1 warning |
| `pytest agent/tests/security/ -q` | 15 passed, 4 warnings |
| `pytest agent/tests/performance/test_irr_agl_v121_perf_smoke.py -q` | 3 passed |
| `cd frontend && npx vitest run --reporter=verbose` | 29 files passed, 256 tests passed |
| `cd frontend && npm run build` | passed; existing Vite chunk-size warning |
| `pytest --tb=short -q --ignore=agent/tests/e2e_backtest` | 4896 passed, 6 skipped, 139 warnings in 262.32s |

## Negative Proofs

| attack | proof |
|---|---|
| Raw `get()` bypass executes R5 shell | `test_get_execute_routes_through_governance_for_r5_shell` keeps execution counter at zero |
| Raw `get()` bypass executes R4 trade write | `test_get_execute_routes_through_governance_for_r4_trade_write` keeps execution counter at zero |
| Public `.inner` escape | `test_public_inner_attribute_is_not_available` |
| Proxy exposes raw tool internals | `test_proxy_does_not_expose_raw_tool_private_members` |
| Forged `RuntimeContext.live_state` satisfies P40 | `test_forged_runtime_context_live_state_does_not_satisfy_p40` |
| Null/failing state provider falls open | `test_null_state_provider_fails_closed_for_live_write`, `test_state_provider_exception_fails_closed_before_adapter` |
| Live connector calls adapter before governance | `test_live_submit_forged_state_denied_before_adapter_call`, `test_live_cancel_provider_failure_denied_before_adapter_call` |
| Malformed policy-denied payload allows execution | `test_policy_denied_payload_malformed_does_not_allow_execution` |
| CircuitBreaker lost updates under concurrency | `test_concurrent_failures_are_atomic`, `test_new_source_concurrent_failures_no_lost_update` |
| TrialLedger retry holds connection | `test_retry_sleep_does_not_hold_connection` |
| Path traversal reads outside artifact root | `test_artifact_path_traversal_returns_404_not_500`, `test_symlink_escape_denied_if_artifact_root_contains_symlink` |
| Backend redaction is key-only | `test_evidence_verify_response_redacts_secret_like_values` |
| Frontend export leaks value sentinel | `exported Markdown is redacted`, `no raw sentinel appears in export text` |
| Malicious scorecard YAML executes code | `test_malicious_scorecard_yaml_cannot_execute_code` |
| Generated subprocess inherits secrets | `test_subprocess_env_excludes_llm_api_broker_live_secrets` |
| Evidence API adds write method | `test_no_write_methods_in_new_evidence_api_routes` |

## Anti-Cheat Proof

- No tests were deleted to make Phase 10.1 pass.
- No old fixtures were deleted.
- No new unjustified `skip` or `xfail` was added.
- No safety gate was weakened.
- No write endpoint was added in the v1.2.1 evidence/read-only API area.
- No real LLM, broker, shell, or network scan was used.
- No main/integration merge, branch deletion, amend, rebase, or tag was performed.

## Residual Risks

| id | severity | status | reason | follow-up |
|---|---|---|---|---|
| R-ruff-backlog | P2 | NEEDS_FOLLOWUP_NON_BLOCKING | Full `ruff check agent/src agent/tests` reports legacy repo-wide lint debt outside Phase 10.1 touched files | Open a separate lint-hardening branch; do not mix with security compatibility patch |
| R-vite-chunks | P2 | NEEDS_FOLLOWUP_NON_BLOCKING | Frontend build passes with existing Vite large-chunk warning | Consider route-level code splitting in a frontend performance pass |

No P0/P1 residual risk remains open.

