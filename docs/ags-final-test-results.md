# AGS Final Test Results

Generated for the AGS v3.1 current-main-safe security and acceptance pass.

## Verification Run

- `git diff --check`: passed. Git emitted Windows line-ending normalization warnings only.
- `python -m compileall -q agent/src agent/cli`: passed.
- Targeted AGS/backend pytest:
  - command: `.venv\Scripts\python.exe -m pytest agent/tests/acceptance agent/tests/security/test_image_upload_clipboard_security.py agent/tests/security/test_paste_markdown_html_security.py agent/tests/security/test_hidden_surface_route_coverage.py agent/tests/security/test_return_value_contract_security.py agent/tests/security/test_config_permission_bypass.py agent/tests/security/test_artifact_cache_thumbnail_ocr_isolation.py agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py agent/tests/contracts/test_ags_response_schema_strict.py agent/tests/research_ledger/test_trial_ledger_append_only.py agent/tests/research_ledger/test_trial_ledger_concurrency.py agent/tests/research_ledger/test_trial_ledger_redaction.py agent/tests/research_ledger/test_ledger_integrity_and_tamper.py agent/tests/alpha_quality agent/tests/alpha_foundry/forward agent/tests/alpha_foundry/dsl -q --tb=short`
  - result: 84 passed, 5 warnings.
- Existing adjacent regressions:
  - command: `.venv\Scripts\python.exe -m pytest agent/tests/test_upload_security.py agent/tests/test_upload_api.py agent/tests/security/test_alpha_genesis_redaction.py agent/tests/alpha_foundry/reports/test_report_builder.py agent/tests/alpha_genesis_demos agent/tests/alpha_genesis/test_phase0_current_bench_contract.py -q --tb=short`
  - result: 27 passed, 5 warnings.
- Existing factor purity/lookahead:
  - command: `.venv\Scripts\python.exe -m pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q --tb=short`
  - result: 915 passed, 5 skipped, 12 warnings.
- Frontend targeted Alpha Genesis security vitest:
  - command: `npm run test:run -- paste-markdown-security image-preview-redaction-security report-export-redaction-consistency decision-badge-truthfulness service-worker-cache-sensitive-report`
  - result: 5 files passed, 11 tests passed.
- Frontend full vitest:
  - command: `npm run test:run`
  - result: 32 files passed, 254 tests passed.
- Frontend build:
  - command: `npm run build`
  - result: passed; Vite emitted existing large chunk-size warnings.
- Focused mypy:
  - command: `mypy agent/src/alpha_foundry/reports/render_markdown.py agent/src/alpha_foundry/forward/store.py agent/src/alpha_quality/decision agent/src/api/alpha_genesis_routes.py agent/src/api/uploads_routes.py --ignore-missing-imports`
  - result: success, no issues in 12 source files.
- Post-review focused rerun:
  - command: `.venv\Scripts\python.exe -m pytest agent/tests/alpha_foundry/forward agent/tests/acceptance agent/tests/security/test_image_upload_clipboard_security.py agent/tests/security/test_paste_markdown_html_security.py agent/tests/security/test_hidden_surface_route_coverage.py agent/tests/security/test_return_value_contract_security.py agent/tests/security/test_config_permission_bypass.py agent/tests/security/test_artifact_cache_thumbnail_ocr_isolation.py agent/tests/contracts/test_ags_response_schema_strict.py agent/tests/research_ledger/test_ledger_integrity_and_tamper.py agent/tests/alpha_quality/decision/test_business_promotion_caps.py agent/tests/alpha_quality/decision/test_llm_caller_config_override_rejected.py -q --tb=short`
  - result: 41 passed, 5 warnings.

## Security Tool Availability

- `bandit`: unavailable in this environment.
- `semgrep`: unavailable in this environment.
- `gitleaks`: unavailable in this environment.
- `trufflehog`: unavailable in this environment.
- `pip-audit`: unavailable in this environment.
- `pyright`: unavailable in this environment.
- `mypy`: available and run on touched AGS/security modules.

## Bug Fixes From Verification

- Markdown report rendering initially over-escaped ordinary hyphens, breaking the existing `not production-ready` non-goal assertion. The escape set was narrowed so normal text remains readable while HTML, Markdown link syntax, control characters, and dangerous URI schemes remain neutralized.
- Forward observation hash-chain verification initially assumed one global chain, while append semantics are per-plan. Verification now tracks previous hashes independently per plan and has an interleaved-plan regression test.

## Final Result

Pass for the implemented AGS v3.1 current-main-safe acceptance scope. No live trading, broker write, ToolRegistry, AgentLoop, AgentContext, SessionService, scheduler executor, or mandate/order/kill-switch changes were made.
