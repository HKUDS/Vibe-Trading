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

- Custom Semgrep AGS bypass rules: detects builtins `getattr`, `builtins.__dict__`, and lambda/type `__import__` hiding patterns; 50 files scanned, 3 rules run, 0 findings.
- Semgrep 1.168.0 registry scan with `p/python` and `p/secrets`: 82 files scanned, 187 rules run, 0 findings. Semgrep reported two timeout warnings in unrelated legacy CLI taint rules, with no findings.
- Bandit 1.9.4: AGS Python paths and `agent/cli/alpha_genesis.py` scanned; no issues identified.
- mypy 2.2.0 strict: AGS packages and `agent/cli/alpha_genesis.py`, 51 source files, no issues.
- pyright 1.1.411: AGS packages and `agent/cli/alpha_genesis.py`, 0 errors, 0 warnings.
- pip-audit 2.10.1: active environment scanned; no known vulnerabilities found.
- Safety 3.8.1: active environment scanned, 267 packages, 0 vulnerabilities.
- CycloneDX 7.3.0: environment SBOM generated successfully under `.tmp/ags-sbom.cdx.json`.
- gitleaks 8.30.1: production AGS code/API/CLI paths scanned, 0 leaks.
- trufflehog 3.95.8: production AGS code/API/CLI paths scanned, 0 verified/unknown secrets.
- `pip check`: no broken requirements after installing and reconciling the security/type tools.

## Tool Packaging

- Security regression tests, property tests, golden fixtures, and custom Semgrep rules are committed as long-term reviewer/CI evidence.
- Heavy Python audit tools are isolated to the optional `security` extra rather than the default `dev` extra.
- `gitleaks` and `trufflehog` remain optional external binaries for local/CI secret scans.
- `mutmut` is not a native-Windows gate and should be run separately under WSL/Linux if mutation testing is required.
