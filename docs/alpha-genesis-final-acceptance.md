# Alpha Genesis Final Acceptance

## Phase Checklist

- Phase 0: current-main baseline and scope lock completed.
- Phase 1: alpha quality scorecard completed.
- Phase 2: trial ledger and data snapshot manifest completed.
- Phase 3: DSL-constrained alpha foundry core completed.
- Phase 4: A-share liquidity/reversal case completed.
- Phase 5: novelty, crowding, and synergy scorer completed.
- Phase 6: alpha quality decision layer completed.
- Phase 7: frozen forward tracking completed.
- Phase 8: read-only reports/API surface completed.
- Phase 9: deterministic demos and final package completed.

## Tests Run

- `powershell -ExecutionPolicy Bypass -File scripts\ags_p0_acceptance.ps1` -> passed.
  - `git diff --check` passed with Windows line-ending normalization warnings only.
  - `compileall` passed for AGS modules and CLI.
  - Focused pasted-text-4 matrix -> 53 passed, 1 Starlette/httpx deprecation warning.
  - `mypy --strict --ignore-missing-imports` on AGS packages and `agent/cli/alpha_genesis.py` -> success, 51 source files.
  - `pyright` on AGS packages and `agent/cli/alpha_genesis.py` -> 0 errors, 0 warnings.
  - Custom AGS Semgrep bypass rules -> 50 files, 3 rules, 0 findings.
  - Semgrep registry `p/python` and `p/secrets` -> 187 rules, 82 files, 0 findings; two unrelated legacy CLI taint rules timed out with no findings.
  - Bandit AGS recursive scan -> passed.
  - `pip-audit` -> no known vulnerabilities found.
  - Safety 3.8.1 environment scan -> 267 packages, 0 vulnerabilities.
  - CycloneDX SBOM generation -> passed.
  - gitleaks 8.30.1 production AGS secret scan -> 0 leaks.
  - trufflehog 3.95.8 production AGS secret scan -> 0 verified/unknown secrets.
- `pytest agent/tests/alpha_genesis_demos -q` -> 7 passed.
- `pytest agent/tests/alpha_foundry/reports agent/tests/security/test_alpha_genesis_redaction.py agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py -q` -> 4 passed.
- `pytest agent/tests/alpha_foundry/forward -q` -> 9 passed.
- `pytest agent/tests/alpha_quality -q` -> 29 passed.
- `pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q` -> 915 passed, 5 skipped, 12 warnings.
- `semgrep scan --config p/python --config p/secrets ...AGS paths...` -> 51 tracked files scanned, 187 rules run, 0 findings.
- `python -m bandit -r ...AGS paths... -ll` -> no issues identified.
- `python -m pip_audit -r .tmp/requirements-audit.txt` -> no known vulnerabilities found.
- `python -m pip check` -> no broken requirements found after installing security tools.
- Post-install targeted regression -> 41 passed, 1 warning.

## Evidence Artifacts

- Demo package: `agent/examples/alpha_genesis_demos/`
- Demo tests: `agent/tests/alpha_genesis_demos/`
- Read-only reports: `agent/src/alpha_foundry/reports/`
- Forward tracking: `agent/src/alpha_foundry/forward/`
- Decision layer: `agent/src/alpha_quality/decision/`

## Deliberately Out Of Scope

- No live trading write path.
- No production-ready alpha claim.
- No POST/PUT/PATCH/DELETE Alpha Genesis API.
- No premium data dependency.

## PR Summary

Alpha Genesis adds a current-main-compatible, read-only, evidence-bound factor
research pipeline with deterministic scorecards, trial history, bounded formula
generation, novelty/synergy checks, adversarial quality decisions, frozen
forward tracking, redacted reports, and flagship demos.

Publication is handled by the current AGS branch push and PR/compare link.

See also `docs/final-acceptance.md` for the latest P0/P1/P2 acceptance matrix
and tool-installation notes.
