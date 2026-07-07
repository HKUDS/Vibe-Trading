# IRR-AGL v1.2.1 Architecture

IRR-AGL v1.2.1 turns the v1.2 evidence-closure design into an auditable runtime path. It does not expand live trading capabilities. The safety boundary remains: high-risk R4/R5 tools are denied before inner execution, evidence writes are best effort, and research conclusions are gated by structured claims and methodology facts.

## Evidence Chain

The canonical chain is:

1. `PolicyDecision`
2. `RecordedPolicyDecision`
3. trace event
4. policy decision artifact
5. optional ledger or outbox event
6. `RunEvidenceIndex`
7. `EvidenceClosureReport`
8. `ClaimSet`
9. `MethodologyFactSet`
10. `BacktestReliabilityScorecard`
11. `ResearchCard`
12. read-only API and UI panels

`RunEvidenceIndex` is a derived view. `EvidenceVerifier` is the audit authority and can rebuild from artifacts and trace when the index is missing.

## Governance Runtime

`GovernedToolRegistry` wraps the existing `ToolRegistry` without changing `ToolRegistry.execute(name, params) -> str`. For R4 trade-write and R5 shell denies, it sets `deny_barrier_engaged=True`, `shadow_deny=True`, and `inner_tool_executed=False` before evidence recording. Evidence write failure never permits tool execution.

## Reliability Artifacts

Artifacts use strict JSON writes and schema versions. v1.2.1 separates semantic IDs from storage references:

- `decision_id`
- `policy_decision_artifact_id`
- `trace_event_id`
- `ledger_event_hash`

Old v1.1/v1.2 fixtures are read tolerantly.

## Claims And Scorecard Gates

Strong research claims are captured in `ClaimSet`; scorecard policy predicates read `ClaimSet` and `MethodologyFactSet`, not arbitrary prose. Triggered rules record `rule_id`, `reason_code`, `explanation`, and `evidence_refs`.

## Surfaces

Route-level tests cover API, MCP SSE/HTTP/stdio, scheduler, swarm, live runtime guard wiring, and generated subprocess env isolation. No Phase 10 work adds write endpoints.

## Quant Diagnostics

Phase 9 adds diagnostics readiness schemas only. These schemas expose readiness gaps and do not alter `conclusion_level` or paper-gate requirements.
