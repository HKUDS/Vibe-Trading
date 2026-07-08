# AGS Hidden Surface Threat Model

## Threat Surfaces

- API routes: report/scorecard/decision reads must stay GET-only and must not trigger mining, jobs, broker writes, or artifact mutation.
- CLI: local report rendering must not mutate ledgers, forward stores, mandates, broker permissions, or live runtime state.
- Frontend: report rendering, export, image preview metadata, and cache helpers must not preserve secrets, raw local paths, OCR prompt text, or live-readiness claims.
- Upload/websocket/media: active browser content and SVG script paths must be rejected or non-renderable.
- LLM/caller config: caller-provided decision, warning, score, or hard-failure payloads are untrusted; deterministic code owns final decisions.
- Scheduler/MCP/background workers: AGS v1 exposes no write/job trigger surface in these paths.

## Controls

- `agent/tests/security/test_hidden_surface_route_coverage.py` locks GET-only AGS API and absence of mining/job/write endpoints.
- `agent/tests/acceptance/test_ags_business_boundary_invariants.py` asserts AGS modules do not import live trading/runtime wrapper objects and validates the boundary truth table.
- `agent/tests/security/test_config_permission_bypass.py` verifies path traversal attempts and missing reads do not escape or create report roots.
- `agent/tests/security/test_artifact_cache_thumbnail_ocr_isolation.py` verifies no-store headers and absence of thumbnail/OCR routes.

## Residual Risk

General application routes outside AGS still include existing upload, scheduler, settings, live, and connector behavior. This AGS pass does not remove or redesign those features. It adds narrow AGS-specific guardrails without changing current-main live safety architecture.
