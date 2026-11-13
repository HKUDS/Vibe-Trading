# Unified local market-data gateway

This branch is independent of the options homepage. It contains backend routing,
continuous read-only subscriptions, API/CLI/tool integration and tests. It does
not change Options Lab, the frontend, agent core, or order execution.

## What runs now

- Historical bars reuse the repository loader registry and each market's compatible
  fallback chain, with the existing normalization, currency and provenance rules.
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
Health expires so a changed network can try the original order again. Historical
health is separated by market and interval. No IP geolocation, proxy purchase,
background scanning or global availability claim is involved. Existing source
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

Other existing research tools/backtest entrypoints retain their current loader calls;
this branch provides the shared gateway and connects the existing options-chain
Agent/MCP surface. A wholesale Agent/tool migration is not part of this isolated
backend change. No frontend file differs from the branch base on `main`.

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
physical footprint; Linux reports RSS. No forced garbage collection is used.
Compare equivalent repeated workloads after warmup and observe the idle tail;
a finite soak cannot establish a universal multi-day memory bound.


### Historical coverage and large requests

`data._coverage` reports requested/observed bounds and whether returned rows were
sampled. `complete` detects missing symbols and known leading crypto boundary
gaps; `complete_scope` explicitly excludes internal-gap/calendar verification.
A nonempty response is not proof of full coverage. The OKX loader now tries its
history endpoint when the recent endpoint returns only a nonempty tail.

The current HTTP request limit is eight symbols, ten years and 1,000 preview
rows per symbol (the existing endpoint-preserving sampler can add a final row).
Preview sampling is declared in the data envelope and must never be used as a
complete backtest input. There is no implemented persistent multi-symbol history
job, quota reservation, resume manifest or storage-settings dialog in this branch.
A ten-symbol multi-year five-minute request needs that separate bounded job path;
increasing the synchronous request limit is not a substitute.

The suggested separate history-store policy is opt-in capacity, chunked acquisition,
resumable manifests, observed coverage and data-version checks, default idle expiry
(e.g. 30 days) for reusable unpinned datasets, and explicit manual retention. These
are design proposals, not active settings; the shipped gateway still uses the
120-second idle RAM / 900-second disk-cache defaults above.

For separate synthetic capacity checks (no market data/network), run
`PYTHONPATH=agent python tools/gateway_memory_pressure.py` for near-entry-limit
subscription churn, or `python tools/gateway_capacity_probe.py --output /tmp/capacity.json`
for a bounded DuckDB/Parquet feasibility experiment. The latter is not connected
to the gateway; it does not establish provider history coverage.
