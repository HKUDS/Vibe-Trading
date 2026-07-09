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

- `semgrep`: installed and run through `scripts/ags_p0_acceptance.ps1`; custom AGS bypass rules and registry `p/python`/`p/secrets` reported 0 findings.
- `bandit`: installed and run on AGS Python paths plus `agent/cli/alpha_genesis.py`; no issues identified.
- `pip-audit`: installed and run; no known vulnerabilities found.
- `safety`: installed and run in non-interactive check mode; 267 packages scanned, 0 vulnerabilities.
- `cyclonedx-py`: installed and run; SBOM generated under `.tmp/ags-sbom.cdx.json`.
- `gitleaks`: downloaded to `.tmp/tools/gitleaks/gitleaks.exe` and run on production AGS code/API/CLI paths; 0 leaks.
- `trufflehog`: downloaded to `.tmp/tools/trufflehog/trufflehog.exe` and run on production AGS code/API/CLI paths; 0 verified/unknown secrets.
- `mypy`: installed and run in strict mode on AGS packages and `agent/cli/alpha_genesis.py`; 51 source files, no issues.
- `pyright`: installed and run on AGS packages and `agent/cli/alpha_genesis.py`; 0 errors, 0 warnings.
- `mutmut`: installed, but native Windows execution is unsupported by the tool. Mutation testing must run under WSL/Linux if a mutation-score gate is required.

Dependency packaging note: pytest/Hypothesis remain in the lightweight dev/test extras. Semgrep, Bandit, pip-audit, Safety, CycloneDX, mypy, and pyright are reproducible through the optional `security` extra for local audit runs. gitleaks/trufflehog are external optional binaries, and `mutmut` is not a Windows/local required gate.

## Pasted-Text-4 Extreme Acceptance Run

- Command: `powershell -ExecutionPolicy Bypass -File scripts\ags_p0_acceptance.ps1`
- Result: passed.
- Included gates: whitespace diff check, compileall, focused pasted-text-4 pytest matrix, mypy strict, pyright, custom Semgrep rules, Semgrep registry rules, Bandit, pip-audit, Safety, CycloneDX SBOM generation, gitleaks, and trufflehog.
- Focused pytest result inside the script: 53 passed, 1 Starlette/httpx deprecation warning.
- Static/type result: mypy success on 51 source files; pyright 0 errors.
- Secret/dependency result: Semgrep 0 findings, Bandit passed, pip-audit 0 known vulnerabilities, Safety 0 vulnerabilities, gitleaks 0 leaks, trufflehog 0 verified/unknown secrets.

## Bug Fixes From Verification

- Markdown report rendering initially over-escaped ordinary hyphens, breaking the existing `not production-ready` non-goal assertion. The escape set was narrowed so normal text remains readable while HTML, Markdown link syntax, control characters, and dangerous URI schemes remain neutralized.
- Forward observation hash-chain verification initially assumed one global chain, while append semantics are per-plan. Verification now tracks previous hashes independently per plan and has an interleaved-plan regression test.

## Final Result

Pass for the implemented AGS v3.1 current-main-safe acceptance scope. No live trading, broker write, ToolRegistry, AgentLoop, AgentContext, SessionService, scheduler executor, or mandate/order/kill-switch changes were made.
