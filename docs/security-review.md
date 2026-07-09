# Security Review

Evidence date: 2026-07-09

## Boundary Review

Changed code is limited to AGS CLI/report handling and AGS-focused tests/docs.
No modified file changes AgentLoop, ToolRegistry, broker connectors, mandate
logic, order routing, kill switch behavior, MCP schemas, or scheduler runtime.

## API Security

- AGS report routes remain GET-only.
- POST, PUT, PATCH, and DELETE requests are rejected without artifact writes.
- Oversized and structured IDs are rejected.
- Corrupt artifacts return sanitized errors without traceback or local paths.
- Query parameters cannot override stored quality decisions.

Primary evidence:

- `agent/tests/security/test_alpha_genesis_api_method_security.py`
- `agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py`
- `agent/tests/contracts/test_ags_response_schema_strict.py`

## CLI Security

- Corrupt JSON, non-object JSON, and incomplete report objects are reported as
  `invalid Alpha Genesis report`.
- CLI errors avoid traceback and local path disclosure.
- CLI report rendering keeps secret-like report metadata redacted.

Primary evidence:

- `agent/tests/security/test_alpha_genesis_cli_security.py`
- `agent/cli/alpha_genesis.py`

## DSL Security

- Code-shaped formulas are rejected before evaluation.
- Valid-looking adversarial formulas are rejected with deterministic codes:
  `LOOKAHEAD_DETECTED`, `WINDOW_OUT_OF_RANGE`, and `OPERATOR_NOT_ALLOWED`.
- Eval, compile, dynamic import, subprocess, and shell paths are guarded by
  tests.

Primary evidence:

- `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py`
- `agent/tests/alpha_foundry/dsl/test_no_eval_exec.py`

## Artifact And Report Security

- Report JSON uses strict serialization with no NaN or Infinity.
- Report builders redact secret-like values.
- Report Markdown escapes hostile content and blocks dangerous URI schemes.
- Full factor panels are not embedded in report JSON.

Primary evidence:

- `agent/tests/alpha_foundry/reports/`
- `agent/tests/security/test_alpha_genesis_redaction.py`
- `agent/tests/security/test_paste_markdown_html_security.py`

## Unavailable Optional Tools

`semgrep`, `bandit`, and `pip-audit` were installed into the local `.venv` for
this validation pass.

Results:

- Semgrep 1.168.0: AGS paths scanned with `p/python` and `p/secrets`; 51 tracked
  files scanned, 187 rules run, 0 findings.
- Bandit 1.9.4: AGS Python paths scanned at medium/high severity; no issues
  identified.
- pip-audit 2.10.1: sanitized requirements file scanned; no known
  vulnerabilities found.
- `pip check`: no broken requirements after installing the tools.

`gitleaks` was not installed. Secret scanning coverage for this pass is provided
by Semgrep `p/secrets` plus AGS-specific redaction tests.
