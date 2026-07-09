# Alpha Genesis Security Review

## Live And Runtime Safety

- No live trading write capability was added.
- No broker connector, mandate, kill switch, ToolRegistry, AgentLoop, or MCP schema was modified.
- Alpha Genesis API routes are GET-only and artifact-backed.

## Formula Safety

- DSL formula handling is data-only.
- No eval, exec, compile, importlib dynamic execution, subprocess, or shell is used for formulas.
- Future-looking fields are rejected by tests.

## Data And Secret Safety

- Report builders redact secret-like keys including api keys, tokens, passwords, and broker secrets.
- Report JSON does not include full factor panels.
- Data snapshot and trial artifacts use hashes and redacted metadata.

## Evidence Integrity

- Trial ledger is append-only.
- Forward observations are append-only and hash-chained.
- Quality decisions are derived from scorecard/context hard failures, not caller claims.
- Hard failures and warnings use exact stable codes.

## Static And Dependency Scans

- Semgrep 1.168.0: AGS paths scanned with `p/python` and `p/secrets`; 51 tracked files scanned, 187 rules run, 0 findings.
- Bandit 1.9.4: AGS Python paths scanned at medium/high severity; no issues identified.
- pip-audit 2.10.1: sanitized requirements file scanned; no known vulnerabilities found.
- `pip check`: no broken requirements after installing the tools.
