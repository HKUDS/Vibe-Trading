# Final Acceptance

Evidence date: 2026-07-09

## Scope

This acceptance package covers Alpha Genesis System v3.1 current-main safe work:
research-only scorecards, DSL validation, trial/forward integrity, quality
decisions, read-only reports/API, CLI handling, deterministic demos, and UI
display safety.

Out of scope remains unchanged: no live trading automation, no broker writes,
no mandate/order-gate/kill-switch changes, no ToolRegistry or AgentLoop
wrapping, and no production-ready alpha claim.

## P0 Gate Result

- Feature-off identity and current bench compatibility: covered by
  `agent/tests/alpha_quality/test_feature_off_identity.py` and existing factor
  purity/lookahead regression.
- Runtime boundary: no modified file touches AgentLoop, ToolRegistry, broker,
  mandate, order, kill switch, or live execution surfaces.
- AGS API read-only: covered by
  `agent/tests/security/test_alpha_genesis_api_method_security.py` and
  `agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py`.
- DSL no-code execution: covered by
  `agent/tests/alpha_foundry/dsl/test_no_eval_exec.py` and
  `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py`.
- Train/valid/test and lookahead barriers: covered by alpha quality,
  alpha_foundry, and factor lookahead tests.
- Caller/LLM override rejection: covered by quality-decision, API-method, and
  response-schema tests.
- Trial ledger status and hash-chain integrity: covered by research_ledger
  append-only, concurrency, redaction, and tamper tests.
- Data snapshot PIT/survivorship cap: covered by alpha_quality decision and
  research_ledger snapshot tests.
- Secret and path redaction: covered by report/API/CLI/redaction tests.
- Rollback path: documented in `docs/rollback-plan.md`.

## Commands Run

- `git diff --check` -> passed.
- `python -m compileall -q agent/src agent/cli` -> passed.
- `pytest ... AGS security/contract/ledger/quality/forward/dsl matrix ...` ->
  104 passed, 5 warnings.
- `pytest agent/tests/alpha_genesis_demos agent/tests/alpha_foundry -q` ->
  54 passed.
- `pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q` ->
  915 passed, 5 skipped, 12 warnings.
- `npm.cmd run test:run` -> 32 files passed, 254 tests passed.
- `npm.cmd run build` -> passed; Vite emitted existing chunk-size warnings.
- `semgrep scan --config p/python --config p/secrets ...AGS paths...` ->
  51 tracked files scanned, 187 rules run, 0 findings.
- `python -m bandit -r ...AGS paths... -ll` -> no issues identified.
- `python -m pip_audit -r .tmp/requirements-audit.txt` -> no known
  vulnerabilities found.
- `python -m pip check` -> no broken requirements found after installing
  security tools.
- Post-install targeted regression -> 41 passed, 1 warning.

## Tooling Notes

- `rg` could not be executed in this sandbox, so PowerShell `Select-String` was
  used for changed-file boundary search.
- `semgrep`, `bandit`, and `pip-audit` were installed into the local `.venv`
  for this validation pass.
- `gitleaks` and `gh` were not installed in the local environment.
- Semgrep and pip-audit needed elevated network access for registry/vulnerability
  lookups.

## Decision

The implemented AGS changes satisfy the current pasted P0 gate set for the
changed scope. Remaining limitations are documented in
`docs/known-limitations.md` and do not expand live trading or runtime authority.
