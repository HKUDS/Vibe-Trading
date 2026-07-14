# Phase 6–7 Execution Realism and Acceptance

This document freezes the implementation and acceptance contract for the
shared `BaseEngine` execution path. These controls apply to historical
research only; they do not place, route, or cancel real broker orders.

## Execution contract

| Capability | Configuration | Contract |
|---|---|---|
| Volume participation | `volume_participation_rate` | Optional scalar or per-symbol map in `[0, 1]`; omitted preserves legacy full-fill behavior. Capacity is cumulative per symbol/bar. Missing or invalid volume provides zero capacity. |
| Order type | `order_type` | `market` (default) or `limit`. |
| Limit price | `limit_price_offset_bps` | Optional non-negative scalar or per-symbol map. Buy limits are below the decision price; sell limits are above it. |
| Time in force | `time_in_force` | `GTC` (default), `IOC`, or `FOK`. IOC may fill partially once and cancels the residual. FOK fills the complete residual or cancels without a fill. |
| Latency | `execution_latency_bars` | Optional non-negative scalar or per-symbol map. Zero preserves legacy behavior. Eligibility is the creation bar plus this many bars. |
| Expiry | `order_expiry_bars` | Optional non-negative scalar or per-symbol map. The expiry bar is inclusive; an order expires before processing the next bar. |
| Unfilled limit | `max_unfilled_bars` | Optional non-negative scalar or per-symbol map. Cancels a GTC order after this many eligible zero-fill attempts. |
| Deterministic rejection | `venue_reject_symbols` | Optional symbol list or symbol-to-reason map, plus an overridable engine rejection hook. |

Every order must satisfy, within numerical tolerance:

```text
requested_quantity
  = filled_quantity + remaining_quantity + cancelled_quantity
```

Every fill records its order ID, type, time in force, limit price, scheduled
eligibility, execution bar, decision/fill prices, costs, and volume-cap
context. Reporting validates order/fill quantities, order linkage, execution
eligibility, limit-price compliance, volume limits, and lifecycle totals.

## Limit-fill assumptions

- A buy limit is eligible only when the bar low is at or below the limit; its
  fill price cannot exceed the limit.
- A sell limit is eligible only when the bar high is at or above the limit;
  its fill price cannot be below the limit.
- If the bar opens through the limit, the model permits price improvement.
- Daily OHLCV does not reveal intrabar path, queue priority, or displayed
  depth. A touched limit is therefore an explicit deterministic approximation,
  not proof that a live venue would fill it.

## Terminal liquidation

Backtests finish flat. Any live residual order is cancelled, then each open
position receives a separately auditable market liquidation order and fill.
When participation limits are enabled, only that forced terminal fill is
capacity-exempt, and `volume_limit_exempt=true` identifies it in `fills.csv`.

## Phase 7 fixed acceptance fixture

The acceptance test uses 41 real daily SPY observations from 2024-01-02
through 2024-02-29, stored at:

```text
agent/tests/fixtures/spy_phase7_2024.csv
```

Fixture SHA-256:

```text
925caa4dbce36342cf89bf66a7dd88096439896565ad3931cac5978119df424d
```

The source is a previously cached Yahoo Finance SPY series. The fixture is
immutable, offline, and contains only date, OHLC, and volume fields. The
acceptance run uses explicit starting capital, one-basis-point commission,
five-basis-point slippage, limit orders, bar latency, expiry, persistence, and
volume participation. It also runs seeded Monte Carlo/bootstrap validation and
fixed walk-forward windows.

Acceptance requires:

- the standard `BaseEngine.run_backtest()` workflow;
- complete order, fill, trade, equity, daily-accounting, metrics, validation,
  report, reconciliation, and run-card artifacts;
- every fill linked to a known order and every completed position quantity
  reconciled to entry/exit fills;
- zero lifecycle, order/fill quantity, limit-price, eligibility, and
  participation violations;
- exact commission/slippage and ending-capital reconciliation;
- a flat terminal portfolio; and
- a second fixture run proving that omitted participation settings preserve a
  single full entry fill.

## Known limitations

- Latency and expiry are measured in data bars, not exchange timestamps.
- The OHLC limit model has no queue position, maker/taker rebate, spread,
  order-book depth, or stochastic fill probability.
- Market impact is represented only by configured slippage and participation
  caps.
- Deterministic venue rejection is a research hook, not a venue protocol
  simulator.
- Forced terminal liquidation is deliberately capacity-exempt so metrics and
  artifacts have one canonical flat ending state.
- Gross returns remain cost-reconciled estimates rather than a separate
  zero-cost resimulation.
