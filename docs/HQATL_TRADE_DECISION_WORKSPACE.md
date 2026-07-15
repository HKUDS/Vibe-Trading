# HQATL Trade Decision Workspace

## Purpose

The future Trade Decision Workspace sits beside the research workspace and converts approved analytical output into explainable decision support. It is not an autonomous trading command system and does not grant order authority.

## Primary conclusion labels

Use only these primary bias labels:

- **Bullish Bias**
- **Bearish Bias**
- **Neutral Bias**

Do not use `BUY` or `SELL` as the primary conclusion label.

## Workspace fields

| Section | Required content |
|---|---|
| Decision context | Market bias; confidence level with explanation; timeframe alignment; stand-aside status; trader notes |
| Researched trade references | Suggested researched entry zone; stop-loss reference; primary take-profit reference; secondary take-profit reference; risk-to-reward estimate |
| Invalidation | Elliott invalidation level; setup invalidation conditions |
| Evidence ledger | Evidence supporting the bias; evidence opposing the bias; evidence still missing |
| Structural view | Primary Elliott count; alternate Elliott count; Fib levels |
| Analytical context | EMA-deviation context; iFVG status; volume/RVOL status; CVD status; Dow/intermarket confirmation |
| Integrity | Data-quality warnings; timestamps; completed-bar/provisional state; source/provenance |

## Behavioral rules

- Keep primary and alternate Elliott counts distinct, each with its own evidence and invalidation.
- Explain confidence through evidence; never display a black-box score.
- Treat entry, stop, and target values as researched references, not commands or guarantees.
- Show opposing and missing evidence with the same care as supporting evidence.
- Activate stand-aside when required evidence, data quality, timeframe alignment, or invalidation clarity is insufficient.
- Preserve human review and decision authority at all times.
