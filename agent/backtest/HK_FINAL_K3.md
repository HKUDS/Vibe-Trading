# Final-week HK market-layer contract

This local K3 revision extends the existing HK implementation. The original
Vibe application, US rules and India rules remain in place. It implements the
HK side; it is not evidence that Jamal's India half has been combined or that
a joint upstream PR, remote CI or team acceptance has completed.

## Actual execution clock

HK fills and forced terminal closes use the sourced XHKG schedule already
used for data validation. A lunch bar, holiday bar, known historical full
closure or half-day afternoon cannot execute. Intraday intervals use bar-open
instants; timezone-aware bars convert to HKT and the normalized loader's naive
HK bars are interpreted in HKT. Daily, weekly and monthly bars must carry an
actual session-date label. They are not executed at a fabricated midnight
clock time. The current run interval is synchronized through composite
dispatch; the rule provider does not use a stale parent timestamp.

The existing historical correction inventory is exposed as
`weather_closure_inventory()`: `date`, `session` (`full` or `morning`), source,
and the restart time for the delayed-open record. It includes the six sourced
full closures in 2016, 2017 and 2023, plus October 9, 2023's 14:00 restart.
It is a limited, explicit inventory, not complete historical certification.

The [HKEX severe-weather reform](https://www.hkex.com.hk/services/trading-hours-and-severe-weather-arrangements/severe-weather-arrangements/overview?sc_lang=en)
started September 23, 2024. Ordinary weather overrides dated on or after that
date are ignored. The September 24, 2025 session remains a trading session;
the [HKEX reminder](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_132_2025.pdf)
documents the policy continuing during the 2025 storm season. A separately
announced exceptional exchange closure is a different policy, not an automatic
weather rule.

`audit_hsi_session_coverage(hsi_daily, start, end, provenance=...)` accepts
actual daily `^HSI` close bars and their loader provenance. Known sourced
closures are already absent from its expected sessions. Other missing
pre-reform bars are reported as unverified closure candidates; missing
post-reform bars are data gaps. Unexpected benchmark sessions are also
reported. A failed provider request is not silently relabelled a market
closure. Further closure candidates need a dated source before changing the
calendar.

## Board lots and duty

Explicit per-symbol lots round down and leave the unused notional as cash.
For Tencent's supplied 100-share lot, a request for 250 shares sizes to 200.
Missing lots use one share with one warning and a reported `lot_assumptions`
entry. Strict callers may opt into `hk_require_lot_sizes: true` to reject gaps.

The dated CSV reader retains its required retrieval timestamp, source URL,
and source hash. A present-day table is not a historical lot-size database.
The previously supplied 95-row CSV is preserved locally; no new source table
is downloaded or added by this revision. Its redistribution rights are not
established: [HKEX terms](https://www.hkex.com.hk/global/exchange/terms-of-use?sc_lang=en)
restrict copying, automated access and redistribution without permission.
Before publication, the existing PR's table requires a maintainer/rights
decision or replacement with an operator-provided file. A source citation
and hash alone do not grant republication permission.

Ordinary HKD-equity stamp duty is applied separately to each buy and sell
note, rounding the duty up to a whole HK dollar:

| Trade date | Rate per side |
|---|---:|
| September 1, 2001 through July 31, 2021 | 0.10% |
| August 1, 2021 through November 16, 2023 | 0.13% |
| November 17, 2023 onward | 0.10% |

Earlier dates require an explicitly researched override. The
[IRD rate history](https://www.ird.gov.hk/eng/pdf/sd_stock_rates.pdf) and
[November 2023 commencement notice](https://www.ird.gov.hk/eng/ppr/archives/23111501.htm)
support the boundaries; the latter specifies commencement on November 17.
Exempt instruments and non-HKD counters need their own declared treatment.

The engine's existing `hk_commission`, `hk_levy`, `hk_settlement` and slippage
inputs retain their configured numerical behavior. They are flat assumptions,
not a certified dated schedule for HKEX, SFC, AFRC, broker or CCASS charges.
The old SFC/FRC label on `hk_levy` has been removed because its default does not
represent a validated sum. Those statutory schedules, settlement minimums/caps,
FX spread and transfer fees are not newly claimed as modelled by this patch.
The separate dashboard estimate can expose current sourced charges and broker
inputs; it must not be presented as this backtest's historical cost model.

## Daily FX acquisition and no look-ahead

`load_hkd_fx_observations` uses Vibe's existing shared loader to request
`HKD=X`, source `yfinance`, interval `1D`, complete frames and provenance.
The resulting rate is HKD per USD. Each daily label needs an explicit
`availability_policy(label, provenance)` returning aware `close_at` and
`available_at` timestamps. There is no default guessed publication time.

`hk_equity_to_usd` accepts an HKD equity series indexed by actual, aware HK
valuation instants, verifies its session dates, acquires the FX, then uses
the strictly prior close and publication-time selection. Rates carry forward
over a weekend or holiday within the configured maximum age; they never
backfill a missing first valuation. USD equity is HKD equity divided by the
selected rate; USD returns are computed from that equity path, not by adding
local returns to an FX rate. The first return remains missing.

Example conservative policy, after the caller has established a table of real
source completion/publication times (`completion`) and retained its evidence:

```python
import pandas as pd
from backtest.market_layer import hk_equity_to_usd
from src.data_gateway.calendars import schedule

def after_next_hk_open(label, provenance):
    # completion is caller-supplied, indexed by the provider's daily labels.
    row = completion.loc[label]
    close_at = pd.Timestamp(row["close_at"])
    published_at = pd.Timestamp(row["available_at"])
    if close_at.tzinfo is None or published_at.tzinfo is None:
        raise ValueError("Source completion times must be timezone-aware")
    day = close_at.tz_convert("Asia/Hong_Kong").date()
    end = (pd.Timestamp(day) + pd.Timedelta(days=14)).date()
    frame = schedule("hk_equity", str(day), str(end))[2]
    next_open = frame.loc[frame["open"] > close_at, "open"].iloc[0]
    return close_at, max(published_at, next_open)

usd_curve = hk_equity_to_usd(
    equity_hkd, availability_policy=after_next_hk_open
)
```

The conservative next-open delay does not invent the source's actual close.
Values at that exact availability instant still use the previous known rate;
the selector requires strict prior availability. The output retains source and
policy provenance and reports `publication_times_certified: false`. Policy
injection is not independent verification of the supplied dataset. If the
source's completion/publication semantics are unknown, the USD research result
must remain unavailable. No strategy or frozen test is rerun by this change.

## Local checks and external acceptance

The tests exercise actual single/composite engine gating and a fill ledger,
all three half-day types, the 2025 severe-weather session, lot rounding and
fallback disclosure, duty boundaries, a mocked shared-loader-to-USD-curve
integration, missing initial FX, invalid timing policy, and HSI coverage gaps.
Adjacent US/India/UK, routing and existing FX behavior are checked separately.
The scratch handoff contains the exact test output and patch hashes.

External items remain: Jamal's actual India code and interface agreement,
the shared signed-off B3 PR, remote CI, team-chat posting, historical FX source
semantics, and the board-lot CSV publication decision. This local revision
does not complete those actions or deploy AWS resources.
