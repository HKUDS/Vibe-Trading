# AGS v3.1 Extreme Acceptance Summary

Generated: 2026-07-09  
Evidence baseline branch: `codex/ags-v31-main`  
Evidence baseline code commit: `cc0d498af583c924eafa58f2671ecedb0781a8af` (`test: add ags extreme acceptance gates`)  
Compare URL: `https://github.com/Elfsa-Miranda/Vibe-Trading/compare/main...codex/ags-v31-main?expand=1`

This report was written after inspecting the repository state, git history, changed files, control documents, selected production code, test files, tooling scripts, and recorded command outputs. It intentionally does not claim that AGS is fully secure or that all possible vulnerabilities are fixed.

## A. Executive Summary

This round hardened AGS v3.1 around adversarial acceptance boundaries rather than changing the intended AGS product shape. The main improvements are artifact path safety, strict JSON artifact writing, stronger formula/DSL injection rejection, read-only API schema binding, stronger secret/path redaction, hash-chain property coverage, constant-rank-IC edge handling, type-checker cleanups, and a synergy column-collision fix.

This round was necessary after the larger AGS v3.1 implementation because the initial implementation proved the pipeline, while the extreme acceptance pass tested whether that pipeline could survive hostile paths, forged API/query/header inputs, formula injection payloads, local path/secret leakage, schema confusion, and regression drift. It also turns several security checks into repeatable gates.

The risks addressed are primarily research-system integrity risks: path traversal, schema confusion, formula execution boundary bypasses, secret leakage in artifacts/API/CLI/Markdown, ledger omission or tampering, statistical edge-case instability, architecture drift into forbidden runtime/live surfaces, and resource-budget regressions.

Current readiness: the branch is pushed to `origin/codex/ags-v31-main` at the evidence baseline commit and is ready to open as a PR from the pushed branch. A real GitHub PR was not created locally because `gh` and GitHub tokens were unavailable in this environment; only the compare link is available.

Remaining limits: verification is local Windows based; WSL is unavailable; `mutmut` is installed but cannot run on native Windows; no local Linux CI run was verified; synthetic fixtures do not prove real market alpha; security scans reduce risk but cannot prove absence of vulnerabilities; the real API server was not launched for an end-to-end network integration run.

## B. Commit and Remote State

Mandatory command outputs captured during this review:

```text
git branch --show-current
codex/ags-v31-main
```

```text
git status --short --branch
## codex/ags-v31-main...origin/codex/ags-v31-main
```

```text
git log --oneline -5
cc0d498 test: add ags extreme acceptance gates
1b9c31a test: harden ags security acceptance
f0e257c test: harden alpha genesis acceptance coverage
6eb3751 merge phase 9 demos final package
997b567 feat: add alpha genesis demos and final package
```

```text
git ls-remote origin refs/heads/codex/ags-v31-main
cc0d498af583c924eafa58f2671ecedb0781a8af	refs/heads/codex/ags-v31-main
```

```text
git rev-parse HEAD
cc0d498af583c924eafa58f2671ecedb0781a8af

git rev-parse origin/codex/ags-v31-main
cc0d498af583c924eafa58f2671ecedb0781a8af
```

Remote state:

```text
origin   https://github.com/Elfsa-Miranda/Vibe-Trading.git (fetch/push)
upstream https://github.com/HKUDS/Vibe-Trading.git (fetch/push)
```

Evidence baseline diffstat against `main`, captured before this report file was added:

```text
194 files changed, 9140 insertions(+), 1 deletion(-)
```

Changed-file classification from the evidence baseline `git diff --name-only main...HEAD`:

| Class | Count | Notes |
| --- | ---: | --- |
| Total changed files | 194 | Full branch diff against `main`. |
| Core production/application files | 57 | `agent/src/**`, `agent/cli/**`, `agent/api_server.py`, and `frontend/src/lib/alphaGenesisSecurity.ts`. |
| Demo/example files | 42 | Deterministic AGS demo fixtures, runners, expected outputs, and READMEs. |
| Agent test files/fixtures | 63 | Backend acceptance, security, contracts, alpha quality/foundry/ledger/performance tests. |
| Frontend test files | 5 | Targeted UI/export/cache/redaction tests. |
| Docs | 24 | Acceptance, security, limitations, rollback, performance, runbook, evidence docs. |
| Tooling/scripts | 3 | `pyproject.toml`, `scripts/ags_p0_acceptance.ps1`, `security/semgrep/ags-python-injection.yml`. |
| Generated artifacts in diff | 0 | `.tmp`, caches, venvs, scan reports, and generated SBOM are not in the branch diff. |

After adding this report file, the current branch diff is:

```text
195 files changed, 9718 insertions(+), 1 deletion(-)
```

Current post-report classification: 57 core production/application files, 42 demo/example files, 68 test files/fixtures, 25 docs, 3 tooling/script files, and 0 generated artifacts.

Latest commit `cc0d498` contains 37 files and is the focused extreme acceptance gate commit. It adds `agent/src/alpha_foundry/artifacts.py`, the P0 acceptance script, custom Semgrep rules, security/property/golden/performance/architecture tests, and hardening edits in DSL, API, ledger, redaction, scorecard, novelty/synergy, and docs.

PR creation status: no real PR exists from this local environment. The GitHub CLI is unavailable locally, `GITHUB_TOKEN`/`GH_TOKEN` were unavailable, and no PR creation connector was callable in this session. Use the compare link above to open the PR.

Worktree state before this report file was created was clean and tracking the remote branch. This report itself is a documentation-only follow-up.

## C. Production Code Changes

### C1. Artifact Path Safety

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/alpha_foundry/artifacts.py` | Added `safe_artifact_path`, `safe_artifact_write_json`, `PathTraversalError`, multi-pass URL decoding, backslash normalization, absolute-path rejection, NUL byte rejection, suspicious Unicode dot rejection, symlink escape checks, parent creation under root, strict JSON serialization, secret redaction, fsync, and atomic replace. | AGS writes reports/artifacts and must not allow caller-controlled paths or unsafe JSON. | Path traversal, URL-encoded traversal, Windows traversal, Unicode traversal-like payloads, NUL byte payloads, symlink escape, partial write corruption, NaN/Infinity JSON. | `agent/tests/security/test_ags_artifact_path_safety.py`, `scripts/ags_p0_acceptance.ps1`, `git diff --check`, `compileall`. |

### C2. DSL Validation and Formula Execution Boundary

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/alpha_foundry/dsl/parser.py` | Enforces `MAX_FORMULA_CHARS`, rejects trailing syntax, rejects top-level bare fields and non-AST bare numeric formulas, and only builds the project AST. | Formula strings must remain data and cannot become Python syntax. | Code-shaped formulas, partial parse bypass, bare scalar/field ambiguity. | `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py`, `agent/tests/alpha_foundry/dsl/test_parser_validator.py`. |
| `agent/src/alpha_foundry/dsl/validator.py` | Expanded lookahead alias detection: `future_`, `next_`, `_next`, `*next`, `fwd_`, `_fwd`, `t_plus`, and `lead`; retains operator/field/window/depth/node restrictions. | Future-looking aliases can bypass a simple `future_` prefix check. | Lookahead leakage and hidden future-field formula acceptance. | `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py`, quality-decision adversarial tests. |
| `agent/src/alpha_foundry/dsl/operators.py` | Validates formulas before evaluation, emits structured security logs on validation failure, uses AST dispatch only, validates DataFrame vs scalar arguments, adds type narrowing/casts, and does not call eval/exec/compile/importlib/subprocess/shell. | Formula execution must be deterministic, bounded, and testable. | Formula injection through dynamic builtins/import tricks, scalar/DataFrame confusion, unstructured rejection logs. | `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py`, `agent/tests/alpha_foundry/dsl/test_no_eval_exec.py`, custom Semgrep. |

Static execution-boundary search over AGS production/API/CLI paths found no formula `eval(`, `exec(`, `compile(`, `importlib`, `subprocess`, `os.system`, or `shell=True` path. The only matches were false positives such as `re.compile` and ledger `query()`.

### C3. API Artifact Schema Binding

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/api/alpha_genesis_routes.py` | Added strict artifact ID regex, root-relative artifact resolution, JSON-object validation, endpoint-specific `schema_version` checks, cross-type hiding via 404, secret/json-safe redaction on output, and no-store/nosniff headers. | Read-only report endpoints must not become IDOR-like local file reads or schema-confusion surfaces. | Artifact ID injection, path traversal, cross-artifact schema confusion, forged query/header decisions, raw secret/path exposure. | `agent/tests/security/test_alpha_genesis_api_injection_extreme.py`, `agent/tests/security/test_alpha_genesis_api_method_security.py`, `agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py`, `agent/tests/security/test_alpha_genesis_secret_leakage_extreme.py`. |
| `agent/api_server.py` | Registers AGS routes additively. | Expose reports through existing API pattern without replacing core runtime. | Route drift and integration mismatch. | OpenAPI GET-only snapshot and API/CLI/UI consistency tests. |

### C4. Redaction Hardening

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/research_ledger/hash_utils.py` | Added recursive redaction for sensitive keys and values, `Authorization`/`Bearer`/`api_key`/`secret`/`token`/`password` patterns, `sk-` style secrets, Windows absolute paths, selected POSIX local paths when path-like keys are used, dataclass and NumPy/pandas JSON safety, and strict canonical JSON hashing. | Artifacts, CLI, Markdown, ledger, and API output share data-model serialization helpers. | Secret leakage, local absolute path leakage, non-finite JSON, unstable canonical hashes. | `agent/tests/security/test_alpha_genesis_secret_leakage_extreme.py`, `agent/tests/security/test_alpha_genesis_redaction.py`, `agent/tests/research_ledger/test_trial_ledger_redaction.py`, `agent/tests/alpha_quality/test_property_invariants.py`. |
| `agent/src/alpha_foundry/reports/builder.py` | Applies `redact_secrets` to report metadata and source config. | Reports are reviewer-facing artifacts and should not carry raw credentials or local paths. | JSON/API/CLI report leakage. | Redaction tests and report builder tests. |
| `agent/src/alpha_foundry/reports/model.py` | Keeps report schema contract and strict JSON path through shared helpers. | Report payload must preserve schema and redact consistently. | Schema drift and serialization leaks. | `agent/tests/alpha_foundry/reports/test_report_builder.py`, secret leakage tests. |
| `agent/src/alpha_foundry/reports/render_markdown.py` | Escapes HTML/Markdown-sensitive characters, removes control chars, neutralizes dangerous URI schemes, and preserves normal hyphenated text like `not production-ready`. | Markdown output must be readable while not rendering active content. | Markdown/HTML injection and broken non-goal assertions. | `agent/tests/security/test_alpha_genesis_secret_leakage_extreme.py`, report builder tests, final verification bug-fix reruns. |
| `agent/cli/alpha_genesis.py` | Adds read-only local report loader/render command with typed CLI errors. | CLI should read/render AGS artifacts, not run mining or mutate state. | CLI secret leakage through shared report serialization and invalid JSON tracebacks. | `agent/tests/security/test_alpha_genesis_cli_security.py`, secret leakage tests. |
| `frontend/src/lib/alphaGenesisSecurity.ts` | Adds frontend redaction/security helpers for report export/cache/UI handling. | UI surfaces should preserve backend truthfulness and avoid displaying sensitive report material. | Frontend display/export/cache leakage. | Frontend tests under `frontend/src/lib/__tests__/`. |

### C5. Ledger and Evidence Integrity

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/research_ledger/trial_ledger.py` | Uses SQLite WAL, `BEGIN IMMEDIATE`, append-only insert table, retry on operational lock errors, stable hash chaining, strict JSON payload writes, redacted metrics/parameter variants, and explicit update/delete mutation errors. | Every success/reject/skip/error trial must be recorded and verifiable. | Unsafe concurrent append, ledger omission, tampering, mutation, Bandit noise around broad writes. | `agent/tests/research_ledger/test_trial_ledger_append_only.py`, `test_trial_ledger_concurrency.py`, `test_property_hash_chain.py`, `test_ledger_integrity_and_tamper.py`. |
| `agent/src/research_ledger/data_snapshot.py` | Produces redacted, hashed data snapshot manifests with PIT/survivorship fields. | Quality decisions depend on reproducible and bias-aware data metadata. | Overclaiming biased/non-PIT data and leaking source configs. | `agent/tests/research_ledger/test_data_snapshot.py`, redaction tests. |
| `agent/src/research_ledger/query.py` | Provides read-only query helper over the ledger. | Query utilities are allowed; mutation APIs are not. | Accidental mutation surface. | Ledger append-only and architecture tests. |

### C6. Quant and Statistics Correctness Fixes

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/alpha_quality/ic_metrics.py` | Skips constant factor/return cross sections before correlation, returns bounded IC series, and keeps standard vs Newey-West t-stat selection. | Constant cross sections can create warnings/NaN correlations and unstable metric output. | RuntimeWarning noise, NaN metric drift, misleading rank IC edge behavior. | `agent/tests/alpha_quality/test_property_invariants.py`, `test_ic_metrics.py`, golden master scorecard. |
| `agent/src/alpha_quality/scorecard.py` | Maintains strict scorecard schema, split/horizon reporting, execution metrics, data snapshot/trial ledger refs, and type-checker cleanups. | Scorecards are the core deterministic evidence artifact. | Non-strict JSON, schema drift, test-scope ambiguity. | `agent/tests/alpha_quality/test_scorecard_contract.py`, `test_golden_master_scorecard.py`, `test_property_invariants.py`. |
| `agent/src/alpha_quality/model.py` | Keeps frozen scorecard/FactorOutputFrame contracts and JSON-safe serialization. | AGENTS requires uniform output objects and immutable factor metadata. | Mutable scorecard/factor contract drift, non-finite JSON. | Property invariant tests and golden master. |
| `agent/src/alpha_quality/forward_returns.py` | Implements explicit horizon and execution lag forward returns. | Avoid same-bar lookahead. | Lookahead through same-bar return alignment. | `agent/tests/alpha_quality/test_forward_returns.py`, property invariants. |
| `agent/src/alpha_quality/masks.py` | Builds A-share masks for ST, suspension, limit, newly listed, and liquidity proxies. | Tradability/coverage must reflect A-share constraints when fixture data provides them. | Overstated tradability and coverage. | `agent/tests/alpha_quality/test_ashare_masks.py`. |
| `agent/src/alpha_quality/execution_return.py` | Computes portfolio-style execution return after costs/turnover. | IC alone is insufficient for tradability. | Cost-insensitive alpha claims. | Scorecard, decision, and property tests. |
| `agent/src/alpha_quality/turnover.py` | Adds deterministic target weights and turnover helpers. | Execution return and cost checks require turnover. | Missing cost/turnover evidence. | `agent/tests/alpha_quality/test_scorecard_contract.py`, decision cost tests. |
| `agent/src/alpha_quality/splits.py` | Defines train/valid/test split access errors. | Discovery code must not read final test data. | Test-set leakage. | Search and scorecard tests. |

### C7. Type-Safety Improvements

Type-safety changes are mostly casts, dataclass/dict narrowing, optional value checks, and stricter helper signatures in:

`agent/src/alpha_foundry/dsl/operators.py`, `agent/src/alpha_foundry/forward/model.py`, `agent/src/alpha_foundry/novelty.py`, `agent/src/alpha_foundry/reports/builder.py`, `agent/src/alpha_foundry/reports/model.py`, `agent/src/alpha_foundry/residualize.py`, `agent/src/alpha_foundry/synergy.py`, `agent/src/alpha_quality/masks.py`, `agent/src/alpha_quality/model.py`, `agent/src/alpha_quality/scorecard.py`, `agent/src/research_ledger/data_snapshot.py`, `agent/src/research_ledger/trial_ledger.py`.

Why: `mypy --strict` and `pyright` were added as gates for AGS data-flow paths. The changes are intended to make implicit optional/dict/object assumptions explicit without changing business decisions.

Risk reduced: type-driven runtime surprises, unsafe casts hidden from review, and untested optional branches.

Tests/tools: `mypy --strict` passed on 51 source files; `pyright` reported 0 errors and 0 warnings; existing pytest/golden tests ensure behavior did not drift.

### C8. Synergy and Correlation Safety

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/alpha_foundry/synergy.py` | Candidate return is renamed to a collision-resistant internal column (`__candidate__`, with fallback names if needed) before concat/drop. | If the pool already has a `candidate` column, marginal IR/correlation calculations can select the wrong series or drop the wrong column. | Redundant factor acceptance/rejection based on wrong marginal portfolio value. | `agent/tests/alpha_foundry/test_synergy.py`, `agent/tests/alpha_foundry/test_crowding_controls.py`, acceptance/performance tests. |
| `agent/src/alpha_foundry/novelty.py` | Tightens correlation calculations and typing. | Duplicate detection must be deterministic and date-aligned. | Duplicate/public alpha bypass and false novelty. | `agent/tests/alpha_foundry/test_novelty.py`. |
| `agent/src/alpha_foundry/residualize.py` | Type and residual calculation cleanups. | Residual IC must be date-wise and stable. | Misleading residual alpha claims. | `agent/tests/alpha_foundry/test_residualize.py`. |
| `agent/src/alpha_foundry/cluster.py` | Adds simple deterministic clustering helpers. | Supports crowding/novelty diagnostics. | Unexplained duplicate grouping. | Foundry novelty/synergy tests. |
| `agent/src/alpha_foundry/scorer.py` | Adds deterministic scoring glue. | AGENTS requires deterministic judgment, not LLM-written decisions. | Caller/LLM score override. | Decision and acceptance tests. |

### C9. Alpha Foundry, Cases, Forward Tracking, and Demos

| Area/files | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/alpha_foundry/candidate_pool.py`, `seed_bank.py`, `mutators.py`, `mechanisms.py`, `search.py` | Adds bounded seed/candidate/search primitives and mechanism labels. | Foundry must generate formulaic candidates under budget and lineage constraints. | Random formula spam, unbounded search, missing lineage. | `agent/tests/alpha_foundry/test_seed_bank.py`, `test_mutators.py`, `test_search_budget.py`. |
| `agent/src/alpha_foundry/cases/ashare_liquidity_reversal.py` | Adds deterministic A-share liquidity/reversal case. | Demonstrate mechanism-first mining with controls. | Hand-picked winner claims and missing bad controls. | `agent/tests/alpha_foundry/cases/test_ashare_liquidity_reversal_case.py`. |
| `agent/src/alpha_foundry/forward/model.py`, `store.py`, `evaluator.py`, `kill_rules.py` | Adds frozen forward plans, append-only observations, hash chaining, out-of-order rejection, deterministic kill rules. | Forward tracking is observation, not backtest mutation. | Retroactive observation edits and premature forward success claims. | `agent/tests/alpha_foundry/forward/*`, demo tests. |
| `agent/examples/alpha_genesis/**`, `agent/examples/alpha_genesis_demos/**` | Adds deterministic demos for future leak, cherry-picked noise, survivorship bias, high turnover, duplicate public alpha, orthogonal liquidity reversal, and forward decay kill. | Demonstrate both rejection and narrow preservation through production builders/adapters. | Beautiful fake alpha overclaiming. | `agent/tests/alpha_genesis_demos/*`, final acceptance docs. |

### C10. API/Upload/Weixin Adjacent Security

| File | What changed | Why | Risk reduced | Tests |
| --- | --- | --- | --- | --- |
| `agent/src/api/uploads_routes.py` | Small additive security adjustment for upload route behavior. | AGS report/image/paste surfaces interact with artifact/cache handling. | Hidden artifact cache or upload contract drift. | `agent/tests/security/test_artifact_cache_thumbnail_ocr_isolation.py`, upload/security regressions. |
| `agent/src/channels/weixin.py` | Minor adjacent hardening/update. | Preserve channel contract while security tests cover return-value behavior. | Return-value contract leakage or unsafe display drift. | `agent/tests/security/test_return_value_contract_security.py`. |

## D. New and Expanded Tests

These tests should be committed with the code. They are not disposable helpers: they are the reproducible evidence that the new acceptance gates, property invariants, golden outputs, architecture constraints, injection tests, and performance budgets continue to hold.

| Test file | Test category | Main risk covered | Important assertions | Deterministic | Production code or fixture/stub | Related AGENTS/ExecPlan requirement |
| --- | --- | --- | --- | --- | --- | --- |
| `agent/tests/security/test_ags_static_semgrep_rules.py` | Static security tooling contract | Custom rule drift | Rule IDs for builtins getattr, builtins dict, dynamic import hiding exist and mention required patterns | Yes | Rule file fixture | No eval/exec/import/shell; security gates |
| `agent/tests/security/test_ags_artifact_path_safety.py` | Path/artifact security | Traversal, symlink escape, atomic strict JSON | Blocks `../`, Windows backslashes, encoded traversal, NUL, Unicode dot payloads; rejects symlink escape; leaves no tmp file | Yes | Production `safe_artifact_path` and `safe_artifact_write_json` | Path and artifact safety |
| `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py` | Formula injection/adversarial DSL | Lookahead aliases and dynamic execution payloads | Rejects future aliases, negative lag, huge windows, unknown ops, Python/import/query-shaped payloads; monkeypatched dynamic execution paths are not called; structured security log emitted | Yes | Production parser/validator/evaluator | DSL no eval, lookahead rejection |
| `agent/tests/alpha_quality/test_property_invariants.py` | Property/stat invariants | Forward-return and IC edge drift | Hypothesis checks lagged close-to-close identity and bounded rank IC; strict JSON sanitizes NaN/Infinity; FactorOutputFrame is frozen and label-aligned | Yes | Production scorecard/model/metrics | Multi-horizon returns, strict JSON, factor output contracts |
| `agent/tests/research_ledger/test_property_hash_chain.py` | Ledger property test | Missing status recording and hash-chain breakage | Random success/reject/skip/error status lists are preserved; first previous hash is null; every record points to prior entry hash | Yes | Production SQLite ledger | Every trial counts; append-only hash chain |
| `agent/tests/alpha_quality/test_golden_master_scorecard.py` | Golden master | Scorecard output contract drift | Deterministic fixture scorecard exactly equals golden JSON | Yes | Production scorecard with fixture panel | Evidence-bound scorecard artifacts |
| `agent/tests/fixtures/alpha_quality/scorecard_golden.v1.json` | Golden fixture | Undetected scorecard schema/value drift | Small sanitized expected scorecard with schema, coverage, execution, horizons, split metrics, refs | Yes | Sanitized fixture | Golden fixture should be committed |
| `agent/tests/contracts/test_ags_architecture_invariants.py` | Architecture boundary | Runtime/live import drift | AGS modules do not import forbidden live/runtime/tool roots, do not reference forbidden runtime names, do not create sockets or logging handlers on import | Yes | Production source AST/import smoke | No core runtime wrapping; no live side effects |
| `agent/tests/security/test_alpha_genesis_api_injection_extreme.py` | API injection/schema binding | Artifact ID injection, IDOR-like path behavior, schema confusion, forged query/header inputs | Malicious IDs return 400/404 without tracebacks/local paths; scorecard endpoint is schema-bound; headers/queries cannot forge decisions | Yes | FastAPI TestClient over production routes | GET-only report API, no forged decisions |
| `agent/tests/security/test_alpha_genesis_secret_leakage_extreme.py` | Secret/path leakage | JSON/Markdown/CLI/API leakage | Raw token, `sk-` secret, bearer secret, semantic API key, and tmp local paths are absent from all rendered outputs | Yes | Production report model/render/CLI/API | Redact secrets and local paths |
| `agent/tests/performance/test_ags_acceptance_budget.py` | Performance/resource budget | Unbounded DSL, scorecard, ledger runtime/size | 250 formula evaluations under 2s; scorecard under 3s and JSON under 100KB; 80 ledger appends under 6s and hash chain verifies | Yes | Production DSL/scorecard/ledger with fixture panels | Resource limits and no full panel report JSON |
| `agent/tests/contracts/test_alpha_genesis_openapi_snapshot.py` | API method contract | Write endpoint drift | Every `alpha-genesis` OpenAPI path is GET-only | Yes | FastAPI route registration | No POST/PUT/PATCH/DELETE AGS API |
| `agent/tests/contracts/test_ags_response_schema_strict.py` | Response schema | Artifact contract drift | AGS responses keep strict schema expectations | Yes | Production models/routes | Canonical artifacts/schema version |
| `agent/tests/acceptance/test_ags_business_boundary_invariants.py` | Business boundary | Live/production-readiness overclaiming | Research-only state transitions and boundary invariants hold | Yes | Production decision/report paths | No live trading surface |
| `agent/tests/acceptance/test_ags_full_flow_reality.py` | Full-flow fixture | Fake alpha not rejected or evidence omitted | End-to-end fixture flow preserves evidence and rejection/cap reasons | Yes | Production code with synthetic data | Evidence-bound claims |
| `frontend/src/lib/__tests__/*.test.tsx` | Frontend security/regression | UI/export/cache truthfulness and redaction drift | Decision badges, image previews, paste Markdown, report exports, and service-worker cache behavior are covered | Yes | Frontend production helper(s) and fixtures | Reports redact secret-like values; UI surfaces do not overclaim |

Additional tests added or expanded include alpha-quality decision hard-fail/advisory/cap/override tests, forward-store append-only tests, demo tests for every flagship scenario, ledger data snapshot/redaction/concurrency tests, novelty/residualize/synergy/crowding tests, and phase-0 run-bench contract/feature-off identity tests.

## E. Tooling and Acceptance Script

`scripts/ags_p0_acceptance.ps1` is the one-command local Windows acceptance gate for this hardening pass. It sets local Semgrep config/cache under `.tmp`, disables Semgrep metrics, requires installed Python security/type tools in `.venv`, and runs deterministic checks over AGS code.

Blocking checks in the script:

- `git diff --check`
- `python -m compileall -q agent/src/alpha_foundry agent/src/alpha_quality agent/src/research_ledger agent/cli`
- Focused pytest matrix:
  - `agent/tests/security/test_ags_static_semgrep_rules.py`
  - `agent/tests/security/test_ags_artifact_path_safety.py`
  - `agent/tests/alpha_foundry/dsl/test_adversarial_payloads.py`
  - `agent/tests/alpha_quality/test_property_invariants.py`
  - `agent/tests/research_ledger/test_property_hash_chain.py`
  - `agent/tests/alpha_quality/test_golden_master_scorecard.py`
  - `agent/tests/contracts/test_ags_architecture_invariants.py`
  - `agent/tests/security/test_alpha_genesis_api_injection_extreme.py`
  - `agent/tests/security/test_alpha_genesis_secret_leakage_extreme.py`
  - `agent/tests/performance/test_ags_acceptance_budget.py`
- `mypy --strict --ignore-missing-imports` on AGS packages and `agent/cli/alpha_genesis.py`
- `pyright` on the same AGS packages and CLI
- Custom Semgrep rules in `security/semgrep/ags-python-injection.yml`
- Semgrep registry `p/python` and `p/secrets` unless `-SkipRegistrySemgrep` is passed
- Bandit recursive AGS scan
- `pip-audit`
- Safety check
- CycloneDX SBOM generation to `.tmp/ags-sbom.cdx.json`

Conditional/advisory external checks:

- `gitleaks` runs if `.tmp/tools/gitleaks/gitleaks.exe` exists; otherwise the script warns and skips it.
- `trufflehog` runs if `.tmp/tools/trufflehog/trufflehog.exe` exists; otherwise the script warns and skips it.
- WSL/mutation testing is documented outside the script as a limitation; native Windows cannot run `mutmut`.

Tooling added through `pyproject.toml` dev extra:

- `hypothesis>=6.0`
- `bandit>=1.9.0`
- `click~=8.1.8`
- `cyclonedx-bom>=7.0`
- `mypy>=2.0`
- `mutmut>=3.0`
- `pip-audit>=2.10`
- `pyright>=1.1`
- `safety>=3.8`
- `semgrep>=1.168`
- `typer==0.16.1`

`click~=8.1.8` and `typer==0.16.1` were pinned because the installed security tooling stack had CLI dependency pressure; pinning keeps the local acceptance script reproducible. This does add maintainer burden because the dev extra becomes heavier. If maintainers prefer a lighter default dev install, the security tools can be moved into a dedicated `security` extra or `requirements-security.txt` without weakening the code changes.

## F. Actual Verification Results

Exact recorded results from the acceptance docs and command outputs inspected in this review:

```text
scripts\ags_p0_acceptance.ps1: passed
Focused pasted-text-4 pytest: 53 passed, 1 warning
Wide AGS regression: 132 passed, 1 warning
Factor purity/lookahead: 915 passed, 5 skipped, 12 warnings
mypy strict: Success: no issues found in 51 source files
pyright: 0 errors, 0 warnings, 0 informations
Custom Semgrep: 50 files, 3 rules, 0 findings
Semgrep registry: 187 rules, 82 files, 0 findings
Semgrep registry warning: two unrelated agent/cli/_legacy.py taint-rule timeout warnings; no findings; exit 0
Bandit: AGS scope passed
pip-audit: No known vulnerabilities found
Safety: 267 packages, 0 vulnerabilities
CycloneDX: SBOM generated to .tmp/ags-sbom.cdx.json, not committed
gitleaks: production AGS/API/CLI paths 0 leaks
trufflehog: production AGS/API/CLI paths 0 verified/unknown secrets
pip check: No broken requirements found
WSL: unavailable locally
mutmut: installed but not runnable on native Windows
```

Additional recorded results from `docs/ags-final-test-results.md`:

```text
Targeted AGS/backend pytest: 84 passed, 5 warnings
Existing adjacent regressions: 27 passed, 5 warnings
Frontend targeted Alpha Genesis security vitest: 5 files passed, 11 tests passed
Frontend full vitest: 32 files passed, 254 tests passed
Frontend build: passed; Vite emitted existing large chunk-size warnings
Post-review focused rerun: 41 passed, 5 warnings
```

Commands inspected or run while preparing this report:

- `git branch --show-current`
- `git status --short --branch`
- `git log --oneline -5`
- `git ls-remote origin refs/heads/codex/ags-v31-main`
- `git diff --name-status main...HEAD`
- `git diff --stat main...HEAD`
- `git diff --name-only main...HEAD`
- `git show --stat --oneline --summary HEAD`
- `git rev-parse HEAD`
- `git rev-parse origin/codex/ags-v31-main`
- `git remote -v`
- Targeted reads of `AGENTS.md`, `execplan.md`, final acceptance/security/limitations/test-result docs
- Targeted reads of production hardening files, tests, Semgrep rule file, acceptance script, and `pyproject.toml`
- Static boundary searches for forbidden runtime/live names and dynamic execution patterns

No command output should be interpreted as proof of absolute safety. The scan results are useful gates and evidence, not a guarantee that no vulnerability exists.

## G. AGENTS / ExecPlan Compliance Review

| Requirement | Evidence reviewed | Status |
| --- | --- | --- |
| No `AgentLoop` modification | Static search over AGS prod/API/CLI paths and changed file names found no `AgentLoop` reference. | Satisfied for inspected paths. |
| No `AgentContext` modification | Static search found no `AgentContext` reference. | Satisfied for inspected paths. |
| No `ToolRegistry` modification | Static search found no `ToolRegistry` reference. | Satisfied for inspected paths. |
| No `SessionService` modification | Static search found no `SessionService` reference. | Satisfied for inspected paths. |
| No live/broker/order/mandate/kill-switch write path | Static search found no live/order/broker/mandate write terms in AGS prod/API/CLI paths; changed file names only include forward `kill_rules.py` for research forward-decay logic. | Satisfied for inspected AGS scope. |
| AGS API remains GET-only | `agent/src/api/alpha_genesis_routes.py` contains three `@app.get` routes and no POST/PUT/PATCH/DELETE; OpenAPI snapshot test enforces this. | Satisfied. |
| Existing `run_bench` behavior not rewritten | `run_bench` remains present; AGS adds `run_bench_with_scorecard` as an additive entrypoint. | Satisfied. |
| No formula eval/exec/importlib/subprocess/shell path | DSL parser/validator/evaluator inspected; dynamic execution search produced only false positives (`re.compile`, ledger `query()`); tests monkeypatch eval/compile/import/subprocess/os.system. | Satisfied for formula path. |
| No submitted secrets/caches/local binary outputs | Diff classification found 0 generated artifacts; `.tmp` absent at review time; generated SBOM/scanner binaries are not committed. | Satisfied. |
| Read-only research scope preserved | CLI reads/renders reports; API returns stored artifacts; no API starts mining jobs. | Satisfied for implemented surfaces. |
| Feature-off identity not weakened | `run_bench` is unchanged behaviorally; feature-off/run-bench contract tests exist. | Satisfied by tests, not by byte-for-byte proof. |
| Report/API redaction strengthened | Shared redaction helpers, report builder, CLI, API, Markdown, and frontend tests were inspected. | Satisfied for tested paths. |
| Deterministic quality-decision boundaries preserved | Decision tests cover hard failures, caps, advisory handling, and caller/LLM override rejection. | Satisfied for fixture-backed scope. |

ExecPlan alignment: the branch follows the current-main-safe direction by adding modules under `agent/src/alpha_foundry`, `agent/src/alpha_quality`, and `agent/src/research_ledger`, preserving `run_bench`, using GET-only report APIs, keeping formulas eval-free, and documenting limitations/rollback.

## H. Security Threat Coverage Mapping

| Threat | New protection | Test coverage | Residual risk |
| --- | --- | --- | --- |
| Path traversal | `safe_artifact_path` resolves under root and rejects absolute paths/parent escapes. | `test_ags_artifact_path_safety.py` | Other artifact writers must use the helper. |
| URL encoded traversal | Multi-pass `unquote` before path normalization. | Encoded and double-encoded API/path tests | Encoding variants outside current cases should remain fuzzed. |
| Windows path traversal | Backslash normalization and absolute path rejection. | Windows backslash traversal test | Windows symlink/junction behavior should be checked in CI. |
| Unicode traversal-like payloads | Suspicious dot characters rejected. | Unicode payload tests | Unicode confusables beyond tested chars may exist. |
| NUL byte | NUL rejected before path resolution. | NUL path/API tests | Python/pathlib already rejects many NUL cases, but helper covers AGS. |
| Symlink escape | Existing symlink targets must resolve under root; write rejects symlink target. | Symlink escape test | Race windows are reduced by checks/atomic replace, not formally proven. |
| Atomic write corruption | Write temp file, flush, fsync, `os.replace`. | Atomic write test checks no temp remains | Does not replace database transaction durability for all stores. |
| Strict JSON NaN/Infinity | `json_safe` converts non-finite floats to null; `allow_nan=False`. | Property scorecard strict JSON test | Upstream callers must avoid bypassing model/helper serializers. |
| DSL lookahead aliases | Validator rejects `future_`, `next_`, `_next`, `fwd_`, `_fwd`, `t_plus`, `lead`. | DSL adversarial tests | New alias families require future rule updates. |
| Formula injection via dynamic builtins/import tricks | AST parser only; no eval/exec/importlib/subprocess/shell; custom Semgrep rules. | DSL monkeypatch tests and Semgrep | Static rules are scoped; not proof against every Python misuse elsewhere. |
| API cross-artifact schema confusion | Endpoint-specific suffix and expected `schema_version`; mismatch hidden as 404. | API injection extreme test | Requires artifact writers to preserve schema_version. |
| API IDOR/enumeration-like behavior | Identifier regex, root-relative path, schema-hiding 404. | API extreme artifact ID tests | Existing artifact IDs are still discoverable if users know them; auth remains required by host app. |
| Query/header injection | Query/header values ignored for artifact payload decisions. | Header/query forge tests | Reverse proxy behavior not tested with a live server. |
| Secret value leakage | Recursive key/value redaction for tokens, bearer lines, `sk-` values. | Secret leakage extreme tests | New secret formats require redaction rule updates. |
| Local absolute path leakage | Windows/local path redaction in metadata/report/API/CLI/Markdown. | Secret leakage extreme tests | POSIX path redaction is key-aware to avoid over-redacting URLs. |
| Ledger hash-chain state coverage | SQLite WAL append table, previous/entry hash, verify chain. | Property hash-chain and tamper tests | External backup/retention remains operator concern. |
| Constant rank IC warning/edge behavior | Skip constant factor/return cross sections before correlation. | Property IC tests, golden scorecard | Synthetic coverage; real panels may reveal additional edge cases. |
| Synergy column collision | Collision-resistant candidate column naming. | Synergy/crowding tests | Portfolio model remains fixture-level and simplified. |
| Architecture import boundary | AST/static import checks and import smoke without sockets/log handler changes. | Architecture invariants test | Scope is AGS modules; whole-repo architecture drift needs broader CI. |
| Performance/resource budgets | Fixture runtime and JSON size budgets for DSL, scorecard, ledger. | Performance acceptance budget test | Budgets are local fixture budgets, not production-scale guarantees. |

## I. What Was Not Fully Covered

- Native Windows cannot run `mutmut`; mutation score gate was not executed.
- WSL is unavailable locally, so WSL/Linux-only mutation testing was not run.
- Full Linux CI was not verified locally.
- A real upstream GitHub PR was not created locally because `gh`/GitHub token/PR connector were unavailable; only the compare link exists.
- Semgrep registry scan had unrelated timeout warnings in legacy CLI taint rules (`agent/cli/_legacy.py`); there were no findings and exit status was 0.
- Real API server integration was not launched; API coverage used FastAPI `TestClient` and OpenAPI snapshots.
- Frontend image/paste/report UI tests were added and recorded as run in the final test results, but the `scripts/ags_p0_acceptance.ps1` backend acceptance script does not run frontend tests.
- Tests use synthetic/deterministic fixtures. They validate security, determinism, contracts, and regression behavior; they do not prove real-world market alpha.
- Security scans, type checks, and tests reduce risk; they cannot prove the absence of vulnerabilities.
- PIT data adapters and real financial data quality are explicitly incomplete in this package.
- The forward tracking store is append-only, but production backup, retention, and operational monitoring are still operator responsibilities.

## J. Commit Hygiene

The following should be included in the branch/PR:

- Production hardening fixes under `agent/src/alpha_foundry`, `agent/src/alpha_quality`, `agent/src/research_ledger`, `agent/src/api`, `agent/cli`, and the small frontend security helper.
- Security tests, including API injection, artifact path safety, static Semgrep rule contract, redaction, hidden surface, upload/paste/cache, CLI, and return-value tests.
- Property tests for forward returns, rank IC, strict JSON, frozen factor output, and trial ledger hash chain.
- Golden master scorecard fixture because it is small, deterministic, and sanitized.
- Custom Semgrep rules in `security/semgrep/ags-python-injection.yml`.
- `scripts/ags_p0_acceptance.ps1` as the one-command local acceptance gate.
- Documentation updates explaining acceptance, security review, limitations, rollback, performance, and evidence.
- `pyproject.toml` dev/test dependency additions because reviewers need the same tools to reproduce the gates. If maintainers prefer a lighter default dev extra, split these into a security extra or `requirements-security.txt`.

The following should remain excluded:

- `.tmp`
- Generated SBOM such as `.tmp/ags-sbom.cdx.json` unless the project explicitly wants committed SBOMs
- Raw Semgrep/Bandit/pip-audit/Safety reports unless requested
- Local caches: `.pytest_cache`, `.mypy_cache`, `.ruff_cache`
- Coverage HTML
- Virtualenvs and downloaded scanner binaries
- Private data, large/private real market data snapshots, OAuth caches, broker exports, local notebooks, and secrets
- Any output containing absolute local paths, token material, or API keys

Current branch diff contains no generated artifacts by the classification command.

## K. Reviewer-Facing PR Summary

Title:

```text
test(alpha): add AGS extreme acceptance gates and harden security boundaries
```

Body:

```markdown
## Goal

Add an extreme acceptance/security pass for AGS v3.1 current-main-safe, covering artifact path safety, formula/DSL injection boundaries, read-only API schema binding, redaction, ledger integrity, statistic edge cases, type gates, and performance budgets.

## What changed

- Added `safe_artifact_path` and `safe_artifact_write_json` with traversal, symlink, NUL, Unicode-dot, strict JSON, redaction, fsync, and atomic replace behavior.
- Hardened the DSL parser/validator/evaluator against future aliases, code-shaped payloads, bare non-AST formulas, dynamic execution bypasses, and DataFrame/scalar misuse.
- Bound Alpha Genesis API endpoints to expected artifact `schema_version` values and kept the API GET-only.
- Expanded shared redaction for sensitive keys, secret-like values, `sk-` tokens, bearer lines, and local absolute paths.
- Strengthened trial ledger hash-chain/property coverage and kept append-only semantics.
- Fixed constant rank-IC edge handling and type-checker data-flow issues.
- Fixed synergy candidate column-name collision risk.
- Added custom Semgrep rules and a local Windows P0 acceptance script.

## Security impact

This reduces risk around path traversal, formula injection, API schema confusion, forged decision payloads, secret/local path leakage, ledger tampering, and architecture drift. It does not prove the absence of all vulnerabilities.

## Safety impact

Live/order/broker impact: none expected. The AGS work remains read-only and research-scoped. No `AgentLoop`, `AgentContext`, `ToolRegistry`, `SessionService`, broker connector, mandate, order gate, or kill-switch path was modified.

## Tests added

- Security: artifact path safety, API injection, secret leakage, custom Semgrep rule contract.
- Property: forward return identity, bounded rank IC, strict JSON, frozen factor output, ledger hash chain.
- Golden: scorecard golden master fixture.
- Contracts: AGS architecture invariants and GET-only OpenAPI.
- Performance: DSL, scorecard, and ledger fixture budgets.

## Tests run

- `scripts\ags_p0_acceptance.ps1`: passed.
- Focused pasted-text-4 pytest: 53 passed, 1 warning.
- Wide AGS regression: 132 passed, 1 warning.
- Factor purity/lookahead: 915 passed, 5 skipped, 12 warnings.
- `mypy --strict`: success, no issues in 51 source files.
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Custom Semgrep: 50 files, 3 rules, 0 findings.
- Semgrep registry: 187 rules, 82 files, 0 findings; two unrelated legacy CLI taint-rule timeout warnings, no findings, exit 0.
- Bandit: AGS scope passed.
- pip-audit: no known vulnerabilities found.
- Safety: 267 packages, 0 vulnerabilities.
- CycloneDX: SBOM generated to `.tmp/ags-sbom.cdx.json`, not committed.
- gitleaks: production AGS/API/CLI paths 0 leaks.
- trufflehog: production AGS/API/CLI paths 0 verified/unknown secrets.
- `pip check`: no broken requirements found.

## Tests not run and why

- `mutmut` mutation testing was not run because native Windows is unsupported by the tool.
- WSL/Linux checks were not run because WSL is unavailable locally.
- A live API server integration run was not launched; API tests use FastAPI `TestClient`.

## AGENTS/ExecPlan compliance

- AGS remains current-main compatible and additive.
- `run_bench` is preserved; AGS adds `run_bench_with_scorecard`.
- No live trading write surface was added.
- Alpha Genesis API is GET-only.
- Formula handling is AST/DSL based and does not use eval/exec/importlib/subprocess/shell.
- Reports and API responses redact secret-like values and local paths.

## Known limitations

- Synthetic fixtures do not prove real-world market alpha.
- Security scans reduce risk but cannot prove absence of vulnerabilities.
- PIT production data adapters remain incomplete.
- Full Linux CI and mutation score gates should run upstream.

## Rollback path

Revert this branch or revert the focused AGS commits. The implementation is concentrated under `agent/src/alpha_foundry`, `agent/src/alpha_quality`, `agent/src/research_ledger`, `agent/src/api/alpha_genesis_routes.py`, `agent/cli/alpha_genesis.py`, tests, docs, the Semgrep rule file, and the acceptance script. No live/order safety stack should need rollback.

## Suggested review focus

- Artifact path safety and redaction helper behavior.
- DSL parser/validator boundaries and operator execution paths.
- API schema binding and GET-only contract.
- Ledger append/hash-chain semantics.
- Whether security tooling should remain in `dev` extra or move into a dedicated security extra.

Signed-off-by: <name> <email>
```

## L. Final Recommendation

The branch is ready to open as a PR from `codex/ags-v31-main`, with the caveat that the local environment could not create the PR automatically. Use the compare URL to create the PR manually or run PR creation from an authenticated GitHub CLI/session.

This can be one PR if reviewers are prepared to review the AGS v3.1 package as an integrated acceptance/security pass. If maintainers prefer smaller review units, split it into:

1. Core AGS production modules and demos.
2. Extreme acceptance/security gates and dependency/tooling changes.
3. Frontend/report/cache redaction and documentation.

The tests are part of the deliverable and should be committed. In particular, security acceptance gates, property tests, golden master fixtures, architecture invariants, adversarial API/secret/path tests, and performance budgets are the regression guardrail for this work.

Reviewers should focus on the artifact path helper, shared redaction rules, DSL evaluator boundary, API schema binding, ledger append/hash-chain design, statistical edge-case handling, and whether the dev extra should be split to reduce default maintainer burden.

Next recommended step after PR creation: let CI run on Linux, add a mutation-testing job or WSL/Linux `mutmut` run if maintainers want mutation score evidence, and decide whether to move heavyweight security tools into a dedicated optional security dependency group.

## Concise Terminal Summary

```text
report path: docs/ags-v31-extreme-acceptance-summary.md
total changed files against main: 195 post-report (194 evidence baseline + this report)
core production/application files changed: 57
demo/example files changed: 42
test files/fixtures changed: 68 (63 backend + 5 frontend)
docs changed: 25 post-report
tools/scripts changed: 3
generated artifacts committed: 0

commands run/inspected:
- git branch --show-current
- git status --short --branch
- git log --oneline -5
- git ls-remote origin refs/heads/codex/ags-v31-main
- git diff --name-status main...HEAD
- git diff --stat main...HEAD
- git diff --name-only main...HEAD
- git show --stat --oneline --summary HEAD
- git rev-parse HEAD
- git rev-parse origin/codex/ags-v31-main
- git remote -v
- targeted control-doc, code, test, script, pyproject reads
- static forbidden-runtime and dynamic-execution boundary searches

pass/fail summary:
- scripts\ags_p0_acceptance.ps1: passed
- focused pytest: 53 passed, 1 warning
- wide AGS regression: 132 passed, 1 warning
- factor purity/lookahead: 915 passed, 5 skipped, 12 warnings
- mypy strict: success, 51 source files
- pyright: 0 errors, 0 warnings, 0 informations
- custom Semgrep: 0 findings
- Semgrep registry: 0 findings, two unrelated legacy timeout warnings
- Bandit/pip-audit/Safety/gitleaks/trufflehog/pip check: passed/no findings as recorded

limitations:
- no local PR was created; compare link only
- local verification is Windows based
- WSL unavailable
- mutmut not runnable on native Windows
- no local Linux CI verification
- real API server not launched
- synthetic fixtures do not prove real market alpha
- scans do not prove absence of vulnerabilities
```

- [x] Branch and remote verified
- [x] Changed files classified
- [x] Production hardening summarized
- [x] Tests mapped to risks
- [x] Actual command outputs recorded
- [x] Limitations recorded
- [x] Commit hygiene reviewed
- [x] PR body drafted
- [x] No unsupported security claims made
