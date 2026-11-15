# Gateway validation — 2026-11-14 (Asia/Singapore)

Branch `codex/data-gateway`, based on local main
`283e300e407a94eeaa82821f791f83a969b11dc1`. The initial sections describe the
pre-history-store implementation; the follow-up below supersedes its open items.
No push, deployment, protected Agent/provider/session-core change, options UI
change or trading operation was performed.

## Main's existing free sources

Ran the existing `backtest.loader_health` lane against that exact main checkout:
14 source canaries, two concurrent isolated child processes, 25 seconds/source,
no API keys, no loader data cache, freshness evaluated for 2026-11-14. The lane
correctly returned nonzero because three sources were not healthy. No failures
were converted to passing skips.

| Source | Observed result | Latest bar / detail |
| --- | --- | --- |
| AKShare | Healthy | 2026-11-13 |
| BaoStock | Healthy | 2026-11-13 |
| Binance | Healthy | 2026-11-13 |
| CCXT | Healthy | 2026-11-13 |
| Eastmoney | Invalid | Empty frame, two attempts; cause not established |
| Nobitex | Healthy | 2026-11-13, Toman pair |
| OKX | Healthy | 2026-11-12 |
| pykrx | Timeout | Exceeded this run's 25-second budget |
| Sina | Healthy | 2026-11-12 |
| Stooq | Invalid | Loader reported anti-bot challenge and 300-second cooldown |
| Tencent | Healthy | 2026-11-13 |
| Wallex | Healthy | 2026-11-13, Toman pair |
| Yahoo | Healthy | 2026-11-13 |
| yfinance | Healthy | 2026-11-13 |

Registry coverage errors: none. Existing exclusions remain: local files, the
local B3 COTAHIST store, and retired mootdx protocol. These are one-symbol daily
canaries on this machine's network, not verification of every symbol, interval,
market or country. Yahoo/yfinance share an upstream; CCXT defaults to Binance;
AKShare aggregates multiple origins. Library count is not independent-feed count.

## Live gateway paths

- POST `/data/bars`: AAPL.US, 601398.SH, 00700.HK, BTC-USDT returned HTTP 200,
  complete=true in 4.03 seconds. Observed providers Yahoo/Tencent/Tencent/OKX;
  shares vs lots, USD metadata and differing adjustments were preserved.
- GET `/data/options?full=true&ticker=AAPL`: 82 calls and 82 puts returned;
  reported totals matched and complete_expiration=true. Public source quality
  remains delayed/unknown, not execution-quality market data.
- CLI `watch crypto:BTC-USDT`: received actual public WebSocket ticker events.
- Injected WebSocket connection failure with the real REST adapter: received an
  OKX `rest_poll` snapshot, source age 0.522 seconds. This proves the recovery path
  against a real endpoint, not a naturally occurring geographic outage.
- Initial 90-second SSE run: two clients shared three topics, 179 snapshot events
  per client. After both disconnected, clients/topics/pending updates were zero.
  Sampled RSS was 20–63 MiB.
- Final 30-second run after historical integration: two clients shared four topics
  (BTC, ETH, AAPL options, HK daily bars), 62 snapshots per client. Both WebSocket
  and REST/bar delivery were observed. RSS samples were 91,360 / 40,432 / 40,352
  KiB; after disconnect, all subscription counts were zero. Serialized memory
  cache was 58,874 bytes and disk cache 64,757 bytes in that run.

RSS is OS-reported resident memory, not total allocation or a universal upper
bound; macOS can compress/page memory. These short runs demonstrate continuing
updates and bounded pending state, not a multi-day leak guarantee. Silent idle
cache deletion and repeated subscribe/cancel lifetime checks are additionally
covered by deterministic tests with shorter test-only time thresholds.

An initial bar-wrapper integration failed because the real loader's
`is_available()` is an instance method. It was corrected to instantiate the
loader, covered by an instance-method test, and the real four-market HTTP path
was rerun successfully. Earlier failed bar requests are not claimed as passes.

## Architecture boundary

The framework can continually refresh bars across existing supported markets.
It cannot create unavailable realtime equity/options entitlements. A snapshot
source remains a snapshot source. No global full-market firehose or permanent
tick database is enabled; subscribe only to the desired topics. Model/Agent
analysis remains separate from deterministic source selection and data quality.

## Silent idle cleanup

The running loopback service was observed with 64,757 bytes in four disk cache
entries after the live run. A later read-only `/data/status` returned zero disk
entries, zero memory entries, zero active requests and an empty health table,
without a manual prune call. Default limits are 8 MiB serialized RAM cache and
64 MiB disk cache; idle memory is evicted after 120 seconds plus at most one
30-second cleanup interval, and disk entries expire after 900 seconds plus a
cleanup interval. These are cache bounds, not a total process-memory ceiling.

Final cleanup/stream test group: 32 passed (20.27 seconds). The lifetime test
subscribes and cancels 100 times with distinct 100 KB payloads; all 100 weak
references are gone after unsubscribe, without forcing global garbage collection.
The earlier historical fallback test failed because both the intentionally slow
source and the healthy normalizer exceeded its test-only 0.3-second source wait.
It now injects a deterministic connection failure and uses normal gateway limits;
the separate real-timeout test still checks occupied worker slots and refusal to
spawn replacements. Production timeout limits were not increased.

Final routing/API/options-tool group: 18 passed (25.23 seconds), with one
existing Starlette TestClient deprecation warning. Together the final scoped
groups passed 50 tests. Ruff and `git diff --check` also passed. A combined run
including the main API options suite was interrupted during prolonged dependency
import/GC; it is not reported as a completed final run.

## Longer soak and extreme history requests (2026-11-14)

A first long run stopped at 20.81 minutes when the chat/tool session was
interrupted; no idle tail was observed, so it is not a completed 30-minute pass.
It logged two client ReadErrors without matching server tracebacks. The fault
injector also allowed a WebSocket handshake already in flight to finish during
an outage. A second complete run uses post-handshake validation, rejection of
in-flight REST replies during total outage, and drops buffered WebSocket events
while faulted. It still distinguishes retained/replayed snapshots from newly
received upstream events. The completed second-run results are recorded below.

Multi-year live requests against the first measured process:

| Request | Source rows | Preview rows | Observed source |
| --- | ---: | ---: | --- |
| AAPL, 5 years daily | 1,255 | 628 | Yahoo |
| AAPL, 10 years daily | 2,513 | 839 | Yahoo |
| AAPL, 10 years weekly | 522 | 522 | Yahoo |
| AAPL, 10 years monthly | 121 | 121 | Yahoo |
| 00700.HK, 5 years daily | 1,232 | 617 | Tencent |
| 601398.SH, 10 years daily | 2,428 | 810 | Tencent |

These six requests took 0.45–2.00 seconds each; the sampled macOS physical
footprint changed from 140,690,176 to 142,820,096 bytes during them. Concurrent
subscriptions were active, so this is not an isolated attribution of all memory
to those requests. All observed first/last bars were recorded. Sampling is
explicit; previews are NOT full backtest datasets.

A ten-symbol/five-year/5m HTTP request returned 422 because the synchronous
endpoint accepts at most eight symbols. It was not silently shortened. There is
no multi-symbol persistent history-job implementation yet.

The separate synthetic capacity experiment generated/scanned 982,800 OHLCV rows
(10 US stocks × assumed 5 years × 252 sessions × 78 five-minute bars/session)
using existing DuckDB, one thread, a 64 MB engine memory setting, 8,192-row Parquet
groups and ZSTD. The file was 19,705,923 bytes; macOS physical footprint peaked at
65,290,792 bytes and OS max RSS was 99,549,184 bytes; elapsed 1.395 seconds. All
temporary files were removed. This is a synthetic columnar feasibility test,
NOT a gateway-integrated dataset store or proof of real-provider coverage.
The engine memory setting is not a total-process ceiling.

### Discovered and fixed coverage defect

OKX's recent endpoint returned 1,439 one-minute bars starting 2026-11-12 18:30 UTC
for a request starting 2026-11-11. The loader accepted any nonempty result and
never tried history. A direct history-endpoint control returned 3,993 bars
starting exactly 2026-11-11 00:00 UTC in 1.762 seconds.

The loader now checks the leading boundary and tries the historical endpoint
before accepting a tail. If neither endpoint covers the start, the earliest
observed frame is retained with a warning. The gateway's `_coverage` reports
requested and observed bounds, sampled status and an explicit unverified/partial
status; known leading continuous-market gaps set `complete=false`. Calendar and
internal-gap completeness are still unverified, stated in `complete_scope`.
Cache identity was bumped so old results cannot hide the new metadata.

A first cold-process verification timed out and is not counted as successful.
After loader initialization, the actual gateway returned 4,011 rows starting
2026-11-11 00:00 UTC in 5.109 seconds using unchanged production wait limits.
The later final bar reflects the later acquisition time. Source normalization,
source worker slots and subscription lifecycle code were not relaxed.

The final combined related regression run passed 70 tests in 24.98 seconds,
including an end-to-end partial-boundary assertion (one existing Starlette
TestClient deprecation warning).
The loader file retains its pre-existing module-import-order lint findings;
new gateway/test harness files pass Ruff and the patch passes diff whitespace
checks. No frontend or protected Agent/provider/session file was changed.

### Near-entry-limit synthetic pressure

`tools/gateway_memory_pressure.py` uses the real gateway and StreamHub with an
explicit synthetic source, normal cache limits, 16 simultaneous topics and two
unread subscribers. It made 320 successful acquisitions across 20 subscribe/cancel
cycles, each payload approximately 1.8 MB. Assertions verify successful snapshots,
no retained channels/listeners, and cache limits on every cycle. No forced GC.
Measured peak physical footprint was 93.345 MiB and max RSS 91.344 MiB. Memory
cache peaked at 7,200,710 bytes and disk at 66,606,556 bytes, below 8/64 MiB caps.
Post-cycle physical footprint varied rather than staying flat (first 69.048 MiB,
last 83.204 MiB); this is not a proof of zero retained allocator memory. Temporary
cache files were removed when the experiment exited. It complements, rather than
replaces, the live network soak.


### Completed live run: 30.77 minutes

The second run finished normally in 1,846.32 seconds with 195 whole-process
samples. It performed 587 SSE subscriptions and 587 unsubscriptions, 12 fault
cycles (WebSocket-only then total source unavailability), and delivered 2,914
client snapshots across all 18 requested topics. No client ReadError occurred in
this run. Real upstream activity: 30 successful WebSocket connections, all 30
closed; 8,064 live WS messages accepted; 81 successful REST snapshots. Retained
snapshots may still be replayed to new subscribers while offline; these are not
counted as live upstream events.

- Whole-process **OS lifetime peak physical footprint: 169.063 MiB**. This comes
  from an independent `proc_pid_rusage` v4 observer, not cache accounting.
- Highest sampled RSS: 98.375 MiB; final RSS: 18.984 MiB. RSS alone significantly
  understates this process's retained physical footprint on this Mac.
- Final physical footprint: **149.891 MiB**. Equivalent-workload cycle medians
  increased **4.219–8.704 MiB** from first to last repetition. The lifetime peak
  did not keep increasing, but this does NOT establish absence of a slow leak or
  allocator retention. Allocation profiling / a longer steady-state run remains
  necessary before claiming zero long-term growth.
- After last unsubscribe: clients, topics, pending updates, upstream sockets and
  active requests all reached zero. Async task count settled at three server
  tasks; Python thread count remained 18 (worker/runtime threads are retained).
  File descriptors settled at 17. No source tick history queue accumulated.
- RAM cache reached zero **143.96 seconds** after the idle phase started, without
  forced GC or manual prune. Disk retained 293,787 bytes / 22 still-valid entries;
  the 900-second disk lifetime intentionally exceeds the three-minute idle tail.
- All 12 forced-offline uncached bar probes returned 503. Of 11 scheduled
  recovery probes, 10 returned complete data immediately and one returned 503.
  A later fresh fetch of that exact failed request returned complete data in
  1.561 seconds. Its original per-source diagnostic was not saved by that runner
  version, so its cause is **unresolved**, not assumed to be a network timeout.
  The reusable runner now retains those diagnostics for future investigations.
- The measured child and its monitor exited; no listener remained on port 8911.
  The ordinary isolated preview remains at http://127.0.0.1:8910/docs.

The long run began before the coverage-only fixes were loaded. Memory/stream
lifecycle code was unchanged; coverage fixes were separately verified by the
70-test regression and real warm gateway history request described above. The
soak is a gateway-process measurement, not total frontend/full-application RAM.

Artifacts (metadata only, outside the checkout):
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-soak-20261114/`.
It contains the interrupted and completed raw reports, completed summary,
independent OS memory samples, multi-year/capacity/pressure results and `final.png`.

**Outcome at `ba7cf5f24` (superseded by the follow-up below):** bounded cache and subscription cleanup verified; repeated live
reconnection verified with one unresolved first-attempt recovery failure; no
GB-scale runaway observed in this finite run. A claim of completely flat or
leak-free total process memory is NOT supported. Multi-year minute datasets,
quota settings, storage dialogs and resumable history jobs remain unimplemented.


## Follow-up: closed-connection retention and complete minute datasets

### Confirmed memory mechanism

Allocation snapshots after warmup, with the same live four-cycle workload,
showed closed TLS buffers attributed to `websockets/asyncio/client.py:453`
growing from 527,920 to 2,639,792 bytes. Compression objects added another
1,536,960 bytes. After natural idle, 5.03 MiB of traced Python allocations
remained; a diagnostic-only GC control reduced this to 0.30 MiB. OS footprint
did not immediately drop, consistent with allocator retention as well as cycles.
This is why zero cache bytes did not establish zero retained process memory.

`gc.get_referrers` on real connections with automatic GC disabled found:

- connection → SDK logger adapter → `extra['websocket']` → connection;
- connection → canceled SDK keepalive task → exception frame → connection;
- after an actual transport abort, protocol → stored parser EOFError traceback
  → `connection_lost` frame → connection → closed TLS transport/buffers.

TLS reuse and disabling compression alone were insufficient. Logging immutable
connection IDs and using the existing OKX application heartbeat removed the
normal-close cycles; releasing stored closed-connection error tracebacks removed
the abnormal-close cycle. Exception type, text and cause identity are preserved;
certificate and hostname verification remain enabled. Three real TLS normal
closes and three real TLS aborts then left zero ClientConnection/SSLProtocol
objects with automatic GC disabled. A local real-socket regression repeats five
aborts and asserts weak references are cleared without `gc.collect()`.

The production service does not run forced GC. The profiling endpoint exists
only in the loopback soak harness; its final GC control is recorded separately
from the natural idle/process measurements.

### Recovery 503: proven defect versus missing historical evidence

The old single 503's server log is empty and its report omitted source attempts.
Its exact historical cause therefore cannot be uniquely reconstructed. A
controlled HTTP regression reproduces a real policy defect: after two source
failures, exponential backoff refuses a now-healthy source at 31 seconds and
returns 503 despite healthy data being available. The new half-open route actually
fetches that source and returns 200. It permits at most one extra attempt per
market/interval per 30-second base cooldown, never before 30 seconds since the
source's last failure; worker caps, deadlines, same-key throttling and prolonged
outage protection remain. A 100-request probe test verifies the throttle.

This fixes a demonstrated recovery failure mode, not proof that it caused the
old event. New soak reports retain full source/stage/type diagnostics so the
next failure is attributable. There is no claim that a permanently unreachable
free provider can always supply data.

### Ten stocks × five years × five-minute bars: real full verification

Source: the existing free BaoStock transport, extended through a dedicated
monthly-minute adapter; the daily loader's interval guard remains unchanged.
Symbols: 601398.SH, 600519.SH, 601318.SH, 600036.SH, 600000.SH, 601288.SH,
601988.SH, 000001.SZ, 000002.SZ, 000333.SZ. Requested range: 2021-11-14 through
2026-11-13, raw prices, CNY, shares, Asia/Shanghai bar-end timestamps. This
verifies mainland equities, not US/HK multi-year minute availability.

- **610/610 monthly chunks, 581,760/581,760 rows**. Every stock has 1,212
  observed trading sessions and 58,176 bars. First bar 2021-11-15 09:35; last
  bar 2026-11-13 15:00. The requested first date was a Sunday.
- Independently re-fetched the entire five-year calendar and daily trading
  statuses, checked every intraday timestamp and chunk digest, then read all
  **582 pages** through the production reader. No samples, omitted pages,
  duplicate timestamps or missing expected bars; the canonical full-row digest
  matches between compressed files and paged reads.
- Canonical SHA256: `0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`.
- Disk including catalog: **11,088,905 bytes (10.575 MiB)**.
  One-month-at-a-time acquisition; the complete dataset was never materialized
  in RAM. Observed download-process peak physical footprint **62.157 MiB**,
  peak RSS **80.141 MiB**. These are whole history-worker process measurements,
  not cache counters and not total memory of the full application/browser.
- Paused at 328 chunks / 312,912 rows, exited the first process, then resumed in
  a new process. Completed files were checksum-verified and skipped. The two
  monitored runs totaled 23.55 minutes; independent full verification
  took 35.40 seconds. One actual source connection closure retried successfully.
- Real 15m/30m/1H probes for 2026-11-09..13 returned 80/40/20 bars with exact
  grids. HTTP first/last pages and the real Agent tool's 25-row page also passed.
- A disposable copy of all 610 real chunks was held across a cleaner cycle
  while pinned, then unpinned and made idle-expired. The actual 30-second
  background cleaner removed every chunk and reduced usage from 11,088,905 to
  331,776 bytes. The original verified dataset was not deleted.
- A real HTTP quota reduction below current usage returned 409 without changing
  the saved limit. Tests also cover shared reservations, low disk, compressed
  write limits, corruption/refetch, cancel/restart, locked metadata, auth and
  bounded tool/list pagination. New SQLite catalogs release metadata pages via
  auto-vacuum; metadata lock waits are bounded instead of hanging callers.

Defaults: history store 256 MiB / 30 idle days, plus the separate hot gateway
cache's 64 MiB / 900 seconds. Pinned and active datasets are protected; capacity
exhaustion pauses a download with its completed prefix intact. Web settings
(11 locales), CLI `vibe-trading data history`, API and Agent/MCP `history_data`
use the same store. Unsupported markets/minute intervals fail explicitly.

Frontend verification: the storage page displayed real usage and active
610-chunk job progress in the browser. The scoped Settings/storage TypeScript
check and Vite production bundle pass; the full TypeScript build encounters two
pre-existing dynamic translation-key errors in untouched
`options/PayoffComparisons.tsx` (byte-identical to HEAD). No options file was
changed to bypass those errors. The isolated preview lacks unrelated session
APIs, so its normal app shell reports that separate service as unavailable.

### Final regressions and uninstrumented process run

With the complete close/abort fix, TLS-buffer allocations were **527,968 bytes
in all four active-cycle snapshots** (two live sockets) and absent after natural
idle. Total traced Python allocations after natural idle were **463,203 bytes
(0.442 MiB)** versus 5,274,925 bytes (5.031 MiB) before the fix. The diagnostic GC
control further reduced the fixed run to 276,961 bytes; that control is not used
in production. Instrumented OS readings include profiler overhead.

A separate run without tracemalloc, forced GC or non-default gateway limits
completed in **8.98 minutes**: 139 subscriptions and 139
unsubscriptions, four outage/recovery cycles, 676 delivered snapshots, and all
18 topics observed. All four injected-offline probes returned 503; all three
scheduled recovery probes returned complete data with HTTP 200. Sixteen actual
WebSockets connected and closed, 1,919 live messages arrived, and all 16 REST
snapshot attempts succeeded. No client errors were recorded.

An independent external OS observer recorded lifetime peak physical footprint
**173.469 MiB**; final physical footprint was **142.782 MiB**.
Highest sampled RSS was **185.062 MiB**, final RSS
**50.250 MiB**. Cycle-end physical footprint was approximately
156.8, 163.2, 171.0 and 156.0 MiB, followed by idle decline. Thread/FD counts
settled at 13/14; three server asyncio tasks remained. Sockets, subscriptions,
pending updates, active requests and RAM cache reached zero; RAM cleanup occurred
within 130.26 seconds of the sampled idle phase beginning. Source workers and
allocators retain baseline resources, so a process is not expected to reach
zero memory. This finite regression fixes the demonstrated retained-connection
mechanism; it does not prove a universal multi-day bound or every provider's
availability. The old 30-minute baseline remains above for comparison.

Validation: 201 related backend regression tests; 13 adjacent CLI tests; 45
frontend storage/i18n tests. Both supported CLI invocation forms work, including
global flags and nonzero exits for failed/unsupported requests. A real 48-bar
BaoStock fetch after the stdout adapter change emitted no SDK text to stdout;
SDK notices are module-local logging under the shared session lock, preserving
MCP JSON-RPC and unrelated threads' output.

Metadata reports and plots (no price payloads) are preserved outside the repo:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-history-20261114/`.
Real compressed data remains at
`~/.vibe-trading/history-validation-20261114/45ce1c3e46024465821ab61b0dc4714e/`.

## Deep-use capacity follow-up (2026-11-14)

Production code remains at `4981ed047`; this follow-up adds live test tooling.
The original combined one-hour run and the separate capacity test use different
server processes. They share this machine/network and therefore can contend for
public upstream capacity. They do not measure the full Electron/frontend/LLM app.

### 32 stocks × two intervals and a real SH/SZ scan

`tools/gateway_scale_probe.py` queried BaoStock's 2026-11-13 inventory and selected
5,224 SH/SZ A-share codes (60/68/00/30 prefixes). This explicitly excludes Beijing,
B-shares, ETFs and indices; it is not an all-country/all-exchange universe.
Thirty-two listed stocks were subscribed at both 1D and 1W, eight topics per SSE
connection. Source workers/pending/cache settings were unchanged.

- Default 16-topic limit: two connections accepted, six returned HTTP 422
  `Topic capacity reached`; all 16 admitted topics delivered, median first delivery
  4.035 seconds, last 5.032 seconds. No source error in this 46-second control.
- Configured 64-topic limit: all eight connections accepted. All 64 topics
  initially delivered, median 6.2525 seconds, last 10.199 seconds, with no initial
  source errors. A 65th topic returned 422. Config validation permits at most 64;
  50 stocks × three intervals (150 topics) is not currently supported.
- After 90 seconds, the driver submitted the complete 5,224-symbol list in
  653 requests of at most eight symbols, with two concurrent HTTP requests, while
  keeping the 64 topics subscribed. Only **79 symbols / 1,738 bars** returned.
  There were ten HTTP 200 responses (one partial), twenty request-timeout 503s,
  and 623 busy/cooldown 503s. The full submission pass took 202.924 seconds and
  is **failed acquisition**, not a successful full-market scan. The test records
  every missing symbol and does not invent data or downgrade the failure.
- The driver deliberately records first-pass admission/failure; it does not
  pretend immediate busy responses are completed work or retry them indefinitely.
  A reliable scan needs a resumable, backpressure-aware job scheduler; that path
  does not exist yet. This result must not be extrapolated to a paced scan's
  maximum eventual coverage.
- Across the 603-second active stage the subscriptions received 324 snapshots
  and 251 source errors; some topics had only three distinct acquisition stamps.
  Raising the topic count alone does **not** establish dependable minute refresh.
  Inspection confirms watchlists and bulk requests share the same two request
  coordinators, four source workers and 16 pending-flight limit, with no reserved
  watchlist capacity. Observed Tencent attempts returned HTTP 501 and Eastmoney
  historical endpoints failed. These observations do not establish whether 501
  originated at the provider or an intermediary, or prove an upstream rate limit.
- A known-symbol control preferring Tencent fell back to BaoStock after 11.65
  seconds; another request took 17.06 seconds and returned a gateway timeout.
  One independent control caller hit its 25-second HTTP read timeout. This
  includes admission/queueing and cannot be reported as pure upstream latency.
- Physical footprint lifetime peak **114.876 MiB**, ending **114.251 MiB**.
  Serialized RAM cache peaked at **551,160 bytes**; disk cache at **739,742 bytes**,
  well below the configured 8/64 MiB budgets. Capacity failure was not caused by
  filling those caches. After three idle minutes: clients/topics/pending updates,
  upstream sockets, active requests and memory cache entries all zero; three
  async tasks remained. Default 16-topic control peak was 98.282 MiB.

The **existing market-ranking tool** is a different product path. Real
`MarketScreenerTool.execute(market=..., top_n=100)` calls returned 100 rows each:
A-share 291.126 ms, US 1,271.494 ms, HK 1,352.578 ms. These are upstream-computed
rankings, not downloading every security's bars to compute arbitrary indicators.
The tool currently calls Eastmoney directly and has not been integrated with the
gateway; no alternate-source behavior was verified for this capability.

### Cache capacity interpretation

8 MiB RAM and 64 MiB disk are serialized short-lived response-cache budgets, not
whole-process limits or a user's total dataset allowance. Defaults also cap each
entry at 2 MiB and each cache at 256 entries; a cache can evict before reaching its
byte budget. Persistent historical datasets have a separate 256 MiB default quota,
30-day idle retention, pinning and bounded paged reads. The previously verified
581,760-row ten-stock/five-year/5m dataset occupied about 10.6 MiB. That observation
supports this measured workload, not all markets' compression or full-market
multi-year intraday storage. The failed capacity run above does not justify
increasing the cache limits as a throughput fix.

### Completed one-hour combined workload — not an overall stability pass

`tools/gateway_soak.py --history --cycles 30 --cycle-seconds 120 --warmup 120
--idle 180` completed on one server PID (87319). Wall time was 4,000.76 seconds;
**active concurrent workload was 3,692.99 seconds / 61.55 minutes**, excluding
warmup and idle cleanup. Thirty cycles alternated online, WebSocket-only outage,
recovery and total source refusal. The test aborted real child-local transports,
not the computer's network. No profiling or forced GC ran in the measured server.
An independent OS observer recorded 779 samples and normal process completion.

- 1,465 subscriptions and 1,465 unsubscriptions; 6,576 client snapshots across
  18 topics. There were 71 real upstream WebSocket connections, all closed,
  15,430 accepted live WS events, and 216 successful REST snapshots.
- All 30 forced-offline bar probes returned 503. All 29 subsequent recovery
  probes returned 200. All 30 first/repeated bar and option timing probes
  returned 200. These checks do not mean every streaming refresh succeeded.
- **Three client ReadErrors occurred** at elapsed 2,878.99 / 2,911.13 / 3,554.14
  seconds, on the short-lived BTC/AAPL churn connections. The server log has no
  matching traceback. Whether cancellation races or another transport condition
  caused them is unresolved. They remain failed observations. The harness now
  records bounded error text, cause type and cancellation state for future runs;
  those fields cannot retrospectively explain this completed run.
- End state: zero clients/topics/pending updates, upstream sockets, active
  gateway requests, outstanding measured source calls and RAM cache entries;
  25 threads, 18 file descriptors and three async tasks remained. History jobs
  were complete or deliberately paused; reservations were zero. Idle was
  configured for 180 seconds; sampled timestamps span **179.98 seconds**, so the
  report's strict `>=180` sample-span flag remains false rather than rounding it
  into a pass. This does not change the measured 61.55-minute active duration.

**The longer test exposed additional retained process memory.** Physical
footprint low points during minutes 10–40 were approximately 216–218 MiB. After
late fallback activity, minutes 50–60 had a median of 302.33 MiB and a minimum of
270.17 MiB. After idle cleanup, physical footprint was **269.876 MiB** (RSS only
38.734 MiB); lifetime physical peak was **581.080 MiB**. The late-half regression
is +2.78 MiB/min, dominated by a late step, not evidence of a constant leak rate.
The previous nine-minute run did not expose this behavior. Clearing serialized
cache entries does not resolve it, and this run is **not a memory-stability pass**.

Native `vmmap` controls: at approximately minute 18, malloc live allocations
were 66.7 MiB and VM_ALLOCATE 129.3 MiB; near minute 53 they were 66.8 MiB and
187.4 MiB respectively. A separate diagnostic process reproduced large retained
footprint around repeated real CCXT fetches:

- Normal automatic GC, three thirteen-row BTC daily fetches: post-call footprints
  131.829 / 304.313 / 235.532 MiB; no exchange instance remained alive by weakref.
  A subsequent diagnostic GC reduced the last value to 223.610 MiB.
- Allocation profiling in a separate process showed only **0.114 MiB net traced
  live-Python growth**, while physical footprint increased **167.047 MiB** from
  first to third fetch. Profiling overhead changes absolute footprint, so this
  is a mechanism control, not a replacement for the unprofiled hour run.
- Restricting Binance metadata to spot-only in another test process made the
  requests faster but left similar retained footprint. This candidate was
  **not adopted as a memory fix**. Exchange-instance leakage is not demonstrated;
  allocator/native retention on this heavy SDK path is the leading explanation,
  with its exact attribution in the main process still unproven. No production
  GC workaround or relaxed resource guard was added.

### Historical completeness and time-to-data

The same server completed ten stocks × five years × 5m: **610 chunks / 581,760
rows**, approximately **31.06 minutes** including injected failures and resumed
work. It then completed 15m for the same symbols/dates: **610 chunks / 193,920
rows**, approximately **26.40 minutes**. A 30m follow-up retained 121 completed
chunks / 19,312 rows and was deliberately paused at the end of the active hour.
Total physical store use was **16,113,799 bytes / 15.37 MiB**, with no outstanding
reservation. No full dataset was loaded into the server's memory at once.

Independent fresh-source verification initially failed twice with BaoStock
`10001001` during concurrent activity. After download work stopped, both fresh
verifications passed: trading-calendar and daily-status queries, every chunk's
hash and exact intraday grid, and every unsampled page (582 pages for 5m, 194 for
15m). All 581,760 five-minute rows also matched the prior independently verified
canonical SHA256 `0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`.
The source-session error remains an observed concurrency risk; its upstream
mechanism is not established. The main download itself had one exhausted-retry
`10001001` failure and was resumed through the production API by the driver.
The driver also resumed nineteen failures attributed to injected network loss.
This is not automatic product-level resume after an exhausted retry budget.

Observed HTTP latency on the combined workload (nearest-rank P95, successful
responses only; failures are counted separately above):

| Path | Samples | P50 | P95 |
| --- | ---: | ---: | ---: |
| First bar request, gateway cache miss | 30 | 512.81 ms | 3,565.17 ms |
| Immediate repeat bar request, fresh cache | 30 | 7.68 ms | 188.44 ms |
| Option request, actual gateway cache miss | 19 | 1,130.96 ms | 1,652.54 ms |
| Immediate repeat options, fresh cache | 30 | 6.46 ms | 144.89 ms |
| Completed history page, 1,000 rows | 6 | 46.12 ms | 69.64 ms |

A separate continuously connected observer measured newly fetched crypto events,
not cached replay as recovery: WebSocket source age P50 164.64 ms / P95 300.15 ms
(1,871 events). Post-recovery first WS data P50 2.76 s / P95 13.81 s; after a
WS-only failure, REST fallback first data P50 **21.47 s** / P95 **27.73 s**. The
15-second polling cadence therefore does not give seamless fallback. Source
clock skew is not calibrated, and this measures crypto public ticks, not realtime
US equity/options entitlements. Option payloads remain delayed snapshots.

The 14 preferred public-route probes obtained data directly from ten sources,
through fallback for three (AKShare/Eastmoney to Tencent; Stooq to Yahoo), and
initially failed Wallex after its source wait expired. Wallex later succeeded in
2.55 s; the subsequent cached response took 7.82 ms. These are one-symbol route
probes on this network, not proof that every source/symbol is fast or available.
The 16 GiB / ten-logical-CPU host had high unrelated load and heavy system swap;
RSS alone substantially understated process memory. No other process was stopped.

### Remaining work established by these tests

Do not market the current implementation as stable full-market scanning plus
multi-cycle monitoring. The evidence calls for bounded, resumable scan scheduling
that honors backpressure, preserved capacity for foreground subscriptions,
capability-specific upstream rate budgets, integration of the separate screening
path, and a bounded lifecycle for heavy SDK allocations. The three churn read
errors and BaoStock session failures need discriminating controls. A new long
run is required after any production fix; the completed run above measures the
unchanged production implementation at `4981ed047`.

## Combined-load repair (2026-11-14, in progress)

The earlier hour and separate scale run above remain failed/limited evidence;
they are not relabelled as passing after code changes.

Confirmed changes before the next hour:

- Two bounded request coordinators now prioritize foreground work; at most one
  background acquisition/source call runs. Pending=16 and source workers=4 stay
  unchanged. Absolute deadlines cancel expired queue entries; cancelled entries
  cannot accumulate under repeated re-admission. Subscription acquisition slots
  remain held until the actual thread exits, including after unsubscribe.
- Scan API/CLI/agent/MCP and the storage page enqueue at most 10,000 total symbols
  in four process-local jobs. Batches contain at most eight symbols and source
  admission is weighted by batch size. Only missing symbols retry, with capped
  exponential backoff. These jobs report acquisition coverage and do not promise
  persistent whole-market datasets. Cache quotas remain RAM8/disk64 MiB.
- Daily/weekly/monthly watchlists share daily acquisition and existing resampling.
  BaoStock sessions prioritize foreground reads with a background turn after four
  foreground admissions. Local SDK admission failure returns `source_busy`, not a
  provider network failure; SDK/socket serialization remains intact.
- Tencent/Eastmoney/AKShare now expose swallowed transport errors as structured
  per-symbol diagnostics. Empty-symbol responses remain `no_data`. A fresh live
  Tencent 501 control returned `server: stgw` and a redirect to
  `waf.tencent.com/501page.html`: this is an observed WAF response, not proof of
  rate limiting or of the exact rule that caused it. Routing cools it down and
  switches compatible providers; it does not bypass the WAF.
- Reusing one CCXT exchange for twelve real calls eliminated repeated growth but
  retained a large first-allocation footprint. The selected approach instead runs
  one bounded short-lived interpreter per CCXT request, kills/reaps it on deadline,
  and exposes its PID/footprint. Twelve real isolated acquisitions all returned
  13 BTC daily bars; post-call parent footprint stayed about 79.5–82.1 MiB,
  versus the previous in-process allocation controls documented above. This alone
  does not measure simultaneous parent+child peak; the new hour includes a 0.5s
  independent parent/child observer and repeated explicit CCXT probes.
- A real local HTTP/SSE transport control reproduced empty `ReadError('')` when
  client/server keep-alive expiry coincided: 1,600 requests yielded 82 ReadErrors
  and one RemoteProtocolError. Earlier client retirement yielded 1,600 successes,
  no errors. The soak client now uses 2s expiry before Uvicorn's 5s expiry and
  records bounded HTTP transport traces on every error. The original three events
  lacked traces, so their precise retrospective cause cannot be uniquely proven.
  This correction is in the test/client pooling path; source errors are not hidden.

Short pilots used real 5,224-symbol SH/SZ inventory, 64 simultaneous topics and
real five-year downloads in one service. They exposed source-health and BaoStock
contention issues and were followed by the fixes above; they are not substitutes
for the requested hour. A final live eight-stock BaoStock batch control returned
all eight symbols in 2.018 seconds without raising resource limits.

Legacy MCP size tests (`test_get_market_data_size.py`, seven failures) expect
large results inline, while the existing MCP tool spools them. Baseline and current
300-row market-data output were byte-identical; the baseline/current
`get_market_data` function AST was identical. These failures are pre-existing
contract drift, not a reason to relax gateway verification.

Formal combined-hour result: completed; see “Combined-hour final result” below.
The resource/recovery checks passed, but full-market acquisition did not finish
in the measured hour; its explicit coverage check remains false.


## Historical router correction (2026-11-14, after combined-hour launch)

The earlier persistent downloader was BaoStock-only even though ordinary gateway
bars already used the wider loader registry. This was a real missing integration,
not merely a misleading label. Persistent jobs now default to auto routing, expose
candidate sources in their plans, retain actual chunk provenance and reject
incompatible series identity. The API, CLI, Agent/MCP and eleven-locale storage
page share this behavior. Discovery measured 27 registered non-local adapters and
16 market chains, including credential-gated adapters; these are not 27 verified
free/live feeds. Unknown source interval coverage is checked on acquisition.

Separate real acquisitions through the new history-job HTTP path:

| Request | Rows | Observed source | Result | Wall time including polling |
| --- | ---: | --- | --- | ---: |
| AAPL + MSFT, 2026-11-02..13, daily | 20 | Yahoo | downloaded, calendar unverified | 1.024 s |
| 00700.HK, same dates, daily | 10 | Yahoo after other candidates | downloaded, calendar unverified | 2.548 s |
| BTC-USDT, 2026-11-12, 5m | 288 | OKX | full continuous grid verified | 0.524 s |
| AAPL, 2026-11-12, 1m | 390 | Yahoo | downloaded, calendar unverified | 0.518 s |
| TD.TO, 2026-11-02..13, daily | 10 | Yahoo | downloaded, calendar unverified | 0.520 s |
| VOD.L, same dates, daily | 9 | Yahoo | downloaded, calendar unverified | 1.017 s |
| AAPL, 2021-11-15, 1m | 0 | no usable route | explicitly failed, no recent-tail replacement | 9.706 s |

Native browser interaction also completed AAPL 1m, 2026-11-09..13, five chunks,
through estimate → candidate-route display → download → downloaded/unverified.
These observations are separate from the combined hour: its parent imported
commit `45a8e0f25` before the new history router existed. Its data acquisition
continues to exercise the original verified BaoStock adapter. Do not use that
hour as evidence that the new multi-source downloader passed an hour-long soak.
The independent observer measured actual children throughout that hour.

Default history storage also collided with the CLI's existing
`~/.vibe-trading/history` text file. It now uses `~/.vibe-trading/datasets/history`,
preserving an existing legacy directory only when it contains a dataset catalog.
An explicit history directory remains unchanged; the CLI history file is untouched.

Further real router checks also downloaded daily data for India, Korea, Vietnam,
Argentina, Brazil, forex, an index and a global futures symbol. An explicit
Binance 5m request returned all 288 bars and passed the continuous grid; explicit
yfinance daily returned ten rows. Explicit Stooq failed visibly on this machine.
These checks establish local reachability, not worldwide availability or verified
exchange-calendar completeness for those daily series.

Low-frequency partitioning was then improved without changing source/cache quotas:
AAPL+MSFT five-year monthly requests decreased from 122 chunks/97.112 seconds to
12 chunks/9.515 seconds, returning the same 122 symbol/timestamp rows and volumes.
They were NOT byte-identical: 299 OHLC values in 103 rows differed, maximum absolute
difference 0.0001270927 and relative difference 4.57e-7. Those are retained as
observed price differences, not silently rounded away or claimed identical.
Weekly AAPL returned 11 rows byte-identically when reduced from three chunks to
one (2.559 → 0.532 seconds). Timings include polling and are observations, not SLAs.

A BTC five-year daily request ending 2026-11-13 correctly failed its final chunk:
OKX returned 316/317 bars for 2026, with no interior gaps and timestamps
2026-01-01T16:00..2026-11-12T16:00 UTC. The source's 1D bars start at UTC+8 midnight;
the bar starting 2026-11-13T16:00 UTC was still open. The gateway refused both a
false full-coverage assertion and a Binance/CCXT splice into that OKX series.
Errors now preserve observed bounds, expected/actual counts and the first
per-source failure across retries; a later cooldown cannot erase its cause.
Grid phase is recorded and checked on resume, including legacy metadata migration.
Cancellation stops before the next fallback attempt and releases the reservation.
A settled request 2021-11-13..2026-11-12 subsequently returned **1,826 rows, six
chunks, all verified**, in 3.978 seconds (some prior-year chunks reused hot cache).

Focused backend regression: 111 passed (gateway/history suites). TypeScript
checking reported only the two existing dynamic i18n-key errors in
`frontend/src/components/options/PayoffComparisons.tsx`; no gateway UI type error.
The existing `main` loader registry is byte-identical to this branch's registry;
the downloader is reusing those routes rather than maintaining a separate list.

Final history-page and eleven-locale frontend tests: **46 passed**. The native
preview verified both auto-route plans and actual per-job sources. It runs the
isolated gateway server, so the unrelated session sidebar shows Not Found; this
is not a full-application session validation. Router evidence and the UI screenshot
are archived alongside the combined-hour artifacts under `gateway-combined-20261114`.

The background downloader's arbitrary ten-year range restriction was subsequently
removed. Its existing 4,096-chunk/100-symbol/job and disk-quota bounds remain; the
synchronous bar-preview API retains its own ten-year/eight-symbol limits. A real
AAPL monthly download **1996-11-14..2026-11-13** acquired **361 rows in 31 chunks**
through Yahoo, in **24.254 seconds**. It is labelled downloaded/calendar-unverified,
not verified complete. This is observed source coverage, not a promise that every
source supplies 30 years or that minute history has the same depth.


## Combined-hour final result (2026-11-14)

Measured service version: `45a8e0f25`, before the historical-router commits
`ffb393951` and `8dd52201f`. The router's separate live acquisitions above and
111 backend/46 frontend checks must not be conflated with this hour.

The same server PID ran **3,844.48 active seconds (64.07 minutes)**, plus warmup
and **189.99 seconds observed idle**, 4,221.43 seconds total. Work was real
upstream acquisition with process-local socket/source fault injection, not a host
network outage or a multi-region test. There were **30 fault cycles** and
**1,449 subscribe/unsubscribe pairs**. Limits stayed at 8 MiB RAM cache, 64 MiB
disk cache, four source workers, sixteen pending requests and 256 MiB history
quota. Only the topic cap was configured to 64 for this requested stress case.

- 64 concurrent topics comprised 30 stocks × daily/weekly, BTC/ETH streams and
  AAPL/SPY delayed options. All 60 bar topics received their first result within
  30.1 seconds, and each recorded 33–37 distinct acquisitions over the run.
  This is not 64 distinct equities, tick-level equities or realtime options.
- The 5,224-stock SH/SZ scan acquired **2,439 stocks (46.69%)**, with 3,024 symbol
  attempts and 585 retries. **2,785 remained** when the test stopped it. No
  terminally exhausted symbol was recorded, but this is not zero failed attempts
  or a completed full-market scan. The report's `full_scan_completed` is false.
  Scan metadata is process-local/idle-expiring; it is not a persistent downloaded
  archive. No extrapolated completion SLA is claimed.
- Ten stocks × five years × 5m completed **610 chunks / 581,760 rows**. After
  shutdown, a fresh independent BaoStock calendar and ten full-range daily-status
  queries verified every session/minute grid and chunk hash. Reading all **582
  production-reader pages** reproduced the same canonical SHA-256:
  `0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`.
  This also matches the separately verified prior dataset. Verification took
  32.11 seconds. The concurrent 15m continuation reached 439/610 chunks and
  139,472 rows, then paused; it is not certified complete. Combined disk use
  was 14,270,275 bytes with zero reserved bytes at idle.
- **No client ReadError or other client transport exception** occurred. All 29
  explicit post-fault recovery probes returned 200; all 30 all-offline probes
  returned visible 503s. The last cycle has stream/history recovery observations
  but no next-cycle recovery probe. Two ordinary bar probes and one options
  probe (plus their immediate repeat reads) still returned 503 while routes
  cooled down after faults. Recovery is not instantaneous or guaranteed when
  every source is unavailable. These are not silently discarded from latency
  statistics. The old three ReadErrors still lack enough evidence for a unique
  retrospective cause; the controlled keep-alive race and its fix are documented
  above.
- Parent physical footprint peaked at **180.81 MiB**, settled at **150.20 MiB**;
  the post-30-minute fitted slope was **−0.04194 MiB/minute**. The 30–40, 40–50
  and 50–60 minute median footprints were 153.66, 154.13 and 153.17 MiB. This
  run shows no continued late growth, not proof of multi-day leak absence.
  Final RSS was 24.77 MiB; macOS physical footprint, including compressed/native
  allocations, is the more relevant retained-memory figure here.
- The independent 0.5-second OS observer collected 8,087 samples and observed
  30 distinct CCXT child PIDs, never more than one concurrently. **Parent plus
  actual child observed peak was 536.66 MiB**; the sum of independently recorded
  parent/child lifetime peaks gives a conservative **558.36 MiB upper bound**.
  Thus total process memory is not the 8 MiB cache limit. Of 30 explicit CCXT
  probes, 29 returned CCXT data; one hit its deadline and returned compatible
  OKX fallback, with the timeout retained in diagnostics.
- At idle: zero subscribers/topics/queued updates, zero upstream sockets, zero
  child processes, zero queued/active source requests, and zero memory-cache
  entries/bytes. All 1,713 instrumented actual source calls finished, including
  calls whose caller could have timed out. The bounded pools retained 25 idle
  threads and 16 file descriptors; this is not a claim that every allocation
  returned to startup size. Disk cache retained 1,813,258 unexpired bytes.
  Independent `ps` and listening-port inspection confirmed the test server
  stopped, while the separate preview servers stayed available.

Observed successful request latency under this workload: uncached bar reads
median **2.078 s**, P95 **6.043 s**, max **9.602 s** (28 successes, two 503s);
repeated cached bars median **2.365 ms**, P95 **4.063 ms**. Uncached option
snapshots had median **1.309 s**, P95 **3.503 s** (16 cache misses; other first
reads were cache hits or one 503). Successful historical chunks had median
**2.472 s**, P95 **6.666 s**, max **19.310 s**; 31 failed chunk attempts remain
in the evidence. Cache hits are fast; upstream reads and a full-universe scan
are not uniformly fast. Source pacing and foreground capacity are deliberately
preserved instead of increasing memory or concurrency to improve this score.

Raw samples, independent OS observations, all-row history verification, final
summary/plot and router UI/live-probe evidence are archived outside the repository:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-combined-20261114/`.
The preview is `http://127.0.0.1:5910/history-storage` on the isolated gateway
API at port 8910. It does not validate the full application's session sidebar.


## Routed mixed-load follow-up (2026-11-14, in progress)

User requested a new hour with the actual historical router, all 5,224 scan
symbols acquired, and 30 progressively complex scenarios. The scenario matrix
is `SCENARIOS.md`; pending entries are not passes. The new measured service
fingerprint is `3a43794f8` and uses fresh history/cache directories. All memory,
disk, source-worker and pending limits remain unchanged.

Confirmed scheduling defects fixed before launch:

1. A partial scan batch imposed the whole source cooldown on all unrelated
   ready symbols, although each missing symbol already had its retry deadline.
   Successful partial batches now use ordinary scan spacing. Total source
   outages retain backoff; source pacing and single background capacity remain.
2. The scanner replaced the gateway's short local-capacity retry hint with the
   longer network cooldown. It now honors that existing hint; it does not lower
   the actual source pacer or network failure backoff.
3. When a batch's first symbol was absent, valid other symbols returned by the
   loader were discarded before provenance was merged. Valid rows now survive
   and are not requested again. Controlled regression pins a missing-first batch.
4. Expanded cross-instance tests exposed an intermittent UUID modulo-64 lease
   collision between unrelated historical jobs. The catalog now assigns unique
   slots transactionally (same bounded 64 lock files, at most 32 datasets).
   Same-job duplicate execution remains refused. Existing catalogs gain slots
   on opening; old/new binaries should not run concurrently on one catalog.

Previous-hour samples contain 2,024.7 seconds of intervals where neither scan
attempts nor completed count changed. This is a sampled stall observation, not
proof that all those seconds have one cause. New per-job acquisition/backoff
counters separate the costs. Short pilot 2 acquired 56/256 with 46.831 seconds
inside acquisition and 61.779 seconds in scanner backoff under compressed fault
cycles. Its real routed AAPL/MSFT five-year monthly job returned all 122 rows in
12 chunks. Short pilots are not an hour result or the requested full scan.

New soak history time-shares the same single worker using production pause,
resume and delete APIs: long auto-routed ten-stock 5m/15m jobs alternate with
US monthly, crypto minute, HK/Canada/UK daily and US minute datasets throughout
the run. The driver explicitly resumes newly created paused jobs. A dedicated
small-scenario run exercises additional real multi-market requests; controlled
fault regressions are labelled separately from live source results.


The first follow-up launch was stopped during its early cycles after an additional
real scenario exposed an eight-symbol US daily timeout. It is retained as an
aborted diagnostic run, not an hour pass. Yahoo's adapter loops symbols serially,
while one gateway invocation had a single six-second source deadline. HTTP batches
are now limited to four symbols per invocation (configurable 1..8), within the
unchanged fifteen-second overall request deadline. BaoStock keeps eight symbols
per login; actual source pacing/concurrency/cache limits do not increase. A
controlled timing regression covers the old self-timeout; real cold eight-stock
reads now returned all eight at daily/weekly/monthly intervals in 8.006/6.386/6.366
seconds, with fresh-cache repeated reads. Network variation prevents interpreting
this as a precisely isolated latency benchmark. The missing-first real batch
also retained all seven healthy symbols and explicitly named the absent one.
The subsequent fresh `gateway-router-hour-v2-20261114` run was rejected, as documented below.


Rejected v2 run pointers:
- Service commit `52a1c756a`; raw report `/tmp/gateway-router-hour-v2-20261114.json`.
- Independent observer `/tmp/gateway-router-hour-v2-os-20261114.json`.
- History root `/Users/wuhaozhe/.vibe-trading/history-router-hour-v2-20261114`.
- Driver uses 30 × 120-second fault cycles, 180-second warmup, 190-second idle;
  `--finish-scan` keeps 64 subscriptions and routed history active after the hour
  until scan terminal (additional timeout 7,200 seconds). Dataset quota remains
  256 MiB. The raw report saves terminal scan state before idle metadata expires.
- Current live scenario results: `/tmp/gateway-live-scenarios-20261114.json` and
  `/tmp/gateway-live-scenarios-v2-20261114.json` (rerun cases 5/10 after HTTP split).
- Real killed-worker/corrupt-chunk recovery passed: `/tmp/gateway-real-crash-20261114.json`.
- Latest regression 116 passed; JUnit `/tmp/gateway-router-hour-regression.xml`.
- Artifact archive `.../01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114`.
- Final tasks: wait for real hour + scan completion, verify complete 5m dataset
  independently, generate combined report/plot, finish all 30 scenario statuses,
  archive evidence, update this document, commit and inspect process cleanup.


### v2 rejection and corrective work

The new-router v2 run exercised 30 fault cycles and 3,981.2 active seconds, but
was **not accepted**. Scan acquired 2,232/5,224 symbols, with 1,652.479 seconds
in acquisition and 2,328.629 seconds in backoff. Some bar topics had 442–966
seconds since their last acquisition near minute 61. The final cancellation
exceeded 45 seconds and the driver exited before an idle tail. No transport
ReadError is not sufficient evidence of healthy subscriptions.

The half-open chooser favored the earliest retry time, repeatedly probing blocked
Tencent/Eastmoney over previously successful BaoStock. It now preserves last
success and rotates bounded recovery attempts. Separately, a real control
measured BaoStock login 4.044 seconds and two daily queries 4.422/2.696 seconds:
the unchanged six-second whole-batch budget cannot accommodate that response
time. An earlier control script failed to advance the SDK row cursor and was
interrupted; its elapsed time is invalid and excluded.

The existing Yahoo client returned three mainland stock samples in
0.266/0.648/0.859 seconds, each declaring CNY. Last-session close and volume
for 601398/000001 matched independent BaoStock responses; the third BaoStock
control timed out and is not counted as a match. Yahoo A-share admission and
SH→SS mapping now join the default fallback chain; old complete source-priority
settings retain their relative order. CNY is required; B shares are excluded.
A real eight-symbol cold auto request still exceeded its 15-second budget while
learning failed sources; the subsequent eight-symbol batch returned all eight
from Yahoo in 11.036 seconds. Cold-start latency is not claimed solved.

History transactions now have an aggregate deadline, and a deterministic
cancel/start race is fixed under the metadata transaction. The observed v2
45-second failure was not retrospectively isolated to only one of these causes.
The driver records acquisition gaps and resumes transiently failed small routed
jobs after the injected outage; these are explicit driver resume calls, not a
claim that the production history worker retries indefinitely.

Current regression: 284 passed (`/tmp/gateway-router-v3-regression-final.xml`).
A fresh short mixed pilot and final-hour rerun are pending; v2 does not substitute
for their results. Resource/cache limits remain unchanged.

The v3 short pilot completed 2×60-second fault cycles and stopped without the
45-second cancellation failure (235.69 seconds total, 35-second idle, not an
hour/memory-idle acceptance). It only acquired 16/256 scan symbols; this exposed
an additional local pressure issue. Queued request expiration now requests a
one-second retry, not a network cooldown. Shared HTTP pacing also previously
ignored the acquisition deadline, letting already-timed-out calls keep sleeping
and start requests later. It now refuses an impossible local pacing slot without
reserving it, classifies that as `source_busy`, and caps the HTTP socket timeout
by the remaining acquisition budget. The rate interval, jitter, concurrency and
cache limits are unchanged. Focused HTTP/loader/scheduling regression: 90 passed.
A real recovery-choice control with identical seeded health chose blocked Tencent
on the old algorithm (failed in 4.802 seconds), and previously working Yahoo on
the fixed algorithm (both stocks returned in 0.878 seconds).

### v3 active run (not yet accepted)

- Frozen service commit: `aeefc0c9f`; all 300 focused regressions passed.
- Started 2026-11-14 08:01:47 UTC; server PID 61356, controller exec 8265, observer exec 96391.
- Raw: `/tmp/gateway-router-hour-v3-20261114.json`; OS: `/tmp/gateway-router-hour-v3-os-20261114.json`.
- History root: `/Users/wuhaozhe/.vibe-trading/history-router-hour-v3-20261114`.
- Ten-stock 5m job: `ad1f34d41ee34f789bdfc915905a627d`.
- Same 30x120s faults, 180s warmup, 190s idle, full 5,224 universe and fixed 8/64 MiB caches.
- `--finish-scan` continues after the nominal hour; first mixed monthly job only
  reached 75 rows before the driver's 90-second window, so that attempt failed
  completion. Do not replace it with the earlier light-load 19-second result.
- Current report-only changes add per-topic acquisition gaps, last-30-minute
  footprint slope, and all ten-minute windows even when the full scan exceeds
  seventy minutes. They do not alter the running service.

### v3 rejected by the mixed-client scenario

The explicit mixed-client probe ran 180 seconds, issuing 24 HTTP requests while
consuming six already-subscribed SSE topics. All 12 bar requests (six-market daily,
five-year US monthly, one-day US minute) succeeded; all eight option requests
returned 503, and four attempts to read an unfinished history prefix returned
409. Crypto received actual upstream WebSocket and REST updates; stocks received
polled historical bars. The downstream client transport is SSE, not WebSocket.

The options path skipped cooled sources without using the router's half-open
recovery. Its snapshots stopped renewing around 08:18 UTC and eventually expired,
while bars/crypto continued. v3 was stopped after 1,981.53 active seconds with
1,012/5,224 scan symbols; it is not a completed hour and is not accepted.
The options path now uses the same bounded half-open mechanism and clears its
legacy failure entry on success. Local capacity failures request a short retry
without poisoning network health. A real seeded-health SPY control failed before
the fix and returned 330 Cboe contracts in 1.521 seconds after it. 302 focused
regressions passed. Source, worker, queue, cache and history-space limits are
unchanged. Final rerun must observe the ongoing age of every topic, including a
source that never recovers; measuring only gaps between two successful updates
misses this right-censored failure. The observer deadline now covers the full
possible scan continuation rather than stopping at two hours.

Unfinished historical datasets deliberately refuse row reads. Streaming committed
prefixes is not implemented; the 409 is retained as a capability limitation, not
changed into an empty successful dataset. Existing research/backtest entrypoints
are also not all migrated; `history_data` and options use this gateway, whereas
legacy market-data tools still have loader paths.

Additional actual cache probe: 10 SPY-chain readers received marked stale data in
42 ms with one background refresh; a new child interpreter reused the disk cache
with zero upstream calls. Idle memory fell from 98,525 bytes to zero while the
disk entry remained. Only TTL/idle timers were shortened for this probe; default
8/64 MiB caches and 4/16 worker/pending limits were kept. Full disk-quota pressure
remains a controlled test, not part of this real-source cache probe.

v2's completed 5m dataset was checked again without new network calls: every
chunk checksum and all 582 production-reader pages, 581,760 rows, are identical
to the earlier independently calendar-verified dataset (canonical SHA-256
`0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`).
Evidence: `/tmp/gateway-router-v2-5m-content-verified.json`.

### v4 interruption / v5 continuation

v4 (same `33fe0975a` service) stopped during warmup, last record about 154 seconds,
with no active mixed workload. On continuation its tool session, controller,
server and observer were absent. No traceback established a cause; not counted
as an hour or product pass. Evidence `/tmp/gateway-router-v4-interrupted.json`.

v5 uses the same service and limits, with detached, log-backed owned processes:
controller 77907, server 77911, observer 77908. Raw
`/tmp/gateway-router-hour-v5-20261114.json`, OS
`/tmp/gateway-router-hour-v5-os-20261114.json`, driver log
`/tmp/gateway-router-hour-v5-20261114.driver.log`. History root
`/Users/wuhaozhe/.vibe-trading/history-router-hour-v5-20261114`, 5m job
`32ab4e56075d4e08a06f39ef15a77b15`. Independent mixed client 79473 records
`/tmp/gateway-mixed-client-v5-20261114.json`, including a second AAPL expiration
when discovery supplies one. It adds a single client to the existing topics; no
resource caps are increased. Adjacent loader/caliber/tool contracts: 139 passed
(`/tmp/gateway-adjacent-contracts-20261114.xml`).


v5 failed early, not accepted. Last saved active sample: 47.74 seconds. The
driver log exposes `httpx.ReadTimeout` while reading history-job status. The
external mixed client subsequently failed to connect after the server exited.
At independent inspection the 10-core/16-GiB host had load average 101.95 and
ordinary shell tools took seconds; the gateway's last sampled footprint was
133.2 MiB. Host pressure is a confounder, not a proven exclusive root cause.
Other sessions' processes were not stopped. The driver's finally block could
mask an earlier exception with the history task's failure; it now persists the
original exception and each cleanup exception separately, with `phase=failed`.
No timeout, resource cap or acceptance criterion was relaxed.
Evidence: `/tmp/gateway-router-v5-failure.json` and the saved driver log.

Short v6 pilot also failed before a saved OS sample: option discovery returned
`ok=false`, then the first lookback raised ReadTimeout at 42.54 seconds. The
corrected harness persisted `phase=failed` and the original driver error.
`/tmp/gateway-v6-pilot.json` is not a memory test. At the following inspection
host load was 83.59 on 10 logical CPUs. A pure-loopback vs idle-gateway control
was started before attempting another expensive soak; no other sessions were
modified.

### Latest responsiveness control and remaining block

Pure local stdlib HTTP: six responses, 2.7-116 ms. Idle gateway status: seven
responses, 22-283 ms. SPY via API returned 503 after 14.119 seconds. An isolated
in-process control also failed: Cboe and Yahoo both exceeded the unchanged
six-second attempt budget, total 12.449 seconds; the subsequent AAPL request
correctly reported source cooldown. This excludes an entirely dead idle event
loop, but does not isolate network latency from host CPU/swap pressure during
source parsing and mixed work. Host load subsequently reached 214.65 on ten
logical CPUs. No resource/time limits were increased and other sessions were
not stopped. No more full-hour retries are being launched under these conditions.

Evidence: `/tmp/gateway-local-responsiveness.json`,
`/tmp/gateway-options-last-control.json`. Current acceptance remains incomplete:
no passing post-fix hour; no complete 5,224-stock scan; no multi-region runtime
evidence. The source recovery fixes have passing controlled and earlier live
controls, not an overall production-readiness claim. Resume when host/source
responsiveness permits an interpretable bounded short control, then the full
hour with the same quotas and full-scan continuation.

### 2026-11-14 09:31 UTC — v7 timeout stacks and inherited SDK isolation

The new test-only watchdog captured slow `/data/bars` and history status requests
in `/tmp/gateway-v7-pilot.server.log`. The source thread was importing `ccxt` via
`binance_loader.DataLoader.is_available`, inherited from `CcxtDataLoader`.
`historical.py` isolated only a route literally named `ccxt`, so the Binance
fallback bypassed isolation and kept the SDK in the API process. This is a
confirmed isolation defect; the stacks do not establish it as the exclusive
cause of every earlier read timeout (host load also varied materially).

Isolation now checks the actual loader inheritance, without importing optional
loaders as a side effect, and the child resolves the requested CCXT-backed
adapter instead of always returning the generic CCXT loader. Same one-child
slot, 6-second source budget and existing response limit. Real explicit Binance
probe: 8.778 s including timeout then fallback, successful data response, no
`ccxt` import in the parent, child exited. Report:
`/tmp/gateway-binance-isolation-v8.json`. New regression prevents either Binance
or CCXT availability checks from running in the parent and checks provenance.
83 relevant gateway/history tests passed (`/tmp/gateway-v8-regression.xml`).

The soak now retains bounded HTTP latency and event-loop lag samples and dumps
threads once per request exceeding 20 seconds. No timeout or resource limit is
relaxed. v7 failed and is retained; v8 is a short diagnostic, not one-hour
acceptance. Its current outcome must be read from the final report.

v8 short test reached `complete` in 264.8 seconds with two fault cycles and
normal history cancellation; no HTTP read failure. It is not hour acceptance;
the routed monthly job was interrupted after 5/12 chunks under injected faults.

A separate source-code audit confirmed Tencent socket/retry waits and OKX's
pagination deadline could outlive the gateway source deadline. Both now cap
network/retry waits by the inherited absolute deadline, rather than returning
a gateway timeout while continuing their original retry budget in a worker.
35 loader tests passed, including new deadline-exhaustion tests proving one
bounded socket attempt and no subsequent retry. Existing successful pagination
and retries without a gateway deadline still pass. Evidence:
`/tmp/gateway-deadline-v9-regression.xml`. No budget was increased.

### 2026-11-14 — v9 metadata contention, v10 snapshot reads

v9 failed at active 11.57 seconds: `_soak/metrics` surfaced
`History storage busy; retry shortly` from `status()` taking the global write
lock while the large history job was being created. This is retained as a
failure (`/tmp/gateway-router-hour-v9-20261114.json`), not an hour result.
Read-only `status()` and unchanged `settings()` now use a SQLite committed
read snapshot without the mutation lock or a pointless UPDATE. Mutations
retain the same timed process/file lock and quota checks. Page readers wait
within the existing two-second lock budget for another reader's lease;
mutators still refuse an occupied job. No lock budget is increased.
Tests hold an uncommitted writer and confirm readers see the old consistent
state, then the committed state; the foreign-lock test still refuses writes.
22 history-store tests passed (`/tmp/gateway-history-store-v10.xml`); the
history router/API run had 37 passing checks and the one now-updated assertion
that formerly required read-only settings to contend on the write lock.

Real HTTP + application CLI subprocess + agent tool subprocess read the same
completed BTC/ETH minute dataset concurrently: each returned 25 unsampled,
verified rows with identical digest; invalid IDs/paths refused. Evidence:
`/tmp/gateway-surfaces-v10-20261114.json`. This verifies those three actual
surfaces, not the MCP transport nor migration of legacy research/backtests.
The server and dataset were isolated from normal user state.

### Completed v10 scenario components (hour/scan still pending)

`/tmp/gateway-mixed-client-v10-20261114.json`: one HTTP/SSE client, 180 s,
32 requests, six subscribed topics. Normal / WS-only outage / all-source
outage / recovered rounds: only the three cold bar requests in the all-source
outage returned 503; all recovered next round. All 12 option requests (including
a second AAPL expiration) passed identity checks; all four completed-history
pages succeeded. Four unfinished dataset reads returned the expected explicit
409. Both crypto topics observed upstream WebSocket and REST fallback, then
WebSocket again; stocks/options remained polled snapshots. No client transport
error. This replaces the earlier option-starvation failure for scenario 28.

`/tmp/gateway-quota-v10-20261114.json`: replayed 2,880 verified real records into
288 distinct production Cache keys. Under unchanged defaults, byte quota
forced eviction at 178 disk entries / 66,747,890 bytes, memory 8,249,742 bytes
(22 entries); oldest key absent and newest intact after a new Cache instance.
After the unchanged 120 s idle expiry, memory was zero and disk intact.
Prune was manually polled once per second (not a housekeeping-thread test);
report observation 151.85 s. Earlier live-cache probe separately verifies
housekeeping and actual process restart. No additional source requests during
quota filling and no fabricated observations.

MCP follow-up: `/tmp/gateway-mcp-v10-20261114.json` uses an actual FastMCP
protocol session (in-memory transport), real tool registry and history store.
Its 25 rows match the same digest as HTTP/CLI/Agent; invalid path refused.
No source/registry mock, no stdio/TCP transport claim. Public inventory checks
also exposed the missing Yahoo entry in the shared A-share fallback-chain
bullet; that guide and the related skill reference are corrected. The history
tool skill description now reflects compatible market/interval routing rather
than the obsolete SH/SZ-only scope. 115 inventory checks pass
(`/tmp/gateway-public-inventory-v10-fixed.xml`).

### v10 extended-run diagnostics (not final acceptance)

The same server exceeded one hour and completed 30 fault/churn cycles; the
5,224-symbol scan continues with 64 subscriptions and history work active.
The production implementation remains `8439edaab`; later commits concern
probes/documentation only. Three unique online cold requests returned timeout
503 (two explicit CCXT daily requests, one BTC five-minute request); an immediate
repeat of the latter returned cooling-down 503. These are not injected-outage
successes. Exact-parameter retests during the online scan-completion phase all
returned 200, cold-cache, in 8.125 / 2.316 / 7.379 seconds. Evidence:
`/tmp/gateway-v10-timeout-retest.json`. Successful retries establish recovery,
not absence of the original latency failures. The report now separately checks
unexpected HTTP errors, preserving them even when every recovery probe succeeds.
It also retains maxima across sample windows: instrumentation percentiles only
hold the latest 4,096 observations, so a late rolling maximum must not erase
an earlier event-loop stall. The captured slow-request stack shows a child SDK
wait and another source doing pandas conversion; it does not establish a
deadlock or prove that host load alone caused these remaining timeouts.

Independent offline session audit of the earlier live datasets used
`exchange_calendars 4.13.2` in an isolated `/tmp` dependency directory. All chunk
hashes were checked, without changing the catalog or making source requests.
Five-year/30-year monthly series contain exactly 61/361 distinct months per
symbol. HK/Canadian daily samples match all 52 expected sessions each. The old
UK sample lacks 2026-11-13; a fresh production API read during v10 includes it
and takes 1.625 seconds (`/tmp/gateway-v10-vod-retest.json`). The original
persisted sample is still incomplete; a later read cannot retroactively certify
it. US minute samples contain all 5,850 expected regular-session minutes per
symbol plus one extra 21:00 UTC closing-time point, with zero volume and equal
OHLC. It is retained as source data, not silently removed or called an ordinary
minute bar. This audit does not verify prices, official exchange announcements,
or promote stored `downloaded/calendar-unverified` jobs to complete. Evidence:
`/tmp/gateway-calendar-audit-20261114.json` and `/tmp/gateway-calendar-audit.py`.

### Deterministic SQLite lease cleanup (v11)

Inspection found a remaining native-resource retention path in `HistoryStore.lease`:
`with sqlite3.connect(...)` ends the transaction but does **not** close the
connection. Every lease lookup left its connection to cyclic garbage collection,
including during the subsequent long-lived file lease. An isolated real-SQLite
control disabled cyclic GC, performed 200 production lease lookups, and measured
OS resources: descriptors 3 → 203 and physical footprint +32,374,808 bytes.
GC then closed the descriptors but the allocator retained the physical pages.
With explicit `finally: db.close()` before the file lease, the same control
kept descriptors at 3 and the physical footprint unchanged at all checkpoints.
The control deliberately disables GC to expose lifetime semantics; it does not
prove that this path alone explains v10's normal-GC whole-process trend.
No quota, worker, deadline or lock protection changed. The regression keeps
strong references to actual connections and asserts they are closed inside the
lease, including a missing-job lookup. All 23 history-store tests pass after
correcting a misplaced assertion in the new test. Evidence:
`/tmp/gateway-lease-before-20261114.json`,
`/tmp/gateway-lease-after-20261114.json`,
`/tmp/gateway-history-lease-v11-fixed.xml`.
The already-running v10 process does not contain this fix; its eventual full
scan must not be presented as a post-v11 memory measurement.

Additional real surface check during v10: HTTP, application CLI and Agent
tool concurrently read offset 564, limit 25 from the 581,760-row five-minute
dataset. The first chunk has 576 rows, so this page crosses a physical chunk
boundary. All three returned the same unsampled 25-row digest
`4177db82058ed8745e5ffece3799a13ef9445e845b601bac97b3a0e30348fdbe`;
invalid IDs/paths remained refused. The probe now accepts `--offset`.
Evidence: `/tmp/gateway-surfaces-v10-chunk-boundary-20261114.json`.

### v10 finished: full universe acquired, cold timeouts remain

Measured production code `8439edaab`, server PID 94913: **7,158.85 active
seconds (119.31 minutes)**, 30 fault cycles, 1,425 paired subscriptions and
unsubscriptions, followed by **190.01 observed idle seconds**. The scan finished
**5,224/5,224, zero failed, zero remaining**: 5,603 symbol attempts, 379 retries,
701 batches, 5,722.696 s in acquisition and 1,431.648 s in scanner backoff.
The universe is SH/SZ A shares returned by BaoStock on 2026-11-13, excluding
Beijing, ETFs, indices and B shares. This is acquisition coverage, not a durable
full-universe dataset or a verified exchange-calendar audit of every scan row.

All 64 topics acquired data; 60 bar topics, two delayed option snapshots and
two crypto topics with actual upstream WebSocket/REST fallback. No client read,
driver, history-driver or cleanup exception. All 29 recovery probes succeeded;
all 30 deliberately offline probes failed visibly. Five-minute history finished
610 chunks/581,760 rows; fifteen-minute history also finished 610 chunks/193,920
rows. Thirty-minute work retained 53,256 rows when deliberately paused for
cleanup. Four routed history shapes succeeded; some individual routed attempts
paused during faults and must not be counted as unconditional successes.

The independent OS observer completed on the same PID: parent lifetime physical
peak **202.782 MiB**, actual concurrent parent-plus-child peak **567.471 MiB**,
at most one SDK child. Final physical footprint **167.860 MiB**, no children.
Late overall physical slope +0.192 MiB/min and final-30-minute slope +0.750
MiB/min remain reported, including the late transient rise; a temporary plateau
at 80–90 minutes does not establish leak absence. Native allocator bytes
allocated were 52.4 MiB at 60 minutes and 52.2 MiB in the early idle snapshot;
allocated bytes, fragmentation, RSS and physical footprint are different metrics.
The SQLite lifetime defect above is independently reproduced/fixed, not assumed
to explain every variation in this old process.

All actual source calls drained (5,246 started = 5,238 succeeded + 8 raised).
Subscribers/topics/pending updates, sockets, in-flight requests, RAM-cache bytes,
history reservations and expired scan metadata were zero at the idle tail.
Sampled 8/64 MiB cache budgets held, and the original driver/server/observer all
exited. **This run still fails the no-unexpected-HTTP-errors check**: three unique
online cold requests timed out, plus one immediate cooling-down repeat. Exact
later retests succeeded, as recorded above. It also predates the SQLite fix;
the fresh post-fix run is still required.

Evidence: `/tmp/gateway-router-v10-final-summary.json`, raw report and OS observer
`/tmp/gateway-router-hour-v10{,-os}-20261114.json` (actual observer filename is
`gateway-router-hour-v10-os-20261114.json`), `/tmp/gateway-router-v10-final.png`.

Fresh full-range calendar/daily-status verification after v10 shutdown passed
for both completed datasets: 5m 581,760 rows / 582 pages / 610 hashes in
34.45 s; 15m 193,920 rows / 194 pages / 610 hashes in 13.06 s. The five-minute
digest remains `0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`;
the fifteen-minute digest is
`a55b26e8d61232c8b887233103a777f64320e75f35534ed4d04d8394d00590c3`.
Reports: `/tmp/gateway-v10-fresh-{5m,15m}-verified.json`.

### Row provenance follow-up and v11 supersession

The post-SQLite-fix v11 server ran 1,022.05 active seconds and acquired 915
scan symbols with no client/driver error or unexpected HTTP status before an
intentional SIGINT. Its driver/server/observer exited; the report's
`CancelledError` records this deliberate stop, not a discovered runtime failure.
It is **not** a completed hour. `/tmp/gateway-v11-superseded.json` records why:
review of the mixed-market history path found stored chunk provenance was
missing from row-page responses, and the Agent status summary also omitted
chunks. Prices could therefore reach a consumer without their declared currency.

Row pages now retain the interval and the metadata for each included symbol/
chunk: source, quote currency, adjustment, volume unit, timezone and timestamp
basis. Missing fields remain null rather than inferred from a ticker. API and
CLI receive the same metadata; Agent/MCP pages use the existing shared output
budget, shrinking whole records and preserving the next offset instead of
truncating JSON. An individually oversized row is refused with an API/CLI
recovery path. No cache, worker, timeout, storage or coverage threshold changed.
41 history-store/router checks pass, including mixed currencies, unknown
metadata, source changes across chunk boundaries, lossless budgeted pagination
and oversized-row refusal (`/tmp/gateway-history-provenance-v12.xml`).

v11's completed 360-second mixed-client probe observed actual driver transitions
online → WS outage → all-source outage → online: 32 requests, all 12 bar reads
returned HTTP 200, but the immediate recovery round's six-market result was
partial (601398.SH and BTC-USDT missing during cooldown). HTTP 200 must not be
counted as complete acquisition. All 12 option reads and four completed pages
succeeded; four unfinished-prefix reads were explicitly 409. During the
all-source outage, bar caches were still fresh
(52–54 s) and the stale AAPL option cache was marked stale (67 s), rather than
misrepresented as a new acquisition. Both crypto topics saw upstream WS and
same-venue REST fallback. No transport errors. This complements v10's cold-
request outage test; it does not replace it. Three-market fresh history also
closed the earlier UK-date gap: 158 rows, HK 52 / Canada 52 / UK 54 exact
session dates in the offline calendar audit; stored coverage still says
downloaded/unverified. Evidence: `/tmp/gateway-mixed-client-v11-20261114.json`
and `/tmp/gateway-v11-three-market-verified.json`.

### v12 recovery-boundary failure and v13 correction

v12 (production `57a2f8270`) exposed two immediate option HTTP 503 responses
at cycle 5, elapsed 870.14 seconds, after the network was restored. These were
`cooling down or busy` responses (<1 ms), not source/read timeouts. The recorded
source-health samples show the CBOE/Yahoo cooldown had expired by that probe.
Code inspection and a failing regression reproduce the extra wait: a different
request identity arriving one second before the source's half-open deadline
skips every source, then `_done` starts a new **30-second request cooldown**.
The old code fails the new test with retry=30 instead of the remaining 1 second.

The correction reports the remaining earliest normal/half-open eligibility when
all routes were skipped. It does not claim a probe, shorten source backoff,
increase resource limits, or change actual source-failure cooldowns. Repeated
callers before the deadline still make zero source calls; after the deadline the
same identity recovers. A separate check pins the one-probe-per-cooldown limit.
Gateway/routing/scheduling regression: 48 passed (`/tmp/gateway-cooldown-v13.xml`).
The v12 incomplete mixed run is retained as failed evidence and superseded; it
must not count toward the corrected version's one-hour acceptance.

### v13 mixed-client result and measured queue timeout

Production `179545175` passed the 167 current gateway/stream/history/loader
regressions (`/tmp/gateway-current-v13-regression.xml`). A further actual spawn
process test passed: another process cannot recover/delete/steal an in-flight
job; cancellation preserves one committed chunk, and resumption reaches all
six fixture chunks. This is real process/file/SQLite ownership with controlled
data, not a real-provider price test (`/tmp/gateway-spawned-writer-v13.xml`).

The 360.065-second mixed client finished 32 requests and six SSE topics. All
12 option reads retained the right underlying/expiry; all four completed row
pages succeeded, all four unfinished-prefix reads returned 409. Normal and
WS-only-outage bar reads were complete. During full outage and immediate
recovery the cold requests failed explicitly; a separate client then retried
the exact three shapes while the original SSE client was still running. All
three eventually returned complete in 103.232 seconds, retaining intermediate
503/partial responses in the report. This is eventual recovery, not instant
complete service or zero transient errors.

The extra six-market timeout has a measured breakdown: request
`1404440380311041` spent 7.595 seconds before coordinator start, then sequential
source work reached the fixed 15-second deadline (caller returned 15.0103 s;
coordinator ended 15.0293 s). It was bounded queue/acquisition contention, not
an unbounded socket read or process crash. The later exact request completed
in 8.072 seconds with every symbol. Limits/deadlines were not raised. The
strict long-soak unexpected-error check remains unchanged; this separate
client's transient error must also be disclosed in the final report.

Evidence: `/tmp/gateway-mixed-client-v13-20261114.json`,
`/tmp/gateway-mixed-recovery-v13-20261114.json`, and v13 server request traces.

### Final v13: completed hour plus all 5,224 symbols

Frozen production `179545175`, isolated API PID 40620, unchanged 8 MiB RAM /
64 MiB disk caches, four source slots, sixteen pending requests, one history
worker, one SDK child and 256 MiB history quota. Only stream-topic capacity
was explicitly set to the requested 64. No profiler or forced collection.

- Active combined workload: 6,330.02 seconds (**105.50 minutes**); total
  warmup/load/idle time 6,709.29 seconds. Thirty fault cycles and 1,447 paired
  subscriptions/unsubscriptions. 560 samples contain all three concurrent
  workloads. Every one of the final report's **26 checks is true**.
- Scan complete: **5,224/5,224**, failed 0, remaining 0; 5,681 symbol attempts,
  457 retries, 711 batches. Acquisition 4,742.474 seconds (79.04 minutes),
  backoff 1,581.065 seconds (26.35 minutes). `last_error` retains a historical
  timeout even after success; it is not the final failed-symbol count.
- Main soak: no client-read/driver/history-driver/cleanup error; all 30 cold
  bars, 30 heavy-SDK probes, 60 option probes and 29 recovery probes returned
  200; no successful bar probe was partial. Thirty intentional offline cold
  probes failed visibly with 503. These claims exclude the separately reported
  mixed-client timeout, and do not erase transient source/stream failures.
- New routes: 45 attempts, 11 calendar-verified complete, 33 downloaded with
  source-calendar limitations, one monthly attempt paused after the test's
  90-second time slice. All four shapes succeeded on other attempts. Do not
  call every attempt successful or promote downloaded to verified. Sources
  observed include Binance, OKX, Tencent and Yahoo.
- Three ten-stock, five-year datasets completed: 5m 581,760 rows, 15m 193,920,
  30m 96,960; each 610 chunks. A 1H job kept downloading until scan completion
  and was intentionally paused with 27 committed chunks/2,164 rows at teardown.
  Total retained history uses 18,490,319 bytes with reserved bytes 0.

Memory and teardown:

- Parent OS lifetime physical peak **190.657 MiB**; final physical footprint
  **162.157 MiB**, RSS 29.891 MiB. Independent 0.5-second process-tree samples
  observed **559.939 MiB** peak, maximum one child, 32 distinct child PIDs, no
  remaining children. The conservative sum of separate peaks is 587.158 MiB;
  it is not the simultaneous measured peak.
- Ten-minute physical medians: 139.45, 141.45, 154.10, 158.09, 159.09, 160.74,
  158.67, 162.92, 162.30, 164.22, 164.14 MiB. After minute 30 slope +0.071
  MiB/min; last 30 minutes +0.040 MiB/min. This is warm-up plus a much flatter
  tail, **not a mathematically flat line or proof of multi-day leak absence**.
- Actual malloc bytes allocated at ~30/~60/~90/early-idle minutes:
  49.5/48.8/50.3/48.6 MiB. Allocator fragmentation at those snapshots:
  11.4/11.4/16.9/16.6 MiB. Physical footprint does not return to cold start
  merely because live records are freed; RSS is also affected by host paging.
- 189.94 seconds of observed idle: clients/topics/pending updates, sockets,
  source flights/queues, history reservations, RAM cache and scan metadata all
  zero. Disk cache retains 121 entries/3,214,514 bytes as configured. Resident
  worker threads remain available until server shutdown; driver, API server
  and observer were independently confirmed exited after the report.

Latency (successful main-soak requests, failures above still retained):

- Cold bars median/p95/max: 2.052/4.689/5.179 seconds; repeated bars
  3.04/7.52/8.06 milliseconds.
- Cold options (21 actual misses): 1.520/3.253/5.384 seconds. Repeated options
  median 1.86 ms; nine first probes also found fresh cache and are separate.
- History page median/p95: 22.22/29.49 ms. Sixty bar topics each had at least
  86 new acquisitions; largest gap 174.572 seconds including injected outages.
- Do not promise every interaction is instant: the separate six-market cold
  request timed out after 7.595 seconds queueing plus source work, then recovered;
  the full run also observed event-loop lag up to 3.454 seconds under load.
  Stocks/options remain polled historical/delayed data, not exchange tick feeds.

Final evidence: `/tmp/gateway-router-v13-final-summary.json`,
`/tmp/gateway-router-v13-final.png`, raw/OS reports
`/tmp/gateway-router-hour-v13-20261114.json` and
`/tmp/gateway-router-hour-v13-os-20261114.json`; reproducible reports and the
30-scenario matrix accompany this document. No Options Lab/frontend changes.

Independent verification after the v13 server exited re-queried the full-range
calendar and daily trade status, checked every stored chunk hash and streamed
every production row page. All three datasets passed:

- 5m: 581,760 rows, 610 chunks, 582 pages, 40.8 seconds; SHA-256 `0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`.
- 15m: 193,920 rows, 610 chunks, 194 pages, 23.08 seconds; SHA-256 `a55b26e8d61232c8b887233103a777f64320e75f35534ed4d04d8394d00590c3`.
- 30m: 96,960 rows, 610 chunks, 97 pages, 12.95 seconds; SHA-256 `aac161ad3cb74dbdf7293c29b9433f08068c1aa29a6399ca153a65ee87eab9b8`.

## v14: bounded foreground fan-out and production exchange calendars (2026-11-14)

The v13 six-market cold timeout was real: request `1404440380311041`
spent 7.595 seconds waiting for a coordinator, then acquired independent markets
sequentially until the 15-second caller deadline. Its later successful retry
was recovery evidence, not a fix. `historical.fetch_bars` now groups foreground
symbols by market and cooperatively drives those independent fallback chains on
the existing four source workers. There is no extra executor or coordinator.
A shared two-slot fan-out budget leaves capacity for one background acquisition
and one ordinary interactive acquisition. Background batches remain serialized;
source pacing is still weighted by symbol count. Queue time still consumes the
same 15 seconds; each source still has six seconds. A timed-out call retains its
actual source/fan-out slots until it exits. Partial responses are no longer saved
as fresh complete cache entries.

The regression replays 7.595 seconds of coordinator occupancy, six independent
1.4-second source calls and a held background source at actual default deadlines
(no scaled CPU/calendar costs). It finishes in the unchanged deadline with exactly
six acquisitions and at most two concurrent fan-out calls. Separate tests verify
that timed-out running calls retain capacity and interactive/background calls
still fit. The 155 gateway/history/calendar/network-profile tests passed in
51.934 seconds (`/tmp/gateway-current-v14-regression.xml`). Adjacent loader,
market-data and Windows file-lock tests passed (165); two additional timestamp tests
verify observed yfinance timezone survives a naive output index and Yahoo
intraday timestamps explicitly declare UTC bar-open semantics. No protected agent
core, Options Lab or frontend changes.

Production history now uses versioned `exchange-calendars` 4.13.2 session grids
for XNYS/XHKG/XTSE/XLON. It constructs only requested schedules, does not use the
global calendar dispatcher cache, and never builds a retained full-minute index.
Tests cover US DST, Thanksgiving/half-day, HK lunch, missing/extra/duplicate bars,
wrong timezones and exact weekly/monthly endpoints. Unknown calendar or timestamp
semantics stay unverified; known missing sessions fail. The existing BaoStock
trade-status/grid proof and continuous crypto grid remain unchanged. A known
Yahoo flat-OHLC/zero-volume session-close point is excluded with an explicit
record, while a real extra trade is refused. Empty closed intervals need no quote
source. Calendar proof does not establish prices, exchange status or per-security
suspensions; the reference version travels with provenance.

Fresh datasets under `~/.vibe-trading/history-calendar-v14-20261114`:

| Case | Rows | Seconds | Production terminal state |
| --- | ---: | ---: | --- |
| AAPL/MSFT 2026-10-26..11-13, 1m | 11700 | 6.564 | complete; two excluded close points recorded |
| AAPL/MSFT 2021-11-14..2026-11-13, 1M | 122 | 8.962 | complete |
| AAPL/MSFT 1996-11-14..2026-11-13, 1M | 722 | 43.533 | complete |
| HK/CA/UK 2026-09-01..11-13, 1D | 158 | 4.530 | complete |
| AAPL closed weekend 2026-11-07..08 | 0 | 0.208 | complete; no price/source fabricated |

All stored row pages passed coverage checks. HK actually encountered Tencent
HTTP 501 and Eastmoney connection failure before Yahoo completed the request;
this download used existing source failover, not a claim of zero source attempts.
The client did not resume/replay a failed job. Evidence:
`/tmp/gateway-calendar-fresh-v14.json`. Real HTTP, CLI, Agent tool and an actual
FastMCP in-memory protocol session returned identical 25-row CAD→GBP pages and
calendar/source/currency metadata; SHA-256 remained
`286f7d05702a8467a81e18d90f02b42df231c3d9c090696651eb27188b59c282`.
Evidence: `/tmp/gateway-v14-surfaces.json`, `/tmp/gateway-mcp-v14-20261114.json`.

Regional mechanisms were exercised with six controlled profiles: DNS refusal,
TLS failure, HTTP 451, HTTP 429, source timeout and complete outage. Across six
markets, tests verify fallback, per-market identity/currency, skipping sources
in cooldown, no fake data when all fail, and returning to the original route
after the network-health TTL expires. These are simulated restrictions, not
geographical measurements. The user has no authorized regional nodes/proxy exits;
real cross-region reachability is explicitly deferred. No unrelated SSH hosts
were used and no server purchase is required for this work.

The targeted v14 mixed-load run intentionally repeats four fault cycles, not a
new one-hour/full-universe acceptance run. The v13 105.5-minute, 5224/5224 result
above belongs to the previous revision and is not relabelled as v14 evidence.
It uses the same 64 topics, 5224-symbol scan queue, multi-year download producer,
routed history shapes, real upstream sockets, repeated unsubscribe/reconnect and
190-second idle tail, with all original memory/cache/source/request limits.

Four rounds submit the six-market daily request, dual-US five-year monthly
request and dual-US one-day minute request simultaneously, using unique valid
preview sizes as cold keys. There are no client retries: 12/12 return before
15 seconds; 11/12 are complete. The remaining six-market reply explicitly lacks
601398.SH because every A-share route is still in the post-outage cooldown. Its
2.659-second partial response is not counted as success and is not cached.
Three additional new cold keys after the online recovery phase all complete
while the upstream WebSocket is disabled and REST remains available. Across the
five six-market first attempts, four are complete (2.248, 7.298, 4.494, 7.875 s)
and one is the retained cooldown partial; across all 15 calls the maximum latency
is 13.202 seconds. This fixes the observed queue-plus-serial-acquisition timeout;
it does not promise complete data during every outage/recovery phase.

Evidence: `/tmp/gateway-cold-v14-valid.json` and
`/tmp/gateway-cold-v14-recovered.json`. The initial probe setup mistakenly used
preview sizes above the public 1000-row limit; three requests were rejected 422
before any acquisition. That harness error remains in `/tmp/gateway-cold-v14.json`
and is excluded from the 15 valid requests, not erased or counted as a gateway
success. The package wheel was built in an isolated build environment and
inspected for calendars.json, the new modules and the calendar dependency.
All 322 distinct automated checks across the gateway and adjacent suites passed.

The targeted run finished: active 514.97 seconds, total 801.37 seconds, four fault
cycles, 201 subscriptions and 201 unsubscriptions. Forty samples overlap all
64 topics, the scan and history. All four routed historical shapes completed
with calendar/grid proof; the five-year minute job remains only a partial
prefix in this short regression. The scan deliberately stopped at 336/5224 when
the four cycles ended. It is not a replacement for the v13 full scan. The formal
hour/full-scan checker retains its unmet long-run checks; the report is produced
with its explicit `--partial` mode, not weakened acceptance thresholds.

The parent physical-footprint peak was 165.02 MiB, final 139.77 MiB; independently
sampled process-tree peak 536.36 MiB with at most one SDK child. This short run
cannot answer multi-hour memory slope after this change. The 190-second natural
idle tail cleared RAM cache, subscriptions, sockets, source/coordination queues,
scan metadata and history reservations. Disk cache stayed 2,886,290 bytes under
the unchanged 64 MiB cap. Main harness read/driver/cleanup errors were zero;
the separate cold-client cooldown partial remains explicitly reported above.
All eight recorded PIDs (driver, observer, server, four SDK children and the
separate surface-test server) were independently checked after exit: none alive.

Stable copies, scripts, passing test XMLs and plot are under
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v14/`.


## v15: complete cooldown-only gaps from observed recovery (2026-11-14)

The v14 partial came from an A-share group finishing while all its routes cooled;
later successful Yahoo acquisitions in sibling markets did not reconsider it.
The fix uses a later successful call to the same adapter in another scope as
eligibility evidence for one half-open probe. It does NOT clear this scope's
backoff, bypass the existing one-probe-per-scope-per-cooldown budget, increase
pacing or substitute another market's prices. A failed probe still backs off;
older success or another adapter does not qualify. Only missing symbols skipped
entirely for cooldown are reconsidered once after the sibling groups finish,
within the same request deadline. Already fetched groups and actual failures
are not replayed. If recovery is not eligible, the envelope exposes per-symbol
`_recovery` and actual remaining retry delay instead of a fresh 30-second delay.

158 gateway/history/calendar/profile checks passed in 57.99 seconds. A real-source
precheck with only A-share health deliberately pre-seeded as cooled completed
all three simultaneous cold requests: six markets 5.841 s, five-year dual-US
monthly 3.019 s, dual-US minute 6.518 s. The A-share missing symbol was fetched
from Yahoo in the same request (`recovered_in_request`), with target currency and
provenance intact. No client retries or mock prices. Evidence:
`/tmp/gateway-v15-recovery-live.json`, `/tmp/gateway-v15-regression.xml`.

The full v15 test uses a fresh cache/history directory, 64 topics, all 5224 scan
symbols, ten-stock five-year minute downloads and four routed historical shapes,
30 repeated fault cycles of at least 120 seconds, plus three simultaneous cold
requests per online cycle (`--mixed-cold`). It must finish at least one hour of
active work and complete the scan; until terminal evidence is appended below,
this paragraph is a protocol, not a claim of completion. Cache 8/64 MiB, four
source workers, sixteen pending requests, 6/15-second deadlines and history
quota 256 MiB are unchanged. No geographic nodes are used.


The candidate `ead2cf068` completed the full live run without restart: 6888.42 s
(114.81 minutes) active, 7270.22 s total including warmup and natural idle.
All 26 formal workload/resource checks passed. There were 587 observed samples
with 64 topics, a running scan and a running history job together. Thirty fault
cycles and 1449 matched subscriptions/unsubscriptions ran; churn/fault injection
ended before the scan-completion tail, while 64 topics and history remained.
No unexpected foreground HTTP, client-read, driver or cleanup errors occurred.
All 30 intentionally offline probes returned explicit 503s. The 29 recovery
probes all returned 200. This is not a claim that public sources never failed.

All 5224 scan symbols were actually acquired, final failures zero: 729 batches,
5830 symbol attempts, 606 retries. Acquisition consumed 5341.539 s (89.03 min),
backoff 1540.376 s (25.67 min). Natural public-source failures during the late
phase are retained separately from the 30 intentional outages. Scan speed is
still limited by network acquisition, host pacing, fallback and background
contention; this does not make a full-market scan instantaneous.

All 90 concurrent cold probes completed on their first client attempts, with
90 gateway cache misses and 30 unique request keys per shape:

| Cold shape (30 calls each) | Median | p95 | Maximum |
|---|---:|---:|---:|
| Six-market daily | 6.796 s | 8.706 s | 11.519 s |
| Dual-US five-year monthly | 6.382 s | 8.728 s | 8.890 s |
| Dual-US one-day minute | 9.224 s | 11.088 s | 11.217 s |

The soak cold probes did not naturally emit `recovered_in_request`; that exact
branch is established by the separate real-source seeded-cooldown precheck
above, plus deterministic positive and negative gateway tests. A still-broken
target stays incomplete, is not cached, and cannot spend a second probe budget.
The final targeted suite passes 17 checks (the original 16 plus the added
negative variant); the broad 158-check run remains applicable to unchanged
production code. Cold success is not inferred from later client retries.

Ten stocks' full five-year 5m dataset completed with 610 chunks / 581760 rows,
production `coverage_verified=true`. After all soak processes exited, a fresh
independent BaoStock calendar and daily trading-status query verified every
symbol/date, every compressed chunk hash, all 581760 row identities/timestamps
and all 582 production-reader pages. The independent run passed in 51.86 s;
canonical SHA-256 `0d37d453f66d93bc75fb2d091129680b1e9091cce3434ba06aeca774543d2119`
also matches the independently verified v13 dataset for this exact range. This
is a full recheck of v15, not reused v13 evidence. Report:
`gateway-v15-fresh-5m-verified.json` in the evidence directory below.
The 15m workload then continued and was
intentionally paused at teardown at 145 chunks / 46128 rows; it is NOT a second
complete dataset in this run. The history driver explicitly calls the production
resume API after bounded failed jobs (41 recorded resumes); this does not prove
unlimited autonomous recovery without a client. All four additional historical
shapes completed at least once, but their attempt result is **41 complete / 4
paused**, not 45 successes. The four pauses reached the harness's 90-second
per-job scheduling window (92.97–98.61 s including cancellation): two US monthly,
one HK/CA/UK daily and one US minute. The first monthly partial had 75 rows / 8
of 12 chunks; retained traces show 11.16–12.22 s coordinator waits followed by
successful Yahoo requests. The other three retain source-unavailable/cooldown
or incompatible-fallback diagnostics. Subsequent US monthly acquisition
completed again. The partials remain in the raw report and formal summary;
`all_four_routed_history_shapes_acquired` only certifies shape coverage, not
success of every attempt. No acceptance threshold was relaxed.

Whole-parent physical peak 197.49 MiB, natural-idle final 170.41 MiB. The
independent 0.5-second observer measured an actual process-tree peak 567.85 MiB,
at most one SDK child; this is not an arithmetic sum of nonconcurrent peaks.
Physical memory rose during warmup and the later workload transition: the
post-minute-30 slope is +0.166 MiB/min, whereas the last 30 active minutes are
-0.234 MiB/min. Ten-minute medians near 80–100 minutes were ~174–175 MiB, then
~171 MiB near 100–110. Do not label the entire curve flat or claim a multi-day
leak proof. Read-only native malloc controls at ~29/~60/~84/~105/late-idle
minutes were 49.2/49.2/51.1/51.8/50.0 MiB allocated; late-idle fragmentation
15.3 MiB. No forced GC, tracemalloc or process restart was used. Descriptors
briefly reached 47 during natural HTTP failures, then fell to 23 at idle;
lsof snapshots preserve the connection evidence, including idle HTTP pools.

The 190.03-second observed natural idle tail cleared RAM cache, subscriptions,
pending push updates, upstream WebSockets, source requests, scan metadata and
history reservations. Disk cache ended at ~2.82 MiB under its unchanged 64 MiB
cap. Sampled RAM/disk cache peaks were 1410366 / 5008011 bytes; history used
12393124 bytes with zero reserved under the unchanged 256 MiB quota. All 5775
actual source calls drained. All 66 established upstream WebSockets closed.
An independent `ps` check after shutdown found none of the 36 recorded PIDs
alive (driver, observer, server and 33 distinct SDK children).

Stable raw reports, OS samples, plot, launch metadata, regression XMLs, cold
audit, native-memory/connection snapshots and exit check are under:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v15/`.
Real geographic-node testing remains deferred. Local routing fault tests do
not certify accessibility from other countries or regions.


## v16: background fairness and one recovery circuit (2026-11-15)

User requested fixing the four v15 routed-history pauses without longer deadlines,
more cache/memory, or another hour-long test. The original four records remain
above: a monthly queue convoy (8/12 chunks in 92.974 s), then monthly/HK-CA-UK
and US-minute source failures/cooldown (1/12, 0/3, 0/2 chunks). A public source
outage itself cannot be repaired locally. The fix addresses the measured queue
convoy and the software barriers that kept a recovered source inaccessible.

Confirmed implementation causes and changes:

- The one background coordinator was held for a whole eight-symbol scan request,
  across its sequential source calls. History therefore repeatedly waited the
  observed 11–12 seconds before even reaching a source. At source boundaries,
  the same coordinator now executes one queued background request before resuming
  the scan. Only one suspension level is permitted. The other coordinator stays
  available to foreground work, the one-background-source semaphore stays in
  force through real completion, and no thread/pool/pending limit is added.
  Source/rate admission is nonblocking and local contention is not recorded as
  source failure. Suspended scan deadlines are not reset or extended.
- History previously used a separate `history:<market>:<interval>` health scope,
  called exact bar routes that did not consult transport cooldown, and also hit
  the gateway's per-request `refresh_after` negative cache. Those layers could
  disagree with a newly observed source recovery. Persisted routes now share
  `bars:<market>:<acquisition interval>` health, including the daily transport
  for weekly/monthly aggregates. Managed exact-source attempts respect the same
  circuit/one-half-open-probe budget and omit the redundant request-key failure
  cache. Wrapped loader network failures remain network diagnostics, rather
  than collapsing into generic missing-data errors. No venue/caliber guard is
  relaxed; failed probes stay failed and repeated cooling reads send no traffic.
- Monthly planning unnecessarily created one chunk per calendar year, including
  a tiny leading partial year. New monthly plans span five years through the
  final month: <1860 daily input bars / <=61 monthly bars, below existing bounds.
  The exact five-year dual-US case uses two chunks instead of twelve, still
  requiring all 122 calendar-derived rows. Daily/intraday plans, persisted old
  plans, chunk/entry/storage caps and source deadlines are unchanged.

164 relevant automated checks passed in 55.84 s. Additional suspended-deadline and timed-out-background-slot retention
regressions passed separately (166 distinct checks total). Four decisive cases run against archived v15
modules fail (queue order, recovered/still-broken managed route, monthly request
count), while the same cases pass with v16. The initial old-code control
accidentally imported current modules because pytest's conftest prepended its
source directory; it is retained but is NOT old-code evidence. The corrected
control preimports the archived modules and prints their paths before pytest;
`/tmp/gateway-v16-old-control-fixed.log` and XML record the four expected failures.

The short live test completed: 571.81 seconds active (9.53 min), 790.91 seconds
including startup and 190.01-second natural idle. Same server PID 59551; four
fault cycles, 64 topics, 201 matched subscriptions/unsubscriptions, and 42
samples with history, the scan and all topics active together. The source code
in the running candidate matches the final five production files byte-for-byte
at diff level; only tests/documentation were added during the run.

| Routed task | Complete rows/chunks | Elapsed including recovery |
|---|---:|---:|
| Dual-US five-year monthly, first | 122 / 2 | 10.039 s |
| BTC/ETH daily window of minute bars | 2880 / 2 | 4.027 s |
| HK/CA/UK daily | 30 / 3 | 3.238 s |
| Dual-US one-week minute bars | 3900 / 2 | 41.437 s |
| Dual-US five-year monthly, repeat | 122 / 2 | 3.138 s |

All five attempts completed, none paused at the unchanged 90-second window.
The US minute task overlapped an injected complete outage, retained two failure
observations and completed after production resume calls; it is not a no-retry
claim. All 12 separate simultaneous foreground cold requests completed on their
first client attempt, max 12.960 s, with no unexpected foreground HTTP/client,
driver or cleanup errors. Seven background handoffs were measured on the same
coordinator. This limited live sample plus controlled recovery regressions
supports the fix, not a guarantee that all public sources are always available.

The 5224-symbol scan was intentionally cancelled after the short workload at
318 acquired / 392 attempts, 74 requeues, zero terminal symbol failures. The
large 5m history workload retained 76 verified chunks / 72240 rows, with a
failed state from the last injected outage/cooldown at teardown; it was not
resumed to complete 610 chunks. These are background-load prefixes, NOT repeat
full-scan/full-history acceptance. The existing full hour/universe/data evidence
remains v15. The unmodified full-run report uses explicit `--partial`: its four
long-run checks (full scan, hour, >=610 history chunks, complete 5m job) stay false;
the other 22 checks pass. The short run really received 3419 upstream WS events
and acquired 87 history chunks across its jobs, despite the >=610 check being
false. No test threshold was changed to manufacture an all-green hour report.

Peak parent physical footprint 176.75 MiB, idle final 151.44 MiB; independently
sampled process-tree peak 546.52 MiB, maximum one SDK child. Memory cache, topics,
listeners, upstream WebSockets, source requests, scan metadata and history
reservations cleared naturally. All 437 source calls drained and all 10 opened
upstream WebSockets closed. All seven recorded PIDs (driver, observer, server,
four SDK children) were independently absent after exit. The unchanged limits
are 8/64 MiB cache, 4 source workers, 16 pending, 6/15-second source/request
budgets, 1 history worker and 256 MiB history quota. No forced GC or restart.

Stable raw/OS reports, short summary/plot, candidate patch fingerprint, tests,
old-code control and exit check:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v16/`.
Real regional-node tests remain deferred. No Options Lab or protected agent
core files changed.

## v17: service-owned automatic history continuation (2026-11-15)

The missing behavior in v15/v16 was durable dispatch after the bounded per-chunk
attempts failed. Those drivers invoked `/resume`; the production service did not.
`HistoryStore.start()` now enables persisted recovery. Transient acquisition,
source cooldown and temporary admission failures schedule `retry_at`; the existing
cleaner dispatches due work through the unchanged single-worker/four-job queue.
Default spacing is 30, 60, 120, 240, then 300 seconds, reset by a committed chunk.
Waiting releases reservations. The lease plus a transactional state recheck
prevents two services or a stale dispatcher from overriding Pause or double
claiming. Waiting prefixes are protected from quota eviction, but normal idle
expiry still applies. Invalid/incomplete data and disk exhaustion stay visible
without indefinite automatic retry. Existing migrated jobs default to disabled
until explicitly started. Retry schedules survive store reopening; active jobs
interrupted by process exit still use the existing paused recovery behavior.

### Real-source short test

`tools/gateway_history_recovery_probe.py` starts a fresh standalone production
HTTP/SSE service. It sends **one initial resume POST**, commits real Yahoo AAPL
monthly history for 2021-11-14 through 2026-11-13, and injects a transport exception
at the MSFT fetch boundary. After observing `failed`, `retry_count=1`, a durable
retry deadline, one completed chunk and zero reserved bytes, the driver only
removes the transport fault. No recovery method, scheduler method or further
resume API is invoked. Successful rows are real provider data, not fixture prices.
This is a targeted transport fault, not a host-wide physical disconnection.

Observed: fault removed at 10.131 seconds; automatic completion at **43.508
seconds** from test start (33.378 seconds after restoration); total including
cleanup **46.532 seconds**. Both calendar-verified chunks yielded **122 monthly
rows**. AAPL's compressed SHA256 was unchanged and its source boundary was called
once; MSFT had three injected failures and one subsequent successful fetch.
There were **64 subscribed topics / eight SSE clients**, 138 delivered SSE events,
533 upstream crypto WebSocket events and no stream-task errors. The concurrent
5,224-symbol scan reached **112/5,224**, no failed symbols, and was deliberately
cancelled; this does not repeat or claim the previous full-scan acceptance.

All existing limits stayed unchanged: 8 MiB memory cache, 64 MiB disk cache,
2 MiB entry/chunk, four gateway workers, 16 pending requests, six-second source
and 15-second request budgets, 256 MiB history quota, one history worker. The
only load override was the previously authorized 64 topics. Idle observations
showed zero active requests, background queue/running work, sockets and clients;
history reservations were zero. The server PID 74722 was independently checked
absent after shutdown. Parent physical footprint was 114.39 MiB at the final
sample. This short sample is **not** a new long-duration memory stability claim.

### Regression checks and UI

- 13 automatic-recovery cases pass: autonomous continuation and intact-prefix
  reuse; pause versus stale dispatch; durable schedules and two dispatchers;
  permanent failures; bounded backoff and healthy-job admission; quota protection,
  idle expiry and delete; routing classification for network/cooldown/capacity/
  timeout versus absent history.
- 45 existing history store/router cases plus 80 API/routing/scheduling/calendar/
  source cases pass (138 distinct backend cases total, grouped runs).
- 47 frontend storage/i18n cases pass, including the waiting-state Pause action
  and **no browser resume call**. Eleven locale keys are present. CUA inspected
  the actual storage component in a temporary Chinese UI fixture; the retry
  countdown and Pause button rendered legibly. This UI fixture is not live-data
  verification; the separate HTTP probe above provides that evidence.
- Ruff and diff whitespace checks pass. Full frontend TypeScript build remains
  blocked by existing `PayoffComparisons.tsx:43,47` dynamic translation-key errors.
  A pristine `git archive HEAD frontend` control reproduced exactly those two
  errors before this change. Options files were not modified.

Evidence (metadata, logs, XML; no market-price payload committed):
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v17/`.

## v18: resume unfinished jobs on application restart (2026-11-15)

The v17 limitation is closed for jobs whose user start enabled automatic recovery.
The gateway's shared FastAPI lifespan reopens an **existing** history catalog at
startup, before any history-page request. No catalog means no new store/worker.
Normal shutdown preserves active/queued download intent; a restart after forced
termination reclaims stale reservations under the existing OS lease and queued
owner checks. Manual Pause's persisted cancellation takes precedence. Never-
started, permanently failed and quota-paused jobs do not become downloads simply
because the application reopened. Waiting network retries retain their deadlines.
Successful chunks still require their saved hash before reuse.

An initial real-source test showed both restart types could finish, but a stronger
shutdown observation caught the host re-raising SIGTERM before the active worker
persisted its stop checkpoint. Queued work was checkpointed, while the active
reservation depended on next-start recovery. `close()` now shares its **existing
one-second wait budget** between stopping the cleaner and waiting for cooperative
worker completion. It adds no thread, request time or shutdown wait allowance.
A source that cannot finish within that budget keeps its lease/reservation until
actual exit, and the next startup reclaims it; reservations are not prematurely
released underneath an active writer.

### Final real-source short test

`tools/gateway_history_restart_probe.py` used fresh catalogs and the production
`dev_server` app / `register_gateway_routes` lifespan. In each case the driver
started an AAPL+MSFT five-year monthly job, held the second fetch after the first
real chunk committed, queued a GOOGL job, started then manually paused TSLA, and
left AMZN never started. Successful rows came from real public sources. The
controlled fetch hold is a test hook, not synthetic price data.

| Case | State observed after stopping | Restart to verified completion | Total case |
|---|---|---:|---:|
| Normal SIGTERM shutdown | Both intended jobs checkpointed with retry deadlines and zero reservations; manual/never-started jobs paused | 3.601 s | 6.537 s |
| Forced SIGKILL | Active job still running with 2,162,688 bytes reserved; queued job still queued | 3.622 s | 5.693 s |

After each restart, the driver used **only read-only SQLite observation** to wait
for completion; it sent no history HTTP request and no resume call until the
catalog already showed both intended jobs complete. Each case made exactly three
initial user-start calls and zero resume calls after restarting. Both intended
jobs then exposed **183 calendar-verified monthly rows** through the normal API.
AAPL's prefix hash was unchanged and its fetch boundary was called once. TSLA and
AMZN made **zero source calls**, remained paused, and had auto-resume disabled.
Final reservations and active gateway requests were zero. All four final-test
server PIDs (80213, 80217, 80227, 80239) were independently observed absent.

Limits remained 8 MiB memory cache, 64 MiB disk cache, 2 MiB chunks, four gateway
workers, 16 pending requests, 256 MiB history quota and one history download
worker. Source/request timeout defaults remain six/15 seconds. This is a targeted
restart test, not a repeat of the earlier full-market/hour memory qualification.
The UI and Options Lab were not changed; existing waiting/Pause states are reused.

Evidence, including the stronger pre-fix shutdown failure and final successful
reports, lives outside the checkout:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v18/`.

Regression: **65 tests passed** across restart (seven cases), automatic retry,
history storage, gateway HTTP and subscription lifecycle suites. The cooperative
checkpoint case was rechecked after tightening its asynchronous-future assertion.
Ruff and whitespace checks passed. No frontend source changed in this revision,
so its previous validation/build limitation was not re-run or reclassified.

## v19: five-year minute history across four mixed-load restarts (2026-11-15)

No production code or resource configuration changed. The new reproducible short
probe `tools/gateway_minute_restart_probe.py` ran the current v18 production app
lifespan and history router, with a real **601398.SH / five-year / 5m** dataset
(2021-11-14 through 2026-11-13). A second five-year task, 600519.SH, was started
then manually paused while queued. Each process simultaneously had **16 default-
budget topics** (two crypto WebSocket topics plus 14 equity-bar topics) and a
real 5,224-symbol scan queue. No topic-budget override was needed.

Four restarts alternated normal SIGTERM and forced SIGKILL after **2, 7, 15 and
30 committed chunks**. A test-only hold occurred after a real source fetch but
before that chunk's durable commit. This deliberately tests the difficult
uncommitted-result boundary. Source prices were never synthesized. New processes
used production startup recovery; the client reconnected subscriptions and
queued scan load but made **zero post-restart history resume calls**. Progress
until each checkpoint was observed through read-only SQLite, not history HTTP
requests that could mask missing initialization. The only two start calls were
the initial main and subsequently paused jobs.

### Observed result

- **198.575 seconds total (3 min 19 s)** including independent verification;
  download, restart and HTTP-page portion: 190.717 seconds.
- **61/61 chunks, 58,176 five-minute rows, 1,212 traded sessions**. First bar
  2021-11-15 09:35, last bar 2026-11-13 15:00, Asia/Shanghai.
- **65 fetch attempts = 61 unique chunks + four interrupted/uncommitted chunks**.
  Completed prefixes retained their compressed SHA256 hashes. The call-log audit
  also checks every phase against the previously committed chunk boundary:
  **zero calls for already committed chunks**, including previously interrupted
  chunks once they had committed. Reacquiring an uncommitted result after killing
  its process is necessary; this is not a claim of exactly-once network delivery.
- A separate fresh full-range BaoStock calendar/daily-status query matched all
  1,212 sessions. Every bar passed exact intraday-grid, identity and strict
  ordering checks, detecting gaps and duplicates across month/restart boundaries.
  Every row from **59 actual HTTP pages** matched the canonical full-data digest
  and the separate verifier's 59 store-reader pages. Canonical SHA256:
  `63210f5b53f22e8daf1dc0b65d99bc7f690ed52f92262391c829236f490c8332`.
- The manually paused task remained disabled with **zero history fetches and zero
  rows across all five processes**. Ordinary scan/quote activity is separate from
  that task and does not count as waking the download.
- **428 SSE deliveries, including 350 WebSocket-tagged updates**, with live
  WebSocket updates in every process and zero stream-task errors. Each process's
  scan progressed: **16, 72, 152, 304, 288** completed symbols at the checkpoints,
  with zero failed symbols. These restarted scan prefixes overlap; they are not
  added as unique coverage and do **not** claim a full 5,224-symbol scan.
- Final history reservations were zero; all five server PIDs (85026, 85104,
  85200, 85292, 85622) were independently observed absent after completion.

The captured gateway limits in every process remained **8 MiB memory cache,
64 MiB disk cache, four workers and 16 pending requests**. History quota remained
**256 MiB**, with the existing one-worker/2 MiB chunk limits and six/15-second
source/request budgets. This test validates restart integrity and mixed-load
progress, not another hour-long whole-process memory bound.

Ruff and whitespace checks passed. The final report-audit helper was replayed
against the captured call log/catalog/stream metrics; it passes the committed-
prefix, live-stream, scan-progress, pause and unchanged-limit assertions. The
production code was unchanged, so the v18 regression evidence is retained rather
than repeating unrelated suites. Raw metadata, logs, calls and independent
verification are outside the checkout (no price rows committed):
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v19/`.

## v20: ten independent historical jobs sharing bounded workers (2026-11-15)

A focused pre-change admission control held one fetch and submitted ten jobs to
the real HistoryStore: tasks 1–4 were queued, **5–10 raised `History worker queue
is full`**. The old executor also ran every chunk of one job before another got a
turn. Merely testing one ten-symbol job would hide both the admission problem and
independent pause semantics, so this revision uses ten separate jobs.

### Changes without higher resource caps

The existing **32-job disk catalog** now retains accepted overflow intent as
`waiting`. This allocates no extra futures: the executor still has **one worker
and at most four submitted jobs**. Scheduled work yields after one committed
chunk; the dispatcher chooses the oldest waiting/retry-ready job. Direct internal
`run()` retains its full-job behavior; API/Agent/MCP start and CLI run use bounded
turns. Pause clears durable waiting intent immediately, and restart dispatch uses
the same lease/state recheck. Waiting prefixes retain the same retention/quota
protection as delayed retries. The Web UI displays Waiting as the existing Queued
translation and offers Pause; CLI polling includes Waiting. No locale key or
Options Lab change was needed.

### Real-source short mixed test

`tools/gateway_ten_job_restart_probe.py` submitted **ten individual five-year 5m
requests once**, 2021-11-14 through 2026-11-13, using 601398.SH, 600519.SH,
600036.SH, 600000.SH, 601318.SH, 600030.SH, 600276.SH, 000001.SZ, 000002.SZ,
000333.SZ. Every job acquired a real prefix before any pauses. At the first
checkpoint it paused **600036.SH while running**, **600000.SH in the executor
queue**, and **601398.SH waiting in the durable catalog**. It then performed
**three restarts**, normal / forced termination / normal, with no subsequent
resume call. Every process had 16 default-budget subscription topics (two crypto
WebSockets and 14 equity bars), plus the real 5,224-symbol scan queue.

The run took **263.533 seconds (4m24s)** including independent verification;
253.772 seconds through final process cleanup. All ten initial starts succeeded.
Observed committed chunks at the four checkpoints:

| Symbol | Before first restart | Second checkpoint | Third checkpoint | Final prefix |
|---|---:|---:|---:|---:|
| 601398.SH (paused) | 2 | 2 | 2 | 2 |
| 600519.SH | 2 | 4 | 6 | 8 |
| 600036.SH (paused) | 1 | 1 | 1 | 1 |
| 600000.SH (paused) | 1 | 1 | 1 | 1 |
| 601318.SH | 1 | 4 | 6 | 8 |
| 600030.SH | 1 | 3 | 5 | 7 |
| 600276.SH | 1 | 3 | 5 | 8 |
| 000001.SZ | 1 | 3 | 6 | 8 |
| 000002.SZ | 1 | 4 | 6 | 8 |
| 000333.SZ | 1 | 3 | 5 | 7 |

All seven unpaused tasks advanced after **every restart**. Each paused task had
**zero new fetch starts after its pause acknowledgement**. Completed prefix
hashes remained unchanged; every source attempt recorded whether its chunk was
already committed: **zero duplicate committed-chunk fetches**. There were 62
acquired attempts / 60 distinct chunk ranges, with 58 committed and the remainder
interrupted before commit or deliberately stopped at final cleanup. Uncommitted
results are allowed to be reacquired; network delivery is not exactly once.

Independent fresh BaoStock calendar/daily-status queries verified every completed
prefix, streaming all gzip records through strict symbol, order and exact 5m
intraday-grid checks. **58 / 610 planned chunks, 51,600 real rows** were verified
without gaps or duplicates **inside those prefixes**. Prefixes end between
2021-11-30 and 2022-06-30. This short test **does not certify all ten five-year
datasets as downloaded**. Incomplete jobs remain unreadable through the completed-
dataset row API; the verifier does not change that contract or forge completion.
All remaining jobs were explicitly paused at test cleanup, leaving zero reserved
bytes; all four server PIDs (90161, 90629, 91469, 91970) were independently absent.

### Mixed-load result and limits

There were **527 SSE deliveries / 464 WebSocket-tagged updates**, with real live
updates in every process and zero stream-task errors. Scan checkpoint completion
counts were **35, 96, 8, 112 / 5,224**, with zero terminal failed symbols, but the
scan was **not error-free**: five missing-symbol retries in phase 0 and eight
symbol retries following a **15-second request deadline** in phase 2. Logs show
Tencent HTTP 501/deadline failures, Eastmoney proxy disconnects and upstream read
timeouts during fallback. Those observations establish upstream failures and
budget exhaustion; they do not prove zero scheduling contention. The phase-2
snapshot includes 30.255 seconds of scan backoff, explaining much of its slow
progress. Restarted scan prefixes overlap and are not added as unique coverage.
These retries are retained as a limitation, not relabeled as a clean full scan.

Each worker snapshot and poll stayed at **one concurrent historical fetch,
executor max_workers=1, at most four futures**. Every captured gateway limit
remained **8 MiB RAM cache / 64 MiB disk cache / four gateway workers / 16 pending
requests**; history quota remains **256 MiB**, chunks **2 MiB**, catalog **32 jobs**,
source/request deadlines **six/15 seconds**. No worker/cache/memory limit was
increased. This short run is not another long-duration whole-process memory test.

Validation: **96 distinct backend tests** passed in grouped runs (50 history
admission/fairness/restart/store tests; 46 HTTP/stream/router/calendar tests), plus
**48 frontend/storage/i18n tests**. Ruff and whitespace checks passed. CUA inspected
the actual storage component connected to the live mixed-test server, verifying
queued/Pause and paused/Resume states and progress counts. Full frontend build
still has only the two pre-existing `PayoffComparisons.tsx:43,47` dynamic-key type
errors reproduced in v17; Options files were untouched.

Evidence (pre-fix admission control, real run, per-prefix verification, calls,
logs and test XML; no price rows committed):
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v20/`.

## v21 — scan deadline diagnosis and mixed short recheck (2026-11-15)

User constraint: repair missing scan symbols and the 15-second timeout without
raising any deadline, cache budget, concurrency or memory limit. Work stays on
`codex/data-gateway`; Options UI and protected Agent core are unchanged.

### Causes and changes

- Live Tencent replies were HTTP 501 with a `waf.tencent.com/501page.html`
  rejection body. Both urllib/requests and raw/encoded commas reproduced it;
  this was not a missing-symbol response. The loader retried the same rejected
  page three times, including 0.6 + 1.2 seconds of backoff. Permanent HTTP
  rejection now fails fast; 408/429/transient failures keep bounded retries.
- ScanQueue submitted eight symbols under one 15-second request although HTTP
  adapters already split them into serial four-symbol invocations. Scan requests
  now use the existing `HTTP_BATCH_SYMBOLS=4`, capped at the API maximum of eight.
  A scaled-time control with identical serial upstream work and deadlines
  completed only four of eight symbols on the old scanner; the new scanner
  completes both batches without retries. This changes work granularity, not
  provider pacing, parallelism or deadlines.
- Request-local memoization previously keyed the entire batch. After a partial
  result, changing batch membership could reacquire the same failed symbol from
  the same source. It now keys source/symbol and preserves successful members.
  Transport failures anywhere in the batch are recorded once; success of its
  first member does not overwrite the failure. Empty data stays distinct from
  a transport failure. Known healthy alternatives now precede an unseen baseline
  route in the same scope; market isolation and expiry behavior remain intact.
- The first instrumented mixed run (`v21a`, 210.528 seconds) still had two missing
  symbols in phase 2. It is **not a clean scan pass**, regardless of its older
  history-only `passed` field. The trace showed Eastmoney failure taking 5.132
  seconds, then BaoStock waiting **5.752 seconds for its occupied SDK session**,
  then Yahoo refusing later symbols because its host-pacing slots no longer fit.
  This established local admission delay in addition to upstream failure.
  Auto-routed reads with alternatives now decline an occupied BaoStock session
  immediately and continue failover. Exact-source requests and history downloads
  retain the original fair session queue. Busy admission does not poison network
  health; no new worker, retry or timeout was added.

Baseline controls failed all four initial targeted tests, the additional serial
request-deadline test and both SDK-admission tests. Their fixed counterparts pass.
The controls execute baseline module contents in separate interpreters and never
replace working-tree files. The final related backend run passed **247 tests**,
covering routing, scheduling, API, streaming, calendars, historical storage,
fairness/recovery/restart, and Tencent/BaoStock contracts. Ruff and whitespace
checks passed. No frontend implementation changed, so unrelated build checks were
not rerun.

### Final all-real mixed run (`v21b`)

`tools/gateway_ten_job_restart_probe.py` completed in **198.318 seconds**. Ten
five-year 5m jobs were submitted once with 16 default-budget live topics and a
5,224-symbol scan queue. Three restarts (normal, forced termination, normal)
exercised production startup recovery; the driver made no post-restart resume
calls. Paused jobs covered running, executor-queued and durable-waiting states.

- **160 completed scan requests** within the trace checkpoint windows: zero
  missing batches, zero scan retries, zero terminal scan failures, zero request
  timeouts; maximum **7.626 seconds**. Queue snapshots show 108 / 256 / 112 / 164
  symbols completed in the four phases. Snapshot calls happen after each trace
  checkpoint time; their batch counts can therefore be slightly later. Phases
  overlap and are not summed as unique full-market coverage.
- Tencent initially recovered, then failed again in later phases. Real busy
  BaoStock fallback attempts in phases 2/3 returned local `source_busy` in
  **0.177 / 1.803 milliseconds**, and real Yahoo supplied the missing symbols.
  The speed improvement is not attributed entirely to code: upstream availability
  changed during these experiments. Deterministic controls isolate code effects.
- **406 SSE deliveries / 348 WebSocket-tagged updates**, with updates in every
  process and zero stream-task errors.
- All seven unpaused history jobs advanced after every restart. The three paused
  jobs made zero new fetch starts after acknowledgement. **58/610 planned chunks,
  51,600 real rows** passed independent calendar/daily-status, exact intraday-grid,
  ordering, symbol and persisted-hash verification. Completed chunks were never
  refetched. There were 62 acquired attempts over 60 distinct ranges; interrupted
  uncommitted data may be reacquired. This is not network exactly-once delivery.
- All ten jobs were paused at cleanup with zero reserved bytes. Server PIDs
  98672, 98874, 99258 and 99463 were independently confirmed absent.

The short test verifies downloaded prefixes (through November/December 2021 or
May/June 2022), **not ten complete five-year datasets or a complete 5,224-symbol
scan**. In-flight scan work can be interrupted by a restart. The harness now
requires zero missing completed batches and zero retries for its overall mixed
`passed` result; trace and source diagnostics are retained rather than hidden.

### Controlled faults with real fallback prices

`tools/gateway_scan_contention_probe.py` separately injects Tencent 501 and a
5.13-second Eastmoney transport failure, holds the real BaoStock session admission
lock, and uses the unchanged gateway against **real Yahoo**. A single request
returns all four requested stock identities in **8.315 seconds**; the occupied
SDK attempt takes **0.480 milliseconds**, with no driver retry. This is explicitly
fault injection with real fallback data, not an all-live upstream benchmark.
Its Yahoo bar calendar coverage remains labelled unverified; it proves routing
and symbol coverage, not independent calendar completeness of those daily bars.

Limits stay **8 MiB RAM cache / 64 MiB disk cache / 2 MiB entries / four source
workers / sixteen pending requests / 6-second source and 15-second request
budgets / one history worker / at most four history futures / 256 MiB historical
quota / 32 catalog jobs**. No forced GC or larger limit was used. This is a short
functional contention/restart test, not another long-duration process-memory
soak or cross-region network qualification.

Evidence, controls, final test XML, traces and source-file fingerprints (no market
price rows committed):
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v21/`.

## v22 — complete 5,224-symbol mixed run (2026-11-15)

**Coverage completed; clean first-attempt coverage and memory stability did not
pass.** Production stayed at `8c5e73772` throughout. No resource limit, timeout,
router implementation or process restart changed during this experiment.

One full scan of the dated 2026-11-13 SH/SZ universe requested daily bars for
2026-11-02..13 while ten five-year 5m jobs and 16 topics (two crypto WebSockets,
fourteen equity bar refreshes) shared the server. The scan took **79m52s**;
startup, 180-second idle cleanup and independent verification brought the total
to **84m39s**. Test-controller memory is excluded from the OS process-tree samples.

| Observation | Result |
| --- | --- |
| Terminal scan coverage | 5,224 / 5,224; zero unresolved symbols |
| Acquisition | 1,568 batches; 6,270 symbol attempts; 1,046 symbol retries |
| Transient omissions | 800 distinct symbols missed their first attempt; 305 incomplete batches |
| Second-half retries | 548 additional symbol retries after 2,612 completed |
| Request deadline | Zero 15-second request timeouts; slowest scan request 7.222s |
| Source deadline | Two scan batches carried source-timeout diagnostics |
| Streams | 10,743 SSE deliveries, including 9,561 WebSocket-tagged events; no transport task errors |
| Retained history verified | 32 datasets, 1,378 chunks, 1,309,536 five-minute rows |
| Peak process tree | Physical footprint 178.63 MiB; RSS 166.31 MiB |
| After 180s idle | Footprint 174.75 MiB; RSS 36.88 MiB; RAM cache zero |
| Final bounded disk use | Cache 1,562,504 bytes; historical storage 26,500,958 bytes; reservation zero |

The SSE counter does not parse source-error payloads; transport continuity does
not mean every bar refresh succeeded. Traces retain occupied BaoStock admission,
Yahoo host pacing and HTTP route cooldown diagnostics. Final recovery does not
erase first-attempt omissions. The raw `report.json` remains `passed: false`.

### Later-half memory

Physical-footprint medians by completed-scan quarter were **128.24, 146.28,
152.00 and 158.89 MiB**. The second-half OLS slope was **+0.341 MiB/minute**.
Cache cleanup worked, but whole-process footprint remained elevated. This run
therefore does **not** establish stable whole-process memory. It also does not
identify a leak's cause: retained catalogs grew from ten to 32 jobs, an older
unsupported history range exercised failures, and the v21 test wrapper snapshots
the catalog twice per historical chunk. Separating live retained objects,
allocator retention and instrumentation cost requires a controlled follow-up.
No forced GC or tracemalloc was used. Legacy raw CPU-time fields are excluded
because their macOS timebase conversion was not validated; RSS/footprint were
independently cross-checked against the OS.

### Historical load and verification scope

The first ten 2021-11-14..2026-11-13 jobs completed all 610 chunks around minute
27. An explicit second wave requested 2016-11-14..2021-11-13; the first partial
month returned no matching minute grid (624 missing bars), and alternatives
failed. These ten empty jobs were paused, their failure metadata preserved, and
they were removed through the normal API. They are failures, not successful
historical-download pressure.

Further explicit ten-job waves repeated the known-working 2021..2026 range in
new datasets to sustain later load. This is intentional stress acquisition, not
refetching committed chunks within one job. Three effective waves completed
30 datasets; the final ten-job wave reached three or four chunks per job before
the scan ended. Wave transitions have brief gaps, so ten successful downloads
were not active at every instant. The last wave retired eight completed datasets
through the API after recording metadata to stay within the 32-job catalog cap;
this explains the retained-chunk drop in the plot. No raw-data archive bypassed
the quota.

At shutdown, the retained catalog held **22 complete and ten manually paused**
jobs. Independent verification checked all retained gzip hashes, symbol/ordered
5m grids and expected sessions via fresh BaoStock calendar/daily-status queries.
It covers all 1,309,536 retained rows, including partial prefixes, not the eight
already-retired datasets. Across retained and retired jobs, 1,866 chunks were
committed. Server PID 3331 and listener 8926 were independently confirmed absent.

### Limits, reconciliation and reproducibility

Unchanged limits: **8 MiB RAM / 64 MiB disk cache / 2 MiB entries / four source
workers / sixteen pending requests / 6s source and 15s request deadlines / one
history worker / four history futures / 256 MiB history quota / 32 catalog jobs**.

The original trace mixed historical fallback calls with scan calls: raw
`completed_scan_requests: 1704` includes **136 historical fallback requests**.
`gateway_full_scan_report.partition_bars` separates them and requires all three
independent queue totals to reconcile: **1,568 batches, 6,270 requested identities,
1,046 missing identities**. Final quarter boundaries use observed scan progress,
not input-symbol ordering. Future traces now carry interval/source/date fields
explicitly; the original measurement and raw report were preserved unchanged.
The harness's `passed` field tests clean scan coverage; memory is a separate
reported measurement, never implicitly passed by that flag.

Drivers: `tools/gateway_full_scan_probe.py`, `gateway_full_scan_wave.py` and
`gateway_full_scan_report.py`; reproduction commands are in the gateway README.
Only test/reporting tools and documentation changed this turn. The exact launched
driver and v21 server instrumentation, production hashes, raw metadata and final
summary/plot are preserved outside Git (no market price rows committed):

`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v22/`.

Bounded real datasets remain at
`/Users/wuhaozhe/.vibe-trading/full-scan-ten-v22-20261115/`.

## v23 — admission and observer-memory diagnosis (2026-11-15, completed)

The v22 trace partitions reconcile to 1,046 missing symbol attempts. Its largest
pattern (975) is BaoStock local admission busy, unconfigured token/file sources,
and cooled HTTP alternatives. The auto-route SDK hint used chain length as a
proxy for a usable fallback, so it abandoned the only usable session. The fix
checks current health/configuration, isolates optional SDK constructor failures,
and queues a wholly local, pre-network admission once after alternatives fail.
A source that already made a network attempt does not qualify. An explicit
`source_admission_yielded` context marker is set only by the SDK before login;
a bare HTTP `source_busy` report cannot authorize redispatch. Both source and
request deadlines, source workers, scan attempts and all cache/quota caps remain
unchanged. Regression checks count actual SDK acquisitions and preserve explicit
source waits, healthy bypass and refusal of mixed/network-failure redispatch.

The old test wrapper also read the complete catalog twice per chunk using
`with sqlite3.connect(...)`; this commits/rolls back but does **not** close the
connection. Replaying 401 reads of the same stopped 32-job catalog in independent
processes, with no explicit GC or network, measured:

| Read path | First → final physical footprint | Open connections at end |
| --- | --- | --- |
| Original test full snapshot | 21.25 → 105.58 MiB | 63 |
| Same snapshot, explicit close | 19.16 → 21.08 MiB | 0 |
| Fixed narrow test queries | 17.70 → 18.20 MiB | 0 |
| Production catalog status methods | 18.00 → 18.50 MiB | 0 |

Thus the measured v22 server included significant test-observer allocation; the
external controller was already excluded, but in-server observer code was not.
The snapshot helper now explicitly closes on success/error, and the ten-job
wrapper uses scalar existence/count queries instead of constructing full tables.
The short mixed driver records server and external-controller memory separately;
its plain mode executes the unmodified development entry with no probe hooks.

Two preliminary mixed candidates are retained, not passed: the first exposed an
optional SDK constructor exception contaminating the active source's health; the
second exposed busy admission followed by failed alternatives. Their scans had
20 and four retries respectively. Their independent verifiers returned BaoStock
10001001 while other live test traffic overlapped, so those prefixes are not
counted verified. A duplicate cleanup call also met already-expired scan metadata
(404); the new driver's stop operation is now idempotent. These are separate
from the final production version's results below.


### Final real mixed short test

The frozen final production version ran as the **plain development server**, with
no probe endpoint, monkeypatch or in-server observer. Four minutes of load plus
180 seconds of idle cleanup and independent verification took 435 seconds total.

| Observation | Final plain server |
| --- | --- |
| Workload | Ten 2021-11-14..2026-11-13 5m jobs; 16 topics; one 5,224-code queued scan |
| Completed scan at planned stop | 252 identities / 63 batches; zero retries, zero terminal failures |
| In-flight boundary | Four further identities were admitted when the short scan was cancelled; not counted as completed |
| Stream deliveries | 539 SSE events, 482 WebSocket-tagged; zero source-error events or transport errors |
| Retained history | All ten prefixes independently verified: 110 chunks, 103,872 rows |
| Final persistent state | Ten paused jobs, all `auto_resume=0`; reservation zero |
| History storage | 2,244,786 bytes under unchanged 256 MiB quota |
| Server footprint peak | 121.84 MiB at 117.6 seconds, in the first half |
| Second-half server footprint | 120.72–121.72 MiB; median 121.53 MiB |
| External controller footprint | 34.19–34.84 MiB |
| After idle cleanup | RAM cache zero; server footprint 121.72 MiB; RSS 31.69 MiB |
| Controller errors | None |

All retained rows were streamed from compressed files, hash checked, and compared
with fresh independent BaoStock trading-calendar/daily-status queries and the
exact 5m session grid. This verifies downloaded prefixes, not ten full five-year
downloads. The short scan was deliberately cancelled; `scan_final` in the driver
is its progress immediately before cancellation, **not** a completed full scan.
No repeated hour-long or full-universe test is claimed.

The second-half linear footprint fit is still **+0.405 MiB/minute**, and is
preserved in `summary.json`, not rounded to zero. Here that window starts after a
~1 MiB drop at minute two and returns within the already-observed high-water mark:
minute-two peak 121.84 MiB exceeds minute-three peak 121.53 and minute-four peak
121.72. The observed one-MiB band and idle plateau do not reproduce v22's growing
quarterly peaks, but this short test cannot prove indefinite memory stability or
attribute every native allocator page. No forced GC or allocator trimming was
used to obtain these numbers.

A preceding light-observer run exercised the same successful SDK admission path
before the final explicit-yield guard was added. It completed 240 scan identities
at its stop boundary; all **61** traced batches (including one finishing after
cancellation) returned every requested identity. Maximum observed request was
**10.937 seconds**, with zero request or source-timeout diagnostics. All ten
historical prefixes (111 chunks / 104,640 rows) independently verified. Its raw
report retains the obsolete double-cleanup 404; the final plain driver fixes it.
This is corroborating path evidence, not a byte-identical network speed benchmark.
An intermediate plain run was stopped before completion to add the explicit SDK
marker and is not counted as a passing final run.

Final verification: **186 relevant tests passed**, including SDK admission,
foreground priority, deadlines, routing, cache/API/streams, historical recovery,
calendar coverage, explicit SQLite close on success/error and no redispatch of
network/HTTP-busy failures. Ruff, compilation and whitespace checks passed. Limits
remain 8/64 MiB caches, 2 MiB entries, four source workers, sixteen pending
requests, 6s source / 15s request deadlines, six scan attempts, one history worker,
four history futures, 256 MiB historical quota and 32 catalog jobs.

All five server/controller PID pairs from this diagnosis were independently
confirmed absent; ports 8926 and 8927 had no listener. Final source fingerprints,
original rejected reports, raw metadata/logs, JUnit results, memory attribution
controls and the memory plot are outside Git at:

`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-router-hour-20261114/v23/`.

Final retained market data remains only at
`/Users/wuhaozhe/.vibe-trading/gateway-v23-final-plain/`.


## v24 — Existing consumers share gateway acquisition (2026-11-15)

Scope: align `codex/data-gateway` with `origin/main` `19c83de9c` (merge
`8fafb5d37`), then connect existing consumers. No options interaction changes,
no new hour-long soak, no resource/timeout/retry-limit increases.

Implementation: public `fetch_market_data` snapshots share `/data/bars`;
33 public-data tool modules use shared acquisition, retaining their providers
and parsers. Registered loaders cover full-frame analysis, backtests, paper
simulation and chart reconstruction. Large symbol universes use sequential
chunks of the existing batch size in the shared background lane. Shared HTTP
clients, bundled skill examples, portfolio reference FX and the read-only
public market-cap lookup also enter shared acquisition. Account/order
operations remain outside the public snapshot cache. Artifact persistence stays
with the requesting run. Internal custom resolver hooks retain their contract.

Cache reuse covers successful public JSON only. Settings changes change its
identity; errors and nested partial failures do not become fresh snapshots.
Depth, keyed/entitlement-scoped reads, mutable files and full DataFrames are
not persisted by this adapter. Opaque results retain every row/dtype/attr;
caller-owned analysis memory is not bounded by the snapshot cache's RAM cap.
The pre-existing explicitly enabled loader cache is not enabled or enlarged.

Validation evidence (overlapping suites; do not add these counts):

- Initial gateway/market/news/depth selection: 133 passed. Market-data/MCP,
  fundamentals, statements, screening/search selection: 237 passed.
- Wider public-reader/gateway selection: 1005 passed initially, two cache
  expectation failures identified. Configuration invalidation was fixed;
  the profile parser test now explicitly requests a new snapshot. The focused
  profile/papers/HTTP/consumer rerun passed all 129 after updating the curl
  timeout assertion to the unchanged 6-second source budget.
- Wider loader/analysis/paper/portfolio selection: 1991 passed, 9 skipped;
  its only failure was that same old curl timeout assertion, resolved above.
- MCP inventories, UI services, existing options routes, SEC paging, skill
  causality and consumer boundaries: 195 passed.
- After bulk chunking: consumer, BaoStock/Tencent, market-data, alpha and paper
  golden selection: 133 passed. Final consumer/scheduling selection: 39 passed.
- Frontend production build passed; 43 locale tests passed across 11 locales.
  New/changed non-skill Python passes Ruff; all changed Python parses. The
  pre-existing example-engine lint findings are outside the changed lines.

Live public-network observations, not an all-provider/region SLA:

- Mixed AAPL.US + 600519.SH snapshot: 0.845 s cold, 0.001 s repeated;
  sources Yahoo/Tencent with original currency and adjustment provenance.
- Stock news: 0.850 s cold; company profile: 2.097 s; option chain: 0.920 s.
  Repeated call timings rounded to 0.000–0.001 s. Four cache entries totalled 45,114 bytes;
  active requests returned to zero.
- Real `/data/bars` request via ASGI: HTTP 200 in 1.164 s; the agent read the
  identical rows in 0.001 s. MCP returned identical rows (cold registry
  initialization included). The initial probe used an artifact directory outside its
  allowed run roots, so it was not counted as evidence of artifact delivery.
  A follow-up configured an isolated authorized run root: agent cold read
  1.263 s / one source call; MCP cold registry read 1.416 s / zero source calls;
  MCP warm read 0.003 s / zero source calls. All three wrote their artifacts
  into their own run directories, outside the gateway cache.
- Full DataFrames for ten US stocks, 2026-10-01..2026-11-13: 8.074 s,
  ten results of 32 rows each, no unresolved symbols. This validates the full
  analysis boundary, not a new multi-year minute-data soak.
- Limits observed unchanged: 8 MiB RAM / 64 MiB disk snapshot cache,
  four source workers, sixteen pending requests; no active request remained.

Evidence outside the checkout:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-consumers-20261115/`.
Multi-region live verification and optional SDK environments remain unverified;
no new claim is made for them.


## v25 — Consumer bypass audit (2026-11-15)

Scope: inspect page/API, Agent, MCP, CLI and bundled skills after v24. No
frontend/options interaction, agent core, resource limits, retry counts or
request deadlines changed; no new soak run.

Found and closed:

- Network/terminal loader-availability probes (OKX/Nobitex/Wallex/Futu/MT5), RSS feeds, preflight
  market probes and custom resolver loader hooks now enter shared acquisition.
- CSI 300 constituents/daily/factors, industry/valuation Tushare endpoints and
  PIT fundamental reads were outside registered bar-loader fetches. Each actual
  acquisition now uses the shared source pool. BaoStock valuation sessions are
  bounded per symbol and materialized before session cleanup/slot release.
- Broker public quote/history/search/reference-data service entrypoints now use
  uncached acquisition. Credential isolation and account/order authorization
  paths remain unchanged.
- 256 bundled skill Markdown files and two Tushare Python scripts now point at
  gateway-backed reads or wrap their SDK collector. This includes code examples
  in reference pages, not just top-level SKILL.md. Yahoo lazy properties are
  materialized within acquisition; SDK download fan-out is disabled.
- Nested coordinator probes keep the owning gateway and directly use its source
  pool, avoiding self-queue deadlocks. Dynamic SDK callables (including Tushare's
  functools.partial endpoints) retain their schema and exception behavior.

Validation (overlapping selections; do not add counts):

- Gateway, market-data, preflight, RSS, routing, options, alpha, broker services,
  portfolio and enforcement selection: 601 passed.
- Tushare loader/fundamentals, industry, valuation, alpha and boundary selection:
  172 passed, 4 skipped (live Tushare tests require TUSHARE_TOKEN).
- Loader probes, skill-reference links, UI services and MCP regression/paging:
  970 passed. Final Futu/MT5 probe and boundary selection: 92 passed.
- Broker/boundary/portfolio selection: 209 passed before the final two boundary
  tests were added; the 601-pass selection includes those final tests.
- All 355 previously parseable Python fences in changed Markdown remain
  parseable; all changed Python parses. Changed runtime Python and new tests
  pass Ruff. The existing malformed noqa in okx.py emits a warning.
- Guards scan bundled skill Python/Markdown for direct provider primitives,
  pin central frontend fetch entrypoints and reject provider SDK imports in
  the MCP facade. Behavioral tests assert actual source ownership, nested
  concurrency, async cancellation/cleanup and credential-specific uncached reads.

Live, on this machine with unchanged defaults:

- OKX availability probe: successful in 0.546 s, one gateway source call.
- API bars: HTTP 200, 1.684 s acquisition, AAPL.US and 600519.SH each returned
  five daily rows for 2026-11-09..2026-11-13.
- Agent and MCP returned those identical nonempty rows with zero additional
  source calls. Their wall times (0.996 s / 3.128 s) include artifact/registry
  work and are not upstream latency measurements.
- Bundled Yahoo SDK adapter: five rows in 1.118 s, one source call, executed on
  gateway-source threads. Cache: one entry / 2,983 bytes; active requests zero.
- Limits: 8 MiB RAM cache, 64 MiB disk cache, 4 source workers, 16 pending.

The first live observer omitted submit_source's keyword arguments and caused
API 503; it is retained as probe-observer-error.json and excluded from passing
evidence. The corrected observer preserves the real signature and made no
provider substitutions. Evidence and probe are outside the repository at:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-boundaries-20261115/`.

No live credentialed Tushare/social/broker account validation or cross-region
claim is made. Arbitrary generated Python and externally installed MCP servers
are not network-sandboxed by this integration. Existing options/frontend build
and locale evidence from v24 is reused because those files are unchanged.


## v26 — Gateway-first agent prompts (2026-11-15)

Following the user's suggestion to address generated Python and external MCP
through prompts, this change adds one shared model policy to the actual main
system prompt, all swarm worker prompts, bash/background descriptions and
remote MCP tool descriptions. It removes two contradictory older instructions
that encouraged raw bash/yfinance (trading-plan prices and worker fundamentals).
The data-routing skill now gives an executable adapter example and distinguishes
source coverage gaps from gateway cooldown/timeout recovery.

The default flow is gateway tool → returned artifact → Python calculation.
Additional vendor fields use bounded adapters; per-symbol subprocess gateways
and independent polling/retry/cache loops are discouraged. External MCP tools
retain original schemas, dispatch and authorization. An uncovered capability or
explicit provider requirement remains usable with the source/coverage gap
reported, rather than silently calling it gateway-managed.

Validation: 143 tests passed across actual main/worker prompt construction,
prompt-cache stability, market-data, MCP adapter dispatch, swarm grounding/context
and gateway boundaries. Tests verify the emitted system message, tool descriptions,
removal of the old exceptions, preserved remote schemas/arguments and unchanged
readonly classification. A second shell/background/deferred-tool selection passed
62 tests. These overlapping selections do not prove model compliance on every turn;
no live LLM compliance benchmark or network-sandbox claim is made. No acquisition,
resource limits, option interaction, subprocess runtime or remote MCP call path
was changed.


## v27 — Main integration and real tasks (2026-11-15)

Fetched origin/main at 19c83de9c; it was already an ancestor of gateway commit
d070af8b7. Fast-forwarded the clean main worktree with no merge conflicts. The
separate research-experience checkout's in-progress merge was not touched.
All runs below use code from the main worktree, not the feature worktree.

Post-merge checks: 274 gateway/history/market/API/MCP/UI/options tests passed;
frontend production build passed (existing chunk-size advisory only). After the
small quote-time guidance correction below, 908 options/guidance/skill-reference
tests passed. These selections overlap and are not additive. No limits changed.

Real model tasks used the user's already selected custom provider/model
(deepseek-v4-1-flash-261017), the normal AgentLoop and full registry with shell
capability. No model was substituted and no response was mocked. The first
harness initialization failed because its isolated runtime could not find the
active custom profile; the corrected harness resolves a read-only provider
snapshot first and stores only task outputs in its isolated runtime. Credentials
were not copied into evidence or committed.

1. Cross-market research (40.58 s): agent fetched AAPL.US, 00700.HK and 600519.SH
   for 2026-11-09..13, then wrote and ran Python on the gateway's returned JSON
   artifact. Produced 15 daily CSV rows and 3 summary rows. Independently checked
   closes, first-to-last returns, sources and adjustment labels against the raw
   tool artifact. The generated script imports only json/pandas and performs no
   network acquisition. Mainland calendar coverage remains explicitly unverified;
   five returned rows are not reported as a verified exchange calendar.
2. AAPL options query (37.76 s): real Cboe data, nearest unexpired expiration,
   three near-money calls and puts, delayed/unknown quote-time metadata. Initial
   answer mislabeled last-trade times as quote times and inferred a timezone.
   Added explicit tool-description/reference guidance separating last execution,
   bid/ask quote time and gateway retrieval time; no options UI/schema changes.
   Re-ran the same user task (29.43 s): answer identifies quote timestamp as
   unavailable, preserves unzoned source strings, labels last_trade_time separately,
   and discloses stale/delayed cache status. This is an observed model run, not a
   guarantee that all future generations obey the guidance.
3. Concurrent history/stream task (12.08 s): real BTC-USDT and ETH-USDT 5-minute
   data for 2026-11-12..13, 2 completed chunks / 1,152 rows. Read every row through
   the history API and independently verified 576 unique symbol/timestamps per
   coin, exactly 300 seconds apart without gaps. API and agent history pages
   match. During download, both crypto topics received real WebSocket ticks;
   144 collected updates included initial REST snapshots and WebSocket events.
   After unsubscribe: 0 clients, 0 topics, 0 pending updates.

Observed resource defaults remain 8 MiB RAM snapshot cache / 64 MiB disk snapshot
cache / 4 source workers / 16 pending requests. No hour-long soak was repeated.
No live orders or outbound messages were requested or executed.

Raw task outputs, generated CSV/Python, initial/recheck responses, stream/history
results and independent audit are outside git:
`/Users/wuhaozhe/.codex/visualizations/2026/11/10/01a1c47d-d274-73c2-a6fa-75631dd811cd/gateway-main-20261115/`.
