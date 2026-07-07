# IRR-AGL Threat Model

This document defines the hardening threat model for the Institutional Research
Reliability and Agent Governance Layer (IRR-AGL). IRR-AGL is a cross-cutting
governance layer over the existing agent, registry, loaders, backtests, MCP,
trace, run-card, and live-safety surfaces. It is not a replacement for any of
those systems.

## Assets

- Live trading authority: mandates, kill switch state, connector profile, order
  guard decisions, and broker write adapters.
- Secrets: LLM credentials, API auth keys, broker tokens, OAuth caches, market
  data tokens, private paths, session cookies, and raw environment variables.
- Research integrity: protocol hashes, trial ledger hash chain, data audit
  records, PIT timestamps, policy decisions, traces, scorecards, and research
  cards.
- Runtime boundaries: local file roots, run roots, artifact root, generated
  subprocess environment, MCP allowlists, scheduler budget, and swarm worker
  inputs.

## Trust Boundaries

| Boundary | Untrusted input | Boundary owner | Required invariant |
| --- | --- | --- | --- |
| User prompt to tools | Natural language, tool args | Agent loop plus registry | ToolRegistry interface stays stable; governance wraps execution. |
| MCP server list and tool calls | MCP commands, URLs, schemas | MCP config and policy | External MCP must be operator allowlisted. |
| Remote API and channel bots | HTTP/chat input | API auth, CSRF, policy | Shell-capable and live-write tools are denied by default. |
| Scheduler and swarm | Stored jobs, worker prompts | Scheduler/swarm runtime | No prompt-injected MCP URL or live write by default. |
| Data loaders | Source names, fallback chains | Loader registry plus data audit | `local:` never silently falls back to network. |
| Generated backtests | Strategy code | Generated subprocess runner | Environment is allowlisted; no LLM/live/broker secrets. |
| Live connectors | Broker operations | LiveOrderGuardTool | UNKNOWN and write tools fail closed. |
| Artifacts/cards/traces | Metadata and summaries | Redaction and schemas | No raw secrets; schema_version is required. |

## Threat Coverage Matrix

| Threat | Mitigation | Regression coverage |
| --- | --- | --- |
| Prompt injection into MCP | MCP tool names and schemas are not prompt-defined; external MCP must be operator allowlisted. | Existing MCP trust tests plus `agent/tests/security/test_irr_agl_regressions.py`. |
| Remote shell exposure | `remote_api`, `mcp_sse`, `mcp_http`, and `channel_bot` deny `R5_SHELL` by default. | `test_remote_and_channel_surfaces_deny_r5_shell`. |
| Scheduler live write | Scheduler denies `R4_TRADE_WRITE` and `R5_SHELL` by default. | `test_scheduler_denies_live_write_and_shell`. |
| Swarm MCP URL injection | Policy rule P35 denies prompt-supplied external MCP URLs from swarm. | Governance policy regression suite. |
| External MCP allowlist bypass | Operator allowlists remain the source of truth; governance does not expand permissions. | MCP trust-model tests. |
| Channel bot remote shell | Channel bot surface is treated like remote API for shell denial. | `test_remote_and_channel_surfaces_deny_r5_shell`. |
| Connector unknown fail-open | Live connector UNKNOWN classification is denied before execution. | `test_unknown_live_connector_fails_closed`. |
| `local:` source fallback to network | Explicit local market data fallback is denied; loader registry keeps no-fallback semantics. | `test_explicit_local_market_data_fallback_to_network_is_denied`. |
| All sources open false success | Data audit and Research Card surface `DATA_ALL_SOURCES_OPEN` as visible hard-failure severity. | `test_all_sources_open_becomes_visible_research_card_warning`. |
| PIT violation or future data | PIT violations enter structured audit/scorecard failures; hard failures cap conclusions. | PIT, data audit, quant scorecard tests. |
| Generated subprocess secret inheritance | Runner copies only allowlisted runtime/data-source environment keys. | `test_generated_backtest_subprocess_env_allowlist_excludes_live_and_llm_secrets`. |
| Trace/artifact/card secret leakage | Artifact metadata and Research Card models pass through shared redaction. | Redaction and schema migration tests. |
| Live mandate self-authorization | `commit_mandate` is not an agent tool; mandate commit remains API/CLI consent surface only. | `test_agent_tool_surface_cannot_import_or_reference_commit_mandate`. |
| Scorecard override by LLM | Scorecard is generated from evidence and schemas; override attempts are hard failures. | Quant scorecard tests. |
| Hard failure hidden by high returns | Scorecard hard failures force `not_reliable`; Research Card hard failures force `not_reliable`. | Quant scorecard and Research Card tests. |

## Fail-Closed Rules

- `R4_TRADE_WRITE` and `R5_SHELL` deny decisions are shadow-denied in
  `observe` and `warn`; they are not executed.
- Policy exceptions deny high-risk tools and remote/scheduler/swarm/live
  surfaces.
- Governance can record, warn, or deny. It cannot approve a live mandate and
  cannot bypass `LiveOrderGuardTool`.
- Data source circuit breakers may stop fallback attempts, but an empty result
  from all open sources must remain visible as a warning or hard failure.

## Non-Goals

- IRR-AGL does not make an agent autonomous with broker authority.
- IRR-AGL does not replace the existing backtest engine, loader registry,
  ToolRegistry, MCP server, or live safety gate.
- DSR/PBO are experimental diagnostics only and are not production gates.
