# Gateway validation — 2026-11-14 (Asia/Singapore)

Branch `codex/data-gateway`, based on local main
`283e300e407a94eeaa82821f791f83a969b11dc1`. No push, deployment, frontend change,
provider-core change, or trading operation was performed.

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

**Outcome:** bounded cache and subscription cleanup verified; repeated live
reconnection verified with one unresolved first-attempt recovery failure; no
GB-scale runaway observed in this finite run. A claim of completely flat or
leak-free total process memory is NOT supported. Multi-year minute datasets,
quota settings, storage dialogs and resumable history jobs remain unimplemented.
