---
name: Institutional Holdings Diff
description: Quarter-over-quarter position changes disclosed by institutional managers, diffed for a chosen set of managers or symbols.
markets: [us]
suggested_schedule: "0 9 15 2,5,8,11 *"
suggested_timezone: America/New_York
data_capabilities:
  - Quarterly institutional holdings disclosures filed with the U.S. securities regulator, per manager and per reporting period
  - Filing index lookup that returns the filing date and the period the filing covers
  - Company profile and share-count reference data for the disclosed symbols
  - Daily price history covering the disclosed period and the interval since it ended
variables:
  managers: (no managers specified)
  symbols: (no symbols specified)
---

# Institutional holdings diff

Diff the two most recently disclosed quarters of institutional holdings for
the managers and symbols below.

Resolve the current date from the run environment, then determine which
reporting periods are actually available from the filings you retrieve. Do not
assume a period is available because the calendar says it should be.

## Inputs

- Managers: {{managers}}
- Symbols: {{symbols}}

At least one of the two must be supplied. If both are empty, stop and say so in
one line — do not substitute a list of famous investors or a market-wide scan.
When managers are given, diff each manager's whole book. When only symbols are
given, diff the disclosed holders of those symbols.

## Data to gather

1. For each manager, the two most recent quarterly holdings disclosures: the
   period each one covers, the date each one was filed, and whether it is an
   original filing or an amendment.
2. The full position list from each of those two filings — symbol, share count,
   disclosed value.
3. For symbols that appear in the diff, the current share count and basic
   company reference data.
4. Price history spanning the disclosed period and the interval between the
   period end and the run date.

## Method

- These filings are due within 45 days of the quarter end. Every position
  therefore describes the manager's book **as of the period-end date**, not as
  of today. Print the period-end date in the report header and repeat it in any
  section that states a position size.
- Classify each change as new, exited, increased, reduced, or unchanged, using
  share counts rather than disclosed values — value moves with price and will
  otherwise be mistaken for activity.
- Report value changes separately, and split them into the part explained by
  the price move over the period and the residual.
- Check for share splits between the two periods before comparing share counts.
  If a split occurred and the filings are not adjusted for it, say so and do
  not report a mechanical change as a position change.
- An amended filing supersedes the original for the same period. Use the latest
  amendment and say that you did.
- These disclosures cover only the security types the rule requires — broadly,
  U.S.-listed equity and certain related instruments. Short positions, cash,
  non-U.S. listings and most derivatives are not disclosed here. State this
  limitation once in the report rather than presenting the filing as the
  manager's full book.

## When data is missing

A source that returns nothing, errors out, or is not configured is a fact to
report, not a gap to fill.

- Name every missing item explicitly in a `Data gaps` section, with the reason
  when the failure gave one.
- Continue using only the evidence actually retrieved.
- Never substitute a value from memory, from a general prior, from a
  third-party summary, or from an earlier run of this playbook. A holding that
  did not come back from a filing on this run does not appear in this report.
- Never present a stale figure as current. Every position line carries the
  period-end date of the filing it came from.
- If only one period could be retrieved for a manager, report that single
  period as a snapshot and explicitly state that no diff was possible. Do not
  diff against remembered or assumed prior holdings.
- If a whole section has no evidence, keep its heading and write
  `no data retrieved` under it.

## Output

Markdown, in this order:

1. `## Coverage` — the managers and symbols actually resolved, the two periods
   compared, and each filing's filing date and amendment status.
2. `## New positions` — table: manager, symbol, shares, disclosed value.
3. `## Exited positions` — same columns, from the earlier period.
4. `## Increased` and `## Reduced` — table: manager, symbol, share change,
   percent change in shares, value change, price change over the period.
5. `## Concentration` — each manager's top holdings by disclosed value in the
   later period, and how that share shifted between periods.
6. `## Limitations` — the as-of lag and the instrument-coverage limitation,
   stated in two lines.
7. `## Data gaps` — always present; write `none` when nothing was missing.

## Boundaries

- Factual diff of public filings. No buy, sell, or hold calls, no price
  targets, no reading of intent into a manager's trade.
- Do not place, modify, or cancel any order, and do not touch a live trading
  connector.
- Do not describe a disclosed position as a current position. The lag between
  the period end and the run date is the single most important caveat in this
  report; keep it visible.
