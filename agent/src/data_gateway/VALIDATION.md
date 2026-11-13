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
