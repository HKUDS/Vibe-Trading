---
name: Pre-market Brief
description: Overnight global market moves plus today's watch items, assembled before the home session opens.
markets: [global, cn, hk, us]
suggested_schedule: "30 8 * * 1-5"
suggested_timezone: Asia/Shanghai
data_capabilities:
  - Daily index levels and percentage changes for the major overnight equity sessions
  - Overnight moves in benchmark commodities, major FX pairs and government bond yields
  - Headline news published since the previous home-market close, with publication timestamps
  - Recent daily price and volume history for the symbols on the user's watch list
  - Macro releases and corporate events scheduled for the current date
variables:
  home_market: China A-shares
  watchlist: (no watch list configured)
---

# Pre-market brief

Produce a pre-open briefing for **{{home_market}}**.

Resolve the current date and time from the run environment on every run. This
instruction text is stored once and replayed on every fire, so it contains no
date of its own — never assume the day it was written is the day it is running.

## Inputs

- Home market: {{home_market}}
- Watch list: {{watchlist}}

If the watch list above is empty or says none is configured, skip the
per-symbol section entirely and say so in one line rather than inventing a
list of symbols.

## Data to gather

1. Closing level and percentage change of the major equity indices whose
   sessions ran while the home market was shut, plus the home market's own
   previous close.
2. Overnight change in the benchmark energy and metals contracts, the main FX
   pairs relevant to the home market, and the 10-year government bond yield of
   the home market and of the United States.
3. Headlines published since the previous home-market close that name the home
   market, its index, its regulator, or any watch-list symbol. Keep the
   publication timestamp attached to each headline.
4. For each watch-list symbol: the last close, the change over the last five
   sessions, and volume against its recent average.
5. Anything scheduled for today — macro data releases, central bank events,
   earnings dates, index changes — that falls in the home market's session.

## Method

- Order the report by how much it can move the home session, not by how
  interesting the headline is.
- Separate what moved from why it moved. Only assert a cause when a retrieved
  source states that cause; otherwise report the move and the coincident
  headline as two separate facts.
- A move smaller than the instrument's own recent daily range is noise. Say so
  instead of narrating it.

## When data is missing

A source that returns nothing, errors out, or is not configured is a fact to
report, not a gap to fill.

- Name every missing item explicitly in a `Data gaps` section, with the reason
  when the failure gave one.
- Continue using only the evidence actually retrieved.
- Never substitute a value from memory, from a general prior, from a
  third-party summary, or from an earlier run of this playbook. A number that
  did not come back from a source on this run does not appear in this report.
- Never present a stale figure as current. If the freshest value available is
  older than the window this brief covers, print its as-of date beside it.
- If a whole section has no evidence, keep its heading and write
  `no data retrieved` under it.
- Every figure carries its as-of date and the source it came from.

## Output

Markdown, in this order:

1. `## Overnight tape` — a table of index / commodity / FX / yield, level,
   change, as-of timestamp.
2. `## What changed overnight` — at most five bullets, each tied to a dated
   headline.
3. `## Watch list` — one line per symbol: last close, 5-day change, volume vs
   average, and any dated news naming it.
4. `## On today's calendar` — scheduled releases and events, with local times.
5. `## Data gaps` — always present; write `none` when nothing was missing.

Keep the whole brief under roughly 700 words.

## Boundaries

- This is a factual briefing. No buy, sell, or hold calls, no price targets,
  no position sizing, no leverage suggestions.
- Do not place, modify, or cancel any order, and do not touch a live trading
  connector.
- Do not forecast the day's direction. Report the setup; the reader decides.
