# IRR-AGL v1.2.1 Threat Model Delta

This delta focuses on risks introduced or closed by the v1.2.1 hardening work.

## Preserved Safety Boundaries

- No public interface change to `BaseTool.execute`, `ToolRegistry.execute`, or `DataLoaderProtocol.fetch`.
- R4/R5 denies are fail-closed before inner execution.
- Remote API and MCP surfaces deny R5 shell by default.
- Scheduler denies R4 trade-write and R5 shell by default.
- Generated subprocess env uses an allowlist and excludes LLM, broker, and live-trading secrets.
- New evidence APIs are read-only.

## Main Threats And Mitigations

| Threat | Mitigation |
|---|---|
| Evidence write failure downgrades deny to allow | Deny Barrier skips inner tool before evidence writes |
| Decision ID confused with artifact ID | `EvidenceIdentity` separates semantic and storage IDs |
| Index loss causes false failure or 500 | Verifier rebuilds degraded reports from artifacts/trace |
| Prose upgrades unreliable research | ClaimSet and ScorecardPolicy gate structured claims |
| Prompt-supplied MCP URL bypasses governance | Session override sanitization and route coverage tests |
| Generated subprocess inherits secrets | Runner env allowlist and security regression |
| UI/API leaks secrets | Redaction helpers and fixture scans |

## Post-416/420 Delta

| Threat | Security impact | Mitigation and proof |
|---|---|---|
| Raw registry escape through `GovernedToolRegistry.get()` | P0: caller could execute R4/R5 raw tool without governance | Public `get()` now returns a governed proxy; red-team tests prove R4/R5 execution counters stay zero |
| Public `inner` access | P0: route or caller could bypass governance by reaching raw `ToolRegistry` | Public `.inner` is absent; `_inner` is private implementation detail; route coverage tests verify governed builders |
| Forged `RuntimeContext` state | P0: caller-provided `live_state`, `user_auth_state`, or `budget_state` could satisfy live gates | R4 live/write gates require authoritative `GovernanceStateProvider`; null/failing provider fails closed |
| Live connector submit/cancel bypass | P0: adapter write call could occur before policy and evidence recording | Submit/cancel are routed through governed pseudo-tools with R4 manifests before adapter execution |
| Policy-denied payload parser exception safety | P1: malformed deny payload could hide deny semantics | Parser catches expected payload errors only and does not swallow `KeyboardInterrupt`, `SystemExit`, or `BaseException` |
| CircuitBreaker TOCTOU and connection lifecycle | P1: concurrent failure counts could be lost and locks left open | Atomic update path and close-on-success/failure/retry tests cover concurrent `record_failure` |
| TrialLedger retry lifecycle | P1: retry sleep could hold SQLite connection and preserve locks | Append closes per attempt; hash-chain unchanged after retry |
| Artifact path traversal and no-leak status | P0: escaped artifact path could read outside artifact root or leak local path | Traversal, encoded dot-dot, symlink escape, and safe 404/no-leak tests added |
| Backend raw research-card response redaction | P0: `/runs/{run_id}` could leak bearer tokens, broker credentials, or inline API keys | Shared backend redaction catches secret-like keys and values |
| Frontend display/export redaction | P1: UI could hide secrets on screen but leak them in Markdown export | Display and Markdown export use redaction helpers; script payload renders inert text |
| MCP/API/CLI/scheduler/session/swarm route coverage | P1: real entrypoint could use raw registry despite fake-registry tests passing | Route-level tests verify governed builders and prompt MCP URL rejection |

## Non-Goals

v1.2.1 does not add live trading capability, broker execution support, optimizer construction, full IC decay calculation, or production quant diagnostics.
