# AGS Full-Flow Security Acceptance

## Scope

This acceptance pass covers AGS v3.1 current-main-safe research surfaces only:

- alpha quality decision, scorecard/report serialization, trial ledger, data snapshot, forward tracking.
- read-only Alpha Genesis API routes and CLI report rendering.
- image, paste, Markdown, cache, and frontend report helper boundaries.

It intentionally does not alter `ToolRegistry`, `AgentLoop`, `AgentContext`, `SessionService`, broker connectors, mandate/order gates, kill-switches, or live trading runtime code.

## Acceptance Matrix

| Area | Implemented Coverage |
| --- | --- |
| Production full flow | `agent/tests/acceptance/test_ags_full_flow_reality.py` builds snapshot, ledger, deterministic decision, report, persisted artifacts, and API readback via production builders. |
| Business boundary | `docs/ags-business-boundary-truth-table.yaml` and `agent/tests/acceptance/test_ags_business_boundary_invariants.py` cover API/CLI/frontend/LLM/MCP/scheduler/websocket/upload/cache surfaces. |
| API/CLI consistency | `agent/tests/acceptance/test_ags_api_cli_ui_consistency.py` checks JSON and Markdown exports preserve decisions and redaction. |
| Image/paste security | backend and frontend tests cover SVG rejection, data URL MIME checks, Markdown/HTML escaping, EXIF/OCR/prompt/path redaction, and dangerous scheme neutralization. |
| Return contract | `agent/tests/security/test_return_value_contract_security.py` and `agent/tests/contracts/test_ags_response_schema_strict.py` lock exact research decision labels and code names. |
| Ledger/forward integrity | ledger and forward-store tests verify append-only behavior, hash chains, tamper detection, out-of-order rejection, and no promotion before minimum observations. |

## Boundary Assertions

- Alpha Genesis API v1 exposes GET-only report/scorecard/decision routes.
- Responses set `Cache-Control: no-store`, `Pragma: no-cache`, and `X-Content-Type-Options: nosniff`.
- API-loaded JSON is redacted again before return, so forged artifacts cannot expose secret-like keys through AGS routes.
- CLI rendering reads and renders reports only; it does not trigger search, jobs, broker access, or ledger mutation.
- LLM/caller claimed quality decisions are treated as untrusted and rejected when they attempt to raise the deterministic result.

## No Feature Removal

The changes are additive and scoped:

- Existing upload support for safe files remains; only active browser content extensions (`.svg`, `.html`, `.htm`, `.xhtml`) are blocked.
- Existing WebSocket image MIME support remains for PNG/JPEG/WebP/GIF; SVG stays excluded.
- Existing AGS report, scorecard, ledger, and forward APIs remain structurally compatible while adding strict code names and headers.

## AGENTS.md And ExecPlan Review

- Current-main compatibility: no `run_bench` implementation, factor registry, live mandate/order/kill-switch, `ToolRegistry`, `AgentLoop`, `AgentContext`, `SessionService`, scheduler executor, or connector registry code was changed.
- Feature-off identity: existing phase-0/current bench contract and `agent/tests/alpha_quality/test_feature_off_identity.py` were included in the targeted AGS pytest run.
- Read-only external surfaces: Alpha Genesis API remains GET-only; CLI report rendering is read-only; no MCP, scheduler, websocket job trigger, or broker write AGS surface was added.
- Research language: new public AGS code and tests use report, scorecard, quality decision, forward tracking, and research-only language.
- Evidence-bound claims: report/decision/ledger/forward tests require schema versions, deterministic code names, hash chains, no-store headers, and no production/live-ready labels.
- Trial integrity: success, reject, skip, and error statuses are recorded and hash-chain verified; tampering and duplicate IDs are rejected/detected.
- Forward tracking: observations are append-only, out-of-order observations are rejected, hash-chain tampering is detected, and existing kill-rule tests prevent promotion before minimum observations.
- Artifact safety: report API path traversal is rejected or not found without leaking paths; missing report reads do not create artifact roots; report JSON is redacted again before API return.
