# Unified local market-data gateway

This branch is independent of the options homepage. It contains backend routing,
continuous read-only subscriptions, API/CLI/tool integration and tests. It does
not change Options Lab interaction, agent execution logic, or order execution. Storage and acquisition
controls are available at the existing `/history-storage` page.

## What runs now

- Historical bars reuse the repository loader registry and each market's compatible
  fallback chain, with the existing normalization, currency and provenance rules.
  Mainland A shares can also fall back to the existing Yahoo transport: `.SH`
  maps to `.SS`, `.SZ` is retained, and the response must declare CNY. B shares
  and indices are excluded from that new route.
- US option snapshots use Cboe then Yahoo by default. `full=true` returns every
  validated standard 100-share contract at one expiration, within the response
  budget. Discover all expiration dates, then request each on demand. Adjusted
  deliverables and broker execution prices are not covered.
- Bar subscriptions (`bars:AAPL.US:1D`, `bars:00700.HK:1m`) continuously refresh
  the existing market routes; their quality stays `historical_bars`, not tick quotes.
- Continuous options subscriptions refresh these delayed/unknown-latency snapshots.
  There is one acquisition per topic, shared by all clients.
- OKX spot subscriptions combine a public WebSocket and same-venue REST snapshots.
  REST supplies initial/fallback state while the socket connects or is silent;
  when fresh socket events resume, polling stops. A failed socket reconnects with
  bounded backoff. Unsubscribing the last client cancels both tasks.
- No account, credential or trading channel is used for these public streams.

## Running and using it

Install the normal project environment, then from this checkout:

```sh
PYTHONPATH=agent python -m src.data_gateway.dev_server
# Read-only loopback server: http://127.0.0.1:8910/docs
PYTHONPATH=agent python -m src.data_gateway capabilities
PYTHONPATH=agent python -m src.data_gateway options AAPL --full
PYTHONPATH=agent python -m src.data_gateway watch crypto:BTC-USDT options:AAPL bars:00700.HK:1D --events 10
PYTHONPATH=agent python -m src.data_gateway bars AAPL.US --start 2026-11-01 --end 2026-11-12
PYTHONPATH=agent python -m src.data_gateway status
PYTHONPATH=agent python -m src.data_gateway prune
```

The main API mounts these routes through its existing authenticated options
registration. The standalone server checks both loopback client and Host.

| Route | Meaning |
| --- | --- |
| `GET /data/capabilities` | Actual wired capabilities and existing historical market/source chains |
| `GET /data/options?ticker=AAPL&full=true` | All standard rows of the selected source expiration |
| `GET /data/stream?topics=options:AAPL,crypto:BTC-USDT` | Shared SSE current-state stream |
| `GET /data/stream?topics=options:AAPL:1893456000` | Subscribe to an explicit expiration |
| `GET /data/subscriptions` | Active topics, clients, pending updates and limits |
| `GET /data/status` | Cache usage, active requests and local-network route health |
| `POST /data/bars` | Existing bar normalization with bounded/adaptive source attempts |
| `POST /data/scans` | Queue up to 10,000 public symbols using the same date/interval fields as bars |
| `GET /data/scans[/{id}]` | Coverage, retry and failure counts for process-local scan jobs |
| `POST /data/scans/{id}/cancel` | Stop new work; in-flight source slots remain held until completion |

SSE sends `snapshot` and `source_error` events. Each envelope contains `topic`,
`id`, and `payload`. Reconnecting clients receive current state, not event replay.
Clients should reconnect after the advertised delay and unsubscribe when hidden.
The existing agent/MCP `get_options_chain` tool shares the gateway; its optional
`offset` pages 60 rows per side through the complete source expiration in strike
order. Omit offset to keep the existing near-spot response. Each page includes
its acquisition time; if it changes between pages, consumers must restart their
collection rather than assume an atomic multi-page snapshot.

## Regional availability and quality

Routing learns from actual requests on this machine. A recent successful route
is preferred over a recently failing one; failures cool down exponentially.
A half-open recovery probe first tries a previously successful source, then
rotates through alternatives if it still fails; there is at most one probe per
scope per cooldown. A later successful acquisition through the same adapter
in another scope can qualify that one probe early; it never clears the failed
scope's backoff or substitutes another market's data. Within a mixed request,
only never-attempted symbols skipped solely for cooldown are reconsidered once
after sibling markets finish, using the original deadline and source slots.
Unresolved cooldowns expose `_recovery` and the actual `retry_after_seconds`;
partial responses are not cached as complete. Health expires so a changed network can try the original order again. Historical
health is separated by market and acquisition interval (daily/weekly/monthly
share the daily transport health). Persisted downloads share that same circuit
with ordinary bar requests, including exact-source fallback attempts. They do
not add a second per-request negative-cache cooldown that could hide fresh
recovery evidence; source backoff and the one-probe budget still apply.
No IP geolocation, proxy purchase,
background scanning or global availability claim is involved. Controlled tests
cover DNS/TLS failure, HTTP 451/429, slow sources, complete outage and recovery
after network changes. Real multi-region measurements remain pending because no
authorized regional nodes or proxy exits are available. Existing source
credentials/availability checks and explicit no-fallback sources stay enforced.

Source changes are visible in provenance. A venue, quote currency or adjustment
is never inferred from another source's successful response. The OKX REST fallback
stays on OKX, not another exchange with a different price. Historical fallback
may return a different declared adjustment; callers must read provenance as before.

A socket being connected does not prove that a quote is fresh. Crypto updates
include the observed source timestamp and age; aged updates are labelled stale.
Option `fetched_at` is acquisition time, not bid/ask update time. Cboe is delayed;
Yahoo's latency is unknown. Neither is labelled realtime or executable. Missing
Delta remains missing. No synthetic substitute is generated when sources fail.

## Resource contract

| Setting (`VIBE_GATEWAY_` prefix) | Default | Meaning |
| --- | --- | --- |
| `MEMORY_MB` | 8 | Serialized cache budget, not total process RAM |
| `MEMORY_IDLE` | 120 s | Evict memory entries with no reads since this idle limit |
| `CLEANUP_INTERVAL` | 30 s | Silent cleanup cadence (bounded above by idle/expiry limits) |
| `DISK_MB` | 64 | JSON cache budget; 0 disables writes |
| `ENTRY_MB` | 2 | Maximum normalized response/cache entry |
| `CACHE_ENTRIES` | 256 | Maximum cache entries |
| `WORKERS` | 4 | Concurrent source calls, including timed-out calls still running |
| `PENDING` | 16 | Distinct queued/in-flight requests |
| `SOURCE_TIMEOUT` | 6 s | Wait budget per source attempt |
| `HTTP_BATCH_SYMBOLS` | 4 | Symbols per serial HTTP-loader invocation and scan request (capped at eight); direct BaoStock batches may share one eight-symbol session |
| `REQUEST_TIMEOUT` | 15 s | Overall acquisition wait budget |
| `HTTP_TIMEOUT` | 5 s | Cboe socket/read deadline |
| `TTL` / `STALE_TTL` | 60 / 900 s | Cache freshness / maximum stale reuse |
| `COOLDOWN` / `HEALTH_TTL` | 30 / 300 s | Failure recovery / local route memory lifetime |
| `STREAM_TOPICS` / `STREAM_CLIENTS` | 16 / 16 | Per-process subscription limits |
| `STREAM_INTERVAL` | 1 s | Minimum SSE delivery interval; coalesces faster quotes |
| `STREAM_POLL` | 60 s | Options refresh interval, no faster than cache TTL |
| `STREAM_SNAPSHOT_INTERVAL` | 15 s | Crypto REST fallback cadence while WS is silent |
| `STREAM_QUOTE_AGE` | 30 s | Crypto source-age threshold for stale status |
| `OPTIONS_SOURCES` | `cboe,yahoo` | Supported option route baseline |
| `CACHE_DIR` | `~/.vibe-trading/cache/gateway` | Must be outside this checkout |

Cache paths ignore `VIBE_TRADING_HOME`. Disk writes are atomic and locked across
processes. Expired files/memory and idle route-health records are cleaned at startup, writes and at most every
30 seconds; reads never extend expiry. The lock file adds a few bytes outside the
JSON budget. No cron is installed. Tick events are never persisted. Idle RAM is reclaimed even
if the disk cache is unavailable. Last-unsubscribe clears the shared snapshot and
queued values immediately; cache entries are evicted after at most idle limit +
cleanup interval (150 seconds with defaults). Disk entries expire after 900 seconds
even if read repeatedly; the byte cap can evict them earlier.

Each stream client retains at most one pending value per topic (up to eight topics
per client), and shared payloads are references rather than per-client deep copies.
There is no unbounded tick history, automatic full-market firehose, Redis, Kafka,
ClickHouse or extra trading engine. Parsed upstream responses and Python/library
runtime overhead are additional to the 8 MB cache limit. Timeouts do not kill
Python threads: their source slot stays occupied until they return, which bounds
resource use but can temporarily return busy. Limits are per process; CLI and API
are separate processes if launched separately.

## Open-source research and design choices (2026-11-14)

| Project | Borrowed architectural idea | Why not embed its whole runtime |
| --- | --- | --- |
| [OpenAlgo](https://github.com/marketcalls/openalgo) | Unified market-data interface and shared subscriptions | Full broker/trading platform; AGPL-3.0 |
| [Cryptofeed](https://github.com/bmoscon/cryptofeed) | Venue adapters, normalized events, continuous feed lifecycle | Crypto focus; current upstream LICENSE is AGPL-3.0 |
| [NautilusTrader](https://nautilustrader.io/docs/latest/concepts/data/) | Explicit instruments, quote/bar types and event distribution | Full trading engine; repository LGPL-3.0 |
| [Intrinio SDK](https://github.com/intrinio/intrinio-realtime-python-sdk) | Contract/chain subscription granularity and queue discipline | GPL-3.0 client; actual equity/options feed requires a data subscription |

This implementation is original code in the existing MIT project; no code or
runtime dependency from these projects has been copied or installed. Free public
routes remain the primary path. Paid-feed and market-wide adapters are not
pretended to exist. Official protocol reference:
[OKX public tickers](https://www.okx.com/docs-v5/en/#websocket-api-public-channel-tickers-channel).

## Verification

```sh
PYTHONPATH=agent python -m pytest agent/tests/test_data_gateway*.py agent/tests/test_options_chain_tool.py -q
```

Tests exercise bounded queues, shared subscriptions, unsubscribe cleanup, socket
recovery, REST fallback and cessation after socket recovery, source-time ordering,
full-expiration coverage, network-route learning/expiry, historical fallback,
cache cleanup, timeouts and authentication. See `VALIDATION.md` for measured live
results and remaining limits. One-machine validation is not a global network SLA.

### Shared consumers (2026-11-15)

The existing page routes, CLI and Agent/MCP market-data tools now share the
snapshot gateway. `get_market_data` uses the same bar request identity as
`POST /data/bars`; artifact persistence remains outside the shared acquisition,
so cached results never reuse another caller's run directory. Options Lab's
interaction and the existing option-chain route are unchanged.

Public JSON readers for company profiles, financial statements/fundamentals,
news, screening, flows, sectors, ownership/ETF holdings, SEC filings,
prediction markets and research papers share the gateway's existing queues,
source workers and bounded cache. Their existing free-provider parsers and
fallback rules are retained. Settings changes invalidate reader cache identity
using a digest of the data configuration, never stored credentials. Errors,
including errors nested in a partial multi-entity result, are not cached.

Order-book depth, keyed/entitlement-scoped data readers, mutable local research
DBs and arbitrary web search/read requests share acquisition capacity but do
not persist a public snapshot. Their original validation/authorization stays
in the reader. Broker account/position/order operations remain on their
separate authorized channels. Public portfolio FX and the public market-cap
lookup use shared acquisition without caching account data or changing gates.

Registered bar loaders also use the gateway source pool for existing backtests,
paper simulation, chart reconstruction, technical indicators and full-series
analysis. Large analysis universes use the shared background lane (leaving foreground
capacity) and are read in sequential chunks of the existing
`http_batch_symbols` size, each using the existing acquisition deadline; the
analysis as a whole can span multiple acquisitions. DataFrames retain every row, index, dtype and attr and are handed
back to their caller, not stored in the snapshot cache. The pre-existing
explicit opt-in loader cache remains an independent user setting; the gateway
does not enable it. Use history jobs for large persisted, resumable datasets.
Internal injected resolver hooks retain their existing integration contract.

Shared HTTP clients and bundled skill examples enter the same acquisition
boundary. A nested provider operation already inside a gateway source slot
runs inline; it never queues behind itself. Source timeout remains 6 seconds,
request deadline 15 seconds, with 4 source slots and 16 pending requests.
Timed-out source work retains its slot until it actually ends. Curl and POST
transports now also cap their socket timeout to the remaining source budget.
Large opaque results are not silently truncated to meet the 2 MiB entry limit;
they are returned without persistent snapshot retention. Caller-owned analysis
frames can still use memory proportional to the requested analysis.

The boundary audit also covers custom resolver loaders, network availability
probes, RSS event feeds, CSI 300 universe reads, industry/valuation panels and
PIT fundamentals. BaoStock valuation reads materialize one serialized symbol
session per acquisition; session cleanup remains inside the owned source slot.
Coordinator-side probes use their current gateway directly, avoiding a nested
request queued behind its own coordinator.

Broker quote/history/search/reference-data reads share acquisition capacity
without public caching or changes to credential selection. Account, position
and order operations retain their authorized broker channels.

Bundled skill Python scripts **and Markdown code examples** use the same
boundary. `skill_sources.tushare_client`, `tushare_bar`, `akshare_query`,
`yahoo_ticker` and `yahoo_download` preserve vendor result schemas for additional
research fields. The Yahoo adapter materializes lazy fast-info inside the slot
and disables a second download thread pool. A custom synchronous collector can
use `managed_reader`; an async collector can use `managed_async_reader` when it
creates and closes all clients inside its body. Collectors must materialize network results before returning; credentials are
not persisted in the public cache.

The main agent, every swarm worker, shell/background tool descriptions and
external MCP descriptions share a gateway-first model policy. It removes the
old prompt exceptions suggesting raw bash/yfinance for prices or fundamentals.
Generated analysis should consume tool-returned artifacts. Additional fields
use the bounded SDK adapters. Timeouts/cooldowns are recovery conditions, not
permission to switch transports, multiply child gateways or raise limits.
Genuinely uncovered external MCP capabilities and explicitly requested providers
remain available with their source and local-gateway coverage gap disclosed;
account/order authorization is unchanged. This policy guides model choices and
does not change MCP dispatch, subprocess execution or the runtime resource caps.

This is application integration, not a network sandbox: arbitrary user/model
Python and separately installed third-party MCP servers can still create their
own clients. The bundled routing skill directs research to supported tools and
bounded adapters, and regression guards scan its executable examples. Software
updates, LLM transport, messaging and authorized order submission are not market
data reads and are not redirected through this gateway.

Historical dataset storage remains available in Settings and at
`/history-storage`. No frontend interaction change is required for these
existing consumers to use the gateway.

### Whole-process soak (opt-in, live public network)

```sh
PYTHONPATH=agent python tools/gateway_soak.py --output /tmp/gateway-soak.json
python tools/gateway_soak_report.py /tmp/gateway-soak.json
# Optional plot, using the project's existing matplotlib dependency:
python tools/gateway_soak_report.py /tmp/gateway-soak.json --plot /tmp/gateway-soak.png
```

The default run lasts about 30 minutes: three minutes warming data shapes,
twelve two-minute fault/churn cycles, then three minutes idle. It starts and
stops its own loopback-only child on port 8911 with a temporary cache. Keep that
port free. No production fault endpoint is added. Test-only hooks abort real
upstream WebSocket transports and refuse reconnect/source attempts inside the
child; they never modify host networking. Recovery calls real public endpoints.

The runner covers nine bar intervals (1m/5m/15m/30m/1H/4H/1D/1W/1M), US/HK/A-share
bars, crypto quotes, full option snapshots across expirations, 2-day/1-year/5-year
history windows, repeated SSE connect/disconnect and an intentionally unread
subscriber. Reports retain counts, provenance summaries and process metrics;
no market-price payload is saved. macOS reports RSS plus `proc_pid_rusage`
physical footprint; Linux reports RSS. Production and ordinary soaks never force garbage collection. Optional
`VIBE_GATEWAY_TRACE_DIR=/tmp/traces` records Python allocations and performs one
explicit diagnostic-only GC control after the natural idle sample.
Compare equivalent repeated workloads after warmup and observe the idle tail;
a finite soak cannot establish a universal multi-day memory bound.


### Historical coverage and large requests

`data._coverage` reports requested/observed bounds and whether returned rows were
sampled. `complete` detects missing symbols, known leading crypto boundary
gaps and exchange-calendar mismatches for settled, unsampled US/HK/CA/UK bars.
Each symbol states whether its calendar was actually verified; unknown markets,
unknown minute timestamp semantics, live ranges and sampled previews remain
unverified. `complete_scope` names these coverage checks instead of claiming
that every returned market has a calendar proof.
A nonempty response is not proof of full coverage. The OKX loader now tries its
history endpoint when the recent endpoint returns only a nonempty tail.

The current HTTP request limit is eight symbols, ten years and 1,000 preview
rows per symbol (the existing endpoint-preserving sampler can add a final row).
Preview sampling is declared in the data envelope and must never be used as a
complete backtest input. Large requests use the separate, unsampled history-job
path below instead of increasing the synchronous request limit.

### Persistent historical datasets

Settings → Historical data storage (also `/history-storage`) offers an estimate
before downloading, a shared disk limit, idle retention, pause/resume, pin and
delete. Defaults are **256 MiB and 30 unused days**; limits are 4 MiB–10 GiB and
1–365 days. This budget is separate from the 64 MiB short-lived gateway cache.
Once a user starts a job, exhausted transient network/cooldown/capacity attempts
schedule automatic continuation in the service. The existing cleanup thread
checks durable `retry_at` deadlines every second and dispatches through the same
one-worker/four-job in-memory queue. Backoff defaults to 30 seconds, doubles after another
failed run, and caps at 300 seconds (`VIBE_GATEWAY_HISTORY_RETRY_BASE` /
`VIBE_GATEWAY_HISTORY_RETRY_MAX`). These are retry spacing, not longer request
or source timeouts. A successful chunk resets the backoff. Waiting jobs release
reservations and retain verified chunks; no client resume loop is needed.

API/Agent/MCP status exposes `auto_resume`, Unix-seconds `retry_at`, and
`retry_count`. A waiting retry retains state `failed` and its error for diagnosis;
the Web UI shows the next retry and offers Pause. Pause/delete disable recovery;
invalid data, missing historical coverage and disk exhaustion do not retry
forever. Waiting chunks remain protected from quota eviction until their normal
idle retention expires. Retry schedules and active/queued download intent survive application restart.
The gateway host reopens an existing catalog during its lifespan startup, without
waiting for a history-page visit or status request. Normal shutdown preserves
unfinished jobs; after a crash, released job leases and dead queued owners allow
recovery to reclaim reservations and remove incomplete temporary files. Verified
chunks are checked and reused. A live owner's job is not taken over. Manual
Pause wins over both recovery paths. Old jobs migrate with automatic recovery disabled until the
user starts them again. No downloading occurs while the application is closed. Reopening the gateway host
continues eligible work; standalone CLI `history run` stays alive while waiting
and Ctrl-C explicitly pauses it.

New storage is created lazily at `~/.vibe-trading/datasets/history`; override with
`VIBE_GATEWAY_HISTORY_DIR` outside every Git checkout. No data is committed.

Downloads default to `source=auto` and route through the existing registry and
configured market order. `/data/capabilities` exposes the actual registered
source/market inventory, including which adapters require existing credentials;
registration is not a network or historical-depth guarantee. Background datasets
have no arbitrary ten-year cap: the 4,096-chunk limit, storage quota and actual
source availability bound each job. The planner accepts
1m/5m/15m/30m/1H/4H/1D/1W/1M and rejects known incompatible routes. Unknown adapter
capabilities are checked against the returned data. Explicit `source` pins that
provider; `local` is not a remote download source. No new credentials are created.

Automatic downloads learn local network health, prefer the previous chunk's
source on resume, and try compatible alternatives on failure. Currency,
adjustment and volume units must remain consistent across each symbol's chunks;
a source switch with unknown units/currency is refused. Crypto venue changes
within one persisted series are refused even when the quote currency matches.
Daily chunks cover at most one calendar year. Monthly chunks cover five years
through the final month (under 1860 daily input bars and at most 61 monthly bars),
without splitting a monthly aggregate; existing persisted plans are unchanged;
weekly chunks cover at most 52 weeks without cutting an aggregate. Intraday chunks
avoid splitting ordinary equity weekends into independent requests. The 4,096
chunk cap is enforced while planning, before an oversized list can accumulate.

Coverage has two distinct terminal states: `complete` means all chunks have a
coverage proof; `downloaded` means source rows were acquired without a complete
calendar proof. Both are readable without sampling; row pages explicitly return
`coverage_verified` and an unverified-coverage warning where applicable. Pages
also carry the interval and per-symbol, per-chunk provenance (source, currency,
adjustment, volume unit, timezone and timestamp basis). Missing metadata stays
null; a mixed-market page never inherits the first symbol's units. Agent/MCP
pages shrink by whole rows to fit the shared tool-output budget, preserving the
next offset; API/CLI pages keep their requested row limit. BaoStock
SH/SZ 5m/15m/30m/1H still checks calendar, daily trading status and exact intraday
grid (raw CNY, shares). Continuous crypto intervals require every expected grid
point. US/HK/CA/UK routes additionally verify exact sessions using
`exchange-calendars` (XNYS/XHKG/XTSE/XLON), including DST, half-days and HK lunch.
Daily/weekly/monthly endpoints use the last requested session of each period.
Minute bars require an observed timezone and bar-open convention (the Yahoo
transport declares UTC). Calendars are built only for the requested chunk; no
global minute index is retained. Missing, duplicate or unexpected bars fail.
A Yahoo flat-OHLC, zero-volume point exactly at session close is excluded from
history with its timestamp/reason recorded; nonzero-volume extra bars fail.
Closed intervals return zero rows with a calendar proof and no fabricated source.
Other markets or unknown timestamp semantics preserve unverified coverage;
nonempty rows alone are never proof. The calendar/version and exclusions travel
with row-page provenance. Calendar rules are a versioned local reference, not
a live exchange-status or independent price-verification service. A recent tail, missing OHLC, a
substituted interval, or a detected truncated boundary fails the chunk visibly.
Neither auto routing nor chunking manufactures unavailable multi-year minute data.

One download worker holds at most four submitted futures; each store permits at most
32 jobs, 100 symbols/job and 4,096 chunks/job. User-started jobs beyond the four
in-memory slots remain as `waiting` records in that existing 32-job catalog;
start accepts their durable intent without allocating more workers or futures.
The worker yields after each committed chunk and the dispatcher admits the oldest
waiting/retry-ready work. This lets large downloads share the worker instead of
making every later task wait for an entire five-year dataset. Pause disables both
waiting and active intent; waiting is displayed as Queued and is included in CLI
completion polling. This does not mean ten simultaneous source connections. Global cross-process reservations
cover each compressed chunk plus catalog overhead. A chunk cannot write past its
2 MiB reservation. Completed gzip JSONL files are atomically renamed and SHA256
verified on resume/read. Interrupted jobs retain their completed prefix. Network
failures retry three times per chunk; invalid/incomplete data fails closed.

Every 30 seconds, unused unpinned datasets expire; when capacity is needed, the
least recently accessed unpinned inactive dataset is evicted first. Pinned or
active datasets are never evicted. Quota/free-space exhaustion pauses the job
with a visible error and releases its reservation. Increasing quota or deleting
an unused dataset allows resume. Lowering a quota below current usage/reservations
is refused. Pin means manual retention, not unlimited storage. OS job leases
prevent conflicting resume/delete operations across processes. Metadata lock waits
are bounded by `VIBE_GATEWAY_HISTORY_LOCK_TIMEOUT` (default two seconds). New
catalogs use SQLite auto-vacuum to release unused metadata pages as well.

```sh
vibe-trading data history --help
# The module entry below exposes the same commands.
PYTHONPATH=agent python -m src.data_gateway history plan --codes 601398.SH 600519.SH --start 2021-11-14 --end 2026-11-13 --interval 5m
PYTHONPATH=agent python -m src.data_gateway history create --codes 601398.SH 600519.SH --start 2021-11-14 --end 2026-11-13 --interval 5m
PYTHONPATH=agent python -m src.data_gateway history run --job JOB_ID
PYTHONPATH=agent python -m src.data_gateway history rows --job JOB_ID --offset 0 --limit 1000
PYTHONPATH=agent python -m src.data_gateway history storage --quota-mb 256 --retention-days 30
```

BaoStock notices are routed to logging under its existing session lock, so CLI
and MCP stdout remain valid JSON without redirecting other threads. `history_data` provides plan/create/start,
status (10 jobs per list page), rows (at most 25 per agent page), cancel, pin/unpin, delete, storage and prune.
HTTP uses authenticated `/data/history/{plan,storage,prune,jobs}`; individual jobs
support `resume`, `cancel`, `pin` and `rows` (up to 1,000 rows/page). No endpoint
loads a whole five-year dataset into RAM. The completion manifest is not evidence
of a backtest result; downstream analysis must consume and validate the rows.

Live verification (queries the source again and reads every row without sampling):

```sh
PYTHONPATH=agent python tools/gateway_history_validate.py --root ~/.vibe-trading/datasets/history --job JOB_ID --output /tmp/history-verification.json
```

For separate synthetic capacity checks (no market data/network), run
`PYTHONPATH=agent python tools/gateway_memory_pressure.py` for near-entry-limit
subscription churn, or `python tools/gateway_capacity_probe.py --output /tmp/capacity.json`
for a bounded DuckDB/Parquet feasibility experiment. The latter is not connected
to the gateway; it does not establish provider history coverage.

### Reconnection memory and recovery

Public WebSocket connections use one verified TLS context, disable compression
for small ticker messages, and use OKX application pings rather than a second SDK
keepalive task. A connection factory records immutable IDs in logs instead of
storing the socket inside its own logger. Closed SDK error traces are released
while preserving error type, text and causes. This removes the closed-connection
reference cycles observed in allocation profiling, without process-wide GC.

Historical routes retain exponential source backoff. When normal routes have
failed, one half-open probe per market/interval per base cooldown may retry a
source whose last failure is at least that old. This prevents repeated outages
from blocking a recovered network for the longest backoff window. Worker limits,
request deadlines, same-key throttling and source identity remain enforced.
Failures report source/stage/type without logging raw upstream bodies or secrets.

### One-hour combined live test

The opt-in harness below runs production HTTP/SSE routes and history downloads
inside **one** isolated server process. It uses a fresh external directory, real
upstreams and normal resource limits. Thirty 120-second fault cycles give at
least one active hour, plus prewarming, probe time and a three-minute idle tail.
The first download is ten SH/SZ equities, 2021-11-14 through 2026-11-13, at 5m;
completed jobs are followed by 15m/30m/1H jobs so downloads continue throughout
the active hour. It cancels the final unfinished job between chunks for idle
measurement, retaining its verified prefix. No market data is written to Git.

```sh
PYTHONPATH=agent python tools/gateway_soak.py --history \
  --history-dir ~/.vibe-trading/history-hour-test-NEW \
  --cycles 30 --cycle-seconds 120 --warmup 120 --idle 180 \
  --port 8912 --output /tmp/gateway-hour.json
python tools/gateway_combined_report.py --input /tmp/gateway-hour.json \
  --output /tmp/gateway-hour-summary.json --plot /tmp/gateway-hour.png
```

`--history-dir` must not already exist. Faults abort this child's real upstream
WebSockets and BaoStock socket, and refuse source calls during simulated total
outage; they do not disrupt the host network. After exhausted chunk retries, the
legacy driver explicitly calls the production resume API. Its historical results
do not establish autonomous recovery; the dedicated recovery probe below does. No forced GC or allocation
profiler is enabled. macOS reports RSS, current/lifetime-peak physical footprint,
CPU time, threads and file descriptors; caches are reported separately.

Optional observers run alongside the same workload (the OS observer is macOS-only):

```sh
python tools/gateway_soak_observer.py --report /tmp/gateway-hour.json --output /tmp/gateway-os.json
PYTHONPATH=agent python tools/gateway_route_benchmark.py --url http://127.0.0.1:8912 --soak /tmp/gateway-hour.json --output /tmp/gateway-routes.json
python tools/gateway_stream_latency.py --url http://127.0.0.1:8912 --soak /tmp/gateway-hour.json --output /tmp/gateway-stream-latency.json
```

The route probe records requested and actual sources, so fallback does not count
as success for the original source. The stream observer requires a newly fetched
event after each network transition; replaying an old snapshot cannot establish
recovery. HTTP and source timings distinguish cache hits, failed requests and
source work. Reports retain only operational metadata, never price bodies.

For the heavier admission/refresh/batch-scan test:

```sh
PYTHONPATH=agent python tools/gateway_scale_probe.py --port 8913 --hold 600 --output /tmp/gateway-scale.json
```

It checks default 16-topic admission, then configures 64 topics (32 stocks × two
intervals) and submits the actual settled SH/SZ A-share inventory in eight-symbol
batches. It reports missing data, busy responses and refresh errors as failures.
It also exercises the existing separate market-ranking tool. See `VALIDATION.md`
for the failed full-scan/refresh case; a larger topic setting is not a guarantee
of throughput or coverage. Cache defaults additionally cap entries at 256, and
50 stocks × three intervals exceeds the current 64-topic configuration maximum.


## Scan scheduling and subscription capacity

Scan jobs use `HTTP_BATCH_SYMBOLS` (default four, capped at eight) per request,
with one background source call at a time. A request no longer holds two serial
HTTP batches under one 15-second budget. Within a request, each source/symbol
result is reused even when a later batch has different members; successful rows
are preserved and missing members move to the next compatible source.
The existing two request coordinators prefer foreground work; background work
cannot occupy both. Between source calls, a background coordinator can run one
waiting background request on its own thread before resuming the scan. This
cooperation is limited to one suspension level; the original deadlines keep
running, and the one-background-source gate remains held until real completion.
Local capacity/rate waits do not mark a source as failed.
Network workers remain four, pending flights sixteen, RAM
cache 8 MiB and disk cache 64 MiB. Source admission spacing is weighted by the
number of symbols (`VIBE_GATEWAY_SOURCE_SPACING`, default 0.25 seconds per symbol);
underlying SDK/host throttles remain in effect. This is process-local admission
pacing, not a promise of a provider's exact HTTP request rate.

A foreground multi-market request overlaps independent routes within those same
four source workers. Fan-out shares at most two slots across requests, leaving
capacity for a background call and an interactive quote/option call. Markets
retain their own sequential fallback chain; background scans stay serialized.
The original 15-second request deadline includes coordinator queue time, and
timed-out sources retain their slots until they actually finish. Partial results
are returned explicitly and are not retained as fresh complete cache entries.

`VIBE_GATEWAY_SCAN_SYMBOLS` defaults/maxes at 10,000 across all retained jobs,
with at most four jobs. `SCAN_ATTEMPTS` defaults to six and `SCAN_SPACING` to 0.25
seconds. Failed batches back off and only unresolved symbols re-enter the queue.
Failed symbols never count as completed. Terminal progress metadata expires after
`MEMORY_IDLE`; scan jobs are **not persistent across restart** and do not create
a durable whole-market dataset. Acquired frames use the ordinary bounded cache.
Use the historical dataset API for persistent minute data.

Run `vibe-trading data scan 601398.SH 600519.SH --start 2026-11-01 --end 2026-11-13`
or `python -m src.data_gateway scan ...`. Agent/MCP `history_data` exposes
`scan_create`, `scan_status`, `scan_cancel`; specify `interval="1D"` for daily scans.
The history/storage page offers the same operation using its symbol/date fields.

At most two subscription acquisitions occupy the async executor. Cancellation
keeps these slots reserved until the actual thread finishes. Daily, weekly and
monthly subscriptions for the same symbol share one 40-day daily acquisition;
weekly/monthly aggregation uses the existing market-data implementation. The
BaoStock SDK remains serialized; foreground reads receive priority, with a
background turn after at most four foreground admissions. Auto-routed reads
with alternative candidates do not wait for an occupied SDK session: they return
local `source_busy` and continue to the next compatible route immediately.
Explicit-source reads and historical downloads retain the existing fair queue.
Local admission waits are not classified as provider network failures.

Recently successful compatible sources precede unobserved baseline candidates.
Tencent fails fast on non-transient HTTP rejection (including observed WAF 501),
while 408/429 and transient server failures retain bounded retries. This does not
bypass provider blocks or remove pacing. Network errors anywhere in a partial
batch are recorded once; a successful first member cannot erase them.

CCXT is acquired in one bounded, short-lived child interpreter because repeated
SDK catalog allocations retained native allocator memory in the long-lived
process. Its deadline includes startup and it is killed/reaped on timeout. At
most one child exists; its PID and physical footprint are exposed in status so
memory monitoring must include it. Other compatible sources remain available.
No cache or memory budget was raised to accommodate the child.

Combined live validation (fresh history directory required):

```sh
PYTHONPATH=agent:tools python tools/gateway_soak.py --universe /tmp/real-universe.json \
  --history --history-dir ~/.vibe-trading/history-combined-NEW \
  --cycles 30 --cycle-seconds 120 --warmup 180 --idle 190 --port 8912 \
  --output /tmp/combined-hour.json
PYTHONPATH=agent python tools/gateway_soak_observer.py \
  --report /tmp/combined-hour.json --output /tmp/combined-os.json
```

`real-universe.json` must come from `gateway_scale_probe.universe()`, never a
synthetic symbol count. This mode keeps 64 topics subscribed, queues the entire
SH/SZ inventory and downloads real five-year minute chunks in the same service.
The observer samples the parent and actual child PIDs every 0.5 seconds. The
harness retains all transport errors; its client retires idle HTTP connections
before Uvicorn's five-second keep-alive timeout to avoid reuse/close races.

History BaoStock transactions share one aggregate timeout (the existing
`VIBE_TRADING_BAOSTOCK_TIMEOUT`, default 30 seconds) across lock admission,
login, calendar/status/bar messages and logout. A cancellation is checked before
the next attempt, and cannot be lost between queued-state inspection and start.
This tightens the cancellation bound; it does not increase source concurrency.
The default six-second gateway bar-source budget may still reject a healthy
BaoStock endpoint when it is slow. A compatible working alternative can take
over; no router can guarantee coverage when every eligible source is unavailable.

HTTP pacing respects the current acquisition deadline. A local pacing rejection
is reported as capacity pressure, does not mark the source as network-down, and
does not reserve a future request slot. Socket waits use the remaining budget;
actual work still holds its source slot until it exits.

### Automatic history recovery short probe

```sh
PYTHONPATH=agent:tools python tools/gateway_history_recovery_probe.py \
  --history ~/.vibe-trading/history-recovery-NEW --fault /tmp/recovery-offline \
  --calls /tmp/recovery-calls-NEW.jsonl --output /tmp/recovery-NEW.json \
  --universe /tmp/real-universe.json
```

This starts two real five-year monthly datasets once, commits the first symbol,
then injects a transport exception for the second. It restores transport after
observing durable retry state and performs **no further resume calls**. The
production scheduler must finish, preserve the first chunk's hash, and expose
122 calendar-verified rows. During recovery, 64 topics and a 5,224-symbol scan
queue provide background load; this short test intentionally cancels the scan
rather than claiming full scan completion. No request budgets or resource limits
are increased. See VALIDATION.md v17 for measured results and limitations.

### Application restart short probe

```sh
PYTHONPATH=agent:tools python tools/gateway_history_restart_probe.py \
  --root ~/.vibe-trading/history-restart-NEW
```

Uses two fresh catalogs to test normal application shutdown and forced process
termination. Each case interrupts real five-year monthly acquisition after a
verified prefix, with another job queued and a third manually paused. The new
process mounts the production gateway lifespan. The driver waits for completion
by reading the catalog directly, so no history HTTP call initializes the service
and no resume call can mask missing startup recovery. Started jobs must finish;
paused and never-started jobs must make no source calls. No resource limits change.

### Multi-year minute history across repeated restarts

```sh
PYTHONPATH=agent:tools python tools/gateway_minute_restart_probe.py \
  --root ~/.vibe-trading/history-minute-restart-NEW \
  --universe /tmp/real-universe.json
```

This bounded short probe downloads one complete five-year 5-minute series, with
16 default-budget subscriptions (crypto WebSocket plus equity bars) and the real
5,224-symbol scan queue alongside it. Four process restarts alternate normal
shutdown and forced termination. A test-only post-fetch hold interrupts a chunk
before it commits; such an unfinished chunk must be reacquired. Already committed
chunks must retain their hashes and must not be fetched again. A second five-year
job is started then manually paused and must remain dormant across every restart.
No post-restart resume API calls are made. After completion, every HTTP row page
is hashed and compared with a separate full-range calendar/daily-status and
intraday-grid verification. Reports distinguish partial scan load from a complete
scan, and interrupted attempts from repeated downloads of completed data.

### Ten historical jobs with mixed load and manual pauses

```sh
PYTHONPATH=agent:tools python tools/gateway_ten_job_restart_probe.py \
  --root ~/.vibe-trading/history-ten-restart-NEW \
  --universe /tmp/real-universe.json
```

Submits ten separate five-year 5m jobs once, pauses a running job, an executor-
queued job and a catalog-waiting job, then restarts with live subscriptions and
scan load. All seven unpaused jobs must advance after every restart. It verifies
every committed prefix against independent calendar/daily-status queries, checks
prefix hashes and source calls for duplicate completed acquisition, and measures
one active history fetch / at most four submitted futures. The short test is
explicitly not a full download of all 610 planned chunks. No resource limits
are raised and no client resume loop is used after restart.

The ten-job probe also writes `scan-trace.jsonl` with per-source timing and
per-batch returned identities/diagnostics (no price rows). A passing mixed report
requires zero missing completed scan batches, zero scan retries and zero terminal
scan failures at all phase checkpoints. In-flight requests interrupted by restart
are distinguished from completed requests. The scan still does not certify a
full 5,224-symbol pass during this short restart test.

For a separate fault-injected scan with real fallback prices:

```sh
PYTHONPATH=agent:tools VIBE_TRADING_DATA_CACHE=0 python tools/gateway_scan_contention_probe.py \
  --root ~/.vibe-trading/scan-contention-NEW
```

This simulates the observed blocked primary sources and an occupied BaoStock
session, then fetches real Yahoo bars once within the unchanged default budgets.
It labels this evidence separately from the all-real mixed restart run.


### Complete universe with ten history jobs and live streams (macOS)

```sh
PYTHONPATH=agent:tools python tools/gateway_full_scan_probe.py \
  --root ~/.vibe-trading/full-scan-NEW --universe /tmp/real-universe.json
PYTHONPATH=agent:tools python tools/gateway_full_scan_report.py \
  --root ~/.vibe-trading/full-scan-NEW --output /tmp/full-scan-report
```

The universe must contain the real 5,224-symbol dated snapshot. This fixed-date
regression uses the November 2026 scan window and 2021..2026 five-year histories.
It runs one server without restarts, samples OS parent/child footprint and RSS,
keeps production resource limits/deadlines unchanged, then observes 180 seconds
of idle cleanup and independently verifies retained historical prefixes. The
experiment wall-clock cap is separate from the unchanged 15-second request
budget. `passed` requires clean scan coverage without retries; memory trend and
SSE source payload quality require separate assessment.

If all ten historical jobs finish while the scan is still running, explicitly
add another wave (no automatic replenishment service):

```sh
PYTHONPATH=agent:tools python tools/gateway_full_scan_wave.py \
  --root ~/.vibe-trading/full-scan-NEW \
  --start-date 2021-11-14 --end-date 2026-11-13
```

The helper refuses unfinished prior jobs and records transitions, retiring only
completed test datasets when necessary to obey the existing 32-job catalog cap.
These are new datasets for load, not resume requests for committed chunks.
The report reconciles scan identities/batches against queue counters and separates
historical fallback calls. See `VALIDATION.md` v22 for the complete run, its
transient omissions, unsupported older range and unresolved memory increase.

### Attribute memory before declaring a gateway leak

Run each catalog replay in a fresh process against a **stopped** probe catalog:

```sh
PYTHONPATH=agent:tools python tools/gateway_memory_attribution_probe.py \
  --root ~/.vibe-trading/full-scan-OLD --mode legacy
# Repeat with --mode closed, --mode narrow, and --mode gateway-catalog.
```

These read-only controls separate unclosed observer SQLite connections, full
catalog materialization, narrow observer queries and the production history
status methods. They perform no network acquisition or forced garbage collection.
The legacy mode deliberately reproduces the old test defect; it is not a gateway
configuration.

For a real mixed short test with ten five-year jobs, sixteen topics and a scan:

```sh
PYTHONPATH=agent:tools python tools/gateway_mixed_memory_probe.py \
  --root ~/.vibe-trading/mixed-plain-NEW --universe /tmp/real-universe.json \
  --mode plain
# After completion, repeat in a fresh directory with --mode instrumented.
```

Defaults are four minutes of acquisition plus three minutes of idle cleanup.
The plain child runs the gateway development entry directly, without a tracing
wrapper or probe endpoint. The external controller records its own memory
separately from the server process tree and writes samples incrementally. The
instrumented variant adds bounded identity/call traces with explicitly closed
SQLite reads. Both retain the same production limits, deadlines and scan retry
policy, and independently verify retained historical prefixes after shutdown.
A short scan is intentionally cancelled; it does not certify all 5,224 symbols.
Do not overlap an independent upstream verifier with another live experiment.
