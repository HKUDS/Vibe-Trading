# Redaction Evidence

Evidence date: 2026-07-09

## Covered Paths

- CLI report rendering redacts `token` and `api_key` metadata.
- API report payloads redact secret-like keys.
- Markdown report rendering escapes hostile HTML and dangerous URI schemes.
- Data snapshot and ledger paths redact secret-like source config values.
- Corrupt CLI/API artifacts do not leak local filesystem paths or tracebacks.

## Tests

- `agent/tests/security/test_alpha_genesis_cli_security.py`
- `agent/tests/security/test_alpha_genesis_redaction.py`
- `agent/tests/security/test_paste_markdown_html_security.py`
- `agent/tests/research_ledger/test_trial_ledger_redaction.py`
- `agent/tests/security/test_alpha_genesis_api_method_security.py`

The latest targeted AGS matrix passed with 104 tests.
