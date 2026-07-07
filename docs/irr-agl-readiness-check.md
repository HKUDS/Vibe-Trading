# IRR-AGL Phase 0.5 Readiness Check

Date: 2026-07-06
Branch: `phase/00-readiness-gate`
Status: Implementation readiness gate

## Scope

Phase 0.5 verifies the local environment and repository contract before Phase 1
adds the artifact store. This phase intentionally changes no runtime behavior.
It adds a readiness document and an environment-contract test only.

## Required Preflight

Executed on Windows PowerShell from `D:\Vibe-Trading`:

```powershell
git status --short
git branch --show-current
.\.venv\Scripts\python.exe -c "import pydantic, scipy; print(pydantic.VERSION); print(scipy.__version__)"
.\.venv\Scripts\python.exe -X utf8 agent/scripts/dump_tool_inventory.py
.\.venv\Scripts\python.exe -X utf8 -m pytest agent/tests/test_tool_inventory_smoke.py -q
```

Observed baseline:

- Worktree was clean before Phase 0.5 edits.
- Current phase branch is `phase/00-readiness-gate`.
- Pydantic is importable with major version `2`.
- SciPy is importable.
- Phase 0 tool inventory emits stable governance fields.
- Phase 0 inventory smoke tests pass.

## Repository Surfaces Checked

Readiness review covered the required Phase 0.5 surfaces:

- `pyproject.toml`
- `AGENTS.md`
- `docs/reliability-governance-rfc.md`
- `agent/cli/`
- `agent/src/agent/tools.py`
- `agent/src/agent/trace.py`
- `agent/backtest/run_card.py`
- `agent/backtest/loaders/registry.py`
- `agent/src/live/`
- `agent/src/tools/mcp.py`
- `agent/mcp_server.py`
- `.github/workflows/test.yml`

Important invariants remain unchanged:

- `BaseTool.execute(**kwargs) -> str`
- `ToolRegistry.execute(name, params) -> str`
- `DataLoaderProtocol.fetch(...) -> dict[str, DataFrame]`
- Explicit `local` data source requests do not fall back to network sources.
- Live write tools remain gated by mandate, expiry, kill switch, intent parsing,
  limits, and `LiveOrderGuardTool`.
- MCP SSE/HTTP shell exposure remains stricter than stdio.
- Run card JSON continues to use strict JSON output with non-finite values
  normalized before serialization.

## Environment Contract Baseline

Phase 0.5 records the configuration contract that Phase 1 and Phase 3 will turn
into runtime modules:

- `VIBE_TRADING_RELIABILITY_MODE` accepts `off`, `observe`, `warn`, `enforce`.
- `VIBE_TRADING_GOVERNANCE_MODE` accepts `off`, `observe`, `warn`, `enforce`.
- Default artifact root resolves under `~/.vibe-trading/artifacts`.
- Default research ledger path resolves under
  `~/.vibe-trading/research-ledger/ledger.sqlite`.
- Environment overrides can point those paths elsewhere.
- Windows-style environment path expansion is covered by a smoke test on
  Windows, with a POSIX equivalent used on non-Windows CI.
- The current CLI package is discoverable through the configured Python path.

The parser used in this phase is test-local on purpose. Phase 1 should introduce
`agent/src/reliability/config.py`; Phase 3 should introduce
`agent/src/governance/config.py`.

## Acceptance

Targeted checks for this phase:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest agent/tests/reliability/test_environment_contract.py agent/tests/test_tool_inventory_smoke.py -q
```

No real LLM, broker, external MCP server, or real external market-data service is
required.

## Rollback

Rollback is limited to deleting:

- `docs/irr-agl-readiness-check.md`
- `agent/tests/reliability/test_environment_contract.py`

No database, artifact root, runtime config, live mandate, API response, MCP
schema, loader, or ToolRegistry rollback is required because Phase 0.5 does not
change runtime code.
