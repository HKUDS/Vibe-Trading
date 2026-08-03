# Vibe-Trading — Repo Improvement Plan

> Exhaustive whole-repo review — August 2, 2026.
> Goal: make the repo the best version of what it does. Prioritized, evidence-based, with
> effort/risk labels so any contributor or maintainer can pick up an item.

---

## 1. What this repo is (and its health)

**Vibe-Trading** is a natural-language finance research AI agent with causal backtesting, a
461-factor alpha zoo, 36 swarm research teams, 91 skills, a shadow-account paper-trading
layer, 12 broker connectors, 16 IM channel adapters, MCP + REST + CLI surfaces, a 5-locale
Web UI, and Docker packaging.

**Scale:** 1,362 Python files (~260k LOC) + 117 TS/TSX files (~22.5k LOC) + 396 test files
(7,084 tests passing) + a Cloudflare wiki.

**Overall health: very strong.** Independent signals:
- Security: 0 hardcoded secrets; external audit's 10 findings all closed; AST-hardened
  backtest sandbox (blocks network/subprocess/eval/os.environ/unsafe-open); SSRF guards;
  hash-locked deps; workspace root isolation. `subprocess`/`exec` usages are all sandboxed
  or test-only (`core/runner.py`, `background_tools.py`, `bash_tool.py`).
- CI: hash-verified lock check, ruff lint **and** format gates, env-var gate, compile checks,
  coverage collection, frontend build + vitest, Windows 3.14 background matrix.
- Hygiene: only 9 real TODOs in `src`, 0 bare `except:`, 0 `api_key = "..."` literals.
- Delivery cadence: daily releases with detailed news + changelog; ~90 contributor PRs/week.

**The gaps are in maintainability, enforcement depth, and observability — not fundamentals.**

---

## 2. Findings (evidence)

### 2.1 Maintainability — megafiles
| File | LOC | Note |
|---|---|---|
| `agent/cli/_legacy.py` | **5,897** | The real CLI. `cli/__init__.py` re-exports every symbol via `globals().setdefault(...)` |
| `agent/mcp_server.py` | 2,254 | 55 `@mcp.tool` registrations in one file |
| `agent/src/channels/feishu.py` | 2,299 | 16 adapters average ~1k+ LOC |
| `agent/src/agent/loop.py` | 1,878 | Core ReAct loop |
| `agent/src/channels/telegram.py` | 1,739 | |
| `agent/backtest/engines/base.py` | 1,617 | |
| `agent/backtest/enhanced_validation.py` | 1,576 | |
| `agent/src/channels/weixin.py` | 1,568 | |
| `agent/cli/main.py` | 1,459 | |
| `agent/src/agent/grounding.py` | 1,455 | |
| `frontend/src/pages/Agent.tsx` | 1,800 | Main chat page |
| `frontend/src/pages/AlphaZoo.tsx` | 1,463 | |

### 2.2 Enforcement that is measured but not enforced
- **Coverage: `fail_under = 0`** in `[tool.coverage.report]` — CI collects `--cov` + XML but a
  drop to 0% would still pass. The gate is effectively off.
- **No type-checker in CI**: 179 `# type: ignore` (mostly optional-import shims — pyright
  would handle these well). No mypy/pyright/pyright-basic step.
- **Frontend**: `strict: true` tsconfig + 60 `any` usages; **no ESLint config at all**.

### 2.3 Depth opportunities
- Backtest/metrics tests are assertion-style ("doesn't crash / returns expected"), not
  property-based. No `hypothesis` in dev deps.
- No golden/snapshot tests freezing deterministic backtest outputs → silent metric
  regressions are hard to catch.
- No performance-regression gate despite `scripts/bench_performance.py`.
- 32 `src` files still use `print()` instead of the `logging` module.

### 2.4 Platform items
- **MCP 2.0 bump unmerged** (breaking; needs lock/runtime migration) — tracked in #950.
- No structured runtime telemetry (run cards exist; no request trace IDs across
  API → agent → tool boundaries).

---

## 3. Prioritized roadmap

### Phase 0 — Quick wins (low risk, ~1–2 days, verifiable now)

| # | Item | Why | How |
|---|---|---|---|
| 0.1 | **Enforce a coverage floor** | Gate exists but `fail_under = 0` | Measure current %, then set `fail_under` (e.g., 50 → 55 → 60) in `pyproject.toml`; keep XML artifact for Codecov/badge |
| 0.2 | **Frontend ESLint + `no-explicit-any`** | No lint config; 60 `any` | Add `eslint` + `typescript-eslint` + `eslint-plugin-react-hooks`; start with warnings, flip key rules to errors |
| 0.3 | **Split `Agent.tsx` / `AlphaZoo.tsx`** | 1.8k / 1.5k LOC pages | Extract message list, tool-trail, chart-panel, and table components into `components/chat/`, `components/charts/` |
| 0.4 | **`print()` → `logging` in `src`** | 32 files | Sweep `agent/src` (keep `print` in CLI/scripts where it is the output contract); route through `src.utils` logger factory |
| 0.5 | **CI: coverage artifact + badge** | XML already emitted, unused | Upload `coverage.xml`; add badge to README; optional PR comment |

### Phase 1 — Maintainability (2–4 weeks, one item at a time, test suite as guardrail)

| # | Item | Why | Risk |
|---|---|---|---|
| 1.1 | **Decompose `cli/_legacy.py` (5.9k LOC)** | Biggest single file; blocks onboarding | Medium-high — keep `cli/__init__.py` re-export shim; rely on ~40 `test_cli_*` files |
| 1.2 | **Decompose `mcp_server.py` (2.3k LOC)** | 55 tools in one file | Medium — group registrations by domain (data/backtest/factor/live/swarm) |
| 1.3 | **Decompose `agent/loop.py` (1.9k LOC)** | Core loop hard to reason about | Medium — extract streaming, tool dispatch, trace recording, content filtering |
| 1.4 | **Split `engines/base.py` + `enhanced_validation.py`** | 1.6k LOC each; per-market rules & per-validation blocks | Medium |
| 1.5 | **Pyright basic-mode gate** | 179 `type: ignore`; catches real bugs before CI | Low-med — baseline curated list; enforce on new code; raise strictness later |

### Phase 2 — Depth & reliability (ongoing)

| # | Item | Why |
|---|---|---|
| 2.1 | **Property-based tests (`hypothesis`)** | Invariants for metrics/risk: no look-ahead, PnL = Σ trade PnL, finite JSON validation output, PSR monotonicity, risk-overlay kill-switch semantics |
| 2.2 | **Golden backtest snapshots** | Freeze deterministic outputs on small fixtures; any change to metrics must be reviewed |
| 2.3 | **CI perf smoke gate** | Keep vectorized paths vectorized; Monte Carlo 1M paths under a time budget |
| 2.4 | **Deterministic agent scenario matrix** | Extend `test_agent_loop_*` series with mock-LLM scenarios: retry storms, terminal states, filter hits, tool-call schema drift |

### Phase 3 — Platform evolution (backlog)

| # | Item |
|---|---|
| 3.1 | **MCP 2.0 migration** (finish #950: lock + runtime migration) |
| 3.2 | **Observability**: structured logging, request trace IDs across API → agent → tools, per-run metrics endpoint |
| 3.3 | **Skill-authoring SDK**: formalize skill template + validation + CI manifest check (AGENT_CONTRIBUTOR_GUIDE exists — make it executable) |
| 3.4 | **Moat depth**: property-tested PIT/look-ahead invariants in Shadow Account; more markets/connectors/skills |

---

## 4. What NOT to change (already best-in-class)

- Backtest sandbox + `core/runner.py` rlimit isolation — keep intact.
- `api_server.py` thin-assembler pattern (398 LOC) — the model other megafiles should copy.
- Hash-locked deps + lock CI check — keep.
- env-var gate + ruff lint/format gates — keep.
- README news discipline + CHANGELOG — community gold.
- i18n (5 locales) — keep parity across any UI change.

---

## 5. Suggested execution order

1. **Phase 0 (all 5)** — verifiable wins this week; each is small and independent.
2. **Phase 1.2 → 1.3 → 1.4 → 1.1** — decompose in increasing risk; run full suite (7,084) after each.
3. **Phase 1.5** (pyright) in parallel with 1.x — lower priority than the splits.
4. **Phase 2** items land alongside feature work (they guard the moat).
5. **Phase 3.1** (MCP 2.0) whenever the lock migration can be scheduled; 3.2–3.4 are backlog.
