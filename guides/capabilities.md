# Data sources and capabilities

## 📡 Data Sources & Smart Fallback

The `get_market_data` tool supports **28 market-data sources**. With `source: "auto"`, it infers the market from the symbol and tries that market’s configured chain. Some sources require credentials, a local terminal or your own files.

| Source | Markets | Auth | Role |
|--------|---------|------|------|
| `tencent` | A-share + HK | none | first public source in the default A-share and HK chains |
| `mootdx` | A-share (explicit-only) | none | retired from the default chain 2026-10: TDX servers stopped answering the client protocol it speaks (#1729) |
| `eastmoney` | A / US / HK | none | OHLCV + deep fundamentals & flow tools (throttled) |
| `baostock` · `akshare` | A (+ US/HK/futures/macro/fx) | none | free fallbacks |
| `tushare` | A / HK equities, mainland indices and listed funds | token | daily bars |
| `gildata` | A / HK / CN index | `GILDATA_TOKEN` + `market_quotes` | Market quotes (explicit Gildata requests only) · `source="gildata"` |
| `yahoo` | US / HK / Canada / UK | none | direct chart/quotes/options; TSX `.TO` / TSXV `.V`; LSE `.L` with declared-currency normalization |
| `sina` · `stooq` | US | none | K-line to 1984 · EOD CSV |
| `yfinance` | US / HK / Canada / UK | none | wrapper; TSX `.TO` / TSXV `.V`; LSE `.L` under the same GBP/GBp contract |
| `longbridge` | US / HK | App Key + App Secret + Access Token | optional historical OHLCV source; install the optional SDK |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | US | key | optional providers |
| `nobitex` · `wallex` | crypto (Iranian Toman pairs) | none | public UDF endpoints; **explicit-only** — the only Toman-quoted sources, so they never join the crypto chain where a USD-quoted series could stand in for one |
| `okx` · `ccxt` · `binance` | crypto | none | OKX + 100+ exchanges + Binance historical / USD-M perps |
| `futu` | HK / A | OpenD | optional local FutuOpenD |
| `mt5` | forex / metals | MT5 terminal | MetaTrader 5 (Exness-style) forex / metal bars, 1m–1D |
| `tickerall` | forex / metals | key + account (read-only) | same broker MT5 feed, **hosted** — no local terminal, any OS (explicit-only, never in auto fallback) |
| `pykrx` | Korea (KRX: KOSPI/KOSDAQ) | none | daily KOSPI / KOSDAQ bars for `.KS` / `.KQ` (optional `krx` extra) |
| `india_broker` | India (NSE/BSE) | broker login | read-only Zerodha / Shoonya / Dhan bars for `.NS` / `.BO` (fallback-chain tail) |
| `b3_cotahist` | Brazil (B3) | none | official daily B3 cash/odd-lot bars (raw, BRL) from the local store populated by `python -m src.br_data sync`; offline fallback for `.SA` |
| `local` | any | none | your own CSV / Parquet / DuckDB via `local:` prefix |

Local sources can read bar dates from a `DatetimeIndex`, with or without a
configured `date_format`; an explicitly mapped date column takes precedence.

**Fallback chains (by IP-ban risk):**

- **A-share** → `tencent` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **US** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `longbridge` · `akshare` · `local`
- **HK** → `tencent` · `eastmoney` · `yahoo` · `futu` · `akshare` · `yfinance` · `tushare` · `longbridge` · `local`
- **India (NSE/BSE)** → `yahoo` · `yfinance` · `india_broker` · `local`
- **Brazil (B3 `.SA`)** → `yahoo` · `yfinance` · `b3_cotahist` · `local`
- **Korea (KOSPI/KOSDAQ)** → `pykrx` · `yahoo` · `yfinance` · `local`
- **Indices** → `yahoo` · `yfinance` · `local`
- **UK (LSE)** → `yahoo` · `yfinance` · `local` *(declared GBP/GBp quotes only)*
- **Crypto** → `okx` · `binance` · `ccxt` · `yfinance` · `local`
- **Forex / metals** → `mt5` · `akshare` · `yfinance` · `local`
- **Canada / Vietnam / Argentina** → `yahoo` · `yfinance` · `local`
- **China futures** → `akshare` · `local` &nbsp;·&nbsp; **funds** → `tushare` · `akshare` · `local` &nbsp;·&nbsp; **macro** → `akshare` · `tushare` · `local`

### A-share installation and availability

The base install includes Tencent's loader (standard-library HTTP) and AKShare.
BaoStock is an optional, token-free TCP source for daily A-share bars; install
the `ashare` extra to make it available:

```bash
pip install --upgrade "vibe-trading-ai[ashare]"
# For a uv tool installation that previously used only the base package:
uv tool install --force --python 3.12 "vibe-trading-ai[ashare]"
```

For uv tool users, `--force` rebuilds the existing tool environment. Keep any
extras you already use when adding `ashare` (for example,
`"vibe-trading-ai[ashare,deepseek]"`) and repeat any existing `--with` arguments
in that command.

`mootdx` is not included in the base install or the `ashare` extra. Its legacy
loader is explicit-only and retired from automatic fallback; installing its
SDK does not guarantee compatibility with the TDX server protocol. A missing
`mootdx` import is expected with the base install.

Automatic fallback skips unavailable loaders. If an Eastmoney-backed request is
throttled, select `source: "auto"` or an available alternative such as
`tencent` or `baostock`. The startup preflight covers selected services, not
every optional loader; an SDK reported as installed does not establish that
its remote data service is reachable.

### Using Longbridge explicitly

Longbridge is an optional US/HK historical OHLCV loader. Install its SDK with:

```bash
pip install "vibe-trading-ai[longbridge]"
```

Configure the three credentials in `.env`:

```dotenv
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
```

For a backtest, set `source` in `config.json`:

```json
{
  "codes": ["QQQ.US"],
  "start_date": "2025-01-01",
  "end_date": "2025-01-10",
  "interval": "1D",
  "source": "longbridge"
}
```

In an Agent conversation, ask explicitly: **"Use Longbridge to fetch QQQ.US historical data."** The explicit source request is separate from `source: "auto"`; `auto` keeps the normal per-market fallback chain.

Beyond OHLCV, **29 read-only data tools** reach into fundamentals & flow — fund flow, dragon-tiger, northbound, southbound, margin, block trades, shareholder count, lockup, sector, research reports, broker research search, news, SEC filings, Chinese-market announcements, financial statements, PIT fundamentals, options chains, crypto order-book depth, stock profile, market screening, symbol search, macro, China macro (EDB), iwencai, institutional holdings (13F), ETF look-through, off-exchange fund NAV, prediction markets, and research papers — all exposed over MCP. An explicit `local:` symbol never silently falls back to a network source.

<details>
<summary>RSSHub event dates and ticker formatting</summary>

RSSHub daily event enrichment uses calendar-date keys: timezone-aware `as_of` values and daily bar labels retain their displayed date, matching the provider’s knowable-date policy. This does not convert intraday publication instants between markets.

RSSHub feed `code_style` transformations separate the final venue suffix from the ticker, preserving share-class dots: `BRK.B.US` becomes `BRK.B` for `bare` routes and `USBRK.B` for `exchange_prefix`; `raw` remains unchanged.

</details>

### Data partner · [Gildata](https://www.gildata.com/products/datamap)

Each Gildata feature requires a token and a separate opt-in under Settings → Data sources. This includes fund NAVs, macro indicators, announcements, broker reports, combined queries, screening, symbol search, portfolio diagnosis and explicitly requested quotes. All nine features are off by default. A saved token alone enables none of them, including after an upgrade. Even with market quotes enabled, Gildata is used only when explicitly selected. Free sources never fall back to Gildata.

---

## 🔩 Detailed Capabilities

Detailed inventories are folded below to keep the main README scannable. Open them when you want to inspect the available building blocks.

<details>
<summary><b>Finance Skill Library</b> <sub>89 skills across 9 categories</sub></summary>

- 📊 89 specialized finance skills organized into 9 categories
- 🌐 Complete coverage from traditional markets to crypto & DeFi
- 🔬 Comprehensive capabilities spanning data sourcing to quantitative research

| Category | Skills | Examples |
|----------|--------|----------|
| Data Source | 9 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar` |
| Strategy | 19 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 23 | `factor-research`, `correlation-regime`, `macro-analysis`, `global-macro`, `valuation-model`, `investor-lenses`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 8 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `trade-journal` |
| Research | 3 | `alpha-zoo`, `strategy-dev-manager`, `strategy-discovery` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

The read-only `report_audit` tool preserves signed financial values in Markdown
tables and `label: value` lines, so losses are checked as losses rather than profits.
Backtest reports ground their figures in the engine's own output for that call.
For list results, equivalent references such as `data.positions[0].contribution_pct`
and `data.positions.0.contribution_pct` select the same element; an explicit index
cannot borrow another element's value. Correction hints suggest exact references
without treating the suggestion itself as evidence.

</details>

<details>
<summary><b>Custom Data Source</b> <sub>register your own historical OHLCV loader</sub></summary>

Need a market or vendor we don't ship a loader for? Add your own historical-bar
loader and select it with `source="<name>"`. The steps edit package source, so
run from a clone (`pip install -e .`).

1. **Write the loader** — create `agent/backtest/loaders/<name>_loader.py` with a
   class that satisfies `DataLoaderProtocol` (duck-typed, no base class needed)
   and is tagged with `@register`:

   ```python
   import pandas as pd
   from backtest.loaders.registry import register

   @register
   class DataLoader:
       name = "mysource"            # the value you pass as source=
       markets = {"us_equity"}      # a_share/us_equity/hk_equity/crypto/futures/fund/macro/forex
       requires_auth = False

       def is_available(self) -> bool:
           return True              # token present? network reachable?

       def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
           # return {symbol: DataFrame indexed by trade_date,
           #         columns: open, high, low, close, volume}
           ...
   ```

2. **Register the module** so `@register` fires — add
   `"backtest.loaders.<name>_loader"` to `_loader_modules` in
   `agent/backtest/loaders/registry.py`.
3. **Allow the name** through config validation — add `"mysource"` to
   `_VALID_SOURCES` in `agent/backtest/runner.py`.
4. *(Optional)* slot it into a market's `FALLBACK_CHAINS` in `registry.py` so
   `source="auto"` can reach it.
5. **Use it** — `source="mysource"` in a backtest config, or via the CLI / agent.

> **Real-time ticks / order-book depth are out of scope for loaders** — the
> loader layer is point-in-time historical bars only. Live market data flows
> through the broker connectors instead: `okx` / `binance` / `ccxt` for crypto,
> `futu` / `tiger` for equities.

</details>

<details>
<summary><b>Broker Connectors</b> <sub>19 brokers — read + paper, bounded-live where supported</sub></summary>

Connector-first profiles. Most do read + paper-account order placement — IBKR is read-only, Robinhood is live-only (no paper account), Scalable Capital is read-only (no paper account exists at all), mStock (India) is read-only live over its Type B REST API (no paper account), and Trading 212 and Toss Securities refuse order placement entirely, paper included; live order placement is bounded by a user-defined mandate (symbol allowlist, order-size / exposure caps, daily trade cap, instant kill switch) and never holds funds — the broker executes. Order-placing tools stay off MCP (agent + CLI only). Research / backtest paths are structurally barred from any live endpoint.

| Broker | Markets | Capabilities |
|--------|---------|--------------|
| **IBKR** | global | local TWS / Gateway, read-only |
| **Robinhood** | US | Agentic MCP (desktop OAuth) — equity read + bounded live; options order placement is not supported |
| **Scalable Capital** | DE / EU | Agentic MCP (desktop OAuth) — fully read-only; no paper account exists |
| **mStock** | India (NSE/BSE) | Separate holdings/net-position reads; no portfolio aggregation or orders |
| **Tiger** | US / HK / A | read + paper + bounded live |
| **Alpaca** | US | read + paper + bounded live (+ TAP credential-isolation mode) |
| **OKX** · **Binance** | crypto | read + paper + bounded live |
| **Futu** | HK / US / A | read + paper + bounded live |
| **eToro** | global | read + paper + bounded live (Public API; demo keys reach only `/demo` paths, plus copy-trading workflows) |
| **MetaTrader 5** | forex / CFD | read + paper + bounded live (Exness-style; demo ⇔ paper identity guard) |
| **KIS** (한국투자증권) | Korea (KOSPI/KOSDAQ) | read + genuine paper (모의투자, a real broker-side sandbox on a separate host) — live order placement not yet wired for this market |
| **Longbridge** · **Dhan** · **Shoonya** · **Zerodha** · **Upbit** | US / HK · India (NSE/BSE) · Korea (crypto) | read + paper only — no runtime paper/live discriminator, so live order placement is hard-refused |
| **Trading 212** · **Toss Securities** | UK / EU · Korea/US | fully read-only — `place_order` / `cancel_order` hard-refuse even paper (no verified sandbox) |

Paper-vs-live is a **structural per-broker runtime guard** (account-id format, host separation, demo flag, or trade environment), never a config flag the agent can flip. A broker exposing no such discriminator is capped at paper + read-only.

</details>

<details>
<summary><b>Preset Trading Teams</b> <sub>30 swarm presets</sub></summary>

- 🏢 30 ready-to-use agent teams
- ⚡ Pre-configured finance workflows
- 🎯 Investment, trading & risk management presets

| Preset | Workflow |
|--------|----------|
| `investment_committee` | Bull/bear debate → risk review → PM final call |
| `global_equities_desk` | A-share + HK/US + crypto researcher → global strategist |
| `crypto_trading_desk` | Funding/basis + liquidation + flow → risk manager |
| `earnings_research_desk` | Fundamental + revision + options → earnings strategist |
| `macro_rates_fx_desk` | Rates + FX + commodity → macro PM |
| `quant_strategy_desk` | Screening + factor research → backtest → risk audit |
| `technical_analysis_panel` | Classic TA + Ichimoku + harmonic + Elliott + SMC → consensus |
| `risk_committee` | Drawdown + tail risk + regime review → sign-off |
| `global_allocation_committee` | A-shares + crypto + HK/US → cross-market allocation |

<sub>Plus 20+ additional specialist presets — run vibe-trading --swarm-presets to explore all.
Bring your own: drop preset YAMLs into <code>~/.vibe-trading/swarm/presets/</code> — they are listed
alongside the bundled roster (same-name files override it, like user skills) and survive upgrades.

</sub>

</details>

<details>
<summary><b>Alpha Zoo</b> <sub>478 pre-built quant alphas across 5 families</sub></summary>

- 🧬 478 cross-sectional alphas, lookahead-banned at the operator layer
- 📈 IC + IR + alive/reversed/dead categorisation in one CLI command
- 🔬 AST purity gate + 300-row lookahead sentinel test + `pytest-socket` network kill-switch
- 📦 Apache-2 attribution for Qlib; per-zoo `LICENSE.md` declaring formulas as mathematical content
- 🤝 Developer Certificate of Origin (DCO) sign-off workflow for community PRs

| Zoo | Count | Source | License |
|-----|-------|--------|---------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158` (Apache-2.0, commit-pinned) | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991 | Formulas are mathematical content |
| **gtja191** | 191 | Guotai Junan (2014), "191 Short-period Trading Alpha Factors" | Formulas are mathematical content |
| **academic** | 12 | Fama-French 5 + Carhart momentum + Jegadeesh reversal + George-Hwang 52-week-high + Amihud illiquidity + Harvey-Siddique skew + Frazzini-Pedersen betting-against-beta + correlation-rewiring stability (price-based proxies) | Public academic literature |
| **fundamental** | 20 | PIT-safe SEC company facts (14, filed-date anchored: earnings yield, book-to-market, ROE, ROA, gross profitability, growth, accruals, leverage, cash-flow yields …) + A-share P/B, P/S TTM and dividend yield (3) + their Shenwan industry-neutral variants (3) | Public financial data |

Run `vibe-trading alpha list` to browse, `vibe-trading alpha show <id>` for formulas + source, `vibe-trading alpha bench --zoo X --universe Y --period Z` to score a whole zoo, and `vibe-trading alpha compare --all` to rank zoos side by side.

</details>

<details>
<summary><b>Backtest Engines</b> <sub>12 engines + options portfolio, cross-market composite</sub></summary>

| Engine | Market | Notes |
|--------|--------|-------|
| **ChinaA** | A-share | T+1, price limits, pre-ST filter |
| **GlobalEquity** | US / HK / Canada / UK | same-session trading; market-specific lots, ticks, settlement currencies, and costs |
| **IndiaEquity** | India (NSE/BSE) | T+1, circuit bands, config-driven STT / stamp / SEBI / GST cost stack |
| **KoreaEquity** | Korea (KRX: KOSPI/KOSDAQ) | long-only, ±30% band judged at execution time on the unified tick grid, 2026 0.20% transaction tax |
| **VietnamEquity** | Vietnam (HOSE) | long-only, T+2 settlement hold, ±7% band on the 10/50/100-VND tick grid, 100-share lots, 0.1% sell-side tax |
| **BrazilEquity** | Brazil (B3) | BRL, B3 trading + settlement fees, configurable broker fee, 1- or 100-share lots, R$0.01 tick, shorting allowed |
| **ArgentinaEquity** | Argentina (BYMA) | ARS, long-only; T+2 → T+1 (2024-05-27), settlement approximated from observed sessions; same-session sale netting; declared CEDEAR ratios and credit dates; explicit tick table/panel (`ar_tick_table`) or per-instrument tick |
| **Crypto** | crypto spot / USD-M perps | funding settlements, execution/mark split |
| **ChinaFutures** · **GlobalFutures** | futures | margin, contract multipliers |
| **Forex** | FX / metals | via the `mt5` loader (local terminal) or the hosted `tickerall` loader (no terminal, any OS) |
| **Composite** | cross-market | one shared capital pool across markets (`source="auto"`) |
| **options_portfolio** | options | multi-leg, Greeks, payoff/scenario |

Benchmark selection honors `.SH`, `.SZ`, and `.BJ` A-share suffixes, plus Yahoo's `.SS` spelling for Shanghai, independently of the chosen loader, including offline local sources.

The engine's trading rules come from each code's market, so a backtest code must name one: a suffix listed above (`.SH`, `.US`, `.HK`, `.L`, `.TO`, `.NS`, `.KS`, `.SA`, `.BA`, `.VN`, …), a bare US ticker, a crypto or FX pair, an index (`^GSPC`), a futures contract, or a mainland code written as six bare digits or with `.SS`. A code no market rule recognises, `local:` datasets included, is refused before any data is fetched instead of running on another market's rules.

Bars: 1m / 5m / 15m / 30m / 1H / 4H / 1D, plus weekly / monthly (1W / 1M, built from daily bars). 15 metrics + benchmark comparison, **5 portfolio optimizers** (equal-volatility / risk-parity / mean-variance / max-diversification / turnover-aware), and 3 validation tools (Monte Carlo / Bootstrap / Walk-Forward).

The turnover-aware optimizer validates per-name and group caps for single-asset
allocations too. It preserves feasible supplied allocations (including cash),
and raises an error when the singleton allocation exceeds a cap.

When the opt-in market-data cache is enabled, local-source cache entries are
scoped to the configured file, query, and column mapping. Changing a symbol's
source declaration does not reuse bars from its previous source. The settled-data
cache policy for an unchanged declaration remains the same.
Unusable cached metadata is treated as a cache miss: the declared local source
is read again, and the replacement entry can serve subsequent cache hits.
The turnover-aware optimizer measures allocation changes in signed position
space: reversing a 50% long to a 50% short contributes 0.5 turnover, including
both the close and the reopen. Its penalty and recorded allocation turnover
include these reversals; execution-derived turnover remains a separate metric.
Local data date ranges include the entire UTC end day, including subsecond
timestamps; bars at the following midnight are excluded before aggregation.

The shared backtest market classifier recognizes `BTC/USD`, `ETH/USD`,
`BNB/USD`, `SOL/USD`, `ADA/USD`, and `DOGE/USD` as crypto. Fiat pairs such as
`GBP/USD`, `EUR/USD`, and `USD/JPY` retain their forex classification.

</details>

<details>
<summary><b>Quant Library</b> <sub>310 tested functions across 25 modules, callable from every transport</sub></summary>

`src/quantlib` holds one tested implementation of each piece of finance math the
agent needs. Skills **import** these rather than carrying formulas inside
markdown code blocks — if you find a pricing formula living in a `SKILL.md`,
that is a bug, not a pattern.

| Module | What it covers |
|--------|----------------|
| `options` | Black-Scholes price + greeks, implied-volatility inversion |
| `fixedincome` | Bond math, Nelson-Siegel / Svensson curve fitting; schedules, accrual, key-rate tenors and yield inversion reject non-finite inputs by name. |
| `credit` | Altman Z-score, Merton / KMV distance-to-default; CDS premium dates retain their configured frequency, with a final stub when maturity falls between coupons. |
| `timeseries` | Stationarity, cointegration, GARCH, bootstrap; OU fits use adjacent observed lag pairs; missing observations never become artificial one-step transitions. |
| `risk` · `var_backtest` | VaR / CVaR / EVT and their backtests |
| `attribution` | Brinson-Fachler decomposition |
| `performance` · `fundmath` | TWR / MWR / Modified Dietz; XIRR / MOIC / DPI / TVPI |
| `factormodel` · `eventstudy` | Factor regressions, event studies; portfolio style exposure reports incomplete factor rows as unmatched weight. |
| `neutralization` | Optional per-observation OLS/WLS factor residualization, audited control quality selection, and cross-sectional PCA at any panel frequency. [Workflow and examples](../agent/src/skills/factor-research/references/neutralization.md). |
| `combination` | Optional walk-forward IC/ICIR-weighted composite of several factor panels, with per-factor and composite diagnostics; a caller-supplied weight table handles any other method. [Workflow and checklist](../agent/src/skills/factor-research/references/combination.md). |
| `multipletesting` · `crossvalidation` | Deflated significance, purged CV; purged walk-forward splits omit folds with no training observations left after purging; Sharpe significance summaries reject non-finite inputs by name. |
| `impact` | Market-impact models |
| `volatility` | Heston (1993) stochastic-volatility pricing; Heston pricing requires finite inputs and a positive integration limit; invalid inputs return a domain error. |
| `portfolio` | Hierarchical Risk Parity allocation |
| `copula` | Gaussian and Archimedean copulas |
| `microstructure` | VPIN, Roll spread, Amihud illiquidity, Kyle's lambda |

The read-only `quantlib_call` tool reaches all of it through one contract, so the
finance math works on the CLI, the Web UI, the REST API and MCP — including
deployments where `bash` is gated off. It is
structurally not a shell — module allowlist, `__all__`-only dispatch, `export_*`
refused. Econometrics needs the `stats` extra
(`pip install "vibe-trading-ai[stats]"`); those functions lazy-import and tell
you which one is missing.

</details>

<details>
<summary><b>Valuation & Institutional Research</b> <sub>DCF, comps, three-statement, and six research commands</sub></summary>

A valuation engine that refuses to invent its own inputs. The one rule in
`contracts.py`: **a missing input makes a model NOT RUNNABLE and is never
silently defaulted** — every default in a valuation model is an opinion wearing
a constant's clothes.

| Model | Behaviour worth knowing |
|-------|-------------------------|
| `run_dcf` | FCFF bridge, WACC build, mid-year discounting, net-debt bridge, WACC×g sensitivity grid. Dual terminal value: each method is cross-checked against the other's implied multiple and implied g |
| `run_comps` | EV bridge, LTM + calendar-year calendarisation, multiple matrix. A peer with a non-positive denominator is **excluded and reported**, never averaged in as a negative multiple |
| `threestatement` | Linked projection with a hard balance assertion, an explicit revolver plug, and an iterated interest↔debt circularity that must converge or raise |

Artifacts are input-hashed and versioned, with xlsx / pptx export.

Six slash commands drive the workflows — `/comps` `/dcf` `/attrib` `/memo`
`/earnings` `/screen` — each carrying a step skeleton and an
arithmetic-consistent worked example (the Brinson decomposition sums exactly to
active return; the earnings bridge sums exactly to the EPS delta). The
`investor-lenses` skill stacks named-investor reasoning frameworks on top as
analysis overlays: each lens is an operating procedure — priority signals,
disqualifying conditions, typical misuse — not a biography, and names no tool.

Beyond bars, `src/entities` ingests irregular dated cash flows (NAVs, capital
calls, coupons) and `cashflow_performance` reports XIRR / MOIC / DPI / TVPI /
TWR / Modified Dietz / MWR over them. This path is deliberately parallel to the
bar engines so a `nav` column can never reach one and get priced as a close.
Flows use the holder's sign convention: a transfer into the portfolio is
negative, and a transfer out is positive.

</details>

<details>
<summary><b>Governance & Audit Trail</b> <sub>answer "what methodology produced that number?"</sub></summary>

Every run writes a **manifest** hashing the prompt, the skill contents, the tool
registry and the package versions, so a number produced last month can be traced
to the exact methodology that produced it.

The **audit ledger** chains each record to its predecessor's hash and fsyncs, so
editing or deleting a record is detectable — and an edit that recomputes its own
hash is still caught one record later via `prev_hash_mismatch`. Timestamps are
always caller-supplied; no module here calls `datetime.now()`.

Trace redaction is **sink-aware**: tool-call arguments and the live audit ledger
use a fail-closed sink where `content` stays redacted, while the tool-result
sink releases it and pattern-scrubs its string leaves. `env` is never released
in either.

</details>

## 📁 Project Structure

<details>
<summary><b>Click to expand</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli/                        # CLI package — interactive TUI + subcommands
│   ├── api_server.py               # FastAPI server — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCP server — 83 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (89 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 122 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, alpha browser + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 478 alphas across 5 families
│   │   │   ├── base.py             #   19 operators (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   AST-only metadata load + lazy compute + sanity gates
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead categorisation
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (12) + fundamental (20)
│   │   │
│   │   ├── api/                    # FastAPI route modules
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, SSE stream
│   │   │
│   │   ├── skills/                 # 89 finance skills in 9 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   30 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   11 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   28 sources: tushare, okx, nobitex, wallex, binance, yfinance, akshare, baostock, tencent, mootdx, ccxt, futu, pykrx, local, eastmoney, sina, stooq, yahoo, finnhub, alphavantage, tiingo, fmp, longbridge, mt5, india_broker, tickerall, gildata, b3_cotahist
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + auto-fallback chains
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, AlphaZoo, RunDetail, Compare, Correlation, Settings
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustand state management
│
├── Dockerfile                      # Multi-stage build
├── docker-compose.yml              # One-command deploy
├── pyproject.toml                  # Package config + CLI entrypoint
├── tools/                          # Repo-level CI helpers
│   └── ci_grep_gates.sh            # rejects yaml.load / trademark / per-stock-data leaks
└── LICENSE                         # MIT
```

</details>
