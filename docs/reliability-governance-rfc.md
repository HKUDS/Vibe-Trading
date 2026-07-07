# IRR-AGL Reliability Governance RFC

Date: 2026-07-05
Branch: `phase/00-rfc-tool-inventory`
Status: Phase 0 baseline

## Purpose

This RFC turns the IRR-AGL architecture baseline in `AGENTS.md` into the first
reviewable implementation checkpoint for Vibe-Trading. Phase 0 does not change
runtime behavior. It records repository facts, exposes a local tool inventory,
and defines the minimum guardrails for later reliability, governance, protocol,
scorecard, eval, and Research Card work.

The core principle is unchanged: improve the existing system through wrappers,
adapters, audit extensions, and read-only surfaces. Do not replace the current
Agent loop, `BaseTool`, `ToolRegistry`, loader registry, backtest engines, MCP
transport, live mandate, kill switch, or `LiveOrderGuardTool`.

## Phase 0 Scope

Phase 0 adds only three review artifacts:

- `docs/reliability-governance-rfc.md`: this RFC.
- `agent/scripts/dump_tool_inventory.py`: a read-only local inventory script.
- `agent/tests/test_tool_inventory_smoke.py`: smoke tests for the inventory
  contract.

The inventory script builds the existing local registry and records metadata.
It never calls `ToolRegistry.execute()` and never calls a tool's `execute()`
method.

## Non-Goals

Phase 0 does not implement:

- `ArtifactStore`.
- `AuditedDataLoader`.
- `PITChecker`.
- `GovernedToolRegistry`.
- `PolicyEngine`.
- `BudgetManager`.
- `ResearchProtocol`.
- `TrialLedger`.
- `QuantReliabilityScorecard`.
- `ResearchCard`.
- UI or API panels.
- Any live trading, shell execution, MCP remote discovery, scheduler, swarm, or
  externally reachable server behavior.

Those capabilities belong to later `phase/*` branches and must remain
feature-flagged, independently testable, and mergeable through
`integration/irr-agl`.

## Repository Facts To Preserve

The following public interfaces remain unchanged:

```python
BaseTool.execute(**kwargs) -> str
ToolRegistry.execute(name, params) -> str
DataLoaderProtocol.fetch(
    codes,
    start_date,
    end_date,
    interval="1D",
    fields=None,
) -> dict[str, DataFrame]
```

The following safety boundaries remain authoritative:

- Shell-capable tools stay behind explicit opt-in.
- File tools stay constrained by existing path allowlists.
- URL/media readers keep SSRF protections.
- Generated backtest subprocesses do not inherit LLM, broker, or live secrets.
- `local:` data sources must not silently fall back to network sources.
- Live orders remain gated by mandate, kill switch, broker classification, and
  `LiveOrderGuardTool`.
- `commit_mandate()` remains outside the agent tool registry.

## Tool Inventory Contract

The Phase 0 inventory emits one row per currently available local tool with
these fields:

```text
name
module
class_name
is_readonly
repeatable
surface_guess
risk_guess
```

Current local inventory summary on this branch:

| Dimension | Count |
|---|---:|
| Total tools | 70 |
| `surface_guess=filesystem` | 3 |
| `surface_guess=live_connector` | 10 |
| `surface_guess=local_cli` | 2 |
| `surface_guess=local_research` | 45 |
| `surface_guess=network_data` | 10 |
| `risk_guess=R0_READ` | 26 |
| `risk_guess=R1_WRITE_LOCAL` | 21 |
| `risk_guess=R2_NETWORK` | 10 |
| `risk_guess=R3_TRADE_READ` | 8 |
| `risk_guess=R4_TRADE_WRITE` | 3 |
| `risk_guess=R5_SHELL` | 2 |

The `surface_guess` and `risk_guess` fields are intentionally heuristic in
Phase 0. They are an audit aid, not an enforcement source. Phase 3 owns the
authoritative `ToolManifest`, policy priority model, fail-safe behavior, and
R4/R5 shadow-deny enforcement.

## Initial Risk Mapping

The Phase 0 script maps tools into the IRR-AGL risk vocabulary:

| Risk | Meaning In Phase 0 |
|---|---|
| `R0_READ` | Local read-only research or analysis tool |
| `R1_WRITE_LOCAL` | Local write or state-mutating tool |
| `R2_NETWORK` | Read-only tool that may depend on network or external data |
| `R3_TRADE_READ` | Live connector account, order, position, quote, or history read |
| `R4_TRADE_WRITE` | Live connector order placement, cancellation, selection, or mutation |
| `R5_SHELL` | Shell-capable or background command execution tool |

Unknown or ambiguous tools must not be assumed safe in later phases. Phase 3
must either classify them explicitly or mark them `UNCLASSIFIED` for policy
review.

## Acceptance

Phase 0 is accepted when these commands pass:

```powershell
.\.venv\Scripts\python.exe -X utf8 agent/scripts/dump_tool_inventory.py
.\.venv\Scripts\python.exe -X utf8 -m pytest agent/tests/test_tool_inventory_smoke.py -q
```

The script may also render a Markdown table for review:

```powershell
.\.venv\Scripts\python.exe -X utf8 agent/scripts/dump_tool_inventory.py --format table
```

## Review Focus

Reviewers should verify:

- No existing registry, loader, live safety, API, UI, or README quickstart
  behavior changed.
- Inventory rows include the required governance fields.
- Shell-capable tools are visible in inventory and marked `R5_SHELL`.
- The script does not execute tools.
- The script does not require real LLM, broker, data-provider, MCP, or network
  access.
- The RFC does not claim later phases are implemented.

## Rollback

Rollback is limited to deleting the three Phase 0 artifacts:

```text
docs/reliability-governance-rfc.md
agent/scripts/dump_tool_inventory.py
agent/tests/test_tool_inventory_smoke.py
```

No database migration, feature flag migration, runtime config change, artifact
store cleanup, or UI/API rollback is required because Phase 0 has no runtime
behavior change.

## Next Branches

After Phase 0 is reviewed and merged into `integration/irr-agl`, start the next
implementation branch from `integration/irr-agl`:

```text
phase/01-artifact-store
```

Phase 1 should implement only the artifact and trace-extension foundation
described in `AGENTS.md`. It must not start Data/PIT enforcement, tool policy
enforcement, Research Protocol, Quant Scorecard, or Research Card UI work.
