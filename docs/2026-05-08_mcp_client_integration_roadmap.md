# 2026-05-08 MCP Client Integration Roadmap

## Summary

Vibe-Trading already exposes tools as an MCP server.
This roadmap covers the opposite direction: letting the built-in agent load tools from external MCP servers.

The first release stays intentionally narrow to reduce risk and keep review scope clear.

| Item | Decision |
| --- | --- |
| Entry points | CLI + SessionService |
| Transport | stdio only |
| Surface | tools only |
| MCP execution | serial only |
| Existing MCP server | unchanged |

## Why This Work Is Needed

Today, the built-in agent can only use local tools.
That blocks users from registering external MCP servers and reusing remote tools inside the normal Vibe-Trading runtime.

Nanobot already has a solid MCP client implementation. The goal here is to reuse its strongest ideas without rewriting Vibe-Trading's synchronous agent loop.

## Scope

| Included in v1 | Excluded from v1 |
| --- | --- |
| user-level MCP config file | resources |
| stdio MCP client adapter | prompts |
| MCP tool wrapper | SSE |
| CLI integration | streamable HTTP |
| SessionService integration | hot reload |
| timeout / retry / logging | parallel MCP execution |
| regression coverage | Web UI MCP config management |

## Proposed Design

### Config Model

Use a structured config file instead of `.env`.

Recommended path:

- `~/.vibe-trading/agent.json`

Priority order:

| Priority | Source |
| --- | --- |
| 1 | `session.config` override |
| 2 | user config file |
| 3 | empty defaults |

Proposed MCP config shape:

| Field | Purpose |
| --- | --- |
| `mcpServers` | top-level MCP server map |
| `type` | transport type |
| `command` | stdio command |
| `args` | command args |
| `env` | extra env vars |
| `toolTimeout` | per-tool timeout |
| `enabledTools` | allowlist |

HTTP-related fields may remain in schema for future support, but non-stdio transports should be rejected in v1.

### Runtime Assembly

The MCP integration point should stay at the registry composition layer.

Runtime flow:

1. Load agent config
2. Build the local tool registry
3. Connect to configured MCP servers
4. Wrap remote MCP tools as local tools
5. Inject them into the registry
6. Run `AgentLoop` with the final registry

This keeps MCP support out of the core reasoning loop.

### MCP Tool Wrapper

Remote tools should be exposed with stable names:

- `mcp_<server>_<tool>`

The wrapper should reuse the most valuable nanobot ideas:

| Area | Reuse |
| --- | --- |
| naming | stable MCP tool prefix |
| schema handling | nullable schema normalization |
| retry | single retry for transient errors |
| timeout | per-tool timeout |
| ordering | local tools first, MCP tools after |

The wrapper should present a synchronous local tool interface even if the MCP SDK is async internally.

When two raw MCP server names sanitize to the same local `mcp_<server>_<tool>`
prefix, v1 should keep the current ASCII-safe naming rules and append a
deterministic hash suffix at the server-segment level so tool names remain
stable and unique.

### Serial Execution Strategy

All MCP tools should be treated as serial tools in v1.

Reason:

| Choice | Why |
| --- | --- |
| serial MCP execution | avoids event loop and thread-safety issues |
| no parallel readonly path | safer fit for the current synchronous runtime |
| narrow first release | easier to review and debug |

This is an explicit design choice, not a temporary accident.

### Failure Model

Failure should be isolated per server.

| Failure Case | Expected Behavior |
| --- | --- |
| missing config file | use empty config |
| invalid config file | warn and fall back |
| one MCP server fails to start | skip that server |
| one MCP server fails to initialize | keep local tools and other MCP servers available |
| one MCP tool times out | return normalized tool error |

## Implementation Roadmap

| Phase | Focus | Deliverables |
| --- | --- | --- |
| Phase 1 | Config foundation | config schema, loader, path helpers, precedence rules |
| Phase 2 | MCP client adapter | stdio connection, MCP wrapper, schema normalization, timeout, retry |
| Phase 3 | Registry integration | local + MCP registry assembly, stable tool ordering |
| Phase 4 | Entry-point integration | CLI wiring, SessionService wiring, session override support |
| Phase 5 | Docs and validation | docs, examples, regression coverage |

## Likely Files

| Area | Files |
| --- | --- |
| Core runtime | `agent/src/agent/loop.py`, `agent/src/agent/tools.py`, `agent/src/tools/__init__.py`, `agent/src/tools/mcp.py` |
| Entry points | `agent/cli.py`, `agent/src/session/service.py`, `agent/api_server.py` |
| Dependencies | `pyproject.toml`, `agent/requirements.txt` |
| Docs | `README.md`, `agent/SKILL.md` |

## Acceptance Criteria

- [ ] CLI agent runs can load tools from external stdio MCP servers
- [ ] SessionService runs can load tools from external stdio MCP servers
- [ ] Remote tools appear with stable `mcp_<server>_<tool>` names
- [ ] `enabledTools` filtering works
- [ ] MCP tools never enter the current parallel readonly path
- [ ] Broken MCP servers degrade safely without breaking local tools
- [ ] Missing or invalid config files fall back safely
- [ ] Existing MCP server mode does not regress

## Test Plan

| Layer | Coverage |
| --- | --- |
| Unit | config schema, loader fallback, naming, schema normalization, timeout, retry |
| Integration | fake stdio MCP server: success, timeout, transient failure, bad schema |
| Entry-point | CLI path + SessionService path |
| Regression | no-config behavior, local tool registry, shell tool policy, existing MCP server mode |

## Key Review Points

| Topic | Core Point |
| --- | --- |
| separate JSON config | MCP servers are structured runtime config, not flat env vars |
| serial execution | safest first step for correctness and maintainability |
| stdio-only v1 | smallest complete integration surface |
| Python docstrings | all new Python methods should include repository-style docstrings |

## Nanobot References

The following nanobot areas should be used as implementation references:

- `nanobot/config/schema.py`
- `nanobot/config/loader.py`
- `nanobot/config/paths.py`
- `nanobot/agent/tools/mcp.py`
- `nanobot/agent/tools/registry.py`

## Outcome

This roadmap adds a minimal but complete MCP client path to Vibe-Trading.
It reuses nanobot's strongest implementation ideas while staying compatible with Vibe-Trading's current synchronous architecture.

## Implementation Checklist

### Cross-Cutting Requirement

- [ ] All new Python methods introduced by this roadmap include repository-style docstrings with `Args`, `Returns`, and `Raises` when applicable

### Phase 1 - Config Foundation

- [x] Add an agent-level config schema for MCP settings
- [x] Add a config loader with safe fallback on missing or invalid files
- [x] Add path helpers rooted at `~/.vibe-trading`
- [x] Define merge order: `session.config` > user config file > defaults
- [x] Reject non-stdio transports in v1

### Phase 2 - MCP Client Adapter

- [x] Reuse the existing `fastmcp` dependency in `pyproject.toml` and `agent/requirements.txt` for MCP client support
- [x] Add stdio-only MCP connection support
- [x] Add an MCP tool wrapper with `mcp_<server>_<tool>` naming
- [x] Normalize nullable tool schemas
- [x] Add per-tool timeout handling
- [x] Add single retry for transient failures
- [x] Normalize tool error messages

### Phase 3 - Registry Integration

- [x] Extend registry assembly to inject MCP tools after local tool discovery
- [x] Keep behavior unchanged when no MCP config is present
- [x] Keep tool ordering stable: local tools first, MCP tools after
- [x] Mark MCP tools as serial-only in v1
- [ ] TODO(v1 limitation): Keep the Swarm filtered-registry path local-only. Do not propagate MCP config into Swarm until a later iteration defines Swarm-specific config loading and execution constraints.

### Phase 4 - Entry-Point Integration

- [x] Load MCP config in CLI agent runs
- [x] Load MCP config in SessionService runs
- [x] Support `session.config` overrides for API-created sessions
- [x] Surface clear warnings for skipped or failed MCP servers
- [x] Surface the same operator-facing server-name collision warning in CLI and SessionService when MCP config disambiguates sanitized server names: `Configured MCP server '<name>' collides with another server after local name normalization. Using local tool prefix 'mcp_<resolved>_<tool>' to keep generated tool names unique. Rename the server in agent config if you want a different prefix.`

### Phase 5 - Docs and Tests

- [ ] Document the new MCP client mode in `README.md`
- [ ] Document config examples and limits in `agent/SKILL.md`
- [ ] Add unit tests for config, wrapper, timeout, retry, and schema normalization
- [ ] Add integration tests with a fake stdio MCP server
- [ ] Add regression tests for no-config behavior and current MCP server mode
- [ ] Verify all acceptance criteria in this roadmap

## Phase Exit Criteria

| Phase | Done When |
| --- | --- |
| Phase 1 | config can be loaded safely and non-stdio transports are rejected |
| Phase 2 | external stdio MCP tools can be discovered and wrapped locally |
| Phase 3 | MCP tools appear in the registry without breaking local tools |
| Phase 4 | CLI and SessionService both use the same MCP loading path |
| Phase 5 | docs are updated and test coverage proves no major regression |

## PR Breakdown

The implementation should be split into small reviewable PRs.

| PR | Status | Title | Main Scope | Keep Out of Scope |
| --- | --- | --- | --- | --- |
| PR 1 | done | Config foundation | add config schema, loader, path helpers, precedence rules | MCP runtime integration |
| PR 2 | done | MCP adapter core | add stdio MCP client support, tool wrapper, timeout, retry, schema normalization | CLI and SessionService wiring |
| PR 3 | done | Registry integration | inject MCP tools into registry, stable ordering, serial-only MCP behavior | API-specific overrides |
| PR 4 | done | CLI integration | load MCP config in CLI runs, add operator-facing warnings | SessionService wiring |
| PR 5 | done | SessionService integration | load MCP config in SessionService, support `session.config` override | Web UI management |
| PR 6 | pending | Docs and hardening | docs, examples, regression tests, fake MCP server coverage | new transports or parallel MCP execution |

### PR 1 - Config Foundation

**Goal**

Create the config layer needed by all later work.

**Expected changes**

- add agent-level config schema
- add config loader with safe fallback
- add `~/.vibe-trading` path helpers
- define precedence rules
- reject non-stdio transports in v1

**Review focus**

- config shape is stable
- fallback behavior is safe
- no runtime behavior changes yet

**Suggested validation**

- schema tests
- loader fallback tests
- invalid config rejection tests

### PR 2 - MCP Adapter Core

**Goal**

Make external stdio MCP tools discoverable and callable through a local wrapper.

**Expected changes**

- add MCP dependency
- add stdio connection path
- add `mcp_<server>_<tool>` wrapper naming
- add schema normalization
- add timeout and single retry
- normalize wrapper error output

**Review focus**

- adapter behavior matches v1 scope
- wrapper interface fits the current synchronous tool model
- error handling is predictable

**Suggested validation**

- wrapper unit tests
- fake MCP server tests for success, timeout, and transient failure

### PR 3 - Registry Integration

**Goal**

Inject MCP tools into the existing registry without breaking local tools.

**Expected changes**

- extend registry assembly flow
- keep local discovery unchanged by default
- sort local tools first and MCP tools after
- force MCP tools onto the serial path

**Review focus**

- no regression when MCP config is absent
- tool ordering is stable
- MCP tools cannot enter the readonly parallel path

**Suggested validation**

- registry integration tests
- no-config regression tests
- tool ordering tests

### PR 4 - CLI Integration

**Goal**

Make the CLI agent use the MCP-aware registry.

**Expected changes**

- load user config in CLI agent runs
- construct registry with MCP enrichment
- surface warnings for skipped or failed servers

**Review focus**

- CLI behavior remains stable without MCP config
- failures are visible and non-fatal

**Suggested validation**

- CLI integration test with fake MCP server
- CLI no-config regression test

### PR 5 - SessionService Integration

**Goal**

Bring the same MCP loading behavior to SessionService and API-driven runs.

**Expected changes**

- load user config in SessionService
- support `session.config` MCP overrides
- keep session-scoped overrides isolated per session

**Review focus**

- CLI and SessionService use the same MCP loading model
- one session's MCP config does not leak into another

**Suggested validation**

- SessionService integration test
- session override isolation test

### PR 6 - Docs and Hardening

**Goal**

Close the loop with docs, examples, and regression coverage.

**Expected changes**

- update `README.md`
- update `agent/SKILL.md`
- add sample config snippet
- expand regression coverage
- verify acceptance criteria

**Review focus**

- docs clearly separate MCP client mode from MCP server mode
- tests cover the intended failure model

**Suggested validation**

- regression suite
- final acceptance checklist pass

## Recommended Merge Order

| Order | PR | Why This Order |
| --- | --- | --- |
| 1 | PR 1 | all later work depends on config loading |
| 2 | PR 2 | adapter can be reviewed before runtime wiring |
| 3 | PR 3 | registry composition should land before entry-point wiring |
| 4 | PR 4 | enables the first user-visible runtime path |
| 5 | PR 5 | extends the same model to API sessions |
| 6 | PR 6 | closes docs and validation after behavior stabilizes |