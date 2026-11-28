---
name: data-routing
category: data-source
description: Map research needs to gateway-backed tools. The runtime gateway owns source routing, bounded acquisition and caching; preserve credentials and source provenance.
---
# Data Routing (Router)

The runtime data gateway owns acquisition, source health, queues and cache.
This skill maps a research need to the existing gateway-backed tool; the model
must not recreate a separate provider-selection or retry loop.

Use `get_market_data`, `get_options_chain`, and the research tools below first.
`get_market_data` with a task workspace exports the same returned rows to CSV
in Python by default (`export_csv=false` disables the sidecar) with source/currency/adjustment metadata and sampling flags. Its
`_csv_file` receipt provides the path, columns, row count and checksum. Sampling
still applies; this is a task artifact, not another acquisition or a full-history
download. `_data_layout` describes the saved JSON structure for custom calculations.
For Python bars use `src.market_data.fetch_market_data`; for additional vendor
fields use `src.data_gateway.skill_sources` or a `managed_reader` that creates,
reads and materializes its SDK result inside the bounded callback. Do not return
lazy SDK properties, iterators or network clients for later unbounded reads.
Credential-scoped data uses uncached acquisition and keeps existing authorization.
Large history requests use `history_data`; do not download whole years into an
unbounded script cache. These adapters share the existing resource limits.

## Generated Python and external MCP

For supported data, acquire it with the available gateway-backed tool in the
agent process and calculate from the returned artifact path. Do not refetch the
same observations inside `bash` or `background_run`. A saved artifact is a
returned file, not a path to guess. This keeps repeated requests in the host's
shared cache and acquisition pool.

For an additional vendor field that the existing tools do not expose:

```python
from src.data_gateway.skill_sources import yahoo_ticker

# This adapter materializes the field inside bounded acquisition.
profile = yahoo_ticker("AAPL").info
print(profile)
```

For other SDKs, place client creation, the read, full result materialization and
client cleanup inside a `managed_reader` function. Use `managed_async_reader`
only for a self-contained async collector that also closes its clients. These
are process-local limits: launching many Python children creates independent
gateways. Do not use per-symbol subprocesses or add polling/retry/cache loops to
get around the host's limits. Use `history_data` for large persisted downloads
when it is available in the current tool catalog.

For public-data MCP calls, first select a gateway-backed equivalent with the
same market, instrument, interval and price basis. A busy response, timeout or
cooldown is a recovery condition, not missing coverage: follow the returned
recovery instructions, and do not switch to raw Python or another MCP provider
to evade it. If a capability truly is not covered, or the user explicitly needs
a particular provider, keep using the existing authorized MCP tool and disclose
its source and the gateway-coverage gap. This policy does not intercept remote
server network activity; do not claim external MCP reads share the local cache.
Account reads and mutations retain their own authorization and order gates.

## Acquisition planning

Resolve bare or ambiguous stock names once before dependent reads, including
options. Batch canonical symbols with the same exact requested dates and
interval. For `get_market_data`, keep `start_date`/`end_date` as the analysis
window. When calculation history is needed, set `warmup_start_date` explicitly
before `start_date`; the result's `_request_window` distinguishes analysis and
acquisition dates, and returned rows/CSV include the prefix. The agent runtime
clips accidental overlapping date padding for a single literal ISO date range
and canonical instruments named in the current user request. Multiple windows,
disjoint comparisons and indicator/backtest internal warmup remain separate.
Reuse the options response's underlying price when sufficient. For a
bounded full-day minute calculation, request `max_rows=0` on the first call;
a sampled result's artifact also contains sampled rows. Inspect an existing
artifact before fetching again, and combine inspection, calculation and CSV
writing in one Python execution where possible. Preserve `quote_currency_basis`:
`source_metadata` is declared upstream; `instrument_market_contract` is the
project's instrument currency rule, not a vendor declaration.

Japanese `.T` bars (for example `7203.T`) route through Yahoo then yfinance,
with JPY metadata required and XTKS calendar checks. This is data coverage;
Japanese backtest execution rules are not implemented. An unknown public venue
returns `unsupported_market`, never an A-share fallback. Resolve the symbol or
report the unsupported coverage instead of changing transports.

European listings in Yahoo's suffix form (`SAP.DE` Xetra, `MC.PA` Euronext
Paris, `ASML.AS` Euronext Amsterdam, `ENI.MI` Borsa Italiana, `NESN.SW` SIX,
`PKO.WA` Warsaw), UCITS ETFs included, route as `europe_equity` through Yahoo
then yfinance. Each venue's declared currency is required: EUR for
.DE/.PA/.AS/.MI, CHF for .SW, PLN for .WA; a line quoted in another currency is
refused. This is data coverage; European backtest execution rules are not
implemented.

## Source Overview

Every name here is a registered OHLCV/backtest source in `VALID_SOURCES`.
"Runner-internal" sources are selected by the backtest runner, not authored as a
per-source skill.

| Source | Markets | Auth (env key) | Network | Skill |
|--------|---------|----------------|---------|-------|
| tushare | A-shares, funds, futures, macro | Yes (`TUSHARE_TOKEN`) | China network | tushare |
| akshare | A-shares, US, HK, futures, macro, forex | No | Unrestricted | akshare |
| yfinance | US, HK, Japan (.T), Canada (TSX/TSXV), Europe (.DE/.PA/.AS/.MI/.SW/.WA) stocks, ETFs | No | Needs Yahoo access | yfinance |
| okx | Crypto (OKX exchange) | No | Needs okx.com access | okx-market |
| nobitex | Crypto, IRT/Toman-quoted pairs (BTC-IRT, USDT-IRT — Iran market premium) | No | Needs apiv2.nobitex.ir access | data-routing (explicit `*IRT` routing only) |
| wallex | Crypto, TMN/Toman-quoted pairs (USDT-TMN, BTC-TMN — Iran market premium) | No | Needs api.wallex.ir access | data-routing (explicit `*TMN` routing only; truly serves 1m/1h/1d) |
| ccxt | Crypto (100+ exchanges) | No | Needs exchange access | ccxt |
| baostock | A-shares (free daily/min) | No | China network | data-routing |
| tencent | A-shares, HK, US (never-banned) | No | Unrestricted | data-routing |
| mootdx | A-shares (retired 2026-10: TDX servers stopped answering the client protocol; explicit `source="mootdx"` only) | No | China network | data-routing |
| futu | A/HK/US via OpenD gateway | Yes (OpenD running) | Local gateway | data-routing (runner-internal) |
| mt5 | Forex & metals (your broker's MT5 feed) | Yes (running, logged-in MT5 terminal; optional `~/.vibe-trading/mt5.json`) | Local terminal (Windows) | data-routing (runner-internal) |
| local | User CSV/parquet on disk | No | Offline | data-routing (runner-internal) |
| eastmoney | A-shares, HK, US equities | No (IP-throttled) | Unrestricted | data-routing |
| sina | US equities (daily OHLCV) | No (IP-throttled) | Unrestricted | data-routing |
| stooq | US equities (daily OHLCV) | No | Unrestricted | data-routing |
| yahoo | US, HK, Canada (TSX/TSXV) equities | No (IP-throttled) | Needs Yahoo access | data-routing |
| finnhub | US equities | Yes (`FINNHUB_API_KEY`) | Unrestricted | data-routing |
| alphavantage | US equities | Yes (`ALPHAVANTAGE_API_KEY`) | Unrestricted | data-routing |
| tiingo | US equities | Yes (`TIINGO_API_KEY`) | Unrestricted | data-routing |
| fmp | US equities | Yes (`FMP_API_KEY`) | Unrestricted | data-routing |
| gildata | A-shares (前复权 dailies), HK equities (raw), CN indices | Token + market quotes enabled in Settings; only when the user requests `source="gildata"`, no fallback | Gildata MCP API | data-routing |

## Capability → Tool Routing

Pick the tool by the data need. "Market" is the universe the tool covers; "Env key"
is required only where listed (no key listed = free / no auth).

| Data need | Tool | Market | Env key |
|-----------|------|--------|---------|
| OHLCV price bars | `get_market_data` | A-share / US / HK / Canada / crypto / futures / forex | per-source (see Source Overview) |
| Fund flow (资金流向) | `get_fund_flow` | A-share, HK, US | — |
| Dragon-tiger (龙虎榜) | `get_dragon_tiger` | A-share | — |
| Northbound flow (北向资金) | `get_northbound_flow` | A-share | — |
| Margin trading (融资融券) | `get_margin_trading` | A-share | — |
| Block trades (大宗交易) | `get_block_trades` | A-share | — |
| Shareholder count (股东户数) | `get_shareholder_count` | A-share | — |
| Lockup expiry (限售解禁) | `get_lockup_expiry` | A-share | — |
| Sector / board taxonomy (板块) | `get_sector_info` | A-share | — |
| Sell-side research reports | `get_research_reports` | A-share | — |
| Stock news | `get_stock_news` | A-share, US, HK | — |
| SEC filings (EDGAR) | `get_sec_filings` | US | — |
| Financial statements | `get_financial_statements` | A-share, US, HK | — |
| Options chain | `get_options_chain` | US | — |
| Stock profile / fundamentals | `get_stock_profile` | US | — |
| Market screen | `screen_market` | A-share | — |
| Symbol search | `search_symbol` | A-share, US, HK, Canada, crypto/index/FX | — |
| Macro / FRED series | `get_macro_series` | Macro (US/global) | `FRED_API_KEY` |
| OTC fund NAV (场外基金净值) | `get_fund_nav` | CN off-exchange funds | `GILDATA_TOKEN` + `fund_nav` opt-in |
| China macro / industry EDB (宏观行业) | `get_cn_macro_series` | CN macro/regional/industry | `GILDATA_TOKEN` + `macro_series` opt-in |
| CN announcements (公告检索) | `get_cn_announcements` | A-share / HK / fund | `GILDATA_TOKEN` + `announcements` opt-in |
| Broker research (券商研报) | `search_broker_reports` | A-share / HK | `GILDATA_TOKEN` + `broker_reports` opt-in |
| iWenCai NL search (问财) | `iwencai_search` | A-share | `VIBE_TRADING_IWENCAI_KEY` |

Notes:
- `get_financial_statements` reads US statements from SEC EDGAR companyfacts
  (ticker -> CIK -> XBRL concepts) and A-share/HK statements from the Eastmoney
  datacenter report API (per-market F10 report names).
- `get_stock_news` routes A-share (SH/SZ/BJ) to an Eastmoney news client and
  US (.US) / HK (.HK) to a Yahoo search client; a failure on one upstream is
  returned as an error envelope, never raised, so a single bad symbol never
  aborts a batch.

## Decision Tree

### Backtest scenario (writing config.json)

Use `source: "auto"` — the runner routes by symbol pattern and falls back across
same-market sources automatically. Only set a concrete source when the user asks.

### Analysis / research scenario

1. Identify the data need, then read the Capability table for the tool + env key.
2. If the need is plain OHLCV, call `get_market_data` and let source fallback run.
3. Set any required env key before calling a key-gated tool; if it is missing,
   report the missing key rather than failing silently.

### Source priority (for OHLCV by market)

The current compatible chains come from `backtest.loaders.registry.FALLBACK_CHAINS`
and the gateway's `/data/capabilities` endpoint. Use `source="auto"` unless the
user requests an explicit source. Local network health and configured source
order determine attempts; a fixed skill-side priority list would drift from
main and could retry a source the gateway has already cooled down.

## Symbol Format Reference

| Market | Format | Examples |
|--------|--------|----------|
| A-shares | `NNNNNN.SZ/SH/BJ` | 000001.SZ, 600000.SH, 430139.BJ |
| US stocks | `TICKER.US` | AAPL.US, MSFT.US |
| HK stocks | `NNNNN.HK` | 00700.HK, 09988.HK |
| Canada TSX / TSXV | `TICKER.TO` / `TICKER.V` | TD.TO, BBD-B.TO, PNG.V |
| Crypto | `SYMBOL-USDT` | BTC-USDT, ETH-USDT |
| Futures | `XXNNNN.EXCHANGE` | CU2406.SHFE |
| Forex | `XXX/YYY` | USD/CNY, EUR/USD |

## Ban-Risk & Fallback Notes

- Use the gateway's compatible routes and observed network health; no source is guaranteed immune to blocking.
- **Eastmoney rate-limits by IP and must be throttled.** Every Eastmoney-backed
  tool/loader routes through the shared per-host throttle; do not hammer it. On a
  throttle/timeout, let the gateway apply its compatible fallback/cooldown policy.
- **Sina / Yahoo also throttle by IP** — same per-host wrapper, same fallback rule.
- **Key-gated sources need their env key** (`FINNHUB_API_KEY`,
  `ALPHAVANTAGE_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`,
  `VIBE_TRADING_IWENCAI_KEY`, `TUSHARE_TOKEN`). If the key is absent the tool/loader
  is unavailable — route to a free same-market source instead of erroring out.
- A single failing symbol or transient HTTP error is reported inside the envelope;
  it never aborts the surrounding batch.

## Data Verification Discipline

When a number will drive a conclusion (valuation, screening, report), do not trust a
single source. Cross-check it:

- **Verify material figures across ≥2 independent sources** before citing them.
  Prioritize original disclosures (company annual/quarterly reports, exchange filings)
  over third-party aggregators.
- **Flag any deviation >1%** between sources as a ⚠️ caliber mismatch — usually a
  definition difference (GAAP vs Non-GAAP, consolidated vs parent-only, currency,
  TTM vs annual). Do not silently pick one; state both and which you adopt.
- **Use the `financial_rigor` tool's `cross_validate` command** to do this exactly:
  pass `{source: value, ...}` and it returns the median consensus + per-source
  deviation + an `all_consistent` flag at a configurable tolerance (default 2%).
- **Mark unverified numbers** as "single-source" or "estimate" — never present an
  uncorroborated figure as established fact.

This discipline is what separates analysis from aggregation.

### Gildata research and OTC funds

When the user has enabled the corresponding feature and configured a Gildata token, use its tool for China
macro observations, announcements and broker reports. Inspect the returned
`api_names`; routing is vendor-selected. Rows retain vendor order and explicitly
report truncation. Narrow the topic or date window to retrieve omitted records.
When declaring a macro observation, reference its actual field, for example
`call_id::rows[0].value`, and preserve the returned unit and date. Indicator codes
are identifiers, not measurements.

`get_fund_nav` reads OTC fund NAV history with an exact vendor-code match.
Exchange-listed ETF/LOF prices still use the OHLCV loaders. Unit, accumulated and
adjusted NAV are different measures; name the one actually reported. Missing NAV
values remain missing. NAV rows never enter the OHLCV backtest loader.
