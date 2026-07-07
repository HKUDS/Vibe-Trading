# Quant Reliability Scorecard

The Quant Reliability Scorecard is the evidence gate for backtest and strict
alpha-bench conclusions. It is additive: it writes optional artifacts and refs
without changing legacy metric meanings.

## Schema

`src.reliability.quant.scorecard.BacktestReliabilityScorecard` uses
`schema_version = "1.0.0"`.

Standard score dimensions:

- `pit_clean`
- `oos_split`
- `cost_model`
- `benchmark`
- `trial_count`
- `execution_realism`
- `universe_pit`
- `capacity`
- `cost_sensitivity`
- `ic_stability`
- `regime_stability`
- `crowding_risk`
- `random_control`

Unknown score breakdown keys are rejected. Missing standard dimensions are
defaulted to zero with a structured warning.

## Required Diagnostics

- Cost sensitivity bps grid: `[0, 5, 10, 25, 50, 100]`.
- Execution realism timestamps: `signal_time`, `decision_time`,
  `order_time`, `fill_time`, and `price_time`.
- Capacity grid: ADV participation `[5%, 10%, 20%]`.
- OOS or walk-forward gate.
- OOS/IS IC ratio guard: if `abs(is_ic_mean) < 0.005`, emit a hard failure and
  do not compute the ratio.
- IC horizons default to `[1, 5, 20]`; all IC output carries `horizon`.
- Factor crowding report.
- Regime-conditional IC.
- Neutralized IC: raw, industry-neutral, size-neutral, and double-neutral.
- Industry classification fallback: Wind, CITIC, SW, then unavailable warning.

## Hard Failures

Hard failures include:

- future data or PIT violation,
- tradability claim without cost model,
- alpha claim without benchmark,
- generalization claim without OOS or walk-forward,
- missing historical universe,
- missing execution timestamps for tradability claims,
- missing trial count while presenting best trial,
- missing critical A-share market rules,
- ignored policy deny,
- LLM scorecard override attempt,
- high crowding without stress test,
- negative regime IC without activation logic.

Hard failures force `conclusion_cap = "not_reliable"` and cannot be offset by
high returns.

## DSR and PBO

DSR and PBO are experimental diagnostics only. They may appear in
`experimental_metrics`, fixtures, and reports, but they are not production
gates and must not be the only reason a result passes.

## Strict Alpha Bench

The scorecard consumes existing strict alpha-bench random-control output from
`bench_runner_strict.py`: `random_control`, `random_ic_mean`, and `alpha_t_*`.
It does not implement a second random-control pipeline.
