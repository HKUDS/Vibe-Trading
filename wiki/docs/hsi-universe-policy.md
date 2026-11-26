# HSI universe: membership policy and real-data smoke

This contribution adds the `hsi` universe and HK data-availability identity to
Alpha Bench/Compare, the API, CLI and existing factor-research selectors.
Quote collectors, MCP quote tools, board-lot/fee engines, FX valuation and
portfolio execution changes are separate follow-ups. This patch does not
change `agent/backtest/engines/composite.py`, providers or broker order gates.

## Source and benchmark eligibility

Wikipedia remains the primary constituent source. Its source timestamp and
revision ID come from the same downloaded HTML as the table; its revision date
is not an effective membership date. Requests fail rather than substitute a
frozen roster, prices, another source or previously cached membership.

The explicit audit reference contains 95 securities, effective September 7,
2026, from [Hang Seng Indexes' August 21 review, Appendix 1](https://www.hsi.com.hk/content/dam/wpb/hsil/en_hk/press_releases/content/20260821_press_release_e.pdf).
November 4, 2026 is the retained snapshot date, not the review effective date.
The source/ref dates are separately reported. The reference must be reviewed
after index changes; a mismatch alone does not prove which source is current.

| Observed source | Benchmark behavior |
| --- | --- |
| 95 unique canonical symbols, exact dated-reference set, revision provenance present | Eligible to request prices. At least two usable price histories are required; partial price coverage is disclosed and marked degraded. |
| Count differs from 95 | Reject with `count_mismatch` before price/cache access. |
| 95 symbols, but at least one missing reference name and one unexpected name | Reject with `membership_mismatch` before price/cache access. `constituent_reference_matches=false`, `degraded=true`, `benchmark_eligible=false`. |
| Invalid/duplicate symbols, ambiguous table, missing revision provenance, or source failure | Reject with a sanitized constituent error. |

**Equal counts are insufficient.** The earlier PR allowed the third case to
continue with a degraded flag. Policy `strict_dated_reference_v4` now blocks it.
The loader neither changes the source's symbols nor claims that the old list
is correct: maintainers must reconcile official effective-date evidence and
update the reference and tests before a new set becomes eligible.

Current constituents are survivorship-biased, not point-in-time membership.
No historical-index reconstruction, adjustment harmonization, currency
conversion or trading-cost simulation is implied by loading the universe.

## Cached prices and price semantics

HSI revalidates the current roster before any price-cache lookup. Its v4 cache
identity includes the symbol set, source revision/content digest and dated
reference. Legacy HSI caches cannot bypass the eligibility gate. Other
universes' cache behavior is unchanged.

The existing HK loader/fallback chain supplies provider-native OHLCV. Small
five-name batches fit the shared gateway's bounded acquisition jobs; the
original 95-name job exhausted that deadline in the initial smoke attempt.
The HSI adapter joins observed provider dates without filling cells or scaling
volume; shared upstream adapters may already drop incomplete OHLC and fill
missing volume with zero. Metadata reports observed cells, per-symbol sources,
adjustment bases, volume units, missing instruments and available sector labels.
The OHLC average is labelled a VWAP proxy, not an actual traded VWAP. XHKG/HKD
identity is reported without reindexing to fabricated exchange sessions.

## Dated real-data check: November 25, 2026, America/Los_Angeles

Prepared against upstream `2134f408b1cd715c74fa8c5021f4402d50b00ea8`.
See the [sanitized JSON evidence](hsi-universe-smoke-2026-11-25.json). It contains
counts, identifiers and provenance, never returned prices, tokens or account
settings. The run started November 25 at 22:57 PST (November 26, 06:57 UTC).

| Real-data case | Constituents | Price coverage, November 2–24 inclusive | Usable? |
| --- | --- | --- | --- |
| Production Wikipedia path, revision 1377881667, source timestamp October 1 | 85 observed; 84 overlap with the 95-name reference; 11 missing and one unexpected (`0881.HK`) | Not attempted: roster rejected first | **No benchmark**: blocked by count/reference validation. |
| Explicit dated-reference price diagnostic | 95 frozen reference names; not substituted into production | 95/95 histories, 17 observed dates, 1,615 nonmissing close cells; no missing OHLCV cells on that observed union | Usable only as evidence that the price path works; **not a benchmark or membership certification**. |

The diagnostic reported Tencent as its price source, raw price adjustment and
volume in shares. Raw prices need adjustment-basis review before return-based
research. Zero missing cells on observed dates does not prove complete calendar
coverage, and does not undo upstream volume filling. No factor, strategy, IC,
Sharpe, order, quote collector or deployment was run.

The successful 95-name price diagnostic does **not** make the rejected
85-member Wikipedia universe usable. In particular, no successful real HSI
benchmark is claimed by this contribution. Synthetic 95-name tests verify the
accept/reject behavior only and are not substituted for this evidence.

Reproduce from the repo root with project dependencies installed:

```bash
PYTHONPATH=agent VIBE_TRADING_HOME=/tmp/hsi-smoke-review python -m src.tools.hsi_smoke --start 2026-11-02 --end 2026-11-24 --reference-diagnostic --output /tmp/hsi-smoke-review.json
```

This makes public network requests and uses an isolated runtime directory. The
reference diagnostic is explicit, does not enter the factor runner/cache, and
always has `benchmark_eligible=false`. The command exits nonzero while the
production roster is blocked even if that diagnostic succeeds. A rerun may
observe different provider/source results; preserve the dated evidence above.

## Local verification and follow-up split

On the prepared Python 3.14 checkout, 1,148 targeted backend tests passed with
23 skips; 1,059 frontend tests and the TypeScript/production frontend build
passed. Scope includes existing alpha/compare/cache/universe contracts, the
HSI gate, provenance and UI registration. These local checks do not replace
the PR's Python 3.11, platform lifecycle, hash-lock or remote CI checks.

The earlier quote/market-layer implementation, including Monday's
`d76826ff` fixes for HK sessions, lot fallback and historical FX, is preserved
separately before the HSI-only split. It should be reviewed in another PR.
No history rewrite or force-push is needed to update the existing PR: merging
current main and narrowing the final diff preserves all earlier commits.
