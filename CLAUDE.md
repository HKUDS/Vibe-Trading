# CLAUDE.md — Vibe-Trading (isolated research fork)

This fork (`Alexanderr003/Vibe-Trading`) is **Xander's ISOLATED research lab** built on
[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading). It is a **hypothesis factory**:
alphas, factors and strategy research. It is **NOT** a live-trading deployment and it is
**completely separate from the OLIMPO project** (different repo, different machine, different keys).

## Session start (mandatory, every session)

1. Activate skills via the Skill tool: `crypto-agent-protocol` (session process) and
   `vibe-lab-agent` (project role & domain rules). Both live in `.claude/skills/`.
2. Read `handoff.md` (volatile state: what happened last session, next steps).
3. Read `MEMORY.md` (durable invariants I-V* and resolved failures — never reopen one).

## Golden rules (full text + evidence in MEMORY.md)

- **I-V1** Total isolation from OLIMPO: never the same machine/env, never OLIMPO's secrets,
  never the OLIMPO Hetzner box.
- **I-V2** No live broker/execution connectors, ever. Data + backtest + paper/shadow only.
- **I-V3** One-way flow: outputs here are HYPOTHESES → re-validated in OLIMPO's own backtester
  before anything touches a money-path. No HKUDS code imported into OLIMPO.
- **I-V6** Fork hygiene: fork-local scaffolding (this file, `.claude/skills/`, `handoff.md`,
  `MEMORY.md`, `DEPLOY_ISOLATED.md`) never goes upstream.
- **I-V7** Paper-first, permanently: this project never executes real money.

## Working in this repo

- Python env: `.venv/` at repo root (`python3 -m venv .venv && .venv/bin/pip install -e .`).
- CLI: `.venv/bin/vibe-trading` (`run`, `serve`, `alpha`, `data`, `chat`, `init`, …).
- API server: `.venv/bin/vibe-trading serve --port 8899` → `GET /health`.
- Dev servers (backend 8899 + frontend 5899): `scripts/dev up` / `status` / `logs` / `stop`.
- Frontend: `cd frontend && npm install && npm run build` (Vite, React 19).
- Tests (offline, CI-parity): `.venv/bin/python -m pytest agent/tests/<file> -q`.
- Config/secrets: `agent/.env` (git-ignored) — template in `agent/.env.example`.
  LLM provider keys are the service's own; never OLIMPO's.

## Environment notes

- Remote session sandboxes have RESTRICTED egress: yfinance / Binance / Kraken return 403
  (verified 2026-07-12). Develop and run the offline test suite here; live data pulls happen
  on the isolated VM (see `DEPLOY_ISOLATED.md`) or a GitHub Actions runner.
- Upstream sync: `main` tracks HKUDS/Vibe-Trading; scaffolding lives on the working branch.

## Language convention

Conversation with Xander: Spanish. Code, comments, commits, PRs: English.
`handoff.md` / `MEMORY.md` / `DEPLOY_ISOLATED.md`: Spanish (operator-facing).
