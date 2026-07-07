# IRR-AGL v1.2.1 Phase 10.1 Security Standards Map

This document maps Phase 10.1 tests and evidence to common security standards. It is not a compliance certification.

## OWASP ASVS 5.0.0 Areas

| area | mapped tests/evidence |
|---|---|
| Authentication/session/state integrity | P40 provider tests in `agent/tests/governance/test_state_provider_p40_security.py`; forged `live_state`, `user_auth_state`, and `budget_state` denied |
| Access control | `test_public_inner_attribute_is_not_available`; route coverage tests for API/MCP/CLI/session/scheduler/swarm |
| Validation/sanitization | Path traversal tests in `agent/tests/research_card/test_research_card_api_security.py`; redaction tests in backend and frontend |
| Error handling/logging | Path traversal no-500/no-leak tests; malformed policy-denied parser tests |
| Data protection/secrets | `test_no_raw_secret_in_trace_artifact_card_api_ui_fixtures`; frontend no raw sentinel DOM/export tests |
| SSRF/network boundary | Swarm prompt MCP URL rejection and local no-fallback tests |
| File/path handling | Artifact lineage traversal, encoded dot-dot, symlink escape, and safe not-found tests |
| Business logic/workflow enforcement | R4/R5 Deny Barrier, live connector governed pseudo-tool tests, budget and provider failure tests |

## OWASP API Security Top 10 2023

| category | mapped tests/evidence |
|---|---|
| Broken object/property/function authorization | Raw registry get/proxy tests; route governance coverage |
| Broken authentication | P40 state provider requires authoritative authentication state for high-risk live writes |
| Unrestricted resource consumption | CircuitBreaker atomic failure tracking; generated subprocess env allowlist and no real external scans |
| Unsafe consumption of APIs | Broker read/write separation; unknown broker fail-closed tests |
| Security misconfiguration | Evidence endpoints GET-only OpenAPI check; no write methods in evidence routes |

## OWASP WSTG

| category | mapped tests/evidence |
|---|---|
| Threat modeling | `docs/irr-agl-v1.2.1-threat-model-delta.md` post-416/420 section |
| Source code review | `docs/irr-agl-v1.2.1-security-static-audit.md` static search classifications |
| Penetration testing | Red-team fake tool, fake adapter, path traversal, and malformed payload tests |
| Input validation | Encoded traversal, symlink escape, malformed deny payload, malicious YAML tests |
| Authorization testing | P40 provider and route governance tests |
| Error handling | No-500/no-leak path traversal and provider failure fail-closed tests |

## MITRE CWE

| CWE area | mapped tests/evidence |
|---|---|
| Improper access control | Raw registry/public inner/proxy bypass tests |
| Path traversal | Artifact and runs API traversal tests |
| Command injection/shell exposure | R5 shell denial and generated subprocess env tests |
| Improper neutralization/XSS | Frontend `<script>` inert text test; no `dangerouslySetInnerHTML` |
| Hard-coded/cleartext secrets | Backend/frontend redaction and no raw sentinel scans |
| Race condition/TOCTOU | CircuitBreaker concurrent failure atomicity tests |
| Resource leak | CircuitBreaker and TrialLedger connection lifecycle tests |
| Improper exception handling | PolicyDenied parser BaseException and malformed payload tests |

## Non-Claims

- This mapping does not certify ASVS, API Top 10, WSTG, or CWE compliance.
- This mapping does not claim production quant diagnostics or expanded live trading capability.
- This mapping does not replace external penetration testing.

