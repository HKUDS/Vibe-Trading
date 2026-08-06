---
name: Portfolio Checkup
description: Periodic risk x-ray of a stated book — exposure, concentration, correlation and drawdown, measured from retrieved prices.
markets: [global, cn, hk, us, crypto]
suggested_schedule: "0 9 * * 6"
suggested_timezone: Asia/Shanghai
data_capabilities:
  - Daily price history long enough to compute volatility, correlation and drawdown for every position
  - Portfolio-level risk decomposition — position weights, volatility contribution, correlation structure, drawdown
  - Sector, industry and listing-venue classification for each holding
  - Benchmark index history for the same window as the holdings
  - Currency reference rates when the book spans more than one currency
variables:
  holdings: (no holdings provided — the report cannot run without them)
  benchmark: the broad index of the book's home market
  lookback_days: "252"
---

# Portfolio checkup

Run a risk x-ray on the book below over a {{lookback_days}}-session lookback,
against **{{benchmark}}**.

Resolve the current date from the run environment; the lookback window ends on
the most recent session for which prices were actually retrieved, not on an
assumed date.

## Inputs

- Holdings: {{holdings}}
- Benchmark: {{benchmark}}
- Lookback: {{lookback_days}} sessions

If no holdings are supplied, stop and say so in one line. Do not invent a book,
do not reuse a book from an earlier run, and do not fall back to an index as a
stand-in portfolio.

## Data to gather

1. Daily closes for every holding covering the full lookback, plus the same
   window for the benchmark.
2. Position weights implied by the supplied quantities and the latest retrieved
   close. If the input gives weights rather than quantities, use them as given
   and say so.
3. A risk decomposition of the book: per-position volatility contribution,
   pairwise correlation structure, realised portfolio volatility, maximum
   drawdown and the dates it ran between.
4. Sector, industry and listing venue for each holding.
5. Where holdings settle in different currencies, the reference rates needed to
   express everything in one currency, with the rate date.

## Method

- Compute every statistic from the price series retrieved on this run. Report
  the exact number of sessions each statistic used.
- A holding whose price history is shorter than the lookback is measured over
  its own available window, and that shorter window is printed beside its
  numbers. Never pad, interpolate, or back-fill a missing series.
- Concentration is reported on three axes at once: single position, sector, and
  listing venue or currency. A book can look diversified on one and be
  concentrated on another.
- Drawdown is stated with both its depth and its date range, and whether the
  book has recovered.
- If the book contains both long and short exposure, say so and state which
  statistics remain meaningful under netting rather than reporting a single
  blended number as if the book were long-only.

## When data is missing

A source that returns nothing, errors out, or is not configured is a fact to
report, not a gap to fill.

- Name every missing item explicitly in a `Data gaps` section, with the reason
  when the failure gave one.
- Continue using only the evidence actually retrieved.
- Never substitute a value from memory, from a general prior, from a
  third-party summary, or from an earlier run of this playbook. A price series
  that did not come back on this run does not enter any calculation.
- Never present a stale figure as current. Print the as-of date of the last
  close used for every holding.
- If a whole section has no evidence, keep its heading and write
  `no data retrieved` under it.
- A holding whose prices could not be retrieved is excluded from the
  statistics, listed by name in `Data gaps`, and its weight is reported as
  unmeasured — never silently dropped and never redistributed across the rest.

## Output

Markdown, in this order:

1. `## Book summary` — number of positions, currencies, as-of date, sessions
   used.
2. `## Exposure` — table of holding, weight, sector, venue, last close, as-of
   date.
3. `## Concentration` — top position weight, top three combined, largest sector
   weight, largest venue or currency weight.
4. `## Risk` — realised volatility, volatility contribution ranking, the most
   correlated pairs, and the same volatility figure for the benchmark.
5. `## Drawdown` — maximum drawdown, its date range, current distance from
   peak; the same for the benchmark.
6. `## Data gaps` — always present; write `none` when nothing was missing.

## Boundaries

- Measurement only. No buy, sell, or hold calls, no price targets, no
  rebalancing instructions, no target weights, no view on any holding.
- Do not place, modify, or cancel any order, and do not touch a live trading
  connector.
- Historical statistics describe the window measured. Do not present them as a
  forecast of future risk.
