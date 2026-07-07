# Research Card

Research Card is the read-only delivery summary for IRR-AGL. It is built from
existing artifacts and metadata; it does not mutate backtest metrics or approve
live trading.

## Model

The current model is `src.research_card.model.ResearchCard` with
`schema_version = "1.0.0"`.

Core fields:

- `card_id`, `schema_version`, and `title`.
- Optional refs: `protocol_ref`, `data_audit_refs`, `policy_decision_refs`,
  `tool_trace_refs`, `backtest_refs`, and `alpha_bench_refs`.
- Optional embedded `scorecard`.
- Evidence summaries: `key_metrics`, `benchmark`, `cost_model`,
  `execution_assumptions`, and `oos_results`.
- Structured `warnings` and `hard_failures`.
- `conclusion_level`, capped by evidence gates.

## Builder Rules

`src.research_card.builder.build_research_card` consumes a
`ResearchCardGraph`. It validates protocol, data audit, policy decision, and
scorecard inputs with Pydantic models before emitting a card.

Conclusion gates:

- Missing scorecard caps the card at `exploratory`.
- Missing OOS, cost model, or benchmark caps stronger claims at
  `research_candidate`.
- PIT violations cap conclusions and remain visible in warnings.
- Hard failures force `not_reliable`.

## Security

Research Card models call shared redaction before validation. Cards must not
contain raw API keys, broker credentials, OAuth tokens, session cookies, raw
environment variables, or private token cache contents.

## Compatibility

Research Cards are optional. Older run cards and traces do not need migration.
When present, Research Card refs should be treated as additive artifact refs,
not as replacements for the original run artifacts.
