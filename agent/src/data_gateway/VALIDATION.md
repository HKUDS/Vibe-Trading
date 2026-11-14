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
