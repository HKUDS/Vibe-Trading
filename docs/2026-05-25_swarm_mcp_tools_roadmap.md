# 2026-05-25 SWARM External MCP Tools Roadmap

Status: implemented. M1-M5 landed in `bb7f2ff`; M6 is the documentation closeout that links README, this roadmap, and the TDD matrix.

## Summary

Vibe-Trading already supports two MCP directions:

1. **Out-bound (server)** — `agent/mcp_server.py` exposes Vibe-Trading tools to any MCP client.
2. **In-bound (client, main agent path)** — `build_registry(agent_config=...)` lets the built-in agent load tools from external MCP servers (delivered in `2026-05-08_mcp_client_integration_roadmap.md`).

This roadmap covers a **third direction**, currently blocked by an explicit TODO at [agent/src/swarm/worker.py:313-316](../agent/src/swarm/worker.py#L313-L316):

> Let SWARM analyst-team workers (the agents inside `run_swarm`) call enterprise-internal MCP tools — `search`, knowledge-base lookup, internal data lake — when Vibe-Trading is itself fronted as an MCP service.

Without this, an external caller of `mcp_server.py::run_swarm` can drive the analyst team but the analysts can only use local Python tools shipped in the repo. They cannot reach enterprise data sources behind their own MCP servers.

| Item | Decision |
| --- | --- |
| Entry points | `mcp_server.py::run_swarm` + CLI swarm runner |
| Transport (initial) | stdio + streamableHttp (reuse `MCPServerConfig`) |
| Surface | tools only (skills stay file-based) |
| Trust model | server-side allowlist, **never** caller-supplied URLs |
| Existing in-bound MCP client | unchanged |
| Existing out-bound MCP server | unchanged |

## Why This Work Is Needed

The default analyst-team presets (`investment_committee`, `quant_strategy_desk`, …) are good at public-market reasoning but **cannot ground their conclusions in enterprise context**:

- internal research notes / IC memos
- proprietary alt-data feeds
- private-deal pipelines
- internal compliance / restricted-list checks
- regulated-content corpora a desk has licensed

Enterprise users currently route this data through their own MCP servers and want the SWARM analysts to query it the same way the rest of their AI tooling does.

The main agent path already supports this. SWARM is the deliberately-excluded path; the TODO has been there since v1 because the trust model and config propagation needed an explicit design pass — this roadmap is that pass.

## Scope

| Included in v1 | Excluded from v1 |
| --- | --- |
| Server-side static MCP allowlist (env / config file) | Caller-supplied MCP server URLs |
| stdio + streamableHttp | sse (transport rarely used internally) |
| Remote MCP tools available to swarm workers via preset YAML `tools:` list | Per-call dynamic tool registration |
| Per-agent tool whitelisting honored across local + remote tools | Per-agent MCP server scoping (all-or-nothing in v1) |
| Audit log of remote tool calls (already in `events.jsonl`) | Tool-call diffing / approval gates |
| Regression tests against a fake MCP server | Production load testing |

## Why The Trust Model Matters

The SWARM is invoked from `mcp_server.py::run_swarm`, which is itself reachable by any MCP client wired into Vibe-Trading's stdio or SSE transport. If the `run_swarm` schema accepted MCP server URLs directly, **any caller could turn the swarm into an SSRF cannon** — analyst workers running on operator infrastructure would dial out to attacker-controlled endpoints with whatever credentials the host process holds.

V1 therefore takes the conservative stance:

- The **operator** declares which MCP servers analysts may reach (via env var / config file at server boot).
- The **caller** can only invoke pre-blessed tools by name — same UX as today's local tools.
- A future v2 may add caller-scoped overlays, but only behind explicit auth and per-tool side-effect tagging.

## Proposed Design

### Config Surface

Reuse the existing `AgentConfig` / `MCPServerConfig` already used by the main agent path ([agent/src/config/schema.py](../agent/src/config/schema.py)).

Boot-time resolution order for SWARM:

| Priority | Source |
| --- | --- |
| 1 | env var `VIBE_TRADING_SWARM_AGENT_CONFIG` (path to JSON) |
| 2 | `~/.vibe-trading/swarm-agent.json` |
| 3 | `~/.vibe-trading/agent.json` (fallback to main agent config) |
| 4 | empty (current behavior — local tools only) |

A separate file is preferred so operators can give the swarm a strict subset of what the interactive agent can reach (typically: read-only data tools, no write/exec tools).

### Runtime Plumbing

Three thread-through points:

1. `mcp_server.py::main` resolves boot config once and stores on the module.
2. `SwarmRuntime.__init__` accepts an `agent_config: AgentConfig | None`; threaded through `start_run` → `_execute_run` → `_run_worker_with_retries` → `run_worker`.
3. `run_worker` calls a new `build_swarm_registry(agent_spec.tools, agent_config=..., include_shell_tools=...)` that fall-through-merges remote MCP tools, then filters by the agent's whitelist.

The TODO at `worker.py:313-316` is removed once point 3 lands.

### Preset YAML Extension

Existing presets keep working unchanged. To grant a remote MCP tool to an agent, the preset author writes the **local naming-convention** name (already used by [agent/src/tools/mcp.py:128-138](../agent/src/tools/mcp.py#L128-L138)):

```yaml
agents:
  - id: bull_advocate
    tools: [bash, read_file, write_file, load_skill, factor_analysis,
            mcp_internal_kb_search,            # NEW: from internal KB MCP server
            mcp_internal_kb_fetch_doc]
```

If a referenced `mcp_*` name is **not** in the boot allowlist, the worker logs `Requested tool 'mcp_xxx' is unavailable and was dropped` (existing behavior in `build_filtered_registry`) — preset stays loadable, that single tool is just absent.

### Audit & Observability

No new event types needed. Remote MCP tool calls already flow through `MCPRemoteTool.execute` → `registry.execute` → the worker loop's existing `tool_call` / `tool_result` events. Tests verify the events carry `server` + `remote_tool` fields so post-hoc audits can distinguish local vs remote calls.

## Milestones

| ID | Milestone | Exit Criteria |
| --- | --- | --- |
| M1 | Config plumbing | `SwarmRuntime` accepts `agent_config`; `run_worker` receives it; existing tests still green |
| M2 | Registry assembly | New `build_swarm_registry()` merges remote MCP tools then filters by `agent_spec.tools`; unit-tested against a fake adapter |
| M3 | Boot wiring | `mcp_server.py` and CLI swarm runners load the swarm-agent.json (with main-agent.json fallback); env override honored |
| M4 | Preset extension test | A test preset references `mcp_*` tools, runs end-to-end against a fake MCP stdio server, evidence appears in events.jsonl |
| M5 | Trust-model regression | A unit test asserts that `run_swarm()` MCP entry point exposes **no field** that lets a caller inject an MCP server URL or override the allowlist |
| M6 | Docs | README section + this roadmap promoted from draft to implemented status |

## Risks & Open Questions

| Risk | Mitigation |
| --- | --- |
| Remote MCP server hangs hold up a swarm layer past the deadline | Existing `tool_timeout` on `MCPServerConfig` (default 30s); layer-deadline already enforces upper bound |
| Token-cost blow-up if a preset author adds dozens of `mcp_*` tools | `enabled_tools` allowlist on each `MCPServerConfig` already constrains discovery; preset's per-agent whitelist constrains exposure |
| Different swarm workers on the same run double-call expensive remote tools | Out of scope for v1 (same as today's local-tool fan-out); revisit if it shows up in prod |
| Operator misconfigures a write-capable MCP server into the swarm allowlist | Document the read-only convention clearly; no programmatic enforcement in v1 |

## Out of Scope (Explicit Non-Goals)

- Letting the calling MCP client pass MCP server URLs into `run_swarm`.
- Per-agent or per-task MCP server scoping (all swarm workers on a run share the boot allowlist).
- SSE transport (no internal demand yet).
- Skill loading from remote MCP servers (skills stay local file-based).

## References

- Source TODO that gates this work: [agent/src/swarm/worker.py:313-316](../agent/src/swarm/worker.py#L313-L316)
- Existing in-bound MCP integration: [docs/2026-05-08_mcp_client_integration_roadmap.md](2026-05-08_mcp_client_integration_roadmap.md)
- SSE follow-up for the main agent path: [docs/2026-05-16_mcp_sse_integration_roadmap.md](2026-05-16_mcp_sse_integration_roadmap.md)
- Schema: [agent/src/config/schema.py](../agent/src/config/schema.py)
- Local MCP wrapper: [agent/src/tools/mcp.py](../agent/src/tools/mcp.py)
