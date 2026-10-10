# Specialized analysis reliability and interaction

User scope: implement all proposed options/factor/correlation improvements and investigate repeated missing-data feedback. Baseline: local commit `3bb01ebe`; no remote publishing requested.

## Confirmed before changes

- Options: invalid edits leave old metrics visible; request generation changes only at dispatch, leaving a debounce race. Charts dispose/init on every data change. At 1280 px the leg editor horizontally clips columns.
- Correlation: matrix and regime fetch separately; Promise.all discards the successful result if either fails. Input edits clear results; no restored page state or observed sample coverage.
- Factors: full-zoo default, unworkable single-asset BTC universe, progress begins after data loading, job id is lost on navigation even while the backend continues. Job stores are process-local.
- Shared market data: empty DataFrames were counted as successful partial results and removed from the fallback queue. US class-share symbols did not match source routing; concatenated crypto could route to China loaders.

## Implemented

- Shared market data treats empty/None frames, including empty resampled frames,
  as missing and continues fallback only for unresolved symbols. US class-share
  routing and USDT alias normalization preserve requested identities; substituted
  providers are attempted once and diagnostics name the actual provider.
  Sanitized attempts and recovery guidance distinguish unavailable sources,
  failed requests and no bars. Explicit-only currency/fallback boundaries remain.
- S&P 500 factor evaluation uses that shared fallback with observed DataFrames.
  Selected fundamental factors load only their declared SEC fields at filing
  dates, preserve missing values and reject unsupported universes before price
  downloads. Both agent/MCP and shared CLI/API paths use this preparation.
- Factor UI evaluates one selected factor or compares a few, checks configured
  readiness, reports loading/computing phases and observed coverage, and warns
  when no factor was evaluable. BTC's single-asset pool is unavailable for these
  cross-sectional evaluations. Request-ID replay avoids duplicate accepted jobs;
  snapshots/SSE and tab-local state recover progress after navigation or reload.
- Correlation matrix and regime use one price snapshot, respect source priority,
  normalize duplicate identities, show actual overlapping observations/dates,
  and keep successful output when the other analysis lacks sufficient data.
- Options and correlation cancel superseded requests and keep previous results
  explicitly labeled. Options charts use the captured result parameters, chart
  instances are reused, advanced inputs are collapsed, and the contract chain
  loads on expansion with 15 contracts per side around the actual quote.
- Drafts/results persist in the browser tab. All new UI strings cover nine locales.

## Verified

- Frontend: 76 test files / 725 tests pass, production build passes, including
  locale parity. Log: `/tmp/vibe-trading-uiux-20261008/analysis-frontend-full.log`.
- Related backend suite: 335 tests pass. After the final empty-resampling fix,
  the 91-test market-data/reliability subset passes (overlapping, not additive).
  Logs: `analysis-backend-final.log` and `final-fallback-tests.log` in the same
  temporary directory. Changed Python files pass Ruff; `git diff --check` passes.
- Actual MarketDataTool requests returned bars for AAPL.US, BRK.B.US,
  600519.SH, 0700.HK and BTCUSDT through Yahoo, Tencent and OKX. The combined
  correlation path returned AAPL/SPY/BRK.B with 30 common observations for
  2026-08-26 through 2026-10-07 and a regime result. These are live provider
  probes, separate from mocked regressions. A final request to the restarted
  latest API returned HTTP 200, 30 common observations from 2026-08-27 through
  2026-10-08, a regime result and no errors.
- Actual single-factor alpha101_001 evaluation for sp500 / 2025-2025 completed:
  503 requested instruments, 500 observed, one evaluated factor. Missing:
  FDXF.US, HONA.US, VYLR.US. The UI listed these and current-roster survivorship
  bias. Navigation/reload recovered the result. After restarting the isolated
  backend with the latest source, the UI still read the saved result; a new
  job `4a84ae13fdf948ffaebb8650e309bec3` reused the panel and completed with the
  same coverage and factor result. Initial progress was 0/1, terminal progress 1/1.
- Actual PIT SEC panel for AAPL.US/MSFT.US returned net_income and
  shares_diluted. This verifies real field retrieval, not a full 503-company
  fundamental benchmark. Health requests stayed responsive during the large
  price fetch (0.5–13.1 ms in five observations).
- Local browser QA: late payoff response/edit races, result restoration,
  correlation partial results, chain 15/15 versus full 60/56 rows, desktop leg
  editor at 1280 px, and no whole-page overflow at 390 px. Stored Chinese/dark
  preferences were preserved. Screenshot: `factor-final.png` in the temporary
  directory. Preview: http://127.0.0.1:5899/.

## Remaining operational limits

- First large-universe download still takes minutes because real public-source
  calls are rate-limited. Scope selection and reuse avoid unnecessary work;
  source throttling and scientific sample gates were not reduced.
- Historical absence, credentials, optional dependencies and provider outages
  can still prevent data retrieval. Diagnostics expose these instead of
  fabricating values. Configured readiness does not promise live availability.
- Job stores remain process-local; restart loses unfinished jobs. Completed
  snapshots are pruned after one hour, while completed tab-local results remain
  readable. New submissions after lost process state can start fresh jobs.
- Current S&P 500 constituents carry survivorship bias. The pre-existing static
  constituent-source date was not independently refreshed in this task.
- No protected agent/session/provider code, live broker action or remote
  publishing was performed. Runtime caches and live probe outputs stayed outside
  the checkout under `/tmp/vibe-trading-uiux-20261008/`.
