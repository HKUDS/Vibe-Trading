# Governance Policy

IRR-AGL governance wraps existing tool execution. It does not replace
`BaseTool`, `ToolRegistry`, MCP schemas, or live order safety.

## Modes

| Mode | Meaning |
| --- | --- |
| `off` | Delegate directly to the wrapped registry. |
| `observe` | Record decisions; low/medium risk denies may continue as warnings. |
| `warn` | Same compatibility posture as observe, with operator-visible warnings. |
| `enforce` | Deny decisions raise `PolicyDenied`. |

Important exception: `R4_TRADE_WRITE` and `R5_SHELL` deny decisions are
shadow-denied even in `observe` and `warn`; the underlying tool is not called.

## Risk Levels

- `R0_READ`: read-only local or research surfaces.
- `R1_WRITE_LOCAL`: local writes inside allowed roots.
- `R2_NETWORK`: network reads or remote data access.
- `R3_TRADE_READ`: broker/account/position reads.
- `R4_TRADE_WRITE`: place, cancel, modify, flatten, or submit orders.
- `R5_SHELL`: shell or generated process execution.
- `UNCLASSIFIED`: unknown tools requiring review.

## Built-In Rule Summary

| Rule | Behavior |
| --- | --- |
| `P10` | UNKNOWN live connector tools fail closed. |
| `P20` | Remote API, MCP SSE/HTTP, and channel bots deny shell tools. |
| `P30` | Scheduler denies live-write and shell tools. |
| `P35` | Swarm workers deny prompt-supplied external MCP URLs. |
| `P40` | Live writes require mandate, clear kill switch, user consent, live order guard, and connector profile. |
| `P50` | Explicit local market data cannot fall back to network. |
| `P100` | Read-only MCP stdio R0 tools are allowed by default. |
| `P900` | Unclassified tools warn before enforcement and deny in enforce mode. |
| `P999` | No matching rule is fail-safe deny. |

## Policy Exceptions

PolicyEngine exceptions are handled fail-safe:

- high-risk tools deny,
- `remote_api`, `mcp_sse`, `mcp_http`, `scheduler`, `swarm`,
  `live_connector`, and `channel_bot` deny,
- low-risk local observe paths warn and continue.

## Live Boundary

Governance cannot approve a live mandate and cannot bypass the kill switch or
`LiveOrderGuardTool`. LiveOrderGuardTool remains the final live-write defense.
