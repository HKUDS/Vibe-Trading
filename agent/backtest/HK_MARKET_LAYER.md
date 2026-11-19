# Hong Kong market layer

Authors: @Jampip, @Joshuaamm7, @james-mulyono, @jaz024, @prs-016.

HK calendar, lot-size and fee extensions for the existing backtest interfaces.
FX valuation consumes explicitly supplied historical observations; a multicurrency
cash ledger and executable FX conversion are separate future work.

## Calendar choice and execution boundaries

Reuse the existing `exchange-calendars>=4.13.2,<5` dependency and existing
`src.data_gateway.calendars.schedule/validate` interface. No new calendar library
is added. XHKG normal sessions are 09:30–12:00 and 13:00–16:00 HKT; half-days
and holidays come from the library. XNYS remains available for alignment.
`validate` rejects lunch bar opens, missing bars, duplicates and extra sessions;
callers must supply the actual bar timezone and bar-open semantics. Calendar
validation does not fabricate missing prices or make them executable.

Auditing installed version 4.13.2 found these missing historical exceptions, now
corrected by `src/data_gateway/hk_sessions.py`:

- August 2 and October 21, 2016; August 23, 2017; July 17, September 1 and
  September 8, 2023: full closures.
- October 9, 2023: opens at 14:00 HKT, with no lunch segment remaining.

Each override links to the relevant HKEX or official SSE Stock Connect notice.
This is an explicit, limited correction inventory, not certification of every
historical weather event. Any further evidenced exceptions should be added as
dated records with tests. Existing library holidays are retained.

[HKEX's approved reform](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2024/CT14824E.pdf)
took effect September 23, 2024: ordinary typhoon/black-rain signals no longer
imply closure. Do not apply the old weather rule to current sessions. Exceptional
future closure notices still require an evidenced override. Intraday validation
and the portfolio execution clock remain distinct: B6 must use the same schedule
for executable orders as well as data checks.

## Dated board lots and actual engine duty

The included `agent/backtest/data/hk_board_lots_20261112.csv` contains the 95-name
operational HSI roster's lot sizes, selected from the unchanged November 12 HKEX
[List of Securities](https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx)
snapshot. Each row retains retrieval time, source URL and original workbook hash.
This reference roster differs from the current Wikipedia loader's observed
85-name table; B3 does not silently substitute constituent sources.

Pass `hk_lot_sizes_file` in a run config, using a path visible to the engine:

```json
{"hk_lot_sizes_file": "backtest/data/hk_board_lots_20261112.csv"}
```

The file is mutually exclusive with `hk_lot_sizes`. File-backed sizing requires
every traded symbol to have a lot and fails on a missing one; it does not assume
100. Existing in-memory maps keep their prior default unless
`hk_require_lot_sizes: true` is set. Snapshot provenance appears in engine
`hk_board_lot_snapshot` diagnostics and sets `historical_lots_verified: false`.

Retrieval date is not an effective-from date. Using this table in 2016–2026
research is an explicit current-lot assumption, not verified historical lot
sizes. Future reviews and changes need a fresh dated snapshot. This CSV is not
an historical constituent-membership database.

`GlobalEquityEngine.calc_commission` now applies whole-HKD ceiling to duty on
both bought and sold notes. The default is 0.1% from September 1, 2001, 0.13%
August 1, 2021–November 16, 2023, and 0.1% from November 17, 2023.
[IRD history](https://www.ird.gov.hk/eng/pdf/sd_stock_rates.pdf),
[the 2023 change](https://www.ird.gov.hk/eng/ppr/archives/23111501.htm) and
[HKEX's bilateral rounding rule](https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-%28Hong-Kong%29/Trading/Transaction?sc_lang=en)
are cited in the implementation. Before September 2001 an explicit researched
`hk_stamp_tax` override is required. Undated direct method calls retain today's
0.1% default; actual engine fills carry their session timestamp. An explicit
`hk_stamp_tax` run override remains available and is still rounded.

Hand calculation: 255 desired Tencent shares round down to 200 with lot 100;
at HKD100.01 the HKD20,002 consideration incurs duty of ceil(20,002×0.0013)=HKD27
on November 16, 2023 and ceil(20,002×0.001)=HKD21 on November 17, on each side.
The other existing engine fees and slippage are retained unchanged. This is not
certification of historical levy schedules, stamp-duty exemptions, short-sale
eligibility, non-HKD counters or fee aggregation across multiple fills.

Composite commission dispatch now synchronizes its current bar timestamp to
the market engine. The existing India T+1/price-band routing is unchanged and
its related tests pass. No India fee implementation is duplicated here.

## Previous-close FX valuation contract

`backtest.market_layer.previous_close_fx` takes a daily FX-observation table
with timezone-aware `close_at`, `available_at` and positive `rate` columns.
Rates are **HKD per USD** for HK portfolios. A caller may acquire `HKD=X` via
`src.market_data.fetch_market_data(..., include_provenance=True, as_frames=True)`;
retain the provider's price/time provenance. Daily date labels alone do not
prove the close or publication instant. Establish those source semantics before
constructing this observation table, or leave USD evaluation unavailable.

For each valuation instant, select the latest close with BOTH timestamps
strictly earlier than valuation. Missing or older-than-configured rates fail
closed (default maximum age seven days). Weekend carry is permitted within that
limit; future/backward filling is not. Returned rows include the selected close
and availability timestamps for audit. The HKD peg is not treated as a fixed7.8.

`local_and_usd_returns` divides the same local portfolio value by its selected
HKD-per-USD rate, then computes local and unhedged USD returns side by side.
The first return is missing. It neither adds local and FX returns nor changes
native input price/volume units. Source adjustment consistency still needs to
be established by the caller. The same utility can consume INR-per-USD
observations supplied by Jamal; this patch does not acquire or certify them.

These utilities are offline and dependency-injected. They do not ship a verified
historical FX dataset or infer historical publication times. B4/B5 must reject a
requested USD metric when no compliant observations are supplied. They also do
not implement an FX cash ledger, hedge returns, executable FX trading, or the
multicurrency portfolio mode proposed in B6.

## Local verification

Verified against upstream `d4bce9b28205d61a81e5a5346bd659433312069c` on November 19, 2026.
188 tests passed in ten selected files, including the 35 new HK cases, with
socket and DNS calls prohibited and zero attempted calls. Exact commands and
raw output accompany the contribution package. The tests cover holiday/weather
closures, late-open and half-day sessions, lunch rejection, prior FX close and
publication-time causality, missing/stale/invalid FX, USD conversion direction,
dated lot coverage, both duty-rate boundaries, whole-dollar hand calculation,
composite timestamp routing and existing India/composite/FX currency guards.

Scoped Ruff passes for all six changed/new Python files. Only the three new
Python files were Black-formatted; unrelated upstream files were not reformatted.
