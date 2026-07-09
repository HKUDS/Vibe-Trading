# Performance Report

Evidence date: 2026-07-09

## Local Results

- AGS security/contract/ledger/quality/forward/dsl matrix: 104 passed in 4.21s.
- Alpha Genesis demos plus alpha_foundry tests: 54 passed in 1.20s.
- Factor purity/lookahead regression: 915 passed, 5 skipped in 203.16s.
- Frontend vitest: 254 passed in 23.90s.
- Frontend production build: passed in 36.83s.
- Semgrep AGS scan: 51 tracked files, 187 rules, 0 findings.
- Bandit AGS scan: 2747 lines of Python scanned, no issues identified.
- pip-audit requirements scan: no known vulnerabilities found.

## Bundle Notes

The frontend build emitted Vite chunk-size warnings for large generated chunks.
No build failure occurred. Bundle splitting can be handled separately because
this PR does not change frontend bundling behavior.

## Artifact Size Notes

Report tests verify AGS report JSON does not embed full factor panels. Large
panels should remain artifact-linked by content hash under an explicit artifact
root.
