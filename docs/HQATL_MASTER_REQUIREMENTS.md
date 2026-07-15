# HQATL Master Requirements

## Status vocabulary

Use only: `NOT AUDITED`, `EXISTING`, `PROMPT ONLY`, `PARTIAL`, `MISSING`, `PLANNED`, `APPROVED`, `IMPLEMENTED`, `TESTED`, `REJECTED`.

No existing capability has been audited in Phase 0. `PLANNED` means documented future work, not executable functionality.

## Master checklist

| Area | Requirement | Status | Evidence / next gate |
|---|---|---|---|
| Vibe framework audit | Inventory executable features, prompt-only claims, architecture, tests, and preservation constraints. | PLANNED | Phase 1 audit required. |
| Elliott Wave completion | Audit executable rules, labeling, invalidation, alternates, and gaps. | PLANNED | Phases 2-3; do not infer from prompts. |
| Fibonacci | Specify retracements/extensions while keeping Fib and statistical projections separate. | PLANNED | Source approval and tests required. |
| EMA stack | Specify EMA 9/21/89/200/233 behavior and timeframe use. | PLANNED | Phase 4 specification. |
| EMA standard-deviation analytics | Specify EMA-89 and EMA-200 deviation calculations and interpretation. | PLANNED | Phase 4 specification and validation. |
| KAMA adaptive bands | Research independent contribution, formula, parameters, and tests. | PLANNED | Phase 6 research gate. |
| Linear-regression deviation channels | Research calculation, anchoring, leakage controls, and value. | PLANNED | Phase 6 research gate. |
| Modern adaptive Bollinger | Define and validate an adaptive design without duplicating other volatility evidence. | PLANNED | Phase 6 research gate. |
| Modern adaptive Supertrend | Define and validate an adaptive design without indicator counting. | PLANNED | Phase 6 research gate. |
| Market structure | Specify swing, trend, break, and invalidation semantics. | PLANNED | Phase 5 specification. |
| iFVG | Define identification, confirmation, mitigation, timeframe, and invalidation rules. | PLANNED | Phase 5 specification. |
| Candle-control interpretation | Specify explainable completed-bar interpretations and provisional states. | PLANNED | Phase 5 specification. |
| Elliott-related harmonics | Research compatibility, conflicts, independence, and validation. | PLANNED | Source and backtest review required. |
| Volume and RVOL | Specify normalization, session handling, data limits, and independent evidence. | PLANNED | Phase 7 research gate. |
| CVD and order flow | Define provider/data requirements, approximations, and limitations. | PLANNED | Phase 7 research gate. |
| Dow Theory and intermarket confirmation | Specify instruments, timing, divergence, and confirmation rules. | PLANNED | Phase 8 research gate. |
| OANDA | Plan historical and practice adapters behind provider interfaces. | PLANNED | Phase 11; no connection now. |
| Moomoo Level 2 and demo trading | Verify OpenD/API access, entitlements, licensing, and demo capability. | PLANNED | Phase 12; verification required. |
| Dashboard | Design linked research/chart workspace beside decision support. | PLANNED | Phase 9; no code now. |
| Backtesting | Share production calculations, prevent leakage, define costs and baselines. | PLANNED | Phase 10 validation. |
| Walk-forward testing | Define rolling train/validation/test windows and parameter governance. | PLANNED | Phase 10 validation. |
| Security | Enforce analysis-only defaults, secret controls, dependency review, and approval gates. | APPROVED | Foundation policy documented; implementation audit pending. |
| Data quality | Track completeness, freshness, mapping, adjustments, provenance, and warnings. | PLANNED | Provider and dashboard specifications. |
| Trade Decision Workspace | Present bias, evidence, uncertainty, invalidation, and stand-aside status. | PLANNED | Phase 9; decision support only. |
| Source review and approval | Register claims, licensing, conflicts, validation, and human approval. | APPROVED | Foundation policy and templates documented. |

## Update rules

- Add evidence links or commit references whenever a status changes.
- `IMPLEMENTED` requires executable code review; `TESTED` requires relevant tests and results.
- `APPROVED` records human approval, not implementation.
- Preserve rejected ideas and rationale for traceability.
