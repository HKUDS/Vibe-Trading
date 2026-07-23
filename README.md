<p align="center">
  <b>English</b> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading: Your Personal Trading Agent</h1>

<p align="center">
  <b>One Command to Empower Your Agent with Comprehensive Trading Capabilities</b>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25527" alt="HKUDS%2FVibe-Trading | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/6TdQnT5xcF"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://vibetrading.wiki/">Website</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">Docs</a> &nbsp;&middot;&nbsp;
  <a href="#-news">News</a> &nbsp;&middot;&nbsp;
  <a href="#-key-features">Features</a> &nbsp;&middot;&nbsp;
  <a href="#-shadow-account">Shadow Account</a> &nbsp;&middot;&nbsp;
  <a href="#-demo">Demo</a> &nbsp;&middot;&nbsp;
  <a href="#-quick-start">Quick Start</a> &nbsp;&middot;&nbsp;
  <a href="#-examples">Examples</a> &nbsp;&middot;&nbsp;
  <a href="#-api-server">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-roadmap">Roadmap</a> &nbsp;&middot;&nbsp;
  <a href="#-contributing">Contributing</a>
</p>

<p align="center">
  <a href="#-quick-start"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 News

> ⚠️ **Security warning:** The X account `VibeTrading_HKU`, Virtuals project `101845`, and token contract `0x640BDBF77b6447E8b7DB7894cED84BD1c40571f4` are not official Vibe-Trading assets. We have never launched or endorsed any token or memecoin. Do not buy, connect a wallet, or sign anything. [Details](SECURITY.md#official-channels--impersonation).

- **2026-07-23** 🔧 **Reliability sweep + strict alpha-bench surfaced + opt-in memory lifecycle**: A 22-PR contributor batch. A broad **reliability sweep** fixes timeframe handling end to end — yfinance `1M`→monthly (not minute), CCXT `1W`/`1M`, akshare/india-broker rejecting unsupported intervals instead of silent daily, and the Tiger/Alpaca/OKX/Shoonya/Longbridge connectors keeping `1H`/`4H` as hour bars — plus trade-journal Excel-date normalization (eastmoney float `YYYYMMDD`, Futu/Tonghuashun serial dates), finite-JSON `report_audit`, blank `holding_days` validation, and Feishu/CLI markdown table edges ([#778](https://github.com/HKUDS/Vibe-Trading/pull/778)–[#794](https://github.com/HKUDS/Vibe-Trading/pull/794), thanks @santhreal). **MT5** `trading_history` now coerces numpy scalars so JSON serialization no longer dies on `int64` ([#776](https://github.com/HKUDS/Vibe-Trading/pull/776), closes [#774](https://github.com/HKUDS/Vibe-Trading/issues/774), thanks @shadowinlife), and **PIT fundamentals** dedup restated rows and stop the snapshot regressing to an older fiscal period on a late restatement ([#772](https://github.com/HKUDS/Vibe-Trading/pull/772), closes [#771](https://github.com/HKUDS/Vibe-Trading/issues/771), thanks @klmtseng). New: **`alpha bench --strict`** finally wires the strict same-universe random-control + OOS gate that shipped unreachable since 0.1.9 ([#796](https://github.com/HKUDS/Vibe-Trading/pull/796), closes [#773](https://github.com/HKUDS/Vibe-Trading/issues/773), thanks @he-yufeng), an opt-in **memory lifecycle** (quality scoring, Ebbinghaus decay, archive-only GC — all off by default) ([#733](https://github.com/HKUDS/Vibe-Trading/pull/733), closes [#732](https://github.com/HKUDS/Vibe-Trading/issues/732), thanks @shadowinlife), and backtest **rebalance-notes** artifacts + turnover metrics ([#795](https://github.com/HKUDS/Vibe-Trading/pull/795), thanks @he-yufeng).
- **2026-07-22** 🚀 **v0.1.12 released** ([Release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.12), `pip install -U vibe-trading-ai`): The **correlation regime timeline** adds a `GET /correlation/regime` endpoint + an opt-in Correlation-tab strip — edge density run through a causal hysteresis state machine that marks FUSED market episodes, descriptive risk context rather than a signal ([#756](https://github.com/HKUDS/Vibe-Trading/pull/756), closes [#719](https://github.com/HKUDS/Vibe-Trading/issues/719), thanks @ebujinovch). Provider endpoint resolution now falls back to each provider's canonical base URL and gracefully handles non-SSE endpoints, fixing the native **zai** provider on glm-5.1 ([#758](https://github.com/HKUDS/Vibe-Trading/issues/758)). Plus a strict-JSON / finite-number **reliability sweep** across metrics, factors, pattern, session, and journal ([#761](https://github.com/HKUDS/Vibe-Trading/pull/761)–[#770](https://github.com/HKUDS/Vibe-Trading/pull/770), thanks @santhreal) and a Binance maintenance-bracket decouple that keeps `-PERP` backtests zero-credential ([#757](https://github.com/HKUDS/Vibe-Trading/pull/757), thanks @honginp). Rolls up ~90 fixes since 0.1.11.
- **2026-07-21** 🔧 **Data-loader completeness + a reliability fix sweep**: Partial market-data results now complete the missing symbols through the fallback chain and fail closed instead of silently shrinking the backtest universe ([#689](https://github.com/HKUDS/Vibe-Trading/pull/689), closes [#681](https://github.com/HKUDS/Vibe-Trading/issues/681), thanks @xkam7ar), and OKX bars use the `history-candles` endpoint with rate-limit retry for deep backfills ([#644](https://github.com/HKUDS/Vibe-Trading/pull/644), thanks @tyj147454413-cmd). Plus a fix sweep: the MCP network guard accepts IPv6 / case-variant hosts ([#750](https://github.com/HKUDS/Vibe-Trading/pull/750), thanks @Robin1987China), trade-journal parsers skip blank/NaN symbol rows ([#749](https://github.com/HKUDS/Vibe-Trading/pull/749), thanks @Robin1987China), the Shadow Account skips the mined entry-hour gate on daily bars ([#748](https://github.com/HKUDS/Vibe-Trading/pull/748), thanks @Robin1987China), and MiniMax regional API endpoints are selectable ([#731](https://github.com/HKUDS/Vibe-Trading/pull/731), thanks @octo-patch).

<details>
<summary>Earlier news</summary>

- **2026-07-20** 🔀 **Providers, MetaTrader 5, and a reliability sweep**: Native **Anthropic Messages API** (optional `[anthropic]` extra, [#695](https://github.com/HKUDS/Vibe-Trading/pull/695), thanks @jelech), **SiliconFlow** ([#565](https://github.com/HKUDS/Vibe-Trading/pull/565), thanks @UNHNQ), and **iFlytek Spark** ([#537](https://github.com/HKUDS/Vibe-Trading/pull/537), thanks @FenjuFu) join the provider roster, and a **MetaTrader 5 (Exness)** broker connector + `mt5` forex/metal data source lands (broker connectors → **12**, [#481](https://github.com/HKUDS/Vibe-Trading/pull/481), thanks @StaniellG). Plus a provider-agnostic **`llm-vision` OCR** engine ([#548](https://github.com/HKUDS/Vibe-Trading/pull/548), thanks @shadowinlife), an **80× signal-alignment vectorization** ([#698](https://github.com/HKUDS/Vibe-Trading/pull/698), thanks @shadowinlife), historical **Binance USD-M funding/bracket** data ([#716](https://github.com/HKUDS/Vibe-Trading/pull/716), thanks @honginp), a swarm MCP-discovery cache ([#704](https://github.com/HKUDS/Vibe-Trading/pull/704)), and a reliability consolidation closing **13** SSE/session/CLI/swarm/scheduler issues ([#584](https://github.com/HKUDS/Vibe-Trading/pull/584), thanks @xkam7ar). Correctness: options **partial-close** now honors the requested quantity instead of flattening the lot ([#577](https://github.com/HKUDS/Vibe-Trading/issues/577)), centralized provider credential resolution ([#563](https://github.com/HKUDS/Vibe-Trading/pull/563)), queued-cancel handling ([#641](https://github.com/HKUDS/Vibe-Trading/pull/641)), a frontend streaming-DOM race ([#717](https://github.com/HKUDS/Vibe-Trading/pull/717), thanks @Marnie0415), and the connector CLI renderers ([#726](https://github.com/HKUDS/Vibe-Trading/pull/726), thanks @nareshkps).

- **2026-07-19** 🔧 **Real US/HK stock-news articles + MCP factor-analysis fix + a robustness pass**: The stock-news tool now returns real **Yahoo Finance articles** (title/url/source/published/snippet) for US and HK tickers instead of related-instrument matches, still routed through the frozen IP-throttled client ([#730](https://github.com/HKUDS/Vibe-Trading/pull/730), thanks @yxhuang). The MCP `factor_analysis` tool is realigned to the registered tool's real CSV contract, so calls no longer die on `KeyError` before running ([#715](https://github.com/HKUDS/Vibe-Trading/pull/715), closes [#635](https://github.com/HKUDS/Vibe-Trading/issues/635), thanks @Robin1987China). Plus a robustness pass: the whole **Kimi K-series** (k2/k3/…/`for-coding`) now auto-forces `temperature=1` as the API requires ([#701](https://github.com/HKUDS/Vibe-Trading/pull/701), thanks @sambazhu), and `split_message`, PDF page ranges, and trade-journal date filters all fail fast on degenerate or inverted input instead of hanging or silently returning nothing ([#727](https://github.com/HKUDS/Vibe-Trading/pull/727)–[#729](https://github.com/HKUDS/Vibe-Trading/pull/729), thanks @santhreal).

- **2026-07-18** 🔧 **Binance crypto fallback + parallel-execution and correctness fixes**: A **Binance** loader joins the crypto historical-data fallback chain ([#643](https://github.com/HKUDS/Vibe-Trading/pull/643), thanks @tyj147454413-cmd), and the IBKR connector moves to a thread-local connection pool with snapshot quotes, fixing hangs under parallel agent runs ([#636](https://github.com/HKUDS/Vibe-Trading/pull/636), thanks @MikeCer). Plus a correctness pass: factor analysis rejects non-positive `n_groups`, inverted period ranges and non-positive detection windows fail fast, an unnamed `DatetimeIndex` in the correlation matrix is handled, `equity.csv` nav/value column aliases are accepted, and empty A-share codes are no longer coerced to `000000.SZ` ([#709](https://github.com/HKUDS/Vibe-Trading/pull/709)–[#714](https://github.com/HKUDS/Vibe-Trading/pull/714), thanks @santhreal). A correlation-rewiring stability factor joins the academic zoo ([#705](https://github.com/HKUDS/Vibe-Trading/pull/705), thanks @ebujinovch), the fundamental zoo is whitelisted for factor analysis ([#707](https://github.com/HKUDS/Vibe-Trading/pull/707), thanks @sambazhu), persisted run state is now fsync-durable ([#645](https://github.com/HKUDS/Vibe-Trading/pull/645), thanks @tyj147454413-cmd), and the dev extra installs the documented Black/Ruff toolchain ([#634](https://github.com/HKUDS/Vibe-Trading/pull/634), thanks @xkam7ar).

- **2026-07-17** 🧩 **Correlation-regime skill + a broad backtest / data / live-safety correctness pass**: a new **correlation-regime** detection skill (bundled skills → 88, [#557](https://github.com/HKUDS/Vibe-Trading/pull/557), thanks @ebujinovch), a Longbridge runtime connection card ([#569](https://github.com/HKUDS/Vibe-Trading/pull/569), thanks @fanfpy), and user-defined swarm presets loaded from `~/.vibe-trading` ([#570](https://github.com/HKUDS/Vibe-Trading/pull/570), thanks @darkknight4563). Plus hardening across the stack: silent-data-corruption fixes in the Futu / Tencent / CCXT / mootdx loaders, look-ahead-bias and strict-OOS guards in the factor bench and Shadow Account, live-trading safety (signed exposure caps, atomic daily order limits, consent-first mandate commits, fail-closed live state), and journal / QVeris-budget / swarm / CI-gate improvements ([#552](https://github.com/HKUDS/Vibe-Trading/pull/552), thanks @xor-xe; much of the correctness work by @xkam7ar).

- **2026-07-16** 🔧 **Dependency lock repaired + Windows settings save fix**: the hash-verified runtime lock is regenerated so Docker's `pip install --require-hashes` resolves cleanly again, fixing the incompatible `caio`/`pydantic-core`/`websockets` pins ([#564](https://github.com/HKUDS/Vibe-Trading/pull/564), closes [#558](https://github.com/HKUDS/Vibe-Trading/issues/558), thanks @tianrking). Saving Agent LLM settings from the Web UI no longer returns HTTP 500 on Windows — the POSIX-only `os.fchmod` hardening is now platform-guarded, with a regression test for platforms without `fchmod` ([#561](https://github.com/HKUDS/Vibe-Trading/pull/561), thanks @CRui5in).

- **2026-07-15** 🧮 **Backtest correctness + Portfolio Studio core**: A 10-PR convergence pass made rebalances causal and order-independent, charged terminal close costs, reported fill-derived turnover, enforced exposure caps, and kept validation output finite and strict ([#530](https://github.com/HKUDS/Vibe-Trading/pull/530)/[#531](https://github.com/HKUDS/Vibe-Trading/pull/531)/[#532](https://github.com/HKUDS/Vibe-Trading/pull/532)/[#540](https://github.com/HKUDS/Vibe-Trading/pull/540)). Charts now reuse the run's actual data source, repeatable market queries are no longer dropped, and `.env` loads refresh cached config ([#535](https://github.com/HKUDS/Vibe-Trading/pull/535)/[#544](https://github.com/HKUDS/Vibe-Trading/pull/544)/[#554](https://github.com/HKUDS/Vibe-Trading/pull/554)). Portfolio Studio [#456](https://github.com/HKUDS/Vibe-Trading/issues/456) and config bug [#541](https://github.com/HKUDS/Vibe-Trading/issues/541) are closed; provider fixes [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529) closed too. Thanks @YZY0108, @santhreal, @Robin1987China, @xkam7ar, @Marnie0415, and @marichu99.

- **2026-07-14** 🌉 **Longbridge market data + modern MCP transport + provider reliability**: Longbridge joins the historical-data fallback layer with key-gated credentials, date-window splitting, strict completeness checks, and an opt-in SDK dependency; four China-market flow tools gain verified Tushare fallbacks, and negative final equity no longer crashes backtest metrics. The MCP server now supports Streamable HTTP, `write_file` safely recovers aliased or missing path arguments, hypothesis updates reject unsupported fields, and Correlation requests are authenticated. NVIDIA NIM is now a first-class provider across Web Settings and both CLI onboarding paths, with a versioned compatibility User-Agent to address the reported 403; Web Settings now writes to the canonical `~/.vibe-trading/.env`, migrates legacy configuration, and reports permission failures clearly, fixing the DeepSeek save-time 500 ([#534](https://github.com/HKUDS/Vibe-Trading/pull/534), closes [#516](https://github.com/HKUDS/Vibe-Trading/issues/516)/[#524](https://github.com/HKUDS/Vibe-Trading/issues/524); [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529)). Thanks @fanfpy, @asahikiko, @santhreal, @sTunnaSu, @abhishekjaisinghani, @huangcheng, @ShiroKSH, @Meru143, @DIEGOD79, and @not-knope for the code, reports, and diagnosis.

- **2026-07-13** 🔒 **Security hardening: all 10 external-audit findings closed + contributor batch**: every finding from the 2026-07-10 external security audit (issue [#476](https://github.com/HKUDS/Vibe-Trading/issues/476), discussion [#468](https://github.com/HKUDS/Vibe-Trading/discussions/468)) is now addressed on `main` — Docker multi-stage rebuild with digest-pinned images, an AST-hardened backtest sandbox blocking network/subprocess/eval/os.environ/unsafe-open (including inside nested function bodies), short-lived single-use SSE auth tickets, hardened Compose (read-only rootfs, dropped capabilities, resource limits), auth + rate limiting on `/correlation`, security headers, hash-locked dependencies, and more. Also merged: opt-in **TAP mode** for Alpaca key isolation ([#377](https://github.com/HKUDS/Vibe-Trading/pull/377), thanks @0xZKnw), realized portfolio turnover surfaced in backtest metrics ([#478](https://github.com/HKUDS/Vibe-Trading/pull/478), thanks @Robin1987China), a **Frazzini-Pedersen betting-against-beta** academic factor (Alpha Zoo → 461, [#480](https://github.com/HKUDS/Vibe-Trading/pull/480), thanks @YogeshModi24), a look-ahead-bias fix across all 5 portfolio optimizers ([#487](https://github.com/HKUDS/Vibe-Trading/pull/487), thanks @YZY0108), and two preflight/provider-config fixes ([#479](https://github.com/HKUDS/Vibe-Trading/pull/479)/[#484](https://github.com/HKUDS/Vibe-Trading/pull/484), closes [#477](https://github.com/HKUDS/Vibe-Trading/issues/477)/[#482](https://github.com/HKUDS/Vibe-Trading/issues/482), thanks @ananaymital/@Bortlesboat).

- **2026-07-12** 🧪 **Strategy Development Manager + contributor fix batch**: the new `strategy-dev-manager` skill (#87) turns academic papers and broker research into registered factors/strategies with a persistent artifact store and automated IC/Sharpe decay monitoring — `sdm_register` / `sdm_status` / `sdm_decay_scan` drive an active → monitoring → decayed → disabled lifecycle over `~/.vibe-trading/` ([#457](https://github.com/HKUDS/Vibe-Trading/pull/457), closes [#455](https://github.com/HKUDS/Vibe-Trading/issues/455), thanks @shadowinlife). Also merged: the Correlation tab accepts bare tickers (`AAPL,SPY`) and walks the full loader fallback chain ([#472](https://github.com/HKUDS/Vibe-Trading/pull/472), closes [#471](https://github.com/HKUDS/Vibe-Trading/issues/471), thanks @yxhuang), the `local` loader honors requested intervals via OHLCV resampling ([#467](https://github.com/HKUDS/Vibe-Trading/pull/467), thanks @Shizoqua), Binance USD-M perpetual history lands with explicit `BTC-USDT-PERP` routing + execution/mark price separation as the first [#462](https://github.com/HKUDS/Vibe-Trading/issues/462) slice ([#470](https://github.com/HKUDS/Vibe-Trading/pull/470), thanks @honginp), FastMCP transport imports now work across both module layouts ([#469](https://github.com/HKUDS/Vibe-Trading/pull/469), thanks @roberttidball), and Requesty is available as an OpenAI-compatible LLM gateway provider ([#474](https://github.com/HKUDS/Vibe-Trading/pull/474), thanks @Thibaultjaigu).

- **2026-07-11** 🚀 **v0.1.11 released** (`pip install -U vibe-trading-ai`): rolls up three weeks since 0.1.10 — first-class Indian equity (NSE/BSE) backtesting, the PIT-safe fundamental factor layer (Alpha Zoo → 460), the 16-adapter IM channel runtime, end-to-end scheduled research, optional QVeris premium data, and today's contributor batch: a turnover-aware optimizer ([#466](https://github.com/HKUDS/Vibe-Trading/pull/466), thanks @Robin1987China), an `analyze_image` vision tool + NapCat DM pairing + the IM-media read fix ([#464](https://github.com/HKUDS/Vibe-Trading/pull/464)/[#463](https://github.com/HKUDS/Vibe-Trading/pull/463)/[#465](https://github.com/HKUDS/Vibe-Trading/issues/465), thanks @fei-moss), Longbridge Decimal serialization ([#459](https://github.com/HKUDS/Vibe-Trading/pull/459), thanks @fanfpy), and packaged-manifest count guards ([#461](https://github.com/HKUDS/Vibe-Trading/pull/461), thanks @asahikiko). Full details: [CHANGELOG](CHANGELOG.md) · [release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.11).

- **2026-07-10** 🇮🇳 **Indian equity (NSE/BSE) support + centralized env config**: a dedicated `IndiaEquityEngine` lands — T+1 delivery, circuit bands, and a config-driven STT/stamp/exchange/SEBI/GST cost stack — with `.NS`/`.BO` symbol routing, an opt-in read-only Shoonya/Dhan data bridge, and 255 alpha101/qlib158 factors opted into the new `equity_in` universe ([#305](https://github.com/HKUDS/Vibe-Trading/pull/305), thanks @muku314115). Environment variables now flow through a single Pydantic `EnvConfig` schema with an AST-based CI gate against future `os.getenv` sprawl ([#440](https://github.com/HKUDS/Vibe-Trading/pull/440), closes [#438](https://github.com/HKUDS/Vibe-Trading/issues/438), thanks @shadowinlife). Also: a second-confirmation dialog before committing a real trading mandate plus unified error toasts ([#453](https://github.com/HKUDS/Vibe-Trading/pull/453), thanks @wison1717-maker), scheduled-research route tests ([#452](https://github.com/HKUDS/Vibe-Trading/pull/452), thanks @Robin1987China), and GLM thinking models no longer lose their reasoning stream on the zhipu provider ([#458](https://github.com/HKUDS/Vibe-Trading/issues/458)).

- **2026-07-09** 🧯 **Docker startup unblocked + provider/CLI contributor batch**: Docker/server startup no longer crashes when FastAPI route iteration sees an included-router-like entry without `path` ([#450](https://github.com/HKUDS/Vibe-Trading/issues/450), thanks @Penn-Live). We also landed the queued quick-win contributor fixes: loader `fetch()` signatures now match the protocol across OKX / Tushare / yfinance ([#437](https://github.com/HKUDS/Vibe-Trading/pull/437), thanks @shadowinlife), the CLI resume prompt preserves the first user message ([#448](https://github.com/HKUDS/Vibe-Trading/pull/448), closes [#447](https://github.com/HKUDS/Vibe-Trading/issues/447), thanks @morluto), Codex OAuth defaults to `openai-codex/gpt-5.4` ([#446](https://github.com/HKUDS/Vibe-Trading/pull/446), thanks @morluto), Kimi for Coding is available as a distinct provider ([#435](https://github.com/HKUDS/Vibe-Trading/pull/435), thanks @yxhuang), opencode provider mappings are wired ([#444](https://github.com/HKUDS/Vibe-Trading/pull/444), thanks @imsankz), and Tushare reference code fences now say `python` instead of `pyhton` ([#449](https://github.com/HKUDS/Vibe-Trading/pull/449), thanks @flash1234pku). Validation included focused server/CLI/provider/loader tests plus a Docker build and `/health` smoke.

- **2026-07-08** 💎 **Fundamental factor layer (Phase 1) + optional QVeris premium data + maintainer day**: PIT-safe SEC fundamentals now flow into daily factor panels — `fund:*` panel columns, filed-date anchoring with restatement and YTD-frame protection, and 4 new quality/value factors (registry now 460 alphas). Data routing gains an optional premium track: the 18 free sources stay the default, while QVeris unlocks 63+ providers via Settings → QVeris or `vibe-trading data mode paid` (see the QVeris section below). Also: `api_server` modularization completed (1,103 → 371 lines, [#424](https://github.com/HKUDS/Vibe-Trading/pull/424) closing [#331](https://github.com/HKUDS/Vibe-Trading/issues/331), thanks @shadowinlife), backtest `validation.json` no longer requires a pre-existing artifacts dir ([#429](https://github.com/HKUDS/Vibe-Trading/pull/429), thanks @isaveall), clearer `--swarm-run` errors ([#428](https://github.com/HKUDS/Vibe-Trading/issues/428), thanks @isaveall), and we reverted the governance stack that broke session chats ([#433](https://github.com/HKUDS/Vibe-Trading/issues/433), thanks @yxhuang for the precise diagnosis).

- **2026-07-07** ✅ **Contributor PR batch**: merged the queued contributor work for IM channel timeout configuration ([#413](https://github.com/HKUDS/Vibe-Trading/pull/413), thanks @SyntaxSawdust), Alpha Library social previews and the beginner tutorial ([#396](https://github.com/HKUDS/Vibe-Trading/pull/396), [#393](https://github.com/HKUDS/Vibe-Trading/pull/393), thanks @kadaliao), value-investing skills / tools / committee presets ([#407](https://github.com/HKUDS/Vibe-Trading/pull/407), thanks @sambazhu), zero-sized order-field handling in `trading_place_order` ([#417](https://github.com/HKUDS/Vibe-Trading/pull/417), thanks @irfanallana-oss), and timezone-aware UTC timestamps across session/API paths ([#397](https://github.com/HKUDS/Vibe-Trading/pull/397), thanks @mustafakamal88).

- **2026-07-06** 🧭 **Preflight hardening, API slices, and CN search fallback**: provider preflight no longer follows redirects ([#404](https://github.com/HKUDS/Vibe-Trading/pull/404), closes [#402](https://github.com/HKUDS/Vibe-Trading/issues/402), thanks @SyntaxSawdust), the remaining API routes moved into focused modules ([#387](https://github.com/HKUDS/Vibe-Trading/pull/387), superseding [#383](https://github.com/HKUDS/Vibe-Trading/pull/383)-[#386](https://github.com/HKUDS/Vibe-Trading/pull/386), thanks @shadowinlife), and CN web-search fallbacks now include Alibaba Cloud IQS ([#408](https://github.com/HKUDS/Vibe-Trading/pull/408), thanks @sambazhu). Maintainer cleanup added no-network fallback tests and EOF whitespace cleanup ([fbac74f](https://github.com/HKUDS/Vibe-Trading/commit/fbac74f77bfed58dd7fc23d0f001c29190b4b2b6)); main CI is green ([run 28780619018](https://github.com/HKUDS/Vibe-Trading/actions/runs/28780619018)).

- **2026-07-05** ✅ **Contributor PR queue closed + Windows baseline green**: merged the four non-draft PRs selected for today's maintainer pass. A-share mootdx batch pulls now let `KeyboardInterrupt` / `SystemExit` propagate instead of being swallowed by a bare `except` ([#399](https://github.com/HKUDS/Vibe-Trading/pull/399), closes [#398](https://github.com/HKUDS/Vibe-Trading/issues/398), thanks @shadowinlife). The Settings route slice and patched dependency floors are now merged under their original contributor PRs ([#382](https://github.com/HKUDS/Vibe-Trading/pull/382), [#390](https://github.com/HKUDS/Vibe-Trading/pull/390), thanks @shadowinlife and @aeonframework). Windows baseline compatibility now isolates loader caches, makes OAuth cache assertions platform-aware, skips one fork-only mock test on Windows, and bypasses proxies for MCP loopback fixtures ([#401](https://github.com/HKUDS/Vibe-Trading/pull/401), thanks @Elfsa-Miranda). Validation: `4701 passed, 47 skipped`.

- **2026-07-04** 🧩 **API route slices, tutorial docs, and dependency floors**: IM channel and Settings routes moved out of `api_server.py` into `src/api/channels_routes.py` and `src/api/settings_routes.py`, continuing the narrow [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) modularization path from contributor work ([#379](https://github.com/HKUDS/Vibe-Trading/pull/379), [#382](https://github.com/HKUDS/Vibe-Trading/pull/382), thanks @shadowinlife). The wiki gained a Chinese beginner tutorial for non-finance readers ([#393](https://github.com/HKUDS/Vibe-Trading/pull/393), thanks @kadaliao), and dependency floors now keep Pillow / LangChain / LangGraph on the installable patched track ([#390](https://github.com/HKUDS/Vibe-Trading/pull/390), thanks @aeonframework).

- **2026-07-04** 🧹 **UTC timestamp cleanup for session and API paths**: tightened the #395 timestamp fix so session, goal, channel, and API timestamps now emit timezone-aware UTC values in explicit ISO form.

- **2026-07-03** 🛡️ **Robinhood MCP refresh + API modularization + SSRF guard**: Robinhood Agentic Trading now uses the current MCP tool names across generic reads, live-runner plumbing, default read-only seeds, and mandate-gate tests, while interactive startup honors the same `.env` search order as the provider loader (`~/.vibe-trading/.env` → `agent/.env` → `$CWD/.env`) ([#391](https://github.com/HKUDS/Vibe-Trading/pull/391), closes [#381](https://github.com/HKUDS/Vibe-Trading/issues/381) and [#380](https://github.com/HKUDS/Vibe-Trading/issues/380)). System routes (`/health`, `/correlation`, `/system/shutdown`, `/skills`, `/api`) moved into `src/api/system_routes.py` as the next narrow API modularization slice ([#378](https://github.com/HKUDS/Vibe-Trading/pull/378), thanks @shadowinlife). Channel media SSRF defenses now reject CGNAT/mesh/non-global targets and QQ media redirects-to-internal before fetching ([#389](https://github.com/HKUDS/Vibe-Trading/pull/389), thanks @hobostay).

- **2026-07-02** ⚡ **Factor acceleration + safer runtime boundaries**: hot rolling factor operators now use `bottleneck`/NumPy fast paths, alpha bench parallelism avoids repeated large-panel worker payloads, and base equity math has regression coverage ([#376](https://github.com/HKUDS/Vibe-Trading/pull/376), closes [#339](https://github.com/HKUDS/Vibe-Trading/issues/339), original work from [#342](https://github.com/HKUDS/Vibe-Trading/pull/342) by @shadowinlife). Upload and Shadow report routes moved out of the monolithic `api_server.py` as the first narrow API modularization slice while [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) stays open ([#375](https://github.com/HKUDS/Vibe-Trading/pull/375), based on [#358](https://github.com/HKUDS/Vibe-Trading/pull/358), thanks @shadowinlife). Generated backtests now inherit only an allowlisted subprocess environment instead of the parent secrets surface ([#374](https://github.com/HKUDS/Vibe-Trading/pull/374), closes [#332](https://github.com/HKUDS/Vibe-Trading/issues/332)), and IM channels gained `/new` session reset plus case-insensitive pairing commands ([#372](https://github.com/HKUDS/Vibe-Trading/pull/372), closes [#371](https://github.com/HKUDS/Vibe-Trading/issues/371), thanks @shadowinlife).

- **2026-07-01** 🧹 **Security polish + tracker cleanup**: tightened API/Docker/frontend dev defaults, stabilized Settings channel and `zh-CN` edges, cleared frontend dependency/CSP alerts, and closed stale WhatsApp + paper-trading tracker items ([#338](https://github.com/HKUDS/Vibe-Trading/pull/338), [#351](https://github.com/HKUDS/Vibe-Trading/pull/351), [#349](https://github.com/HKUDS/Vibe-Trading/pull/349), [#365](https://github.com/HKUDS/Vibe-Trading/pull/365), [#367](https://github.com/HKUDS/Vibe-Trading/pull/367), [#350](https://github.com/HKUDS/Vibe-Trading/pull/350), [#335](https://github.com/HKUDS/Vibe-Trading/pull/335), [#283](https://github.com/HKUDS/Vibe-Trading/issues/283)).

- **2026-06-30** 💬 **IM channel runtime for research delivery**: Vibe-Trading can now attach the same agent session runtime to 16 built-in message adapters — WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, email, and Mochat. CLI (`vibe-trading channels status/start/stop/login/pairing`), REST (`/channels/status`, `/channels/start`, `/channels/stop`, `/channels/pairing/command`), and the Web UI Settings panel expose status, recovery hints, start/stop, and sender pairing; SDK-backed adapters stay behind extras such as `vibe-trading-ai[telegram]` or `vibe-trading-ai[channels]` ([#341](https://github.com/HKUDS/Vibe-Trading/pull/341)).

- **2026-06-29** 🛡️ **Live advisory safety + Trading 212 read-only connector + Windows/Gemini fixes**: live order guards now have an opt-in, broker-agnostic `PreTradeAdvisoryInterface` that records advisory reviews without bypassing the mandate gate, kill switch, or audit trail ([#328](https://github.com/HKUDS/Vibe-Trading/pull/328), closes [#317](https://github.com/HKUDS/Vibe-Trading/issues/317), thanks @shadowinlife). Trading 212 joins the connector layer with read-only account, positions, orders, history, and instrument-metadata support; `place_order` / `cancel_order` still hard-refuse until a structural paper/live boundary exists ([#321](https://github.com/HKUDS/Vibe-Trading/pull/321), closes [#309](https://github.com/HKUDS/Vibe-Trading/issues/309), thanks @mvanhorn). Windows startup avoids the pandas 3.0 `Timestamp` crash via the `<3.0.0` constraint ([#329](https://github.com/HKUDS/Vibe-Trading/pull/329), closes [#324](https://github.com/HKUDS/Vibe-Trading/issues/324), thanks @hannibal-lee); Gemini `thought_signature` dict-history replay was verified/fixed on `main` ([#318](https://github.com/HKUDS/Vibe-Trading/issues/318)); `.US` financial statements now route to SEC EDGAR instead of Eastmoney ([#325](https://github.com/HKUDS/Vibe-Trading/issues/325)); and the Alpha Library landing page got cache/date/selector/noscript/DNS-prefetch hardening while heavier CSP and social-card follow-ups stay tracked ([#323](https://github.com/HKUDS/Vibe-Trading/issues/323)).

- **2026-06-28** 🧰 **Cross-platform setup/dev + runtime and file-tool hardening**: `vibe-trading setup` and `vibe-trading dev` now handle Windows TypeScript builds, launch the backend from the right cwd, use the Vite 5899 port, and shut child processes down cleanly ([#292](https://github.com/HKUDS/Vibe-Trading/pull/292), thanks @digger-yu). Runtime status polling now degrades instead of crashing ([#322](https://github.com/HKUDS/Vibe-Trading/issues/322)); MCP OAuth cache keys are sanitized ([#313](https://github.com/HKUDS/Vibe-Trading/issues/313)); OpenAI defaults and Robinhood `agent.json` validation were tightened ([#319](https://github.com/HKUDS/Vibe-Trading/pull/319), [#320](https://github.com/HKUDS/Vibe-Trading/pull/320), thanks @mvanhorn); and file tools got isolated read/write roots plus broader sandbox tests ([#299](https://github.com/HKUDS/Vibe-Trading/pull/299), thanks @skloxo).
- **2026-06-27** 🧯 **Content-filter resilience + Shadow Account feature contract cleanup**: event-driven and swarm runs now skip individual LLM content-moderation hits, warn in run cards when filter rates are high, and recognize Gemini safety finish reasons instead of aborting an entire analysis ([#308](https://github.com/HKUDS/Vibe-Trading/pull/308), closes [#307](https://github.com/HKUDS/Vibe-Trading/issues/307), thanks @shadowinlife). Shadow Account extraction/codegen now share one `PRICE_FEATURES` contract and keep four-decimal return bounds, preventing rule/codegen drift and precision loss on `prior_5d_return` ([#316](https://github.com/HKUDS/Vibe-Trading/pull/316), thanks @Robin1987China).
- **2026-06-26** 🎯 **Shadow Account conditional entry + tushare ETF/index/HK routing**: extracted Shadow Account rules now carry RSI / prior-return bounds, so the generated SignalEngine enters on real conditions (RSI in range, prior-return in range) instead of blindly replaying the holding cadence ([#314](https://github.com/HKUDS/Vibe-Trading/pull/314), follows [#302](https://github.com/HKUDS/Vibe-Trading/pull/302), thanks @Robin1987China). The tushare loader also routes ETF/LOF → `fund_daily()`, indices → `index_daily()`, and HK equities → `hk_daily()` instead of always calling `daily()` (which silently returns empty for non-stocks), with per-symbol empty-result + partial-fetch warnings ([#315](https://github.com/HKUDS/Vibe-Trading/pull/315), closes [#310](https://github.com/HKUDS/Vibe-Trading/issues/310), thanks @shadowinlife).
- **2026-06-25** 🧪 **Strict validation JSON + calmer agent context**: standalone backtest validation now normalizes nested `NaN` / `Infinity` values before writing `artifacts/validation.json` or CLI stdout, so strict JSON parsers no longer choke on validation payloads ([#306](https://github.com/HKUDS/Vibe-Trading/pull/306), thanks @gyx09212214-prog). The agent prompt also derives the current data-source count from the loader registry, and `_microcompact()` now waits for real token pressure instead of clearing older tool results during short runs ([#296](https://github.com/HKUDS/Vibe-Trading/pull/296), closes [#282](https://github.com/HKUDS/Vibe-Trading/issues/282), thanks @MarkfuGod).
- **2026-06-24** 🎯 **Shadow Account price context + reactive Chinese UI + LAN auth fix**: Shadow Account rule extraction now sees PIT-safe entry context — `entry_rsi14` and `prior_5d_return` fetched through the loader registry as of `buy_dt`, with graceful offline/no-data degradation ([#302](https://github.com/HKUDS/Vibe-Trading/pull/302), follows [#295](https://github.com/HKUDS/Vibe-Trading/issues/295), thanks @Robin1987China). The main Web UI panels now use reactive English / zh-CN translations across charts, chat, Alpha Library, Correlation, and Run Detail ([#301](https://github.com/HKUDS/Vibe-Trading/pull/301), thanks @skloxo). Remote same-origin Web UI deployments with `API_AUTH_KEY` can post and upload again after the CSRF hardening, while mismatched cross-site origins remain blocked ([#304](https://github.com/HKUDS/Vibe-Trading/pull/304), thanks @Hinotoi-agent).
- **2026-06-23** 🛡️ **Local API CSRF hardening**: a malicious web page can no longer drive unsafe cross-site requests (POST/PUT/DELETE) against the loopback API — CORS blocks reading the response but not the side effect, so loopback dev-mode trust now applies the existing cross-site guard to unsafe methods *before* honoring it. Safe methods and local CLI / non-browser uploads are unaffected ([#293](https://github.com/HKUDS/Vibe-Trading/pull/293), thanks @Hinotoi-agent).
- **2026-06-22** 🔧 **Live-authorize OAuth fix + Alpha Zoo headline fix**: `connector authorize` now holds the OAuth handshake open through a multi-minute broker sign-in (tunable via `VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS`) and no longer spawns a competing callback server on retry, so the token actually persists ([#281](https://github.com/HKUDS/Vibe-Trading/pull/281), closes [#259](https://github.com/HKUDS/Vibe-Trading/issues/259), thanks @Robin1987China). The Alpha Zoo page no longer prints its alpha count twice ([#287](https://github.com/HKUDS/Vibe-Trading/pull/287), closes [#286](https://github.com/HKUDS/Vibe-Trading/issues/286), thanks @digger-yu). Scheduled research also picked up end-to-end usage docs ([#288](https://github.com/HKUDS/Vibe-Trading/pull/288)).
- **2026-06-21** ⏰ **Scheduled-research executor + Reports library + post-backtest attribution**: scheduled research now runs **end to end** — a default-off background executor (`VIBE_TRADING_ENABLE_SCHEDULER`) fires due interval/cron jobs through the session runtime ([#278](https://github.com/HKUDS/Vibe-Trading/pull/278), thanks @mvanhorn, closing [#254](https://github.com/HKUDS/Vibe-Trading/issues/254)). A new **`/reports` Run Library** page lists, searches, and filters report-worthy runs with links into Run Detail + Compare ([#224](https://github.com/HKUDS/Vibe-Trading/pull/224), thanks @LemonCANDY42). And after every backtest the agent now runs **layered attribution** — trade-level winners/losers, beta regression, market-regime analysis, and a Monte Carlo permutation test, gated by data availability and routing ([#280](https://github.com/HKUDS/Vibe-Trading/pull/280), thanks @shadowinlife).
- **2026-06-20** 🔬 **Research Autopilot loop closes (Phase 3) + loader OHLC integrity guard + 4 academic alphas**: **Research Autopilot** now runs **hypothesis → signal-engine → backtest** end to end — `scaffold_signal_engine` writes a contract-correct engine and `link_autopilot_backtest` feeds run metrics back to the hypothesis (**68 tools**) ([#267](https://github.com/HKUDS/Vibe-Trading/pull/267)). A structural **OHLC sanity check** drops dirty bars (`high < low`, non-positive prices, bad bracketing) centrally at the loader boundary, guarding every data source ([#274](https://github.com/HKUDS/Vibe-Trading/pull/274), thanks @Shizoqua). And the **academic alpha family grows 6 → 10** — Jegadeesh reversal, George-Hwang 52-week-high, Amihud illiquidity, Harvey-Siddique skew (**456 factors**) ([#277](https://github.com/HKUDS/Vibe-Trading/pull/277), thanks @Robin1987China).
- **2026-06-19** 🚀 **v0.1.10 — Global data layer**: market-data sources grow 10 → 18 (free **Eastmoney / Sina / Stooq / Yahoo** + key-gated **Finnhub / Alpha Vantage / Tiingo / FMP**, ban-risk fallback) plus **18 read-only data tools** (fund flow, dragon-tiger, northbound, margin, block trades, SEC EDGAR + XBRL, financials, options chains, full-market screening…) across A-share / US / HK, all over MCP. Also bundles everything since 0.1.9 — 10 broker connectors, `alpha compare`, the provider-reliability overhaul, and the opt-in data cache. `pip install -U vibe-trading-ai`
- **2026-06-18** 🔬 **Research Autopilot Phase 1 + a local Data Bridge loader, + a Discord security notice**: new `run_research_autopilot` + `generate_backtest_config` wire **Hypothesis → Research Goal → backtest** end to end (now **50 tools**), and a **`local`** loader reads OHLCV straight from your own **CSV / Parquet / DuckDB** files ([#260](https://github.com/HKUDS/Vibe-Trading/pull/260), [#252](https://github.com/HKUDS/Vibe-Trading/pull/252), thanks @Robin1987China), alongside DeepSeek `DSML` tool-call parsing and an identifier-containment hardening wave. ⚠️ **Security:** the old community Discord invite now points to a server we don't control running a fake Collab.Land wallet-"verification" phishing scam — removed everywhere; the **only** official Discord is the HKUDS server ([discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF)), and we'll never ask you to connect a wallet.
- **2026-06-17** 🧩 **Install compatibility + Opus/Kimi provider fixes**: Baseline `pip install vibe-trading-ai` no longer pulls the optional `pyharmonics` / `ta` dependency chain; harmonic detection now lives behind `vibe-trading-ai[harmonic]` while the bundled detector remains available ([#250](https://github.com/HKUDS/Vibe-Trading/pull/250), closes [#249](https://github.com/HKUDS/Vibe-Trading/issues/249)). The agent loop also avoids assistant-prefill handoff messages rejected by Opus 4.8+, and Kimi/Moonshot can override the client `User-Agent` with `MOONSHOT_USER_AGENT` ([#248](https://github.com/HKUDS/Vibe-Trading/pull/248), closes [#246](https://github.com/HKUDS/Vibe-Trading/issues/246) and [#204](https://github.com/HKUDS/Vibe-Trading/issues/204)); follow-up tests now directly cover background-result and auto-compact handoff paths ([#251](https://github.com/HKUDS/Vibe-Trading/pull/251)).
- **2026-06-16** 🛡️ **Security/API hardening + GLM/Zhipu alias**: Settings writes require auth when configured ([#245](https://github.com/HKUDS/Vibe-Trading/pull/245)); API shell-capable tools require explicit `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` opt-in ([#243](https://github.com/HKUDS/Vibe-Trading/pull/243)); local shutdown requires auth when an API key is configured ([#241](https://github.com/HKUDS/Vibe-Trading/pull/241)); and untrusted loopback-looking hosts are rejected instead of treated as local ([#242](https://github.com/HKUDS/Vibe-Trading/pull/242)). Runtime edges also got cleaned up: Web chat syncs completed attempts ([#236](https://github.com/HKUDS/Vibe-Trading/pull/236)), run cards emit strict JSON for non-finite metrics ([#238](https://github.com/HKUDS/Vibe-Trading/pull/238)), malformed `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S` falls back safely ([#240](https://github.com/HKUDS/Vibe-Trading/pull/240)), and ddgs retry fallback is regression-covered ([#239](https://github.com/HKUDS/Vibe-Trading/pull/239)). GLM/Zhipu is now a first-class provider alias with model-name inference ([#247](https://github.com/HKUDS/Vibe-Trading/pull/247), closes [#237](https://github.com/HKUDS/Vibe-Trading/issues/237)).

- **2026-06-15** 🧭 **Web-search resilience + Web UI run-continuity fixes**: `web_search` no longer fails when a single engine is rate-limited — it now queries several free, no-key engines in order (DuckDuckGo, Google, Bing, Brave, Mojeek, Yahoo) with retry/backoff, treats "no results" as an empty answer rather than an error, and returns an actionable message instead of a bare ❌ when every engine is throttled (override the engine list with `VIBE_TRADING_SEARCH_BACKENDS`) ([#232](https://github.com/HKUDS/Vibe-Trading/pull/232), closes [#231](https://github.com/HKUDS/Vibe-Trading/issues/231), thanks @Ethan-sun01). In the Web UI, switching pages during a run no longer freezes it — the chat re-subscribes to the live stream and replays missed progress on return ([#234](https://github.com/HKUDS/Vibe-Trading/pull/234)) — and the Stop button now takes effect mid-stream and between tools instead of only at iteration boundaries ([#235](https://github.com/HKUDS/Vibe-Trading/pull/235)), closing both halves of [#229](https://github.com/HKUDS/Vibe-Trading/issues/229) (thanks @kalkinj). The baostock loader also accepts native `sh.601398` / `sz.000001` codes alongside tushare-style `601398.SH` ([#230](https://github.com/HKUDS/Vibe-Trading/pull/230), thanks @bhlt).

- **2026-06-14** 📊 **Per-run token usage + progressive Run Detail charts**: Every agent run now persists provider-reported token usage as a run-scoped `llm_usage.json` — provider/model, aggregate totals, and per-iteration counts — surfaced additively on `/runs/{id}`, so a finished run's token cost stays auditable after the live stream is gone (provider-reported only; no prompt/content capture, no price estimation) ([#223](https://github.com/HKUDS/Vibe-Trading/pull/223), thanks @LemonCANDY42). The Run Detail page no longer loads every symbol's candlesticks up front: the default `/runs/{id}` response is unchanged, but the UI now renders the run summary first and loads each symbol's chart on demand through opt-in `?chart_payload=summary` / `?chart_symbol=` modes, with per-symbol loading state and a load-all-with-progress control ([#225](https://github.com/HKUDS/Vibe-Trading/pull/225), thanks @LemonCANDY42). Two loader fixes close the cycle: yfinance's exclusive `end` boundary no longer drops the final requested trading day — the download now passes `end + 1 day` while cache keys keep the original range ([#226](https://github.com/HKUDS/Vibe-Trading/pull/226), thanks @gyx09212214-prog) — and a malformed `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` value now warns and falls back to its default instead of raising at import and blocking startup ([#227](https://github.com/HKUDS/Vibe-Trading/pull/227), thanks @gyx09212214-prog).
- **2026-06-13** ↩️ **Resume a past session by ID from the CLI**: The interactive CLI now prints the session-id on exit, with a copy-paste `vibe-trading resume <session-id>` hint — so locating the trace for a finished run no longer means guessing which folder under `agent/sessions/` is newest by timestamp. The new `vibe-trading resume <session-id>` subcommand reopens that exact session and replays its recent turns into the loop; an unknown id fails fast instead of silently starting a blank session ([#218](https://github.com/HKUDS/Vibe-Trading/pull/218), thanks @zwrong).
- **2026-06-12** 🩺 **Provider reliability overhaul — DeepSeek hangs, Kimi access, streaming liveness**: A cluster of provider reports — DeepSeek runs stuck on "Agent is working…" ([#208](https://github.com/HKUDS/Vibe-Trading/issues/208), thanks @XYWOX), `reached max iterations` masking empty model responses ([#203](https://github.com/HKUDS/Vibe-Trading/issues/203), thanks @mojianliang), the UI never recovering after a stall ([#195](https://github.com/HKUDS/Vibe-Trading/issues/195), thanks @mafia23), and Kimi rejecting the client ([#204](https://github.com/HKUDS/Vibe-Trading/issues/204), thanks @liao497) — shared one root: every OpenAI-compatible provider ran through a single shim that applied DeepSeek/Kimi/Gemini quirks globally and silently swallowed stream failures. Provider-specific behavior now lives in an explicit **capability layer** — reasoning capture/replay, Gemini thought signatures, the Kimi `User-Agent`, OpenRouter's reasoning body are each gated to their own provider instead of cross-contaminating. Reasoning-only streams show a live **"Reasoning…"** indicator instead of dead air; a stream failure raises a contextual `provider_stream_error` with one automatic retry for transient resets (deterministic 4xx fail fast) instead of silently falling back to a slow non-streaming call; an empty model response is reported as `empty_model_response` instead of "max iterations"; SSE heartbeats no longer break reconnect replay; and a stuck read-only tool times out instead of hiding behind heartbeats forever. A new **`vibe-trading provider doctor`** prints a redacted provider/model/package/proxy snapshot for one-command triage of environment-side hangs. DeepSeek users can opt into the official native adapter with `pip install "vibe-trading-ai[deepseek]"`, and kimi-k2.x's `temperature=1` requirement is applied automatically — the Kimi path is verified end-to-end against the live API (tool calls + strict multi-turn reasoning replay on `kimi-k2.6`).

- **2026-06-11** 🐝 **Swarm workers now pull market data through the loader layer**: An investment-committee run on NVDA exposed a chain of gaps — workers wrote ad-hoc yfinance scripts, trusted a malformed latest bar (volume present, OHLC empty), leaked `NaN` into non-strict JSON, and a context-free continuation prompt re-routed to the wrong preset ([#198](https://github.com/HKUDS/Vibe-Trading/issues/198), thanks @BillDin for an exceptional diagnosis plus both fixes). Swarm workers now get a local `get_market_data` tool backed by the same normalized loader registry as MCP — strict JSON, non-finite floats serialize as `null` — wired into **every market-data preset** (21 workers across 13 presets) with a prompt policy that steers OHLCV work tool-first ([#199](https://github.com/HKUDS/Vibe-Trading/pull/199)); `run_swarm` takes an explicit `preset_name` and refuses ambiguous continuation fragments instead of silently falling back to `equity_research_team` ([#200](https://github.com/HKUDS/Vibe-Trading/pull/200)). Grounding got smarter too: a bare US ticker like `NVDA` in a swarm prompt is promoted to `NVDA.US` (stopword-guarded), so workers start from authoritative pre-fetched prices. The tool joins the main agent registry as well — **48 tools** now. Also: **your Docker data now survives updates** — persistent memory, the session search index, user-created skills, shadow accounts and broker config live in named volumes, so `docker compose up --build` no longer wipes them ([#197](https://github.com/HKUDS/Vibe-Trading/issues/197), thanks @FlyerJ).
- **2026-06-10** 🐳 **Docker reaches a host-side Ollama out of the box**: Inside the container `localhost` is the container itself, so the shipped `OLLAMA_BASE_URL=http://localhost:11434` failed the LLM preflight for every Dockerized Ollama setup. `docker-compose.yml` now defaults to `http://host.docker.internal:11434` (export `OLLAMA_BASE_URL` to point elsewhere) and adds the `host-gateway` `extra_hosts` mapping so the same file works on Linux as well as Docker Desktop ([#196](https://github.com/HKUDS/Vibe-Trading/pull/196), thanks @ShahNewazKhan).
- **2026-06-09** 🔑 **Clearer error when the Web UI is opened from another machine**: Reaching the chat from a non-loopback client (another machine, a VM host, a phone on your LAN) without `API_AUTH_KEY` set returned `403` on every sensitive endpoint — sending a message, listing sessions, live status — but the chat only showed a generic "Failed to send message, please retry." The send path now surfaces the real reason — *"Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use."* — and the README's web-UI setup spells out the localhost-vs-LAN rule plus the three fixes (browse via `localhost` on the same machine; set `API_AUTH_KEY` and enter it once in Settings; or `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` for Docker Desktop's host gateway) ([#191](https://github.com/HKUDS/Vibe-Trading/issues/191), thanks @mafia23).
- **2026-06-08** 🔧 **Gemini 3.x multi-turn tool-calling fix**: This completes the Gemini 3.x thinking-model fix. The 6/05 round-trip ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176)) only covered in-memory history, but the real agent loop replays history as OpenAI-format dicts where LangChain dropped the per-tool-call `thought_signature` before the request was built — so multi-turn tool calling still 400'd with `missing thought_signature`. It is now re-attached at the single `_convert_input` chokepoint both `invoke` and `stream` pass through (parallel calls, where only the first of N is signed, included) ([#184](https://github.com/HKUDS/Vibe-Trading/pull/184), thanks @ngoanpv).
- **2026-06-07** 🐝 **Live swarm status in the chat timeline**: When the agent launches a multi-agent swarm (investment committee, quant desk, risk committee, …), the chat now renders an inline **status card** that streams each worker's state — waiting / running / done / failed / blocked / retrying — in real time, the same per-agent visibility the standalone swarm dashboard already had. Runtime events are bridged into the session SSE stream without changing the existing `/swarm/runs` API, and a finished card rehydrates from the final `run_swarm` result on reconnect or history replay ([#188](https://github.com/HKUDS/Vibe-Trading/pull/188), thanks @BillDin). Preset routing also got sharper: an explicitly named preset (e.g. `investment_committee`, with or without underscores) now wins over keyword scoring, and the bare `IV` derivatives keyword no longer false-matches inside ordinary words like "g**iv**en" ([#189](https://github.com/HKUDS/Vibe-Trading/pull/189), thanks @BillDin).
- **2026-06-06** ⚖️ **Alpha compare — head-to-head across CLI, Web UI, REST & agent**: A new `alpha compare` benches a hand-picked shortlist of Alpha Zoo alphas against each other on a universe and period, then ranks them by IC mean/std, IR, IC-positive ratio or sample count — each with its gap to the leader. Unlike a full-zoo bench it evaluates **only the alphas you name** (a new `run_bench(only=…)` subset filter), so comparing three alphas no longer scores all 191 in their zoo. One shared core powers every surface: `vibe-trading alpha compare <id1> <id2> … --sort ir` (CLI), a **Compare view** in the Alpha Zoo Web UI (tick alphas in the catalogue → one-click compare with a streamed ranking table), `POST /alpha/compare` + SSE (REST), and a read-only `alpha_compare` agent tool (**47 tools** now).
- **2026-06-05** 🇮🇳 **Dhan + Shoonya connectors (India) — 10 brokers total**: The connector-first trading layer adds **Dhan** and **Shoonya** for the Indian market (NSE/BSE equities + F&O), bringing the roster to ten brokers. Both are **paper + read-only** — like Longbridge, their APIs expose no runtime paper/live discriminator, so their `place_order` / `cancel_order` hard-refuse any non-paper config at the first line (the rule: a broker with no structural paper/live guard is capped at paper + read-only) ([#181](https://github.com/HKUDS/Vibe-Trading/pull/181), closes [#174](https://github.com/HKUDS/Vibe-Trading/issues/174)). This cycle also fixes **Gemini 2.5 / 3.x thinking models**: their per-tool-call `thoughtSignature` now round-trips through the OpenAI-compatible path, so multi-turn function calling no longer fails with `INVALID_ARGUMENT` ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176), closes [#170](https://github.com/HKUDS/Vibe-Trading/issues/170), thanks @mvanhorn & @jliu6789). Chinese docstrings landed on all **452 Alpha Zoo factors** ([#180](https://github.com/HKUDS/Vibe-Trading/pull/180), thanks @LeeCQiang), and a **frontend test suite (197 vitest tests)** plus backend auth / path-traversal / CORS security tests joined CI ([#175](https://github.com/HKUDS/Vibe-Trading/pull/175), thanks @sambazhu).
- **2026-06-04** 🗃️ **Opt-in local data cache for all 7 data sources**: A new `VIBE_TRADING_DATA_CACHE` switch lets every backtest loader — tushare, okx, ccxt, akshare, mootdx, yfinance, futu — cache settled historical bars under `~/.vibe-trading/cache` (user home, never the repo), so repeated and long-horizon / cross-market backtests skip the network and avoid provider rate limits. Off by default. Batch and connection loaders (yfinance, futu) skip the bulk download / FutuOpenD connection entirely on a full cache hit, a staleness guard never caches a range ending today (its last bar is still forming), and cached frames round-trip byte-identical to freshly fetched ones ([#177](https://github.com/HKUDS/Vibe-Trading/pull/177), thanks @mvanhorn). A new contributor guide for AI / automation-assisted PRs also landed, mapping safe local checks and high-risk broker/MCP/credential surfaces ([#173](https://github.com/HKUDS/Vibe-Trading/pull/173)).
- **2026-06-03** 🧹 **Community triage + trace correlation**: Tool-call trace entries now carry the originating `call_id`, so a `tool_result` can be matched back to its `tool_call` when replaying a run trace — arg previews stay truncated to keep trace files small ([#168](https://github.com/HKUDS/Vibe-Trading/pull/168), thanks @zwrong). Source comments no longer point at an internal-only docs path that external contributors couldn't find ([#166](https://github.com/HKUDS/Vibe-Trading/issues/166), thanks @jaleelpersonal). Also clarified that the `langchain-community` resolver warning on install is a harmless leftover-package notice, not a failure ([#167](https://github.com/HKUDS/Vibe-Trading/issues/167)), and scoped Gemini 2.5/3.0 `thoughtSignature` round-tripping for function calls as a `help wanted` task with a full fix plan ([#170](https://github.com/HKUDS/Vibe-Trading/issues/170), thanks @jliu6789).
- **2026-06-02** 🔌 **Six new broker connectors (Tiger / Longbridge / Alpaca / OKX / Binance / Futu)**: The connector-first trading layer gains a direct-SDK transport alongside IBKR (local) and Robinhood (MCP). Each connector exposes read-only account / positions / orders / quote / history **plus paper-account order placement** — test your strategies across these broker paper accounts. Five of them (Tiger, Alpaca, OKX, Binance, Futu) also support **bounded, mandate-gated order placement** behind the same safety model as Robinhood: a user-committed mandate (symbol universe / order size / exposure / leverage / daily cap), a filesystem kill switch, a fail-closed pre-trade gate, and a full audit ledger. **Longbridge is paper + read-only only** (its API exposes no runtime paper/live discriminator). Every paper/live distinction is a structural per-broker guard — account-id format, host separation, demo flag, or trade environment. New `trading_place_order` / `trading_cancel_order` tools; HK and A-share asset classes added to the mandate universe. Experimental / use at your own risk.
- **2026-06-01** 🚀 **v0.1.9 released** (`pip install -U vibe-trading-ai`): Rolls up everything since 0.1.8. Connector-first broker profiles (IBKR local read-only TWS / IB Gateway + Robinhood Agentic Trading behind OAuth, a committed mandate, order guard, audit ledger, and instant halt). Research Goal runtime across CLI / REST / MCP / Web. A swarm pass — live reconcile + MCP keepalive, operator-configured worker MCP tools, a strict alpha-bench random control, and a new `retry_run` to relaunch failed/stale runs (**36 MCP tools** now). The `agent/cli/` package refactor with a refreshed terminal UI, the `mootdx` no-token A-share loader, and a robustness pass across backtest / agent loop / sessions. `--version` now always matches the installed package, fixing the 0.1.8 drift ([#156](https://github.com/HKUDS/Vibe-Trading/issues/156)).
- **2026-05-31** 🔌 **Connector-first broker architecture (IBKR + Robinhood)**: Trading access now starts from a selectable connector profile instead of separate broker/live entry points. `vibe-trading connector list/use/check/account/positions/orders/quote/history` and the MCP `trading_*` tools share the same selected profile, where paper/live is an attribute of the connector. IBKR can be used immediately through a local read-only TWS / IB Gateway profile, while the official IBKR remote MCP path is seeded as an OAuth `mcp.read` probe until stable read tool names are available. Robinhood Agentic Trading remains the bounded live MCP connector behind OAuth, a committed mandate, order guard, audit ledger, and instant halt.
- **2026-05-30** 🧰 **Robustness pass — backtest, agent loop, sessions**: LLM-generated signal engines now pass pre-flight interface validation before instantiation, catching circular self-imports, a missing `generate()`, non-defaulted `__init__` args, and wrong return types with actionable JSON errors instead of raw tracebacks ([#149](https://github.com/HKUDS/Vibe-Trading/pull/149)); a follow-up routes source-level AST validation errors through the same clean JSON envelope. The agent loop no longer burns all 50 iterations into a `failed` status with no output — it mirrors the swarm worker's wrap-up nudge at 80% of the iteration budget and drops tool definitions on the last iteration to force a final text answer ([#148](https://github.com/HKUDS/Vibe-Trading/pull/148)), guarded to fire only mid-run so it never displaces research-goal context. Session message writes now `flush + fsync` each append so expensive AI responses survive a mid-write crash, and the read path skips corrupted JSONL lines (logging the first 200 chars for recovery) instead of 500-ing the whole `/messages` endpoint ([#147](https://github.com/HKUDS/Vibe-Trading/pull/147)). The Web composer also fixes IME Enter handling so a composition-confirming Enter no longer submits mid-word ([#146](https://github.com/HKUDS/Vibe-Trading/pull/146)).
- **2026-05-29** 🔐 **Robinhood Agentic Trading support (opt-in, bounded autonomy)**: Adds support for Robinhood Agentic Trading (remote MCP, OAuth). Off and read-only by default; the agent acts only inside a user-committed mandate (symbols / order size / exposure / leverage / daily cap), with a filesystem-level instant kill switch, preemptive flatten, mandate auto-expiry, a full audit ledger, and a persistent autonomous runner. No custody, no venue — the broker holds funds and executes; we only relay intent. Experimental / use at your own risk.
- **2026-05-28** 🧪 **Swarm safety + strict alpha gate + worker MCP**: Swarm DAG blocks downstream tasks when upstream fails ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145)). New `run_bench_strict()` adds a same-universe random control + OOS split to catch factors that just track market beta ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143), thanks @Soli22de). Swarm workers can call operator-configured external MCP servers, with trust boundary pinned ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142), thanks @shadowinlife).
- **2026-05-27** 📊 **mootdx A-share data source + output polish**: New `mootdx` loader speaks the native 通达信 TCP protocol for A-share OHLCV (no auth, no IP rate-limit, daily + intraday with 25-page walk-back pagination), slotting between tushare and akshare in the fallback chain ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107)). CCXT loader now reads `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` so Binance/OKX public data works from restricted networks ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126), thanks @ruok808). Final-answer rendering also dropped the ugly full-width `---` horizontal separators on CLI and Web: the system prompt now nudges the agent toward markdown tables and `##` headings, the CLI renderer strips standalone HRs as defense-in-depth, and the chat bubble hides any `<hr>` that slips through ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139), thanks @sdwxm188).
- **2026-05-26** ✅ **Research Goal lifecycle closure**: Goal mode now behaves like a real task runner: Web UI goal creation creates or binds the session and immediately sends the kickoff turn; active goals can be continued, edited, cancelled, and completed across Web/API/CLI/MCP; and the agent advances from the current goal snapshot (criteria, evidence, claims, open items) instead of only the original prompt. Covered-but-still-active goals now enter an audit/status update instead of stopping silently, with regression coverage across backend, CLI, MCP, and frontend events.

- **2026-05-25** 🧼 **Cleaner chat UI + composer workflow**: The Web UI keeps chat focused on the next action: upload, swarm, and research-goal modes now live behind the composer `+` menu instead of floating panels. Active context appears above the input as compact chips, and goal details expand inline only when needed. The UI also drops the old custom i18n layer in favor of direct English copy, gates Full Report cards to report-worthy runs, and hardens local dev startup/status reporting for reliable browser smoke tests.
- **2026-05-24** 🎯 **Research Goal runtime**: Added a session-scoped Research Goal layer across backend, CLI, API/MCP, SSE, and Web UI. Goals persist claims, acceptance criteria, evidence rows, budgets, and completion policy; agent tools can create goals and attach evidence; `/goal` gives the CLI a direct entry point; REST/MCP expose goal snapshots and evidence writes; SSE keeps chat clients fresh. Follow-up audit fixes locked down verified evidence, blocked live-trading risk tiers through agent tools, wired CLI-created goals into later turns, cleaned goal ledgers on session deletion, enabled replay-all, and fixed cross-session frontend races.
- **2026-05-23** 🖥️ **Interactive CLI refresh**: The terminal front door now opens with a larger Vibe-Trading banner, a cleaner prompt divider, prior-turn recap, post-run timing, and a Claude Code-style activity rail for live agent work. Tool calls, web/data fetches, shell-style actions, Markdown answers, and pipe tables render in a more readable transcript, while piped or non-TTY runs keep plain-text output for automation. Generated CLI screenshots are now treated as local artifacts instead of committed docs files, keeping the repository lighter.
- **2026-05-22** 🧭 **Swarm recovery + MCP keepalive**: Swarm status now reconciles from live task files on every read, so API/MCP/SSE/list views recover crashed or stale runs instead of showing permanent `running` snapshots. `run_swarm` sends MCP progress heartbeats while it polls, with a fixed first frame of `swarm_started run_id=<id>` for clients that reconnect after transport drops; workers now heartbeat through LLM streaming, grounding fetches, and tool execution. The stale-run reaper uses per-run thresholds and derives terminal status from task states, `SwarmTool` no longer cancels a still-running team just because its wait budget elapsed, and MCP clients can call `reap_stale_runs()` for explicit cleanup. Today's DX pass also refreshed provider default models and aligned CI syntax checks with the new `agent/cli/` package. 22 new regressions cover hydration, terminal recovery, stale reaping, keepalive cadence, env parsing, and heartbeat wiring; the full swarm/MCP suite is at 169 passed, 4 skipped.
- **2026-05-21** 🧱 **CLI package refactor**: `agent/cli.py` (3216 LOC) split into the `agent/cli/` package — interactive front door, slash router, Rich components, plus a `_legacy.py` shim that preserves every subcommand and re-exports every public symbol so `cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` keep working. New FastAPI middleware serves the SPA shell when a browser opens `/runs/{id}` or `/correlation` directly; same narrowing landed in the Vite dev proxy. Version unified via `cli/_version.py` (no more drift between `--version` and the banner), `python -m cli` restored via `__main__.py`, and the chat-gate narrowed so `chat --help` / `chat extra` reach legacy argparse instead of being swallowed by the REPL.
- **2026-05-20** 🔬 **Hypothesis Registry CLI**: Closes the CLI side of the Hypothesis Registry shipped backend-only on 2026-05-16. `vibe-trading hypothesis list` prints a Rich table or JSON (`--status` filter, `--limit`); `show <id>` renders a detail panel including linked run cards; `invalidate <id> --note "..."` flips status to `rejected` while preserving prior invalidation notes when `--note` is omitted. Honors the existing `VIBE_TRADING_HYPOTHESES_PATH` env override and adds a per-invocation `--path`. 22 new tests cover wiring, JSON output, status filter, limit, missing-id errors, and note persistence.
- **2026-05-19** ✨ **Live tool feedback + graceful cancel**: Long-running tools (backtests, large PDFs, swarm workers) no longer look frozen. Each tool call now emits a 3-second heartbeat plus structured per-stage progress — `run_backtest` shows phase markers (`validate` / `simulate` / `finalize`), `read_document` ticks per page on PDF or per sheet on Excel, `read_url` marks `fetch` / `parse`. The CLI Rich Live dashboard renders a Unicode spinner, ASCII progress bar, ETA, and stacks up to 3 parallel tools keyed by name; the frontend chat ships a new `ToolProgressIndicator` with rAF-coalesced renders, ARIA `role="status"` + hidden native `<progress>` for screen readers, and a determinate `ProgressRing` SVG when total is known. First `Ctrl+C` during a CLI run now calls `agent.cancel()` for graceful exit (current step finishes, trace closes cleanly); a second within 2s force-quits. Reusable primitives extracted along the way: `ProgressBar.tsx` and `lib/tools.ts` (shared tool-name i18n).
- **2026-05-18** 🧹 **Cleanup pass + three latent bug fixes**: `CompositeEngine` no longer misroutes bare Chinese-futures codes like `RB2410` to `GlobalFuturesEngine` — `_is_china_futures` moved into a shared `_market_hooks` module with a case-normalized product table and a non-CN exchange guard, plus 9 new regression cases. Session FTS5 indexes now persist timestamps so cross-session search can sort by date; the same path also fixed a re-upsert that was wall-clocking every session's `started_at`. The Vite dev-mode proxy gained the missing `/alpha` entry so the AlphaZoo page resolves on `npm run dev`. `tests/test_e2e_harness_v2.py` (real-LLM e2e suite) is now gated behind `VIBE_TRADING_RUN_LIVE_E2E=1` so CI no longer changes shape based on env-key presence. Ruff `per-file-ignores` added for the factor zoo (3783 → 0 F401 noise), frontend tsconfig enables `noUnusedLocals` / `noUnusedParameters` as regression guards, and 76 unused `vw = vwap(...)` boilerplate lines were dropped from `gtja191` alphas. Net **-918 LOC**.
- **2026-05-17** 🧬 **Alpha Zoo v1 (0.1.8)**: 452 pre-built quant alphas across 4 zoos — `qlib158` (Microsoft Qlib, Apache-2 attribution), `alpha101` (Kakushadze 101 Formulaic Alphas, paper rewrite from arXiv:1601.00991), `gtja191` (Guotai Junan 2014 short-horizon factor report), and `academic` (Fama-French 5 + Carhart price-based proxies). One-line CLI to bench any zoo on your universe: `vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`. Ships with AST purity gate, lookahead-guard test, `pytest-socket` network kill-switch, per-zoo LICENSE.md, and a Developer Certificate of Origin (DCO) workflow for community PRs. Auto-rendered Alpha Library at [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/) + research-lab post [Which of the 191 GTJA alphas still work in 2026?](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html).
- **2026-05-16** 🧪 **Research spine update**: Added a backend Hypothesis Registry with `create_hypothesis`, `update_hypothesis`, `link_backtest`, and `search_hypotheses`; external-content readers now attach warning-only `security_warnings`; and Shadow Account scanning now uses deterministic OHLCV feature evaluation instead of the old calendar-phase stub.
- **2026-05-15** 🪪 The run detail page now surfaces the Trust Layer run card alongside metrics and artifacts, completing the UI side of the `run_card.json` work landed on 2026-05-12. `PersistentMemory.add()` was also hardened on length, empty/whitespace-only names, and C0/C1 control bytes from the #108/#109/#110 triage ([#112](https://github.com/HKUDS/Vibe-Trading/pull/112), thanks @Teerapat-Vatpitak).
- **2026-05-14** 🌐 the public wiki is now live at [vibetrading.wiki](https://vibetrading.wiki/) with docs, tutorials, Research Lab, and Alpha Library sections deployed through Cloudflare Pages. Persistent memory is also inspectable from the CLI via `vibe-trading memory list/show/search/forget` ([#102](https://github.com/HKUDS/Vibe-Trading/pull/102), thanks @Teerapat-Vatpitak), and memory tokenization/slugs now support Thai, Arabic, Hebrew, and Cyrillic text ([#104](https://github.com/HKUDS/Vibe-Trading/pull/104)).
- **2026-05-13** 🧭 Swarm runs now ground workers with fetched market data and cleaner persisted reports ([#93](https://github.com/HKUDS/Vibe-Trading/pull/93), [#84](https://github.com/HKUDS/Vibe-Trading/pull/84)).
- **2026-05-12** 🧾 Backtests now emit `run_card.json` and `run_card.md` alongside artifacts for reproducible research runs.
- **2026-05-11** 🧭 **Memory slugs, swarm accounting, and CLI preflight**: Persistent memory now preserves CJK characters when generating file slugs, preventing silent filename collisions for Chinese/Japanese/Korean notes ([#95](https://github.com/HKUDS/Vibe-Trading/pull/95), thanks @voidborne-d). Swarm run totals now prefer provider-reported token usage with the existing estimate fallback ([#94](https://github.com/HKUDS/Vibe-Trading/pull/94), thanks @Teerapat-Vatpitak), and the CLI run UI gained a startup preflight check for common environment issues ([#96](https://github.com/HKUDS/Vibe-Trading/pull/96), thanks @ykykj).
- **2026-05-10** 🧱 **Regression guardrails + run metadata**: Memory recall now treats underscores as token boundaries, so snake_case saved memories such as `mcp_wiring_test` match natural-language queries like "mcp wiring" ([#87](https://github.com/HKUDS/Vibe-Trading/pull/87), thanks @hp083625). The MCP server has a subprocess smoke test covering initialize → `tools/list` → `tools/call` to guard the first-call deadlock path ([#86](https://github.com/HKUDS/Vibe-Trading/pull/86)), while low-risk hardening landed for Windows path-sensitive tests, API best-effort exception handling, backtest `run_dir` allowed-root validation, and SwarmRun provider/model metadata ([#88](https://github.com/HKUDS/Vibe-Trading/pull/88), [#90](https://github.com/HKUDS/Vibe-Trading/pull/90), [#91](https://github.com/HKUDS/Vibe-Trading/pull/91), [#92](https://github.com/HKUDS/Vibe-Trading/pull/92), thanks @Teerapat-Vatpitak).
- **2026-05-09** 🛡️ **API path hardening + MCP server stability**: API run/session routes now validate path IDs before lookup, rejecting malformed newline-containing parameters and pinning the behavior in the auth/security regression suite ([#80](https://github.com/HKUDS/Vibe-Trading/pull/80), thanks @SJoon99). The MCP server now pre-warms the tool registry on the main thread before serving `tools/call`, avoiding a first-call deadlock in lazy tool discovery ([#85](https://github.com/HKUDS/Vibe-Trading/pull/85), thanks @Teerapat-Vatpitak). The Vite dev proxy also honors `VITE_API_URL` for non-default backend targets ([#82](https://github.com/HKUDS/Vibe-Trading/pull/82), thanks @voidborne-d).
- **2026-05-08** 🧾 **Tushare statement fields in filters**: A-share daily backtests can now request PIT-safe financial statement fields through `fundamental_fields`, so signal engines can screen on `income_total_revenue`, `income_n_income`, `balancesheet_total_hldr_eqy_exc_min_int`, `fina_indicator_roe`, and similar table-prefixed columns after their announcement/disclosure dates ([#76](https://github.com/HKUDS/Vibe-Trading/pull/76), thanks @mrbob-git). Follow-up hardening makes explicit statement-field requests fail fast if Tushare enrichment cannot run, instead of silently falling back to raw price bars ([#77](https://github.com/HKUDS/Vibe-Trading/pull/77)).
- **2026-05-07** 📈 **Tushare fundamentals + community triage**: Added a point-in-time `TushareFundamentalProvider` contract for fundamental research workflows, with regression coverage for the project `TUSHARE_TOKEN` environment path ([#74](https://github.com/HKUDS/Vibe-Trading/pull/74)). Community triage also clarified that Vibe-Trading keeps rapid iteration focused on one UI language for now, avoids adding redundant search dependencies while DuckDuckGo-backed `web_search` is already bundled, and treats unofficial hosted deployments as untrusted places for API keys or data-source tokens.
- **2026-05-06** 🚀 **v0.1.7 released** ([Release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7), `pip install -U vibe-trading-ai`): Security-boundary hardening is now published on PyPI and ClawHub, covering safer API/read/upload/file/URL/generated-code/shell-tool/Docker defaults while keeping localhost CLI/Web UI workflows low-friction. This cycle also includes Web UI Settings, correlation heatmap, OpenAI Codex OAuth, A-share pre-ST filtering, interactive CLI UX, swarm preset inspection, dividend analysis, dev workflow polish, and audited frontend build-dependency floors. Thanks to the 0.1.7 contributors and to lemi9090 (S2W) for coordinated security validation.
- **2026-05-05** 🛡️ **Security boundary follow-up**: Completes the remaining security-boundary hardening around explicit CORS origins, Settings credential indicators, web URL reading, and Shadow Account code generation, with regression tests added for each path. Normal localhost CLI/Web UI workflows stay the same; remote deployments should continue using `API_AUTH_KEY` and explicit trusted origins.
- **2026-05-04** 🖥️ **Interactive CLI UX + CI cleanup**: Interactive mode now has a live bottom status bar showing provider/model, session duration, last-run latency, and cumulative tool-call stats, plus prompt history navigation and cursor editing with arrow keys via `prompt_toolkit` ([#69](https://github.com/HKUDS/Vibe-Trading/pull/69)). The CLI still falls back to Rich prompts when `prompt_toolkit` or a TTY is unavailable. CI path expectations were also aligned with the hardened file-import sandbox and cross-platform `/tmp` resolution, returning main to green ([`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)).
- **2026-05-03** 🛡️ **Security hardening patch**: Tightens default API authentication for non-local deployments, protects sensitive run/session/swarm reads, restricts upload and local file-reading boundaries, gates shell-capable tools by entry point, validates generated strategy loading before import, and runs the Docker image as a non-root user with a localhost-only published port by default. Local CLI and localhost Web UI workflows remain low-friction; remote API/Web deployments should set `API_AUTH_KEY`.
- **2026-05-02** 🧭 **Dividend analysis + sharper roadmap**: Added the `dividend-analysis` skill for income stocks, payout sustainability, dividend growth, shareholder yield, ex-dividend mechanics, and yield-trap checks, pinned by bundled-skill regression tests. The public roadmap now focuses on upcoming work: Research Autopilot, Data Bridge, Options Lab, Portfolio Studio, Alpha Zoo, Research Delivery, Trust Layer, and Community sharing.
- **2026-05-01** 🔥 **Correlation heatmap + OpenAI Codex OAuth + A-share pre-ST filter**: New correlation dashboard/API computes rolling return correlations and renders an ECharts heatmap for portfolio and symbol analysis ([#64](https://github.com/HKUDS/Vibe-Trading/pull/64)). OpenAI Codex provider support now uses ChatGPT OAuth via `vibe-trading provider login openai-codex`, with Settings metadata and adapter regression tests ([#65](https://github.com/HKUDS/Vibe-Trading/pull/65)). Added and hardened the `ashare-pre-st-filter` skill for A-share ST/*ST risk screening, including Sina penalty relevance filtering so securities-account mentions do not inflate E2 counts ([#63](https://github.com/HKUDS/Vibe-Trading/pull/63)).
- **2026-04-30** ⚙️ **Web UI Settings + validation CLI hardening**: New Settings page for LLM provider/model, base URL, reasoning effort, and data source credentials, backed by local/auth-protected settings APIs and data-driven provider metadata ([#57](https://github.com/HKUDS/Vibe-Trading/pull/57)). Also hardens `python -m backtest.validation <run_dir>` so missing, blank, malformed, non-existent, and non-directory inputs fail with clear operator-facing messages before validation starts ([#60](https://github.com/HKUDS/Vibe-Trading/pull/60)).
- **2026-04-28** 🚀 **v0.1.6 released** (`pip install -U vibe-trading-ai`): Fixes `vibe-trading --swarm-presets` returning empty after `pip install` / `uv tool install` ([#55](https://github.com/HKUDS/Vibe-Trading/issues/55)) — preset YAMLs now bundled inside the `src.swarm` package and pinned by a 6-test regression suite. Plus AKShare loader correctly routes ETFs (`510300.SH`) and forex (`USDCNH`) to the right endpoints with hardened registry fallback. Rolls up everything since v0.1.5: benchmark comparison panel, `/upload` streaming + size limits, Futu loader (HK + A-share), vnpy export skill, security hardening, frontend lazy loading (688KB → 262KB).
- **2026-04-27** 📊 **Benchmark panel + upload safety**: Backtest output now ships a benchmark comparison panel (ticker / benchmark return / excess return / information ratio) with yfinance-backed resolution for SPY, CSI 300, etc. ([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). Plus `/upload` streams the request body in 1 MB chunks and aborts past `MAX_UPLOAD_SIZE`, bounding memory under oversized/malformed clients ([#53](https://github.com/HKUDS/Vibe-Trading/pull/53)) — pinned by a 4-case regression suite.
- **2026-04-22** 🛡️ **Hardening + new integrations**: Path containment enforced in `safe_path` + journal/shadow tool sandbox, `MANIFEST.in` ships `.env.example` / tests / Docker files in sdist, route-level lazy loading shrinks frontend initial bundle 688KB → 262KB. Plus Futu data loader for HK & A-share equities ([#47](https://github.com/HKUDS/Vibe-Trading/pull/47)) and vnpy CtaTemplate export skill ([#46](https://github.com/HKUDS/Vibe-Trading/pull/46)).
- **2026-04-21** 🛡️ **Workspace + docs**: Relative `run_dir` normalized to active run dir ([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). README usage examples ([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).
- **2026-04-20** 🔌 **Reasoning + Swarm**: `reasoning_content` preserved across all `ChatOpenAI` paths — Kimi / DeepSeek / Qwen thinking work end-to-end ([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). Swarm streaming + clean Ctrl+C ([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).
- **2026-04-19** 📦 **v0.1.5**: Published to PyPI & ClawHub. `python-multipart` CVE floor bump, 5 new MCP tools wired (`analyze_trade_journal` + 4 shadow-account tools), `pattern_recognition` → `pattern` registry fix, Docker dep parity, SKILL manifest synced (22 MCP tools / 71 skills).
- **2026-04-18** 👥 **Shadow Account**: Extract your strategy rules from a broker journal → backtest the shadow across markets → 8-section HTML/PDF report showing exactly how much you leave on the table (rule violations, early exits, missed signals, counterfactual trades). 4 new tools, 1 skill, 32 tools total. Trade Journal + Shadow Account samples now live in the web UI welcome screen.
- **2026-04-17** 📊 **Trade Journal Analyzer + Universal File Reader**: Upload broker exports (同花顺/东财/富途/generic CSV) → auto trading profile (holding days, win rate, PnL ratio, drawdown) + 4 bias diagnostics (disposition effect, overtrading, chasing momentum, anchoring). `read_document` now dispatches PDF, Word, Excel, PowerPoint, images (OCR), and 40+ text formats behind one unified call.
- **2026-04-16** 🧠 **Agent Harness**: Persistent cross-session memory, FTS5 session search, self-evolving skills (full CRUD), 5-layer context compression, read/write tool batching. 27 tools, 107 new tests.
- **2026-04-15** 🤖 **Z.ai + MiniMax**: Z.ai provider ([#35](https://github.com/HKUDS/Vibe-Trading/pull/35)), MiniMax temperature fix + model update ([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). 13 providers.
- **2026-04-14** 🔧 **MCP Stability**: Fixed backtest tool `Connection closed` error on stdio transport ([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).
- **2026-04-13** 🌐 **Cross-Market Composite Backtest**: New `CompositeEngine` backtests mixed-market portfolios (e.g. A-shares + crypto) with shared capital pool and per-market rules. Also fixed swarm template variable fallback and frontend timeout.
- **2026-04-12** 🌍 **Multi-Platform Export**: `/pine` exports strategies to TradingView (Pine Script v6), TDX (通达信/同花顺/东方财富), and MetaTrader 5 (MQL5) in one command.
- **2026-04-11** 🛡️ **Reliability & DX**: `vibe-trading init` .env bootstrap ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19)), preflight checks, runtime data-source fallback, hardened backtest engine. Multi-language README ([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).
- **2026-04-10** 📦 **v0.1.4**: Docker fix ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8)), `web_search` MCP tool, 12 LLM providers, `akshare`/`ccxt` deps. Published to PyPI and ClawHub.
- **2026-04-09** 📊 **Backtest Wave 2**: ChinaFutures, GlobalFutures, Forex, Options v2 engines. Monte Carlo, Bootstrap CI, Walk-Forward validation.
- **2026-04-08** 🔧 **Multi-market backtest** with per-market rules, Pine Script v6 export, 5 data sources with auto-fallback.

</details>

---

## ✨ Key Features

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="Self-improving trading agent"/><br>
      <h3>🔍 Self-Improving Trading Agent</h3>
      <div align="left">
        • Natural-language market research<br>
        • Strategy drafts and file/web analysis<br>
        • Memory-backed workflows
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="Multi-agent trading teams"/><br>
      <h3>🐝 Multi-Agent Trading Teams</h3>
      <div align="left">
        • Investment, quant, crypto, and risk teams<br>
        • Streaming progress and persisted reports<br>
        • Workers grounded with fetched market data
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="Cross-market data and backtesting"/><br>
      <h3>📊 Cross-Market Data & Backtesting</h3>
      <div align="left">
        • A/HK/US equities, crypto, futures, and forex<br>
        • Data fallback and composite backtests<br>
        • PIT data, validation, and run cards
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • Broker-journal behavior diagnostics<br>
        • Rule-based Shadow Account comparisons<br>
        • Exportable audit reports and strategy code
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 What Is Vibe-Trading?

Vibe-Trading is an open-source research workspace for turning finance questions into runnable analysis. It connects natural-language prompts to market-data loaders, strategy generation, backtest engines, reports, exports, and persistent research memory.

It is designed for research, simulation, and backtesting — and, when you choose, autonomous trading through a broker you authorize yourself (e.g. Robinhood Agentic Trading). It holds no funds and never trades outside the limits you set, and you can halt it instantly.

---

## ✨ What You Can Do

| Task | Output |
|------|--------|
| **Ask a trading question** | Market research with tools, data, documents, and reusable session context. |
| **Backtest a strategy idea** | Strategy code, metrics, benchmark context, validation artifacts, and run cards. |
| **Review your own trades** | Broker-journal parsing, behavior diagnostics, rule extraction, and Shadow Account comparisons. |
| **Read documents & charts** | Parse PDF / DOCX / XLSX / PPTX / images with pluggable OCR (`read_document`), and read chart screenshots semantically with a vision model (`analyze_image`). |
| **Improve repeated research** | Persistent memory and editable skills turn useful routines into reusable workflows. |
| **Run analyst teams** | Multi-agent research reviews for investment, quant, crypto, macro, and risk workflows. |
| **Put research into IM channels** | Run the same session runtime through WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Teams, email, and Mochat with CLI, REST, and Web UI controls. |
| **Ship usable artifacts** | Reports, TradingView Pine Script, TDX, MetaTrader 5, MCP tools, and later research sessions. |
| **Bench a pre-built alpha zoo** | One-line IC + alive/reversed/dead categorisation across 462 alphas (Qlib 158 + Kakushadze 101 + GTJA 191 + academic + PIT-safe fundamental) on your universe. |
| **Spot correlation regimes** | An edge-density + hysteresis timeline on the `/correlation` surface showing when markets fuse into one bloc — descriptive risk context, not a signal. |

---

## ⚡ Quick Example

```bash
pip install vibe-trading-ai

# Natural-language research
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# Bench a pre-built alpha zoo (one line)
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 👥 Shadow Account

Shadow Account starts from your own trading records instead of a generic strategy template.

Upload a broker export, let the agent summarize your behavior, then compare the actual trading path with a rule-based shadow strategy.

| Step | Agent output |
|------|--------------|
| **1. Read your journal** | Parses broker exports from 同花顺, 东方财富, 富途, and generic CSV formats. |
| **2. Profile your behavior** | Holding days, win rate, PnL ratio, drawdown, disposition effect, overtrading, momentum chasing, and anchoring checks. |
| **3. Extract your rules** | Turns recurring entries/exits into an explicit strategy profile instead of a hand-wavy summary. |
| **4. Run the shadow** | Backtests the extracted rules and highlights rule breaks, early exits, missed signals, and alternative trade paths. |
| **5. Deliver the report** | Produces an HTML/PDF report that can be inspected, archived, or refined in a later session. |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 🧪 Research Workflow

Most runs follow the same evidence path: route the request, load the right market context, execute tools, validate outputs, and keep the artifacts inspectable.

| Layer | What happens |
|-------|--------------|
| **Plan** | Selects the relevant finance skills, tools, data sources, and swarm preset when useful. |
| **Ground** | Pulls A-shares, HK/US equities, crypto, futures, forex, documents, or web context through the available loaders. |
| **Execute** | Generates testable strategy code, runs tools, and uses the matching backtest engine or analysis workflow. |
| **Validate** | Adds metrics, benchmark comparison, Monte Carlo, Bootstrap, Walk-Forward, run cards, and warnings where applicable. |
| **Deliver** | Returns reports, artifacts, tool traces, and exports for TradingView, TDX, MetaTrader 5, MCP clients, or later sessions. |

---

## 📡 Data Sources & Smart Fallback

One `get_market_data` call, **22 free market-data sources** (plus the optional **QVeris** premium marketplace). Set `source: "auto"` — the loader picks by symbol, then walks a per-market chain ordered by **IP-ban risk**: never-banned public sources first, throttled / key-gated ones last. Zero config, no single point of failure.

| Source | Markets | Auth | Role |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share | none | never IP-banned (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / US / HK | none | OHLCV + deep fundamentals & flow tools (throttled) |
| `baostock` · `akshare` | A (+ US/HK/futures/macro/fx) | none | free fallbacks |
| `tushare` | A / futures / fund / macro | token | richest A-share |
| `yahoo` · `sina` · `stooq` | US (/HK) | none | direct chart/quotes/options · K-line to 1984 · EOD CSV |
| `yfinance` | US / HK | none | wrapper |
| `longbridge` | US / HK | App Key + App Secret + Access Token | optional historical OHLCV source; install the optional SDK |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | US | key | optional providers |
| `qveris` | global multi-asset | key · credits | **premium marketplace** — 63+ providers via one key (explicit-only, never in auto fallback) |
| `okx` · `ccxt` · `binance` | crypto | none | OKX + 100+ exchanges + Binance historical / USD-M perps |
| `futu` | HK / A | OpenD | optional local FutuOpenD |
| `mt5` | forex / metals | MT5 terminal | MetaTrader 5 (Exness-style) forex / metal bars, 1m–1D |
| `india_broker` | India (NSE/BSE) | broker login | read-only Shoonya / Dhan bars for `.NS` / `.BO` (fallback-chain tail) |
| `local` | any | none | your own CSV / Parquet / DuckDB via `local:` prefix |

**Fallback chains (by IP-ban risk):**

- **A-share** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **US** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `longbridge` · `akshare` · `local`
- **HK** → `eastmoney` · `yahoo` · `futu` · `yfinance` · `akshare` · `longbridge` · `local`
- **India (NSE/BSE)** → `yahoo` · `yfinance` · `india_broker` · `local`
- **Crypto** → `okx` · `ccxt` · `binance` · `yfinance` · `local`
- **Forex / metals** → `mt5` · `yfinance` · `akshare` · `local` &nbsp;·&nbsp; *(futures / fund / macro → `tushare`/`akshare` → `local`)*

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

Beyond OHLCV, **18 read-only data tools** reach into fundamentals & flow — fund flow, dragon-tiger, northbound, margin, block trades, shareholder count, lockup, sector, research reports, news, SEC filings, financial statements, options chains, institutional holdings, market screening, symbol search, and macro — all exposed over MCP. An explicit `local:` symbol never silently falls back to a network source.

<!-- QVERIS-START -->
### 💎 Optional premium data — QVeris

<img src="https://www.qveris.com/logo-color.png" alt="QVeris" height="36">

**Data: free routing or premium, your choice.** Free stays the default: 22 built-in sources with ban-risk fallback, no key, no cost. Premium via QVeris adds 10,000+ capabilities (per QVeris) across 63+ providers for options Greeks, premium fundamentals, China/HK/global data, macro, crypto, news, and filings; failed calls are not charged. Enable it in Settings -> QVeris or `vibe-trading data mode paid`.

*QVeris disclosure: [signing up through the Vibe-Trading referral link](https://qveris.ai/?ref=Vyjjo5G_1cAHJA) gets you **+1,000 bonus credits** and supports the project.*
<!-- QVERIS-END -->

---

## 🔩 Detailed Capabilities

Detailed inventories are folded below to keep the main README scannable. Open them when you want to inspect the available building blocks.

<details>
<summary><b>Finance Skill Library</b> <sub>88 skills across 9 categories</sub></summary>

- 📊 88 specialized finance skills organized into 9 categories
- 🌐 Complete coverage from traditional markets to crypto & DeFi
- 🔬 Comprehensive capabilities spanning data sourcing to quantitative research

| Category | Skills | Examples |
|----------|--------|----------|
| Data Source | 10 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar`, `qveris` |
| Strategy | 19 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 22 | `factor-research`, `correlation-regime`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 8 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `trade-journal` |
| Research | 2 | `alpha-zoo`, `strategy-dev-manager` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

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
<summary><b>Broker Connectors</b> <sub>12 brokers — read + paper, bounded-live where supported</sub></summary>

Connector-first profiles. Each does read + paper-account order placement; live order placement is bounded by a user-defined mandate (symbol allowlist, order-size / exposure caps, daily trade cap, instant kill switch) and never holds funds — the broker executes. Order-placing tools stay off MCP (agent + CLI only). Research / backtest paths are structurally barred from any live endpoint.

| Broker | Markets | Capabilities |
|--------|---------|--------------|
| **IBKR** | global | local TWS / Gateway, read-only |
| **Robinhood** | US | Agentic MCP (desktop OAuth) — read + bounded live |
| **Tiger** | US / HK / A | read + paper + bounded live |
| **Alpaca** | US | read + paper + bounded live (+ TAP credential-isolation mode) |
| **OKX** · **Binance** | crypto | read + paper + bounded live |
| **Futu** | HK / US / A | read + paper + bounded live |
| **MetaTrader 5** | forex / CFD | read + paper + bounded live (Exness-style; demo ⇔ paper identity guard) |
| **Longbridge** · **Dhan** · **Shoonya** | US / HK · India (NSE/BSE) | read + paper only — no runtime paper/live discriminator, so live order placement is hard-refused |
| **Trading 212** | UK / EU | fully read-only — `place_order` / `cancel_order` hard-refuse even paper |

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
<summary><b>Alpha Zoo</b> <sub>462 pre-built quant alphas across 5 families</sub></summary>

- 🧬 462 cross-sectional alphas, lookahead-banned at the operator layer
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
| **fundamental** | 4 | PIT-safe SEC company facts — earnings yield, ROE, gross profitability, asset growth (filed-date anchored) | Public financial data |

Run `vibe-trading alpha list` to browse, `vibe-trading alpha show <id>` for formulas + source, `vibe-trading alpha bench --zoo X --universe Y --period Z` to score a whole zoo, and `vibe-trading alpha compare --all` to rank zoos side by side.

</details>

<details>
<summary><b>Backtest Engines</b> <sub>8 engines + options portfolio, cross-market composite</sub></summary>

| Engine | Market | Notes |
|--------|--------|-------|
| **ChinaA** | A-share | T+1, price limits, pre-ST filter |
| **GlobalEquity** | US / HK | T+0 |
| **IndiaEquity** | India (NSE/BSE) | T+1, circuit bands, config-driven STT / stamp / SEBI / GST cost stack |
| **Crypto** | crypto spot / USD-M perps | funding settlements, execution/mark split |
| **ChinaFutures** · **GlobalFutures** | futures | margin, contract multipliers |
| **Forex** | FX / metals | via the `mt5` loader |
| **Composite** | cross-market | one shared capital pool across markets (`source="auto"`) |
| **options_portfolio** | options | multi-leg, Greeks, payoff/scenario |

Intraday bars: 1m / 5m / 15m / 30m / 1H / 4H / 1D. 15 metrics + benchmark comparison, **5 portfolio optimizers** (equal-volatility / risk-parity / mean-variance / max-diversification / turnover-aware), and 3 validation tools (Monte Carlo / Bootstrap / Walk-Forward).

</details>

## 🎬 Demo

<div align="center">
<table>
<tr>
<td width="50%">

https://github.com/user-attachments/assets/4e4dcb80-7358-4b9a-92f0-1e29612e6e86

</td>
<td width="50%">

https://github.com/user-attachments/assets/3754a414-c3ee-464f-b1e8-78e1a74fbd30

</td>
</tr>
<tr>
<td colspan="2" align="center"><sub>☝️ Natural-language backtest & multi-agent swarm debate — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 Quick Start

### One-line install (PyPI)

```bash
pip install vibe-trading-ai
```

Then run a first research task:

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **Upgrading from an older version?** 0.1.10 moved to LangChain 1.x. If imports break after `pip install -U vibe-trading-ai` over a pre-0.1.10 install (e.g. langgraph fails to import), recreate the venv or run `pip install --force-reinstall vibe-trading-ai`. A fresh install is unaffected.

> **Package name vs commands:** The PyPI package is `vibe-trading-ai`. Once installed, you get three commands:
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | Interactive CLI / TUI |
> | `vibe-trading serve` | Launch FastAPI web server |
> | `vibe-trading-mcp` | Start MCP server (for Claude Desktop, OpenClaw, Cursor, etc.) |

```bash
vibe-trading init              # interactive .env setup
vibe-trading                   # launch CLI
vibe-trading serve --port 8899 # launch web UI
vibe-trading-mcp               # start MCP server (stdio)
```

### Or choose a path

| Path | Best for | Time |
|------|----------|------|
| **A. Docker** | Try it now, zero local setup | 2 min |
| **B. Local install** | Development, full CLI access | 5 min |
| **C. MCP plugin** | Plug into your existing agent | 3 min |
| **D. ClawHub** | One command, no cloning | 1 min |

### Prerequisites

- An **LLM API key** from any supported provider — or run locally with **Ollama** (no key needed)
- **Python 3.11+** for Path B
- **Docker** for Path A
- OpenAI Codex can also be used with ChatGPT OAuth: set `LANGCHAIN_PROVIDER=openai-codex`, then run `vibe-trading provider login openai-codex`. This does not use `OPENAI_API_KEY`.

> **Supported LLM providers:** OpenRouter, Requesty, OpenAI, Anthropic (native Messages API), DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, SiliconFlow (CN + Global), Xiaomi MIMO, iFlytek Spark, Z.ai, NVIDIA NIM, Ollama (local). When no `*_BASE_URL` is set, each provider falls back to its canonical endpoint, so just a key is enough. See `.env.example` for config.

> **Tip:** All markets work without any API keys thanks to automatic fallback. yfinance (HK/US), OKX (crypto), mootdx (A-shares, TCP-direct, no IP throttle), and AKShare (A-shares, US, HK, futures, forex) are all free. Tushare token is optional — mootdx is the preferred no-token A-share fallback, with AKShare as a broader backup.

### Path A: Docker (zero setup)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

Open `http://localhost:8899`. Backend + frontend in one container.

Docker publishes the backend on `127.0.0.1:8899` by default and runs the app as a non-root container user. If you intentionally expose the API beyond your own machine, set a strong `API_AUTH_KEY` and send `Authorization: Bearer <key>` from clients.

> [!NOTE]
> **Using Ollama with Docker:** the container reaches a host-side Ollama via `host.docker.internal`, not `localhost` (inside the container `localhost` is the container itself). `docker-compose.yml` defaults `OLLAMA_BASE_URL` to `http://host.docker.internal:11434`; export `OLLAMA_BASE_URL` (or set it in a top-level `.env`) to point elsewhere. This relies on the `host-gateway` mapping in `extra_hosts`, which requires **Docker Engine ≥ 20.10 / Compose v2** (provided automatically on Docker Desktop).

Your data survives updates: persistent memory, the cross-session search index, user-created skills, shadow accounts, broker connector config, web sessions, backtest runs, swarm history, and uploads all live in named Docker volumes, so `git pull && docker compose up --build` keeps them. They are deleted only by `docker compose down -v`.

### Path B: Local install

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

<details>
<summary><b>Start web UI (optional)</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev
```

Open `http://localhost:5899`. The frontend proxies API calls to `localhost:8899`.

**Production mode (single server):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

> [!NOTE]
> `vibe-trading serve` binds `0.0.0.0` and is loopback-only by default: opening the UI on the **same machine** (`http://localhost:8899`) works with zero config. If you browse from **another machine, a VM host, or a phone on your LAN**, sensitive endpoints return `403` and the chat shows "Remote API access requires an API key" — set a strong `API_AUTH_KEY` in `agent/.env`, restart, and enter the same key once in **Settings**. (Docker Desktop's host gateway: set `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` with the default `127.0.0.1` port bind.)

</details>

### Path C: MCP plugin

See [MCP Plugin](#-mcp-plugin) section below.

### Path D: ClawHub (one command)

```bash
npx clawhub@latest install vibe-trading --force
```

The skill + MCP config is downloaded into your agent's skills directory. See [ClawHub install](#-mcp-plugin) for details.

---

## 🧠 Environment Variables

Copy `agent/.env.example` to `agent/.env` and uncomment the provider block you want. Each provider needs 3-4 variables:

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Yes | Provider name (`openrouter`, `deepseek`, `groq`, `ollama`, etc.) |
| `<PROVIDER>_API_KEY` | Yes* | API key (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, etc.) |
| `<PROVIDER>_BASE_URL` | Yes | API endpoint URL |
| `LANGCHAIN_MODEL_NAME` | Yes | Model name (e.g. `deepseek-v4-pro`) |
| `TUSHARE_TOKEN` | No | Tushare Pro token for A-share data (falls back to AKShare) |
| `TIMEOUT_SECONDS` | No | LLM call timeout, default 120s |
| `API_AUTH_KEY` | Recommended for network deployments | Bearer token required when the API is reachable from non-local clients |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | No | Explicit opt-in for shell-capable tools in remote API/MCP-SSE style deployments |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | No | Extra comma-separated roots for document and broker-journal imports |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | No | Extra comma-separated roots for generated-code run directories |
| `CONTENT_FILTER_WARNING_THRESHOLD` | No | Content-filter warning ratio threshold (default 0.05 = 5%). When the ratio of LLM responses blocked by content moderation exceeds this, the run card warns you to switch providers. |

<sub>* Ollama does not require an API key. OpenAI Codex uses ChatGPT OAuth and stores tokens via `oauth-cli-kit`, not in `agent/.env`.</sub>

**Free data (no key needed):** A-shares via AKShare, HK/US equities via yfinance, crypto via OKX, 100+ crypto exchanges via CCXT. The system automatically selects the best available source for each market.

### 🎯 Recommended Models

Vibe-Trading is a tool-heavy agent — skills, backtests, memory, and swarms all flow through tool calls. Model choice directly decides whether the agent *uses* its tools or fabricates answers from training data.

| Tier | Examples | When to use |
|------|----------|-------------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | Complex swarms (3+ agents), long research sessions, paper-grade analysis |
| **Sweet spot** (default) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | Daily driver — reliable tool-calling at ~1/10 the cost |
| **Avoid for agent use** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | Tool-calling is unreliable — the agent will appear to "answer from memory" instead of loading skills or running backtests |

The default `agent/.env.example` ships with DeepSeek official API + `deepseek-v4-pro`; OpenRouter users can use `deepseek/deepseek-v4-pro`.

---

## 🖥 CLI Reference

The interactive TUI (`vibe-trading`) now uses a terminal-native transcript: a startup banner, prompt rule, previous-turn recap, live activity rail, Markdown/table rendering, and run timing all stay in the CLI. Non-interactive invocations such as `vibe-trading run`, pipes, and `--json` remain script-friendly.

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # browse 462 pre-built alphas; show / bench / compare / export-manifest sub-commands available
vibe-trading channels status --local  # inspect IM channel config and install hints
vibe-trading provider doctor  # print redacted provider/proxy/package diagnostics
```

<details>
<summary><b>Slash commands inside TUI</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/skills` | List all 88 finance skills |
| `/swarm` | List 30 swarm team presets |
| `/swarm run <preset> [vars_json]` | Run a swarm team with live streaming |
| `/swarm list` | Swarm run history |
| `/swarm show <run_id>` | Swarm run details |
| `/swarm cancel <run_id>` | Cancel a running swarm |
| `/list` | Recent runs |
| `/show <run_id>` | Run details + metrics |
| `/code <run_id>` | Generated strategy code |
| `/pine <run_id>` | Export indicators (TradingView + TDX + MT5) |
| `/trace <run_id>` | Full execution replay |
| `/continue <run_id> <prompt>` | Continue a run with new instructions |
| `/sessions` | List chat sessions |
| `/settings` | Show runtime config |
| `/clear` | Clear screen |
| `/quit` | Exit |

</details>

<details>
<summary><b>Single run & flags</b></summary>

```bash
vibe-trading run -p "Backtest BTC-USDT MACD strategy, last 30 days"
vibe-trading run -p "Analyze AAPL momentum" --json
vibe-trading run -f strategy.txt
echo "Backtest 000001.SZ RSI" | vibe-trading run
```

```bash
vibe-trading -p "your prompt"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # Export indicators (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

```bash
vibe-trading alpha list --zoo gtja191 --limit 10
vibe-trading alpha show gtja191_171
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

</details>

<details>
<summary><b>IM channels</b></summary>

IM channel adapters connect outside chat apps to the same session runtime used by the Web UI and CLI. Configure enabled adapters under `channels` in `~/.vibe-trading/agent.json`; SDK-backed adapters are optional extras, and missing SDKs report recovery hints instead of crashing the runtime.

For long-running channel tasks, tune the central assistant-reply wait budget with `replyTimeoutS` (seconds, default `600`):

```json
{
  "channels": {
    "replyTimeoutS": 1800,
    "feishu": {
      "enabled": true
    }
  }
}
```

This controls how long the shared channel runtime waits for the agent session to produce an assistant message; adapter HTTP/socket timeouts remain adapter-specific.

```bash
vibe-trading channels status --local   # inspect config and missing SDK hints without API
vibe-trading channels status           # query the running API runtime
vibe-trading channels start            # start enabled adapters through the API
vibe-trading channels stop             # stop enabled adapters through the API
vibe-trading channels login weixin     # run an adapter login hook when needed
vibe-trading channels pairing --channel telegram list
```

The built-in adapters cover `websocket`, `telegram`, `slack`, `discord`, `matrix`, `whatsapp`, `signal`, `qq`, `napcat`, `weixin`, `wecom`, `feishu`, `dingtalk`, `msteams`, `email`, and `mochat`. Use narrow extras such as `pip install "vibe-trading-ai[telegram]"`, or install the full channel set with `pip install "vibe-trading-ai[channels]"`.

**In-chat slash commands** (channel-agnostic, work in all 16 adapters):

| Command | Description |
|---------|-------------|
| `/new` | Reset the current session — the next message starts a fresh conversation |
| `/reset` | Alias for `/new` |
| `/newsession` | Alias for `/new` |
| `/pairing list` | Show pending sender-pairing requests (operators only) |

Commands are case-insensitive and must be sent as the entire message (e.g. `hello /new` is treated as a regular message, not a reset).

> **`/pairing` is operator-gated.** In-chat pairing-control commands are rejected unless the sender is listed as an operator — set `channels.operators` (cross-channel authority) or a channel section's own `operators` list in your channels config. With no operators configured, in-chat `/pairing` is refused (fail-closed) and pairing is managed only through the authenticated CLI (`vibe-trading channels pairing …`) and the auth-gated REST endpoint. This prevents any allow-listed group member from taking over pairing across channels.

</details>

---

## 💡 Examples

### Strategy & Backtesting

```bash
# Moving average crossover on US equities
vibe-trading run -p "Backtest a 20/50-day moving average crossover on AAPL for the past year, show Sharpe ratio and max drawdown"

# RSI mean-reversion on crypto
vibe-trading run -p "Test RSI(14) mean-reversion on BTC-USDT: buy below 30, sell above 70, last 6 months"

# Multi-factor strategy on A-shares
vibe-trading run -p "Backtest a momentum + value + quality multi-factor strategy on CSI 300 constituents over 2 years"

# After backtesting, export to TradingView / TDX / MetaTrader 5
vibe-trading --pine <run_id>
```

**Bench a pre-built alpha zoo** (one line):
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**Browse the catalogue** and inspect a single alpha:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**Compose a multi-factor signal** from the zoo (Python):
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

### Market Research

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Swarm Workflows

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"topic": "Is TSLA a buy at current levels?"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'
```

### Cross-Session Memory

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### Upload & Analyze Documents

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

## 🌐 API Server

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | List runs |
| `GET` | `/runs/{run_id}` | Run details |
| `GET` | `/runs/{run_id}/pine` | Multi-platform indicator export |
| `POST` | `/sessions` | Create session |
| `POST` | `/sessions/{id}/messages` | Send message |
| `GET` | `/sessions/{id}/events` | SSE event stream |
| `POST` | `/upload` | Upload PDF/file |
| `GET` | `/swarm/presets` | List swarm presets |
| `POST` | `/swarm/runs` | Start swarm run |
| `GET` | `/swarm/runs/{id}/events` | Swarm SSE stream |
| `GET` | `/alpha/list` | List alphas (filter by zoo/theme/universe) |
| `GET` | `/alpha/{alpha_id}` | Alpha metadata + source code |
| `POST` | `/alpha/bench` | Start a bench job (returns `job_id`) |
| `GET` | `/alpha/bench/{job_id}/stream` | SSE progress stream |
| `GET` | `/settings/llm` | Read Web UI LLM settings |
| `PUT` | `/settings/llm` | Update local LLM settings |
| `GET` | `/settings/data-sources` | Read local data source settings |
| `PUT` | `/settings/data-sources` | Update local data source settings |
| `GET` | `/channels/status` | Read IM channel runtime and adapter status |
| `POST` | `/channels/start` | Start configured IM channel adapters |
| `POST` | `/channels/stop` | Stop configured IM channel adapters |
| `POST` | `/channels/pairing/command` | Run a sender-pairing command against the shared store |
| `POST` | `/scheduled-runs` | Create a scheduled research job (interval-ms or cron) |
| `GET` | `/scheduled-runs` | List scheduled jobs |
| `DELETE` | `/scheduled-runs/{job_id}` | Cancel a scheduled job |

Interactive docs: `http://localhost:8899/docs`

### Security defaults

For localhost development, `vibe-trading serve` keeps the browser workflow simple. For any non-local client, sensitive API endpoints require `API_AUTH_KEY`; use `Authorization: Bearer <key>` for JSON/upload requests. Browser EventSource streams are handled by the Web UI after you enter the same key once in Settings.

Shell-capable tools (`bash` / `background_run`) are enabled only for the interactive local CLI. Every other surface — the HTTP/SSE API and the MCP server on **all** transports (stdio included) — keeps them off unless you explicitly opt in with `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` (or pass `--enable-shell-tools` to `vibe-trading-mcp`). Transport type never implicitly grants shell access. Document and journal readers are limited to upload/import roots by default; place files under `agent/uploads`, `agent/runs`, `./uploads`, `./data`, `~/.vibe-trading/uploads`, or `~/.vibe-trading/imports`, or add a dedicated directory through `VIBE_TRADING_ALLOWED_FILE_ROOTS`.

Generated backtest code runs as a local Python subprocess and can make network requests through the configured market-data loaders. Its environment is intentionally narrow: the runner keeps OS/Python basics, proxy/certificate settings, `VIBE_TRADING_ALLOWED_RUN_ROOTS`, and read-only market-data keys such as `TUSHARE_TOKEN`, `FMP_API_KEY`, `FRED_API_KEY`, and `VIBE_TRADING_IWENCAI_KEY`. It does not pass LLM provider keys, API auth tokens, shell-tool switches, broker trading secrets, or live/advisory toggles to generated strategy code by default.

### Web UI Settings

The Web UI Settings page lets local users update the LLM provider/model, base URL, generation parameters, reasoning effort, and optional market data credentials such as the Tushare token. Settings are persisted to `agent/.env`; provider defaults are loaded from `agent/src/providers/llm_providers.json`.

Settings reads are side-effect free: `GET /settings/llm` and `GET /settings/data-sources` never create `agent/.env`, and they only return project-relative paths. Settings reads and writes can expose credential state or update credentials/runtime environment, so they require `API_AUTH_KEY` when configured. If `API_AUTH_KEY` is unset for dev mode, settings access is accepted only from loopback clients.

The same Settings page includes an **IM Channels** panel for local operators. It polls `/channels/status`, shows configured/enabled/available/loaded/running states, surfaces adapter recovery hints, and can start or stop the configured channel runtime without going back to the terminal.

### Scheduled research

Run a research prompt or backtest on a repeating schedule. The background executor is **off by default** — start the server with `VIBE_TRADING_ENABLE_SCHEDULER=1` to enable it:

```bash
VIBE_TRADING_ENABLE_SCHEDULER=1 vibe-trading serve --port 8899
```

Then create jobs over REST. `schedule` is either a bare integer (interval in **milliseconds**) or a 5-field cron expression (`min hour dom mon dow`):

```bash
# every 6 hours (cron)
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Scan CSI300 for momentum breakouts and backtest the top 5","schedule":"0 */6 * * *"}'

# list / cancel
curl http://localhost:8899/scheduled-runs
curl -X DELETE http://localhost:8899/scheduled-runs/<job_id>
```

Each fire runs the `prompt` through a fresh agent session (optional backtest parameters go in `config`), and jobs persist under `~/.vibe-trading/` so they survive restarts. Without the flag, the `/scheduled-runs` endpoints still record jobs but nothing fires. Add `-H "Authorization: Bearer <key>"` to each call when `API_AUTH_KEY` is set.

---

## 🔌 MCP Plugin

Vibe-Trading exposes 54 MCP tools for any MCP-compatible client. Runs as a stdio subprocess — no server setup needed. Core research tools work with zero API keys for HK/US/crypto; trading connector tools use the selected connector profile, and `run_swarm` needs an LLM key.

<details>
<summary><b>Claude Desktop</b></summary>

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

</details>

<details>
<summary><b>OpenClaw</b></summary>

Add to `~/.openclaw/config.yaml`:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

For a first research-only smoke test, confirm tool discovery and run a market
data or backtest request before selecting a trading connector profile. Core
research tools can run without broker credentials; connector-backed `trading_*`
tools should be used only after you intentionally select and check a connector
profile. `run_swarm` requires an LLM key.

</details>

<details>
<summary><b>Cursor / Windsurf / other MCP clients</b></summary>

```bash
vibe-trading-mcp                   # stdio (default)
vibe-trading-mcp --transport http  # Streamable HTTP (current MCP spec default) at http://127.0.0.1:8900/mcp
vibe-trading-mcp --transport sse   # legacy SSE (deprecated) for older clients
```

For HTTP clients (QwenPaw, and any client that negotiates by POSTing an
`InitializeRequest`), use `--transport http` and point the client at the single
`/mcp` endpoint — e.g. `http://127.0.0.1:8900/mcp`. Do **not** point an HTTP
client at `/sse`; that path belongs to the deprecated two-endpoint SSE transport
and will return `405 Method Not Allowed` on `POST`. Override the bind address
with `--host` / `--port`.

</details>

**MCP tools exposed (54):** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`.

### SWARM external MCP tools

`run_swarm` workers can call operator-approved tools from external MCP servers. Configure the server-side allowlist in `VIBE_TRADING_SWARM_AGENT_CONFIG`, `~/.vibe-trading/swarm-agent.json`, or the fallback `~/.vibe-trading/agent.json`; then list remote tools in a swarm preset using the local MCP wrapper name, such as `mcp_internal_kb_search`. Caller-provided `variables` stay template data only and cannot inject MCP URLs, commands, environment variables, or allowlist overrides.

<details>
<summary><b>Install from ClawHub (one command)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` is required because the skill references external APIs, which triggers VirusTotal's automated scan. The code is fully open-source and safe to inspect.

This downloads the skill + MCP config into your agent's skills directory. No cloning needed.

Browse on ClawHub: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — self-evolving skills</b></summary>

All 88 finance skills are published on [open-space.cloud](https://open-space.cloud) and evolve autonomously through OpenSpace's self-evolution engine.

To use with OpenSpace, add both MCP servers to your agent config:

```json
{
  "mcpServers": {
    "openspace": {
      "command": "openspace-mcp",
      "toolTimeout": 600,
      "env": {
        "OPENSPACE_HOST_SKILL_DIRS": "/path/to/vibe-trading/agent/src/skills",
        "OPENSPACE_WORKSPACE": "/path/to/OpenSpace"
      }
    },
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

OpenSpace will auto-discover all 88 skills, enabling auto-fix, auto-improve, and community sharing. Search for Vibe-Trading skills via `search_skills("finance backtest")` in any OpenSpace-connected agent.

</details>

---

## 🔌 Loading Tools from External MCP Servers (MCP Client Mode)

> **This is the opposite direction from the MCP Plugin above.**
> The MCP Plugin lets *other* agents call Vibe-Trading tools.
> This section lets the *built-in* Vibe-Trading agent call tools from *your* external MCP servers.

### Quick start

Create `~/.vibe-trading/agent.json`:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-mcp-server"]
    }
  }
}
```

Run any CLI command — tools from ordinary external servers are automatically injected into the agent's registry after local tools:

```bash
vibe-trading run "use my-server to do X"
```

### Official IBKR MCP read-only probe

Vibe-Trading can connect directly to Interactive Brokers' official remote MCP
endpoint in read-only mode. Add this to `~/.vibe-trading/agent.json`:

```json
{
  "mcpServers": {
    "ibkr": {
      "type": "streamableHttp",
      "url": "https://api.ibkr.com/v1/api/mcp",
      "auth": {
        "type": "oauth",
        "scopes": ["mcp.read"],
        "clientName": "Vibe-Trading",
        "cacheDir": "~/.vibe-trading/live/ibkr/oauth"
      },
      "enabledTools": ["*"]
    }
  }
}
```

Then start the browser OAuth flow:

```bash
vibe-trading connector authorize ibkr-live-official-mcp-readonly
```

The wildcard is accepted only for IBKR's `mcp.read` probe. Authorizing this
profile confirms access to IBKR's official read scope; generic `trading_account`
and `trading_positions` calls stay disabled until IBKR publishes stable read
tool names that Vibe-Trading can map safely. A config that adds `mcp.write` must
pin an explicit tool allowlist and still passes through the live order guard.

If IBKR issues a pre-registered OAuth client, add `clientId` and `clientSecret`
inside `auth`.

### Trading connectors: fastest path

For users who cannot wait for IBKR OAuth client approval, connect to a local
TWS or IB Gateway session. Credentials stay inside IBKR's desktop app; Vibe-
Trading only connects to `127.0.0.1` and exposes it as a connector profile.

Install the optional SDK:

```bash
pip install "vibe-trading-ai[ibkr]"
```

Open TWS paper trading or IB Gateway paper, enable API socket clients, then run:

```bash
vibe-trading connector list
vibe-trading connector use ibkr-paper-local
vibe-trading connector configure ibkr-paper-local --yes
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector orders
vibe-trading connector quote AAPL
vibe-trading connector history AAPL --duration "30 D" --bar-size "1 day"
```

Default local ports:

| App | Paper | Live read-only |
|-----|-------|----------------|
| TWS | `7497` | `7496` |
| IB Gateway | `4002` | `4001` |

The agent exposes connector-scoped tools named `trading_connections`,
`trading_select_connection`, `trading_check`, `trading_account`,
`trading_positions`, `trading_orders`, `trading_quote`, and `trading_history`.
Live-broker raw MCP tools are not registered directly as `mcp_<broker>_*`.
No IBKR order-placement tool is registered.

### 🔐 TAP Mode — full credential isolation & human-approved writes

**Opt-in, off by default.** If the `TAP_*` variables below are unset, the
connector behaves exactly as before (direct broker SDK) — nothing changes.

[TAP](https://tap.human.tech) (Tool Authorization Protocol) is a credential
proxy: the agent never holds the raw broker API secret, and consequential writes
are gated on **human approval**. With TAP mode on, **every** Alpaca call — order
placement, cancel, and the reads (account/positions/orders/quote/bars) — is sent
to the TAP proxy's `/forward` endpoint instead of the broker SDK; TAP injects the
real key server-side, then forwards upstream.

- The agent process holds **no Alpaca key at all** — and doesn't even need
  `alpaca-py` — because the whole egress goes through TAP. The secret is
  referenced by name (`<CREDENTIAL:alpaca.key_id>`) and TAP substitutes it.
- **Writes block on human approval.** An order or cancel cannot reach the broker
  without a human approving it; even a prompt-injected "buy now" is held, and
  denying it means it never reaches Alpaca. Orders carry a deterministic
  `client_order_id`, so an approval-race retry is deduplicated rather than
  double-placed.
- **Reads auto-approve.** Account/positions/orders/quote/bars are GETs that TAP
  forwards without a human step — this is credential *isolation* (no key in the
  process), not a gate, so there's ~zero added friction.
- `allowed_hosts` on the TAP credential pins where the key may be sent, so a
  tampered target is rejected (403) before injection.

**Enable it:**

1. In the TAP dashboard, create a **multi-secret** credential named `alpaca`
   holding your Alpaca key pair as fields `key_id` and `secret_key`, assigned to
   your agent, with allowed hosts `paper-api.alpaca.markets` (or the live host
   `api.alpaca.markets`) **and** `data.alpaca.markets` (the market-data host used
   by quote/bars). Use **separate TAP credentials for paper and live** (e.g.
   `alpaca-paper` / `alpaca-live`, selected via `TAP_ALPACA_CREDENTIAL`), each
   with `allowed_hosts` pinned to its own API host — TAP then structurally
   refuses to send the paper key to the live host and vice versa, keeping the
   paper/live separation crisp end to end.
2. Add to `agent/.env`:

| Variable | Required | Description |
|----------|:--------:|-------------|
| `TAP_PROXY_URL` | Yes | TAP proxy base URL (e.g. `https://proxy.tap.human.tech`) |
| `TAP_AGENT_KEY` | Yes | Your TAP agent API key (secret) |
| `TAP_ALPACA_CREDENTIAL` | No | TAP credential name for Alpaca (default `alpaca`) |
| `TAP_APPROVAL_TIMEOUT` | No | Seconds to wait for a human decision (default `300`) |

When a write is placed, approve or deny it in your TAP channel (Telegram /
dashboard). An approved order/cancel is forwarded to Alpaca; a denied or
timed-out one returns an error and is **never sent**.

> **Known limitation — approval race.** If the human approves right at the
> `TAP_APPROVAL_TIMEOUT` boundary, TAP may forward the order while the poll has
> already given up: the gate then reports an error even though the order reached
> the broker, and the `max_trades_per_day` counter under-counts by one. The
> deterministic `client_order_id` keeps a retry from double-placing that order;
> if you rely on a tight trades-per-day cap, check open orders after a TAP
> timeout error before retrying.

**Scope:** covers Alpaca **order placement, cancel, and all five reads** — the
full connector egress, so the process holds no key on any path. HMAC-signed
brokers (Binance/OKX) are follow-ups (client-side signing doesn't fit pure egress
injection). The hooks are additive — they live inside the Alpaca connector and
leave the live mandate gate unchanged.

### Config reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | inferred for stdio; required for HTTP | Omit for stdio, or set to `sse` / `streamableHttp` for URL-based servers. |
| `command` | string | required for stdio | Executable to spawn for stdio servers. Invalid for `sse` / `streamableHttp` servers. |
| `args` | array | `[]` | Command-line arguments for stdio servers only. |
| `env` | object | `{}` | Extra environment variables merged into the subprocess env for stdio servers only. |
| `url` | string | required for `sse` / `streamableHttp` | Remote SSE / streamable HTTP endpoint URL. Not used for stdio servers. |
| `headers` | object | `{}` | Extra HTTP headers for `sse` / `streamableHttp` servers only. |
| `toolTimeout` | number | `30` | Per-tool call timeout in seconds |
| `initTimeout` | number | unset (`max(toolTimeout, 30)`) | MCP initialize / OAuth authorization timeout in seconds. Use this for slow browser authorization without widening ordinary tool calls. |
| `enabledTools` | array | `["*"]` | Tool allowlist. Use `["*"]` to expose all tools from the server |

Config file location: `~/.vibe-trading/agent.json` (JSON or YAML).

For URL-based transports, `type` is required. The agent no longer guesses between SSE and streamable HTTP from the URL suffix.

### Per-session overrides (API)

When creating a session via the API you can pass `mcpServers` inside `session.config` to extend or override the global config for that session only:

```json
{
  "config": {
    "mcpServers": {
      "research-server": {
        "command": "uvx",
        "args": ["research-mcp"],
        "enabledTools": ["search", "fetch"]
      }
    }
  }
}
```

### Tool naming

Ordinary remote tools are exposed with stable names: `mcp_<server>_<tool>`.
Live-broker MCP servers stay behind the `trading_*` connector surface.

If two server names produce the same ASCII-safe local prefix (e.g. `foo-bar` and `foo_bar` both become `foo_bar`), a deterministic hash suffix is appended at the server-segment level so names remain unique. The operator receives a warning:

```
WARNING: Configured MCP server 'foo-bar' collides with another server after local name
normalization. Using local tool prefix 'mcp_foo_bar_<hash>_<tool>' to keep generated
tool names unique. Rename the server in agent config if you want a different prefix.
```

### v1 limits

| Limit | Detail |
|-------|--------|
| Transport | stdio, SSE, and streamable HTTP |
| Execution | serial only — MCP tools never enter the parallel readonly path |
| Surfaces | tools only (resources and prompts excluded in v1) |
| Hot reload | not supported — restart the process to pick up config changes |
| Swarm path | MCP tools are not available inside Swarm worker registries in v1 |

---

## 📁 Project Structure

<details>
<summary><b>Click to expand</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli/                        # CLI package — interactive TUI + subcommands
│   ├── api_server.py               # FastAPI server — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCP server — 54 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (88 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 68 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, alpha browser + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 462 alphas across 5 families
│   │   │   ├── base.py             #   19 operators (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   AST-only metadata load + lazy compute + sanity gates
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead categorisation
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (12) + fundamental (4)
│   │   │
│   │   ├── api/                    # FastAPI route modules
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, SSE stream
│   │   │
│   │   ├── skills/                 # 88 finance skills in 9 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   30 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   7 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   23 sources: tushare, okx, binance, yfinance, akshare, baostock, tencent, mootdx, ccxt, futu, local, eastmoney, sina, stooq, yahoo, finnhub, alphavantage, tiingo, fmp, longbridge, mt5, qveris, india_broker
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

---

## 🏛 Ecosystem

Vibe-Trading is part of the **[HKUDS](https://github.com/HKUDS)** agent ecosystem:

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>Ultra-Lightweight Personal AI Assistant</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/AI-Trader"><b>AI-Trader</b></a><br>
      <sub>Agent-Native Signal &amp; Copy Trading Platform</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>Making All Software Agent-Native</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>Self-Evolving AI Agent Skills</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Agent Swarm Intelligence</sub>
    </td>
  </tr>
</table>

---

## 🗺 Roadmap

> We ship in phases. Items move to [Issues](https://github.com/HKUDS/Vibe-Trading/issues) when work begins.

| Phase | Feature | Status |
|-------|---------|--------|
| **Trust Layer** | Reproducible run cards are emitted and shown in Run Detail; v1 adds tool traces and citations | v0 Shipped |
| **Hypothesis Registry** | Durable research hypotheses with lifecycle status, data sources, skills, run-card links, and invalidation notes | Backend MVP Shipped |
| **Research Autopilot** | Manual-first research loop: hypothesis → deterministic backtest → evidence report | Phase 1–3 Shipped |
| **Data Bridge** | Bring-your-own data: local CSV/Parquet/SQL connectors with schema mapping | Local loader Shipped |
| **Options Lab** | Vol surface, Greeks dashboard, payoff/scenario explorer | Planned |
| **Portfolio Studio** | Risk x-ray, constraints, turnover-aware optimizer, rebalance notes | Turnover-aware optimizer **Shipped 0.1.11**; rest Planned |
| **Alpha Zoo** | 462 pre-built alphas (Qlib 158 + Kakushadze 101 + GTJA 191 + academic + fundamental) with one-line bench, agent integration, and Web UI | **Shipped 0.1.8**, extended through 0.1.12 |
| **Strategy Development Manager** | Register papers / broker research as factors & strategies with a persistent store + automated IC/Sharpe decay lifecycle | **Shipped 0.1.11** |
| **Correlation Regime** | Edge-density + hysteresis regime timeline layered on `/correlation` — spot when markets fuse into one bloc | **Shipped 0.1.12** |
| **Research Delivery** | Scheduled briefs and live research sessions through Slack / Telegram / email-style IM channels | Scheduler + IM Runtime Shipped |
| **Community** | Shareable skills, presets, and strategy cards | Exploring |

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Good first issues** are tagged with [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — pick one and get started.

Want to contribute something bigger? Check the [Roadmap](#-roadmap) above and open an issue to discuss before starting.

---

## Contributors

Thanks to everyone who has contributed to Vibe-Trading!

Recent v0.1.12 cycle contributors and credits:

- @santhreal — a 30-PR correctness sweep: strict-JSON / finite-number hardening across metrics, factors, pattern, and options (#764/#765/#766/#767/#739/#740/#744), loader correctness (#761 yahoo 1m bars), and session / journal robustness (#762/#763/#768/#769/#770)
- @xkam7ar — broad reliability across packaging, web, scheduler, swarm, and CLI (#584), cancellation before the first AgentLoop iteration (#641, closes #638), QVeris session budget + atomic credit accounting (#685/#686), CI / OOS gates (#630/#632), and journal month-filter / side-parse fixes (#626/#628)
- @shadowinlife — the Strategy Development Manager skill (#457, closes #455), pluggable OCR + LLM-vision extraction (#548), centralized provider credentials (#563), the 80× signal-alignment vectorization (#698), and swarm MCP-discovery caching (#704)
- @ebujinovch — the correlation regime timeline endpoint + UI (#756, closes #719) and its `correlation-regime` skill (#557), plus the `academic_corr_rewire` factor (#705)
- @honginp — Binance USD-M routing with execution/mark separation (#470/#716) and the maintenance-bracket decouple that keeps `-PERP` backtests zero-credential (#757)
- @StaniellG — the MetaTrader 5 (Exness) broker connector + `mt5` data source (#481)
- @tyj147454413-cmd — the Binance fallback loader (#643), bounded OKX history with rate-limit handling (#644), and codex stream-failure classification (#663)
- @Marnie0415 — composite sub-engine fallback for unknown symbols (#734) and the frontend `insertBefore` streaming DOM-race fix (#717)
- @YZY0108 — the look-ahead-bias fix across all five portfolio optimizers (#487)
- @UNHNQ — the SiliconFlow CN + Global providers (#565)
- @FenjuFu — the iFlytek Spark provider (#537)
- @jelech — the native Anthropic Messages API adapter (#695)
- @octo-patch — MiniMax regional API endpoints (#731)
- @Thibaultjaigu — the Requesty OpenAI-compatible gateway provider (#474)
- @Robin1987China — realized portfolio turnover metrics for every optimizer (#478)
- @YogeshModi24 — the Frazzini-Pedersen betting-against-beta academic factor (#480)
- @0xZKnw — opt-in TAP mode for Alpaca (#377)
- @sambazhu — the fundamental zoo `_VALID_ZOOS` whitelist (#707)
- @nareshkps — Robinhood connector `account_number` wiring (#726)
- @darkknight4563 — user swarm-presets directory discovery (#570)
- @MikeCer — IBKR thread-local connection pool + snapshot quotes (#636)
- @Shizoqua — `local` loader interval resampling (#467)
- @roberttidball — FastMCP transport import compatibility (#469)
- @yxhuang — bare-ticker resolution in the correlation matrix (#472, closes #471)
- @Bortlesboat — stale `OPENAI_BASE_URL` provider-switch fix (#484, closes #482)
- @ananaymital — preflight `EnvConfig` stale-cache fix (#479, closes #477)
- @GabbaTauchi — reported the native zai streaming / base-URL bug (#758)
- @warren618 / Haozhe Wu — the correlation regime backend integration, the zai provider streaming + base-URL resolution fix (#758), release integration, and open-PR/issue triage

<details>
<summary>v0.1.11 cycle contributors</summary>

- @shadowinlife — the `api_server` modularization capstone (1,103 → 371 lines, #424 closing #331), centralized env config with the AST CI gate (#440), loader `fetch()` protocol conformance (#437), and the Strategy Development Manager RFC in review (#455/#457) — 12 merged PRs this cycle
- @Robin1987China — Research Autopilot Phase 3 loop closure (#267), 4 canonical academic alphas (#277), Shadow Account PIT-safe entry conditions (#302/#314/#316), the turnover-aware portfolio optimizer (#466), scheduled-research route tests (#452), and test-coverage batches for trade-journal / pattern / loader layers (#268/#269/#276)
- @muku314115 — first-class Indian equity (NSE/BSE) support: the `IndiaEquityEngine`, cost stack, `.NS`/`.BO` routing, and the `india_broker` bridge (#305)
- @mvanhorn — the end-to-end scheduled-research executor (#278), the Trading 212 read-only connector (#321), OpenAI default-model resolution (#319), and Robinhood config validation (#320)
- @fei-moss — the `analyze_image` vision tool (#464), NapCat DM pairing (#463), and the IM-media allowed-roots report (#465)
- @sambazhu — the value-investing toolkit: financial-rigor + report-audit tools, 4 skills, and the `value_investing_committee` preset (#407/#408)
- @Elfsa-Miranda — the evidence-bound alpha research pipeline exploration (#405/#416, since re-scoped into #442)
- @Hinotoi-agent — loopback CSRF rejection (#293) and authenticated remote same-origin UI requests (#304)
- @dpersek — configurable IM reply timeout (#413) and the provider-preflight redirect fix (#404)
- @digger-yu — cross-platform `setup`/`dev` commands (#292) and dev-dependency pre-checks (#349)
- @skloxo — tilde expansion + file-roots safety fallback (#299) and reactive zh-CN localization (#301)
- @kadaliao — the beginner tutorial (#393) and Alpha Library social cards (#396)
- @morluto — CLI resume first-message preservation (#448) and the Codex OAuth default model (#446)
- @yxhuang — the Kimi for Coding provider (#435) and the precise #433 diagnosis behind the governance-stack revert
- @isaveall — the `validation.json` artifacts-dir fix (#429) and clearer `--swarm-run` errors (#428)
- @mustafakamal88 — timezone-aware UTC timestamps (#397)
- @irfanallana-oss — the zero-size order guard in `trading_place_order` (#417)
- @Shizoqua — the central OHLC-invariant loader guard (#274)
- @hobostay — SSRF-guard hardening for CGNAT/mesh ranges + the QQ media redirect fix (#389)
- @aeonframework — Pillow / langchain CVE floor bumps (#390)
- @hannibal-lee — the pandas version-constraint fix (#329)
- @MarkfuGod — dynamic data-source counts + token-gated microcompaction (#296)
- @gyx09212214-prog — strict JSON validation outputs (#306)
- @LemonCANDY42 — the backtest report library (#224)
- @fanfpy — Longbridge Decimal→float serialization (#459)
- @asahikiko — packaged SKILL.md capability-count sync + the manifest guard test (#461)
- @wison1717-maker — the mandate second-confirmation dialog + unified error toasts (#453)
- @imsankz — opencode provider mappings (#444)
- @flash1234pku — the tushare reference code-fence fix (#449)
- @Penn-Live — the Docker startup route-iteration crash report (#450)
- @warren618 / Haozhe Wu — the fundamental factor layer (PIT-safe SEC panels), the QVeris premium track, the IM channel runtime, India-equity integration review, CN search fallbacks, and release integration

</details>

<details>
<summary>v0.1.10 cycle contributors</summary>

- @Hinotoi-agent — a security-hardening wave: local-shutdown auth (#241), loopback-host rebinding rejection (#242), agent shell-tool opt-in (#243), settings-write auth (#245), mandate proposal-id containment (#256), persistent-memory type validation (#257), and MCP swarm run-id containment (#258)
- @mvanhorn — the opt-in local data cache (#177), Gemini thoughtSignature round-trip over OpenAI-compat tool calls (#176), the custom data loader guide (#194), and the glm/zhipu provider alias + model-name inference (#247)
- @gyx09212214-prog — loader robustness for malformed crypto/RSSHub timeout env vars (#227, #240), requested yfinance end-date inclusion (#226), strict run-card JSON for non-finite metrics (#238), and ddgs retry-fallback coverage (#239)
- @BillDin — swarm agent status in the chat UI (#188), explicit preset-name handling (#189), the loader-backed market-data tool for swarm workers (#199), and preset-context continuations (#200)
- @Robin1987China — the Research Autopilot goal-hypothesis bridge (#260), the local CSV/Parquet/DuckDB data loader (#252), and an assistant-prefill fix + configurable Kimi User-Agent (#248)
- @LemonCANDY42 — the read-only runtime status dashboard (#210), persisted AgentLoop usage artifacts (#223), and opt-in Run Detail chart payloads (#225)
- @zwrong — the trace.jsonl overhaul with zero truncation + offload (#206) and session-id on exit + `resume <session-id>` (#218)
- @forge-builder — the AI contributor guide (#173) and the OpenClaw MCP research-only smoke-test docs (#165)
- @skloxo — Chinese (zh-CN) frontend localization (adopted from #217)
- @LeeCQiang — Chinese docstrings across all 452 Alpha Zoo factors (#180)
- @KaiLuettmann — GHCR pre-built image publishing on release (#187)
- @ngoanpv — Gemini thought_signature preservation through the AgentLoop dict path (#184)
- @ShahNewazKhan — Docker host-Ollama reachability via host.docker.internal (#196)
- @sambazhu — frontend sync of completed chat attempts (#236)
- @bhlt — baostock-native code format support (#230)
- @octo-patch — MiniMax M3 default model upgrade (#162)
- @warren618 / Haozhe Wu — the global data layer (8 sources + 18 read-only data tools), the 10 broker SDK connectors, the alpha-compare full stack, the provider-reliability overhaul, multi-engine web_search fallback, responsive Stop + SSE reconnect, and release integration

</details>

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## Disclaimer

Vibe-Trading is research and trading software. It is not investment advice, holds no funds, and runs no execution venue. Trading through a broker channel you explicitly authorize (e.g. Robinhood Agentic Trading) happens only within the limits you set and which you can halt at any time. This broker-trading capability is experimental and not verified by us against a real broker account — use it at your own risk. Past performance does not guarantee future results.

## License

MIT License — see [LICENSE](LICENSE)

---

<p align="center">
  ⭐ If <b>Vibe-Trading</b> helps your research, a star helps more people find it.
</p>

---

<p align="center">
  Thanks for visiting <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
