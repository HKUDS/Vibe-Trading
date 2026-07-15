# HQATL Architecture Overview

## Architectural intent

HQATL will separate data acquisition, analytical calculations, research validation, evidence synthesis, presentation, and any future execution capability. This document is a target architecture, not an implementation claim.

## Logical layers

1. **Provider adapters** implement historical, realtime, depth, execution, and instrument-mapping interfaces.
2. **Canonical market data** normalizes instruments, timestamps, timeframes, sessions, completeness, provenance, and quality flags.
3. **Shared analytics** contains a single implementation for calculations used by interactive analysis and backtesting.
4. **Structural interpretation** maintains Elliott primary and alternate counts, their evidence, and separate invalidation levels.
5. **Evidence modules** contribute measurable, non-duplicative context such as Fibonacci, EMA deviation, structure, iFVG, volume, CVD, and intermarket evidence.
6. **Research and validation** evaluates hypotheses with reproducible tests, leakage controls, baselines, and walk-forward analysis.
7. **Evidence synthesis** exposes supporting, opposing, and missing evidence without black-box certainty.
8. **Workspaces** present the research/chart view and Trade Decision Workspace without duplicating backend calculations.
9. **Execution boundary** remains disabled by default and requires a separate human-approved phase.

## Core boundaries

- Strategy and analytical code depend on provider interfaces, never OANDA or Moomoo directly.
- Frontend components render backend results rather than recalculate them.
- Confirmed signals use completed bars; provisional results are labeled.
- Elliott primary and alternate counts never collapse into one result.
- Fibonacci projections never masquerade as statistical projections.
- Every result carries provenance, parameters, timeframe, data-quality state, and an explanation.

## Quality attributes

Explainability, reproducibility, testability, provider neutrality, security, observable data quality, and long-term maintainability take precedence over feature count.
