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

## Non-Goals

v1.2.1 does not add live trading capability, broker execution support, optimizer construction, full IC decay calculation, or production quant diagnostics.
