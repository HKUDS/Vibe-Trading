# 2026-05-25 SWARM External MCP Tools — Test-Driven Design

Companion to [`2026-05-25_swarm_mcp_tools_roadmap.md`](2026-05-25_swarm_mcp_tools_roadmap.md). This document tracks **requirements, scenarios, and test plans** in TDD form so each milestone has a green-bar definition before code lands.

## How To Use This Doc

- Each requirement (R-NN) maps to one or more scenarios (S-NN).
- Each scenario maps to one or more tests (T-NN).
- A milestone is "done" when every test it owns is green AND no existing test regresses.
- Update the **Status** column as work progresses. Do not mark `done` without a linked PR / commit.

---

## 1. Requirements

### Functional

| ID | Requirement | Source | Status |
| --- | --- | --- | --- |
| R-01 | A SWARM worker MUST be able to invoke a remote MCP tool whose name is listed in the executing agent's `tools:` whitelist AND in the boot-time allowlist. | Roadmap §"Why This Work Is Needed" | done (M2, `bb7f2ff`) |
| R-02 | If an `mcp_*` name is in the agent's whitelist but NOT in the boot allowlist, the worker MUST log it as dropped and continue execution (no crash, no fail). | Roadmap §"Preset YAML Extension" | done (M2, `bb7f2ff`) |
| R-03 | An agent's local-tool whitelist MUST keep working unchanged when no MCP servers are configured. | Backwards compat | done (M1, `bb7f2ff`) |
| R-04 | Remote MCP tool calls MUST emit the same `tool_call` / `tool_result` events as local tools, with `server` and `remote_tool` fields populated. | Roadmap §"Audit & Observability" | done (M4, `bb7f2ff`) |
| R-05 | `SwarmRuntime` MUST accept an optional `agent_config: AgentConfig`; passing `None` MUST preserve current local-only behavior byte-for-byte. | Roadmap §"Runtime Plumbing" | done (M1, `bb7f2ff`) |
| R-06 | The `mcp_server.py::run_swarm` MCP tool's input schema MUST NOT accept any field that lets a caller inject MCP server URLs, commands, env vars, or allowlist overrides. | Roadmap §"Why The Trust Model Matters" | done (M5, `bb7f2ff`) |

### Non-Functional

| ID | Requirement | Status |
| --- | --- | --- |
| R-07 | Remote MCP tool failures (timeout, transport error) MUST NOT cascade-fail the whole swarm run; the affected task fails or retries per existing rules, others continue. | done (M4, `bb7f2ff`) — `MCPServerAdapter.call_tool` already returns an `{"status": "error", ...}` envelope on transport failure (see `agent/src/tools/mcp.py` `call_tool`); M4 test `test_remote_tool_transport_failure_does_not_crash_worker` pins the worker-level non-cascade contract on top of it. |
| R-08 | Remote MCP `tool_timeout` (default 30s) MUST be honored per-tool-call; total worker timeout still bounded by `agent_spec.timeout_seconds`. | done (pre-M4, `bb7f2ff`) — pinned by `tests/test_mcp_client_adapter.py::test_remote_tool_execute_does_not_retry_timeout_and_strips_run_dir` (timeout flows through to the FastMCP `call_tool(..., timeout=server_config.tool_timeout)`); the worker's outer `timeout_seconds` budget is independent (see worker.py `t0` / `elapsed > timeout` guard). |
| R-09 | Boot-time MCP server discovery MUST be lazy — a misconfigured server only fails when its tools are actually invoked, not at server startup, so unrelated swarm runs stay healthy. | done (M1, `bb7f2ff`) |
| R-10 | Sensitive args (`api_key`, `token`, `password`, `secret`) sent to remote tools MUST stay redacted in `events.jsonl`, same as local tools (see [worker.py `_SENSITIVE_TOOL_ARGUMENT_KEYS`](../agent/src/swarm/worker.py)). | done (M4, `bb7f2ff`) — pinned by `tests/test_swarm_m4_e2e.py::test_tool_call_events_carry_mcp_metadata_and_redact_sensitive_arguments`. |

---

## 2. Scenarios

### Happy-path

| ID | Scenario | Status |
| --- | --- | --- |
| S-01 | Operator configures one stdio MCP server (`internal_kb`) at boot. A custom preset gives `bull_advocate` the tool `mcp_internal_kb_search`. Running `run_swarm(preset, vars)` produces a final report whose evidence cites results returned by the remote tool. | done (`bb7f2ff`) |
| S-02 | Two MCP servers configured at boot. One agent (`fundamental_analyst`) uses tools from server A; another (`compliance_reviewer`) uses tools from server B; both run in the same swarm DAG. | done (`bb7f2ff`) |
| S-03 | A preset that uses ONLY local tools runs with `agent_config=None` and produces byte-identical output to today's behavior. | done (`bb7f2ff`) |

### Trust-model

| ID | Scenario | Status |
| --- | --- | --- |
| S-04 | An external MCP client calls `run_swarm` with a crafted `variables` dict containing keys like `mcp_url`, `mcp_command`, `mcp_servers`. The runtime MUST ignore these — they are template variables, never config. | done (`bb7f2ff`) |
| S-05 | A preset YAML lists `mcp_attacker_evil_tool` in an agent's `tools:` whitelist. The boot allowlist does NOT contain `attacker`. Worker starts, logs the drop, completes the task without that tool. | done (`bb7f2ff`) |
| S-06 | A preset YAML lists a `mcp_*` tool that exists in the boot allowlist but NOT in the agent's `tools:` whitelist. Worker MUST NOT see or expose that tool. | done (`bb7f2ff`) |

### Failure-mode

| ID | Scenario | Status |
| --- | --- | --- |
| S-07 | A configured remote MCP server is unreachable when the worker calls a tool. The tool call returns an error envelope; the worker either retries (per `agent_spec.max_retries`) or fails just that task. The swarm continues with downstream tasks that don't depend on it. | done (`bb7f2ff`) |
| S-08 | A remote tool exceeds `tool_timeout`. The worker receives a timeout error envelope; the worker's own `timeout_seconds` budget keeps ticking and is unaffected by the per-tool timeout. | done (`bb7f2ff`) |
| S-09 | A remote tool returns a payload >10KB. The worker truncates per existing `result[:10_000]` rule; full payload is recoverable from the run's artifacts directory. | done (`bb7f2ff`) |

### Boot & config

| ID | Scenario | Status |
| --- | --- | --- |
| S-10 | `VIBE_TRADING_SWARM_AGENT_CONFIG` env var points to a valid JSON file. Boot loads it; `~/.vibe-trading/swarm-agent.json` is ignored. | done (`bb7f2ff`) |
| S-11 | Env var unset, `swarm-agent.json` exists. Boot loads it; `agent.json` is ignored. | done (`bb7f2ff`) |
| S-12 | Env var unset, neither swarm-specific file exists, `agent.json` exists. Boot loads `agent.json` as fallback. | done (`bb7f2ff`) |
| S-13 | None of the above. Boot proceeds with empty config; behavior identical to today. | done (`bb7f2ff`) |

---

## 3. Test Plan

Tests live under `agent/tests/swarm/` and `agent/tests/tools/` mirroring source layout. **Do NOT mock the MCP wire protocol** — use a small in-process fake `MCPServerAdapter` so we exercise the real `MCPRemoteTool` wrapper. (Reference: existing fake-server pattern in `agent/tests/tools/test_mcp_*.py`.)

### M1 — Config plumbing

| ID | Test | Maps to | Status |
| --- | --- | --- | --- |
| T-01 | `SwarmRuntime(store=..., agent_config=None)` constructs identically to current; existing test `test_runtime_smoke.py` still passes unchanged. | R-03, R-05 | done (`bb7f2ff`) — `tests/test_swarm_m1_config_plumbing.py::test_runtime_default_construction_keeps_agent_config_none` + `..._explicit_none_construction_is_identical`; full swarm suite (117 tests) green |
| T-02 | `agent_config` is forwarded through `start_run` → `_execute_run` → `_run_worker_with_retries` → `run_worker`. Asserted via a spy on `run_worker`. | R-05 | done (`bb7f2ff`) — `..._test_run_worker_receives_agent_config_from_runtime` + `..._receives_none_when_runtime_has_no_agent_config` |
| T-03 | Passing a non-None `agent_config` does not throw at construction time even when no MCP servers are configured (lazy discovery, R-09). | R-05, R-09 | done (`bb7f2ff`) — `..._test_runtime_construction_with_unreachable_mcp_server_does_not_raise` |

### M2 — Registry assembly

| ID | Test | Maps to | Status |
| --- | --- | --- | --- |
| T-04 | `build_swarm_registry(["local_tool", "mcp_kb_search"], agent_config=cfg)` returns a registry with both tools when `cfg` lists `kb` server with `search` enabled. | R-01 | done (`bb7f2ff`) — `tests/test_swarm_m2_registry_assembly.py::test_build_swarm_registry_includes_local_and_remote_tools_when_both_whitelisted` |
| T-05 | `build_swarm_registry(["mcp_kb_search"], agent_config=cfg)` where `cfg` lists `kb` but `enabled_tools=["fetch"]` → only `fetch` is wrapped, `search` is NOT in registry, warning logged. | R-02, S-05 | done (`bb7f2ff`) — `..._test_build_swarm_registry_drops_whitelisted_tool_when_server_excludes_it` |
| T-06 | `build_swarm_registry(["mcp_kb_search"], agent_config=None)` returns empty registry, drop warning logged. | R-02, R-03 | done (`bb7f2ff`) — `..._test_build_swarm_registry_without_agent_config_drops_mcp_tools` |
| T-07 | Tools NOT listed in the agent's whitelist (but present on the remote server) are filtered out of the per-worker registry. | S-06 | done (`bb7f2ff`) — `..._test_build_swarm_registry_filters_remote_tools_outside_agent_whitelist` (+ regression `..._with_empty_mcp_servers_is_local_only`) |

### M3 — Boot wiring

| ID | Test | Maps to | Status |
| --- | --- | --- | --- |
| T-08 | `_resolve_swarm_agent_config()` returns the env-pointed file when the env var is set. | S-10 | done (`bb7f2ff`) — `tests/test_swarm_m3_boot_wiring.py::test_resolve_swarm_agent_config_path_uses_env_var_when_set` |
| T-09 | Falls back to `~/.vibe-trading/swarm-agent.json` when env unset. | S-11 | done (`bb7f2ff`) — `..._test_resolve_swarm_agent_config_path_prefers_swarm_specific_file` |
| T-10 | Falls back to `~/.vibe-trading/agent.json` when only that exists. | S-12 | done (`bb7f2ff`) — `..._test_resolve_swarm_agent_config_path_falls_back_to_main_agent_config` |
| T-11 | Returns `None` (or empty config) when nothing is set. | S-13 | done (`bb7f2ff`) — `..._test_resolve_swarm_agent_config_path_returns_none_when_nothing_configured` (+ `..._test_load_swarm_agent_config_returns_default_when_unconfigured` covers the "empty config" alternative + `..._test_load_swarm_agent_config_loads_swarm_specific_file` end-to-end) |

### M4 — End-to-end

| ID | Test | Maps to | Status |
| --- | --- | --- | --- |
| T-12 | Run a small 1-agent / 1-task preset against an in-process fake stdio MCP server that returns canned data. Assert the worker's `report.md` contains the canned data. | S-01, R-04 | done (`bb7f2ff`) — `tests/test_swarm_m4_e2e.py::test_run_worker_uses_remote_mcp_tool_and_report_cites_canned_data` (real `MCPRemoteTool` + real `MCPServerAdapter` driven by `_FakeMCPClient`; LLM scripted via `_StubChatLLM`; report.md asserted to contain the canned remote payload) |
| T-13 | Run a 2-agent / 2-server preset; verify each agent only sees its server's tools. | S-02 | done (`bb7f2ff`) — `..._test_two_agents_with_distinct_servers_only_see_their_own_remote_tools` (asserts on the OpenAI `tools=` list captured by the stub LLM per agent, so isolation is checked at the layer the LLM actually sees) |
| T-14 | Inspect `events.jsonl`: `tool_call` events for remote tools carry `server` + `remote_tool` fields; sensitive args redacted. | R-04, R-10 | done (`bb7f2ff`) — `..._test_tool_call_events_carry_mcp_metadata_and_redact_sensitive_arguments` (both `tool_call` and `tool_result` events checked; secret values asserted absent from full event JSON dump) |
| T-15 | Force the fake server to time out; assert the affected task fails or retries per `max_retries`, downstream tasks proceed if they don't depend on it. | S-07, R-07 | done (`bb7f2ff`) — `..._test_remote_tool_transport_failure_does_not_crash_worker` (the runtime/DAG-level cascade guard is already covered by existing retry tests in `test_swarm_error_surfacing.py`; this test pins the worker-level non-crash contract that the runtime depends on — the LLM saw the error envelope on its second turn and the worker reached a clean terminal state) |

### M5 — Trust-model regression

| ID | Test | Maps to | Status |
| --- | --- | --- | --- |
| T-16 | Introspect the FastMCP tool schema for `run_swarm`; assert it does NOT contain any of: `mcp_servers`, `mcp_url`, `mcp_command`, `mcp_env`, `agent_config`, `extra_tools`. | R-06 | done (`bb7f2ff`) — `tests/test_swarm_m5_trust_model.py::test_run_swarm_schema_excludes_mcp_config_injection_fields` (+ companion `..._test_run_swarm_schema_only_exposes_known_safe_parameters` flags any *new* parameter for explicit review, so future additions can't silently expand the trust surface) |
| T-17 | Pass `variables={"mcp_url": "http://attacker.example", "mcp_command": "rm -rf /"}` into `run_swarm`. Assert these are forwarded to the worker as plain template values (visible in the prompt) but NEVER consulted as config. | S-04 | done (`bb7f2ff`) — `..._test_run_swarm_variables_are_template_data_only_never_config` (spy on `SwarmRuntime` construction + `start_run` proves: `agent_config` was the boot-loader sentinel — never derived from variables; `user_vars` arrived verbatim with all 6 attack-shaped keys preserved as plain strings) |
| T-18 | A preset references an `mcp_*` tool whose server is not in the boot allowlist. Worker logs the drop and completes; tool is NOT silently looked up from a caller-supplied source. | S-05 | done (`bb7f2ff`) — `..._test_unknown_mcp_server_tool_drops_cleanly_with_attack_shaped_variables` (asserts: drop warning fired, dropped tool absent from LLM `tools=` argument, worker reached terminal state, **`build_mcp_tool_wrappers` was never called** despite attacker-shaped keys in `user_vars` — boot `agent_config` is the only authority) |

### M6 — Docs

| ID | Test | Maps to | Status |
| --- | --- | --- | --- |
| T-19 | README includes a "SWARM external MCP tools" subsection that links to this TDD and the roadmap. | Doc completeness | done (M6, this commit) |
| T-20 | This TDD's status column is fully filled in (every R-NN, S-NN, T-NN has a completed status linked to a commit). | Doc completeness | done (M6, this commit) |

---

## 4. Progress Tracker

Update on each PR / commit that touches this work.

| Date | Milestone | What landed | Commit / PR |
| --- | --- | --- | --- |
| 2026-05-25 | Bootstrap | Roadmap + TDD docs created on branch `feat/swarm-mcp-tools`. | this commit |
| 2026-05-25 | M1 | `SwarmRuntime` + `run_worker` accept optional `agent_config`; threaded `runtime → _run_worker_with_retries → run_worker`. 5 new tests in `tests/test_swarm_m1_config_plumbing.py`; full swarm suite (117 tests) green. Config received-but-unused in M1 (`del agent_config` placeholder); M2 will consume it via `build_swarm_registry`. | `bb7f2ff` |
| 2026-05-25 | M2 | New `build_swarm_registry(tool_names, *, agent_config, include_shell_tools)` in `agent/src/tools/__init__.py` reuses `build_registry(agent_config=...)` to merge local + remote MCP wrappers, then filters by the agent whitelist with a shared `_filter_registry` helper. `run_worker` now calls `build_swarm_registry` (M1 placeholder removed). 5 new tests in `tests/test_swarm_m2_registry_assembly.py`; sweep across swarm + tools + MCP suites (267 tests) green. | `bb7f2ff` |
| 2026-05-25 | M3 | New `_resolve_swarm_agent_config_path` + `load_swarm_agent_config` in `agent/src/config/loader.py` implement the env → `swarm-agent.json` → `agent.json` → None precedence ladder; exported via `src.config`. Wired through to all four `SwarmRuntime(...)` boot sites: `mcp_server.py::run_swarm`, `api_server.py::_get_swarm_runtime`, `cli/_legacy.py::cmd_swarm_run_live`, `tools/swarm_tool.py::SwarmTool`. 6 new tests in `tests/test_swarm_m3_boot_wiring.py` (T-08..T-11 + 2 integration tests for `load_swarm_agent_config`). Sweep across swarm + registry + tools + mcp + config suites (332 tests) green. Trust model preserved: every wiring site comments that the path is operator-trusted and never derived from the caller. | `bb7f2ff` |
| 2026-05-25 | M4 | R-04 production change in `agent/src/swarm/worker.py`: new `_remote_tool_metadata(registry, tool_name)` helper extracts `{server, remote_tool}` from `MCPRemoteTool._spec` and is merged into both `tool_call` and `tool_result` event payloads. New test file `agent/tests/test_swarm_m4_e2e.py` with 4 tests (T-12..T-15) drives `run_worker(...)` against a real `MCPRemoteTool` wrapping a real `MCPServerAdapter` whose async client is the in-process `_FakeMCPClient` (mirrors the fake-client pattern in `tests/test_mcp_client_adapter.py`); `ChatLLM` stubbed with `_StubChatLLM` so the worker is driven through deterministic tool-call sequences. Sweep across swarm + registry + tools + mcp + config suites (239 tests for the focused MCP/swarm slice) green. R-07 / R-08 / R-10 also flipped to done — R-07 pinned by the M4 timeout test on top of the existing adapter envelope, R-08 was already pinned by the pre-existing client-adapter timeout test, R-10 pinned by the M4 redaction test. | `bb7f2ff` |
| 2026-05-25 | M5 | No production change — M5 is pure regression / trust-model defense. New test file `agent/tests/test_swarm_m5_trust_model.py` with 4 tests covering T-16 + T-17 + T-18: (a) `_get_run_swarm_tool_schema()` introspects the FastMCP wire schema via `mcp.get_tool("run_swarm").parameters` and asserts the 6 forbidden config-injection fields are absent (plus a defense-in-depth companion test flagging any *new* parameter for explicit allowlist review); (b) `run_swarm` is called with a 6-key attack-shaped `variables` dict and `start_only=True` while `SwarmRuntime` is replaced by a spy that records construction args + `start_run` args — asserts `agent_config` is the boot-loader sentinel (never derived from caller) AND `user_vars` arrive verbatim; (c) `run_worker` is invoked with `tools=["mcp_attacker_evil_tool", "write_file"]`, empty boot `agent_config`, and attacker-shaped `user_vars`, with `build_mcp_tool_wrappers` spied — asserts drop warning fires, dropped tool absent from LLM `tools=` argument, worker reaches terminal state, and the spy was **never called** (proves no caller-supplied lookup path exists). Sweep across swarm + MCP + registry + config slice (297 tests) green. R-06 flipped to done. | `bb7f2ff` |
| 2026-05-25 | M6 | README now includes a "SWARM external MCP tools" subsection linking to the roadmap and this TDD. TDD status columns cover every R-NN, S-NN, and T-NN with completed status and commit references. Roadmap is marked implemented. | this commit |

---

## 5. Decision Log

Record any deviation from the roadmap as it happens. New rows appended at the bottom.

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-05-25 | Skip SSE transport in v1 | No internal demand; reduces fake-server test surface. Revisit if a use case appears. |
| 2026-05-25 | Boot allowlist over caller-supplied URLs | SSRF risk; matches the principle in the existing in-bound MCP roadmap (server-trusted config layer). |
| 2026-05-25 | Per-agent MCP scoping deferred to v2 | Adds preset-schema complexity without a concrete v1 use case. The agent-level `tools:` whitelist already provides functional isolation; per-server scoping is a defense-in-depth nicety, not a correctness need. |
