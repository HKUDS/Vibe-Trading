---
name: A-Share Money Flow Review
description: Post-close A-share flow review — exchange public trading disclosures, northbound flows, sector money flow and the limit-up board.
markets: [cn]
suggested_schedule: "0 19 * * 1-5"
suggested_timezone: Asia/Shanghai
data_capabilities:
  - Exchange daily public trading disclosures naming the top buying and selling seats for each listed stock
  - Northbound Stock Connect flow figures for the session
  - Per-stock and per-sector money flow broken down by order size
  - Margin financing and securities lending balances by stock and in aggregate
  - Sector and industry performance rankings for the session
  - Daily price, volume and turnover history for individual A-share tickers
variables:
  watchlist: (no watch list configured)
---

# A-share money flow review

Review where money actually went in the A-share session that just closed.

Resolve the current date from the run environment and confirm the session date
from the retrieved data itself. On a holiday or a half-day the newest available
session may not be today — say which date the report covers, and say it in the
first line.

## Inputs

- Watch list: {{watchlist}}

The watch list only adds a final cross-reference section. The rest of the
report is market-wide and runs with or without it.

## Data to gather

1. The exchange's daily public trading disclosures for the session: which
   stocks qualified, why they qualified, and the top buying and selling seats
   on each, with amounts.
2. Northbound Stock Connect flow for the session, at whatever granularity the
   source actually publishes.
3. Money flow by order size, both at the sector level and for the day's most
   active names.
4. Margin financing and securities lending balances for the session, in
   aggregate and for any name that moved sharply.
5. Sector and industry performance for the session, ranked.
6. The stocks that closed at their daily price limit, up or down, and the
   turnover and time-to-limit information the source provides.
7. For each watch-list symbol, its session return, turnover, and whether it
   appeared in any of the above.

## Method

- A-share boards apply different daily price limits, and stocks under special
  treatment apply a different one again. Determine the applicable limit for a
  stock from the retrieved data rather than assuming one number for the whole
  market, and state which board each limit-up name trades on.
- Seat-level disclosures identify a counterparty channel, not an investor.
  Describe what the disclosure literally shows — this seat bought this amount —
  and do not name or characterise who sat behind it.
- If the northbound source publishes only end-of-day aggregates, use the
  aggregates and say so. Do not reconstruct an intraday path from an end-of-day
  number.
- Cross-check the day's story: a sector leading on performance but not on money
  flow, or a limit-up name with no matching flow, is worth one line as a
  contradiction rather than being smoothed over.
- Report flow in the currency and unit the source used, and label the unit.

## When data is missing

A source that returns nothing, errors out, or is not configured is a fact to
report, not a gap to fill.

- Name every missing item explicitly in a `Data gaps` section, with the reason
  when the failure gave one.
- Continue using only the evidence actually retrieved.
- Never substitute a value from memory, from a general prior, from a
  third-party summary, or from an earlier run of this playbook. A flow number
  that did not come back on this run does not appear in this report.
- Never present a stale figure as current. Several of these disclosures are
  published at different times after the close; if the newest available record
  is from a previous session, print its date beside it and label it as the
  previous session, not as today.
- If a whole section has no evidence, keep its heading and write
  `no data retrieved` under it.
- Every figure carries its session date, its unit, and the source it came from.

## Output

Markdown, in this order:

1. `## Session` — the date this report covers and the index closes for it.
2. `## Northbound` — the flow figures retrieved, with their granularity stated.
3. `## Sector flow` — ranked table: sector, session return, net flow, unit.
4. `## Public trading disclosures` — per stock: reason it qualified, top buy
   seats, top sell seats, net.
5. `## Limit board` — limit-up and limit-down names, board, turnover, and the
   sector they cluster in if they cluster at all.
6. `## Margin balances` — aggregate change and any notable per-stock change.
7. `## Watch list cross-reference` — omit when no watch list was supplied.
8. `## Data gaps` — always present; write `none` when nothing was missing.

## Boundaries

- Factual review of one session. No buy, sell, or hold calls, no price
  targets, no next-day predictions.
- Do not place, modify, or cancel any order, and do not touch a live trading
  connector.
- Do not attribute flows to a named institution, fund, or individual. Report
  the disclosed channel and amount.
- Concentrated buying is an observation, not a signal. Say what was disclosed
  and stop there.
