---
name: Earnings Season Tracker
description: Upcoming earnings dates for held and watched names, plus what changed in expectations and in the last reported quarter.
markets: [us, cn, hk, global]
suggested_schedule: "0 7 * * 1-5"
suggested_timezone: America/New_York
data_capabilities:
  - Scheduled and confirmed earnings dates for a given list of symbols
  - Reported income-statement and cash-flow lines for recent fiscal periods, with the filing or announcement date
  - Regulatory filings and company announcements covering results, guidance and pre-announcements
  - Analyst estimate and rating changes with the date each change was published
  - Recent daily price and volume history around the reporting dates
variables:
  universe: (no holdings or watch list configured)
  horizon_days: "14"
---

# Earnings season tracker

Track the reporting calendar and the expectation drift for **{{universe}}**
over the next {{horizon_days}} days.

Resolve the current date from the run environment. This text is stored once and
replayed on every fire, so the reporting window must be computed at run time,
never read off this page.

## Inputs

- Universe: {{universe}}
- Horizon: {{horizon_days}} calendar days forward from the run date

If the universe above is empty or says none is configured, stop after saying so
in one line. Do not substitute an index, a sector, or a set of well-known
tickers.

## Data to gather

For each symbol in the universe:

1. The next earnings date, and whether it is confirmed by the company or is an
   estimate. Keep that distinction — it is the single most misread field on
   any earnings calendar.
2. The fiscal period that will be reported, and the date the previous period
   was reported.
3. The revenue, operating income, net income and operating cash flow of the
   last two reported periods, each tagged with the date the figures were filed
   or announced.
4. Any consensus estimate for the coming period, with the date the estimate was
   last revised, plus rating or target changes published since the previous
   report.
5. Company announcements since the previous report that touch guidance:
   pre-announcements, revisions, profit warnings, restatements.
6. The symbol's price change and volume over the twenty sessions before the run
   date.

## Method

- Sort by earnings date ascending. Names reporting inside the horizon come
  first; the rest go into a short tail section.
- Report expectation drift as a delta between two dated observations, never as
  a level. "Consensus EPS revised from X on date A to Y on date B" is usable;
  "consensus is Y" is not.
- Where the last reported period contains a one-off (disposal, impairment,
  tax item) that a filing calls out, say so beside the growth figure.
- Do not compute a surprise number unless both the reported figure and the
  pre-report estimate were actually retrieved on this run.

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
  older than the window this report covers, print its as-of date beside it.
- If a whole section has no evidence, keep its heading and write
  `no data retrieved` under it.
- Every figure carries its as-of date and the source it came from.
- An earnings date that could not be retrieved is listed as unknown. Do not
  infer it from the previous year's reporting pattern.

## Output

Markdown, in this order:

1. `## Reporting inside the horizon` — a table: symbol, date, confirmed or
   estimated, fiscal period, 20-day price change.
2. `## Expectation changes` — one bullet per dated revision, most recent first.
   Omit the section body and write `none retrieved` if nothing was found.
3. `## Last reported quarter` — per symbol, the two-period comparison of the
   lines gathered above, with filing dates.
4. `## Announcements since last report` — dated, one line each.
5. `## Reporting after the horizon` — symbol and date only.
6. `## Data gaps` — always present; write `none` when nothing was missing.

## Boundaries

- Factual tracking only. No buy, sell, or hold calls, no price targets, no
  view on whether a name will beat or miss.
- Do not place, modify, or cancel any order, and do not touch a live trading
  connector.
- Do not model a future quarter. This playbook reports what has been filed and
  what estimates have been published, and nothing else.
