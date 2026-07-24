# Changelog

All notable changes to Vibe-Trading are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Memory Tier 2: Structural Organization** — four independently-gated modules for memory lifecycle enhancement:
  - H-MEM hierarchical directory routing (`VT_MEMORY_HIERARCHY`)
  - A-MEM semantic linking via BM25 (`VT_MEMORY_LINKS`)
  - Auto-compression pipeline with TF-IDF key-sentence extraction (`VT_MEMORY_COMPRESSION`)
  - FTS5 full-text search index with CJK bigram tokenization (`VT_MEMORY_FTS_INDEX`)
- **`VT_MEMORY=off|on|full` preset** — one-line business-friendly configuration replacing 7 individual flags
  - `off`: no lifecycle management (default)
  - `on`: quality scoring + auto-decay + garbage collection (Tier 1)
  - `full`: all features including hierarchy, links, compression, and FTS (Tier 1 + Tier 2)
  - Individual `VT_MEMORY_*` flags still work as explicit overrides
- Dependency-conflict warnings when `VT_MEMORY_COMPRESSION=true` without `VT_MEMORY_GC`
- Lazy FTS5 auto-rebuild on first search when index is empty
- 9 end-to-end integration tests + 23 benchmark tests against real production corpus

## [0.1.12] — 2026-07-22

### Added
- **User swarm-presets directory**: preset YAMLs dropped into
  `~/.vibe-trading/swarm/presets/` are discovered alongside the bundled
  roster (same-name files override it — the same rule as user skills) and
  survive `pip install -U`. `list_presets()` entries now carry a
  `source: "user" | "bundled"` field; explicitly named user presets run
  through `run_swarm(preset_name=...)`, while keyword auto-routing stays
  limited to the curated table. Preset names are validated to a single path
  segment before any filesystem lookup.
- **Security hardening**: all 10 findings from the 2026-07-10 external audit
  closed (#476, tracking discussion #468) — Docker multi-stage rebuild with
  digest-pinned base images, AST-hardened backtest sandbox (blocks
  network/subprocess/eval/os.environ/unsafe-open reachable from generated
  code, including inside nested function bodies), short-lived single-use SSE
  auth tickets replacing a long-lived key in the URL/logs, hardened Compose
  (`read_only`, dropped capabilities, `no-new-privileges`, resource limits),
  auth + rate limiting on `/correlation`, security headers (CSP
  Report-Only, `X-Content-Type-Options`, `Permissions-Policy`), `/live` +
  `/ready` health split, hash-locked dependencies wired into the Docker
  build, GitHub Actions pinned by commit SHA, and an HMAC-authenticated
  factor cache.
- Opt-in **TAP mode** for Alpaca (#377, thanks @0xZKnw) — routes all broker
  egress through a self-hosted TAP proxy so the agent process never holds
  the raw API key, with writes blocking on human approval.
- Realized portfolio turnover (`avg_turnover` / `total_turnover`) surfaced
  in backtest metrics for every optimizer (#478, thanks @Robin1987China).
- **Frazzini-Pedersen betting-against-beta** academic factor (#480, thanks
  @YogeshModi24) — Alpha Zoo: 460 → **461**.
- **MetaTrader 5 connector + data source** (Exness-style MT5 brokers,
  Windows-only `pip install "vibe-trading-ai[mt5]"`). Broker connectors:
  11 → **12** — full read surface plus order placement against a locally
  running terminal, with a bidirectional identity guard (paper profile ⇔
  demo `trade_mode`, login pinned, contest rejected), connector-level
  `max_order_volume`/`max_order_notional_usd` guards on demo AND live, and
  hedging-safe position close by ticket. The live mandate gate gains
  `forex`/`cfd` instrument vocabulary (schema v1 unchanged) and a lot-aware
  `quantity_notional_usd` sizing hook so USD caps bind on lot-sized orders
  (0.1 lot EURUSD ≈ $10,800, never 0.1 × quote). Market-data sources:
  20 → **21** — the `mt5` loader heads the forex fallback chain (broker-exact
  symbols with Exness suffix discovery, 1m–1D bars), `get_market_data` learns
  forex/metal symbol routing (`EUR/USD`, `XAUUSD.FX` previously fell through
  to tushare), and akshare's forex path accepts the canonical slash form so
  degradation off-Windows keeps working.
- **Strategy Development Manager** skill (#457, thanks @shadowinlife, closes
  #455) — `sdm_register` / `sdm_status` / `sdm_decay_scan` turn academic
  papers and broker research into registered factors/strategies with a
  persistent SQLite artifact store (`UNIQUE(name, universe)`) and automated
  IC/Sharpe decay monitoring driving an active → monitoring → decayed →
  disabled lifecycle. Pluggable OCR for `read_document` (local RapidOCR by
  default; cloud Qwen-VL is explicit opt-in only via
  `VIBE_TRADING_OCR_ENGINE=qwen-vl`, never auto-selected). Skills: 86 → **87**.
- **Requesty** as an OpenAI-compatible LLM gateway provider (#474, thanks
  @Thibaultjaigu) — same `provider/model` naming and capability shape as
  OpenRouter, wired through CLI onboarding, provider menu, and Settings.
- Binance USD-M perpetual routing, slice 1 of #462 (#470, thanks @honginp) —
  explicit `BTC-USDT-PERP` symbol contract with execution/mark price
  separation, fail-closed when the two aren't timestamp-synchronized.
- **Correlation regime timeline** (#756, thanks @ebujinovch, closes #719) — a
  new additive `GET /correlation/regime` endpoint plus an opt-in "Regime
  timeline" strip on the Correlation tab: rolling pairwise correlations reduce
  to an edge-density series, causally smoothed, and run through a two-threshold
  hysteresis state machine that marks FUSED episodes ("when did the market fuse
  into one bloc?"). Descriptive risk context, not a trading signal; shares
  `/correlation`'s auth + rate-limit budget. Backed by the **correlation-regime
  skill** (#557, thanks @ebujinovch).
- **Three new LLM providers** — SiliconFlow CN + Global (#565, thanks @UNHNQ),
  iFlytek Spark (#537, thanks @FenjuFu), and a **native Anthropic Messages API**
  adapter (#695, thanks @jelech; `pip install "vibe-trading-ai[anthropic]"`).
  MiniMax now exposes its regional API endpoints (#731, thanks @octo-patch).
- **Historical USD-M funding settlements** for Binance perpetuals (#716, thanks
  @honginp); maintenance brackets are supplied as a validated, versioned
  artifact rather than a live authenticated fetch (#757, thanks @honginp), so a
  plain `-PERP` backtest stays zero-credential.
- **Pluggable OCR** for `read_document` with optional LLM-vision extraction and
  a configurable text-density threshold (#548, thanks @shadowinlife) — local
  RapidOCR by default; cloud engines are explicit opt-in, never auto-selected.
- New academic factor `academic_corr_rewire` (#705, thanks @ebujinovch) and the
  fundamental zoo wired into the `_VALID_ZOOS` whitelist (#707, thanks
  @sambazhu). Binance crypto fallback loader (#643) and bounded OKX history
  fetches with rate-limit handling (#644, thanks @tyj147454413-cmd).
- QVeris premium-track hardening — session budget applied to backtest data
  calls (#685) and atomic credit accounting (#686, thanks @xkam7ar).

### Changed
- Correlation tab accepts bare tickers like `AAPL,SPY` and walks the full
  loader fallback chain instead of failing with `Fetched: []` (#472, thanks
  @yxhuang, closes #471).
- `local` loader honors the requested interval via OHLCV resampling instead
  of silently returning daily bars (#467, thanks @Shizoqua).
- Provider credentials are resolved through one centralized path, fixing a
  gateway misroute (#563, thanks @shadowinlife, closes #549/#553). When no
  `*_BASE_URL` is set, the backend now falls back to the provider catalog's
  canonical `default_base_url` (the same default Web Settings already used), so
  a CLI / manual-`.env` user reaches the right endpoint instead of defaulting
  to `api.openai.com`.
- Signal alignment is vectorized for an ~80× speedup on wide panels (#698,
  thanks @shadowinlife); swarm workers cache MCP tool-discovery specs to avoid
  redundant RPC round-trips (#704, thanks @shadowinlife).

### Fixed
- Explicit `source: local` backtests now route US/HK equities to the
  global-equity engine instead of the crypto default, and explicit benchmarks
  are fetched through the configured source's loader — `local` fails closed
  (no yfinance fallback) so offline runs stay offline (#550).
- Loading `.env` now invalidates an `EnvConfig` singleton cached during early
  CLI imports, so the welcome panel, `/settings`, and dotenv diagnostic report
  the configured provider and model consistently (#541).
- FastMCP transport imports work across both module layouts (#469, thanks
  @roberttidball).
- Portfolio optimizers no longer include the decision bar's close-to-close
  return in weights executed at that bar's open (#487, thanks @YZY0108).
- Backtest turnover metrics now use actual filled and rounded position sizes;
  targets rejected by market rules no longer inflate reported turnover.
- End-of-backtest liquidations now apply exit slippage and include their
  commission in the final reported equity.
- Open-price rebalances no longer use the decision bar's close for sizing or
  depend on whether a replacement symbol sorts before the position it closes.
- Preflight (`vibe-trading run`) no longer resolves provider/model against a
  stale `EnvConfig` snapshot cached before dotenv loads (#479, thanks
  @ananaymital, closes #477).
- Switching providers no longer leaves a stale `OPENAI_BASE_URL` from a
  previous configuration silently overriding the newly-resolved endpoint
  (#484, thanks @Bortlesboat, closes #482).
- **Strict-JSON / finite-number hardening** across the backtest + tools stack
  (thanks @santhreal): risk ratios stay finite when equity crosses zero mid-path
  (#765) or annualizes an explosive path (#739/#740); scalar backtest metrics
  (#766), factor IC std (#767), and pattern trend-slope (#764) emit strict
  RFC-8259 JSON (`null`, never bare `NaN`/`Infinity`); Black-Scholes helpers
  treat non-positive spot/strike as intrinsic (#744).
- **Loader / data correctness** — yahoo `1m` stays minute bars instead of being
  uppercased to monthly (#761, @santhreal); the composite engine falls back to
  the first available sub-engine for unknown symbols (#734, thanks @Marnie0415);
  mootdx history that doesn't reach the requested start is rejected (#692, thanks
  @xkam7ar).
- **Session / journal robustness** — one corrupt `session.json` (#762) or a
  schema-bad `messages.jsonl` line (#763) no longer aborts listing/reading;
  Excel float-stringified A-share codes (#770), unicode-dash PDF page ranges
  (#769), and `export KEY=` dotenv lines (#768) all parse correctly (@santhreal).
- **Native `zai` provider on glm-5.1** (#758) — endpoints that stream zero
  chunks fall back to a non-streaming invoke instead of raising, and an HTML
  error page surfaces an actionable base-URL hint.
- Partial market-data results are completed through the loader fallback chain
  instead of silently shrinking the universe (#689, closes #681).
- Cancellation is honored before the first AgentLoop iteration (#641, thanks
  @xkam7ar, closes #638); streaming output no longer triggers an `insertBefore`
  DOM race in the frontend (#717, thanks @Marnie0415); codex stream HTTP
  failures are classified for correct retry (#663, thanks @tyj147454413-cmd).
- Robinhood connector `account_number` wiring and remote-MCP display shape
  (#726, thanks @nareshkps).
- Broad reliability fixes across packaging, web, scheduler, swarm, and CLI
  (#584, thanks @xkam7ar).

## [0.1.11] — 2026-07-11

### Added
- **Indian equity (NSE/BSE) as a first-class market** (#305, thanks
  @muku314115). A dedicated `IndiaEquityEngine` — T+1 delivery, no overnight
  shorts (opt-in intraday), configurable circuit bands, 1-share lots, and a
  config-driven STT / stamp-duty / exchange / SEBI / GST cost stack — with
  `.NS`/`.BO` symbol routing (`yahoo → yfinance → india_broker → local`), an
  opt-in read-only Shoonya/Dhan `india_broker` data bridge, and 255
  alpha101/qlib158 factors opted into the new `equity_in` universe. Backtest
  engines: 7 → **8**; market-data sources: 19 → **20**.
- **Fundamental factor layer, Phase 1.** PIT-safe SEC fundamentals flow into
  dense daily `fund:*` factor panels — filed-date anchoring, first-filed
  restatement policy, true-quarter `(start, end)` frame selection with Q4
  synthesis (so YTD/annual frames can't contaminate TTM), and rolling TTM —
  plus a `get_fundamentals` tool and 4 quality/value factors in a new
  `fundamental` zoo family. Alpha Zoo: 456 → **460** across **5** families.
- **Research Autopilot Phase 3 — the loop closes** (#267, thanks
  @Robin1987China). `scaffold_signal_engine` writes a contract-correct signal
  engine from a hypothesis and `link_autopilot_backtest` runs it, completing
  hypothesis → signal-engine → backtest end to end.
- **4 canonical academic alphas** (#277, thanks @Robin1987China) — Jegadeesh
  short-term reversal, George–Hwang 52-week high, Amihud illiquidity, and
  Harvey–Siddique co-skewness join the academic family (452 → 456), with a
  **central OHLC-invariant guard** at the runner fetch boundary dropping
  malformed bars from every loader (#274, thanks @Shizoqua).
- **Scheduled research runs end to end** (#278 closing #254, thanks
  @mvanhorn). A default-off background executor
  (`VIBE_TRADING_ENABLE_SCHEDULER`) fires due interval/cron jobs through the
  session runtime, on top of a crash-safe atomic job store, 3 auth-gated
  `/scheduled-runs` REST routes, a Reports library, and post-backtest
  attribution. Route test coverage followed in #452 (thanks @Robin1987China).
- **IM channel runtime — research delivery over 16 adapters.** The agent
  session runtime now attaches to 16 built-in message adapters (WebSocket,
  Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat,
  WeChat/WeCom, Feishu, DingTalk, email, MS Teams, MoChat), dependency-gated
  with install hints, configurable via `AgentConfig.channels`, and surfaced in
  REST (`/channels/*`), CLI (`vibe-trading channels ...`), and Web Settings —
  in all 5 UI locales.
- **QVeris optional premium data track.** The 19 free sources stay the
  default; an explicit-only QVeris mode (Settings → QVeris or
  `vibe-trading data mode paid`) unlocks 63+ providers behind 3 key-gated
  tools (`qveris_search` / `qveris_inspect` / `qveris_execute`) with
  preview-by-default and a session budget gate. Never enters auto-fallback.
- **Trading 212 read-only connector** (#321, thanks @mvanhorn) — 11 brokers
  total. Trading 212 exposes no runtime paper/live discriminator, so the
  connector is fully read-only: `place_order`/`cancel_order` hard-refuse
  every order, paper included. Live order guards also gained an opt-in,
  broker-agnostic `PreTradeAdvisoryInterface` that records advisory reviews
  without bypassing the mandate gate.
- **Turnover-aware portfolio optimizer** (#466, thanks @Robin1987China) —
  fifth optimizer: mean-variance utility with an L1 penalty on weight changes
  versus the previous rebalance (SLSQP, long-only simplex), so the portfolio
  only trades when expected improvement outweighs churn. Optimizers: 4 → **5**.
- **`analyze_image` vision tool** (#464, thanks @fei-moss) — send a local
  chart / K-line screenshot / app screenshot to the session model as a
  multimodal message and get a semantic read (complements `read_document`'s
  OCR). Path-validated against the allowed file roots; requires a
  vision-capable model. Tools: 71 → **72** free-mode (75 with QVeris).
- **Value-investing toolkit** (thanks @sambazhu): financial-rigor +
  report-audit tools, 4 skills, and a `value_investing_committee` swarm
  preset. Swarm presets: 29 → **30**.
- **CN-friendly search fallbacks** — `web_search` gains China-reachable
  backends in the ordered no-key engine chain.
- **Provider roster additions**: Kimi for Coding as a distinct provider
  (#435, thanks @yxhuang), opencode provider mappings (#444, thanks
  @imsankz), Codex OAuth default model bumped to `openai-codex/gpt-5.4`
  (#446, thanks @morluto).
- **SKILL.md manifest guard test** (#461, thanks @asahikiko) — the packaged
  skill's capability counts (skills / presets / zoo / sources / MCP tools /
  engines) are now asserted against source, so distribution paperwork can't
  silently drift again.

### Changed
- **`api_server.py` modularization completed** — 1,103 → 371 lines (#424
  closing #331, thanks @shadowinlife), after route slices for channels,
  settings, and the remaining route groups, plus a shared compat layer with
  session-service writeback fixes.
- **Centralized environment variable management** (#440 closing #438, thanks
  @shadowinlife) — every env var flows through a single Pydantic `EnvConfig`
  schema, enforced by an AST-based CI gate that rejects raw
  `os.getenv`/`os.environ` outside `agent/src/config/`.
- **Factor engine acceleration** — hot rolling operators use
  `bottleneck`/NumPy fast paths, and alpha-bench parallelism stops resending
  large panel payloads to workers.
- **Robinhood Agentic MCP refresh** — current MCP tool names across generic
  reads, live-runner plumbing, default read-only seeds, and mandate-gate
  tests; interactive OAuth holds the handshake open through multi-minute
  broker sign-ins (`VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS`).
- **Loader `fetch()` signatures** now match the loader protocol across
  OKX / Tushare / yfinance (#437, thanks @shadowinlife).
- **Timezone-aware UTC timestamps** across session, goal, channel, and API
  paths (#397, thanks @mustafakamal88).
- **Inbound IM media now lands under `~/.vibe-trading/uploads/<channel>/`**
  (fixes #465, thanks @fei-moss for the report) — inside the default allowed
  file roots, so the agent can read what users send over IM channels with
  zero configuration. The Matrix E2E store moves to the runtime dir (legacy
  path honored) so credentials never enter the readable root.

### Fixed
- **Docker/server startup crash** when FastAPI route iteration hit an
  included-router entry without `path` (#450, thanks @Penn-Live).
- **GLM thinking models on the zhipu provider** no longer lose their
  reasoning stream (#458).
- **Trading mandate UX guards** — a second-confirmation dialog before
  committing a real mandate, unified error toasts, and clarified inputs
  (#453, thanks @wison1717-maker).
- **`trading_place_order` treats zero quantity/notional as unset** instead of
  passing a zero-size order to the broker (#417, thanks @irfanallana-oss).
- **Longbridge Decimal values serialize as floats** across quotes, bars,
  balances, positions, orders, and executions (#459, thanks @fanfpy).
- **NapCat private messages now trigger pairing codes** (#463, thanks
  @fei-moss).
- **Backtest validation artifacts**: `validation.json` no longer requires a
  pre-existing artifacts dir (#429, thanks @isaveall), and nested
  `NaN`/`Infinity` values are normalized before writing, so strict JSON
  parsers don't choke.
- **CLI**: `resume` preserves the first user message (#448 closing #447,
  thanks @morluto); `--swarm-run` rejects extra tokens with a clear error
  (#428, thanks @isaveall); the interactive CLI prints the session-id on
  exit with a copy-paste resume hint.
- **Shadow Account**: extracted rules carry RSI / prior-return entry bounds
  computed from PIT-safe context fetched through the loader registry, so
  generated engines enter on real conditions (#302/#314/#316, thanks
  @Robin1987China); tushare ETF/index/HK symbol routing fixed along the way.
- **Content-filter resilience** — event-driven and swarm runs skip individual
  LLM content-moderation hits and warn when filter rates are high; Gemini
  safety finish-reasons recognized.
- **IM channel reply timeout is configurable** (#413, thanks @dpersek).
- **Provider preflight no longer follows redirects** (#404 closing #402,
  thanks @dpersek).
- **Windows baseline green** — `vibe-trading setup`/`dev` handle Windows
  TypeScript builds, correct cwd, the Vite 5899 port, and child-process
  shutdown; mootdx batch pulls let `KeyboardInterrupt`/`SystemExit`
  propagate.
- **Security hardening** — loopback API CSRF protection (cross-site POSTs
  can no longer drive side effects on the local API), SSRF guards on
  interactive fetch paths, tightened API/Docker/frontend dev defaults, and
  cleared frontend dependency/CSP alerts.
- **Reverted the IRR-AGL reliability/governance stack** (#405/#416) after it
  broke session chats on day 1 (#433 — thanks @yxhuang for the precise
  diagnosis); the evidence-bound research-pipeline direction continues in
  reviewable slices on #442.

## [0.1.10] — 2026-06-19

Roll-up release; see the
[v0.1.10 release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.10)
for the full narrative.

### Added
- **Global data layer** — market-data sources 10 → 18 (direct-API Eastmoney /
  Sina / Stooq / Yahoo + key-gated Finnhub / Alpha Vantage / Tiingo / FMP)
  with ban-risk-ordered fallback chains behind a shared throttled HTTP gate,
  plus **18 read-only data tools** (fund flow, dragon-tiger, northbound,
  margin, block trades, shareholder count, lockup, sector, research, news,
  SEC filings, financial statements, options chains, institutional holdings,
  screening, symbol search, FRED macro, iwencai) — all MCP-exposed.
- **10 broker SDK connectors** — Tiger / Longbridge / Alpaca / OKX / Binance /
  Futu / Dhan / Shoonya join IBKR (local read-only) and Robinhood (Agentic
  MCP); direct-SDK live orders pass the fail-closed bounded-autonomy gate;
  brokers without a runtime paper/live discriminator are structurally capped
  at paper + read-only.
- **Alpha Zoo `alpha compare`** across CLI, REST, Web UI, and agent tool.
- **Research Autopilot Phase 1** (`run_research_autopilot`,
  `generate_backtest_config`) and the local Data Bridge loader.
- **Opt-in local data cache** (`VIBE_TRADING_DATA_CACHE`) for settled bars
  under `~/.vibe-trading/cache/`.
- Per-run token usage (`llm_usage.json`) + progressive Run Detail charts;
  CLI `resume <session-id>`.

### Changed
- **Provider reliability overhaul** — DeepSeek hang fixes, Kimi access,
  streaming liveness watchdog, Gemini 3.x multi-turn tool-calling fix.
- Swarm workers pull market data through the loader layer; live swarm status
  cards stream in the chat timeline.
- Baseline install slimmed (`pyharmonics`/`ta` behind
  `vibe-trading-ai[harmonic]`).

### Fixed
- Community security-hardening wave (#241–#258): Settings write auth, shell
  tools opt-in, LAN-access 403 clarity, Docker-to-host Ollama URL rewrite,
  web_search multi-engine fallback, and more.

## [0.1.9] — 2026-06-01

### Added
- **Connector-first broker profiles (IBKR + Robinhood).** Trading access now
  starts from a selectable connector profile rather than separate broker/live
  entry points; `vibe-trading connector list/use/check/account/positions/orders/quote/history`
  and the MCP `trading_*` tools share the selected profile, with paper/live as
  a property under the connector. IBKR is usable immediately as a local
  read-only TWS / IB Gateway profile; the official IBKR remote MCP path is
  seeded as an OAuth `mcp.read` probe until stable read tool names ship.
  Robinhood Agentic Trading is a bounded connector behind OAuth, a committed
  mandate, an order guard, an audit ledger, and an instant halt switch.
- **Research Goal runtime.** Long-running, research-only goals with auditable
  checklist criteria, budgets, and a `/goal` CLI command, plus REST + MCP
  endpoints (`start_research_goal`, `get_research_goal`, `add_goal_evidence`,
  `update_research_goal_status`) and a Web `GoalDrawer`.
- **Swarm `retry_run`.** Re-launch a failed/stale/cancelled run with the
  original preset + variables; exposed as both `POST /swarm/runs/{id}/retry`
  and an MCP `retry_run` tool (the `list_runs → retry` loop). 36 MCP tools now.
- **Operator-configured external MCP tools in swarm workers** (#142) and
  **remote MCP transports** for the built-in agent.
- **`mootdx` A-share OHLCV loader** — native 通达信 TCP, no token, sits between
  tushare and akshare in the fallback chain. CCXT loader now reads proxy env
  for restricted networks (#126).
- **Hypothesis Registry CLI** — `list / show / invalidate`.
- **Strict alpha-bench mode** with a mandatory random control (#143).

### Changed
- **CLI split into the `agent/cli/` package** (from a 3216-LOC single file),
  with a refreshed interactive terminal UI (figlet banner + activity rail) and
  a single `cli/_version.py` version source.
- Swarm status reconciles from live task files on every read; `run_swarm`
  sends MCP progress heartbeats, and the stale-run reaper uses per-run
  thresholds (#132).
- Refreshed provider default model ids; bumped `langgraph` for CVE-2026-28277.

### Fixed
- **`--version` no longer drifts (#156).** The version derives from package
  metadata, falling back to reading `pyproject.toml` directly — no hardcoded
  constant left to forget on release.
- **Session running-status indicator** now survives reconnect / page reload /
  sidebar navigation; **swarm DAG** blocks downstream tasks when an upstream
  task fails (#145).
- **Robustness pass:** pre-flight validation for LLM-generated signal engines
  with clean JSON errors (#149), graceful agent-loop exit at the iteration
  budget instead of an output-less `failed` (#148), `flush + fsync` session
  message writes that skip corrupted JSONL lines on read (#147), and IME Enter
  handling in the Web composer (#146).
- **Full Report** link now always renders when a `runId` exists, even cross-browser
  (#150); SSE idle timeout is configurable via `VIBE_TRADING_SSE_TIMEOUT` (#157);
  cross-market correlation normalizes timestamps so crypto-vs-equity pairs align (#158).

## [0.1.8] — 2026-05-17

### Added — Alpha Zoo (450+ pre-built quant alphas)
- `agent/src/factors/` — base operators (`rank`, `scale`, `ts_*`, `delta`,
  `decay_linear`, `signed_power`, `safe_div`, market-aware `vwap`) and a
  registry that AST-extracts metadata from each alpha module without
  importing it. Lookahead is enforced at the operator level
  (`delta(d>=1)`), and registry sanity checks reject `+/-inf` and
  outputs that are more than 95 % NaN.
- 4 zoos shipping 452 alphas total:
  - **qlib158** (154 alphas) — port of Microsoft Qlib's `Alpha158`
    feature handler under Apache-2.0, with pinned commit SHA per file.
  - **alpha101** (101 alphas) — implementation of Kakushadze (2015)
    *"101 Formulaic Alphas"* (arXiv:1601.00991), written from the paper
    appendix; the relevant trademarked string is intentionally absent.
  - **gtja191** (191 alphas) — implementation of Guotai Junan's 2014
    *"191 Short-period Trading Alpha Factors"* research report.
  - **academic** (6 factors) — Fama-French 5 + Carhart momentum, shipped
    as honest price-based proxies (not the canonical FF series).
- `vibe-trading alpha {list,show,bench,compare,export-manifest}` CLI
  subcommand. `show` and `export-manifest` enforce path-traversal guards.
- New agent tools: `AlphaZooTool` (browse) and `AlphaBenchTool`
  (orchestrator with Jinja2 autoescape + strict CSP HTML report).
- `ZooSignalEngine.from_zoo(...)` — composite multi-factor signal engine
  with cross-sectional standardisation, weighting, and optional top-N /
  bottom-N long-short conversion.
- `wiki/scripts/build_alpha_library.py` — Alpha Library renderer.
  Reads `manifest.json` produced by `vibe-trading alpha export-manifest`
  and emits 452 per-alpha HTML pages plus 4 per-zoo overviews, each with
  `script-src 'none'` CSP. The landing page hydrates per-zoo counts
  from `content/index.json`.
- New blog post: *"Which of the 191 GTJA alphas still work in 2026?"*
  with aggregate IC statistics, theme breakdown, and the top alphas
  that survive eight years of out-of-sample data.

### Added — Web UI for Alpha Zoo
- New page at `/alpha-zoo` in the Vite + React frontend with three
  views: browse (4 zoo cards + filter bar + paginated table), detail
  (formula, metadata, collapsible source code), and bench-runner
  (form → SSE-streamed progress + Alive/Reversed/Dead stat cards +
  Top-5-by-IR table + by-theme breakdown chart). "Alpha Zoo" nav
  entry added to the layout.
- Four new REST routes in the FastAPI server:
  - `GET /alpha/list` — filterable alpha catalogue
  - `GET /alpha/{alpha_id}` — meta + source code
  - `POST /alpha/bench` — kicks off a background bench job and
    returns a `job_id`
  - `GET /alpha/bench/{job_id}/stream` — Server-Sent Events with
    `progress`, `result`, `done`, and `error` event types. In-memory
    job state with a 1-hour TTL; no Redis/Celery dependency.
- Bench math is refactored into `agent/src/factors/bench_runner.py`
  so the CLI driver (`agent/scripts/w4a_run_benches.py`) and the new
  API worker share a single implementation.

### Added — Safety floor
- `agent/tests/factors/test_alpha_purity.py` — AST allowlist scan over
  every `zoo/**/*.py` module (whitelist: pandas, numpy, scipy.\*,
  `src.factors.base`, `__future__`, `typing`, `math`, `dataclasses`;
  banned: `os`, `sys`, `subprocess`, `socket`, `urllib`, `requests`,
  `httpx`, `pathlib`, `Path`, `open`, `eval`, `exec`, `compile`,
  `__import__`, and `getattr(_, "__*")`).
- `agent/tests/factors/test_lookahead.py` — sentinel future-row
  injection on a 300-row synthetic panel; corrupting rows after the
  probe must leave the probe value unchanged within 1e-9.
- `tools/ci_grep_gates.sh` — CI gate that rejects `yaml.load(` without
  `safe_load`, any trademarked-name leak in shipped artifacts, and any
  per-stock-code data leak in `wiki/**/*.{json,csv,html}`.
- `agent/tests/factors/conftest.py` — opt-in `pytest-socket` integration
  that hard-fails any test attempting outbound network during the
  factors test suite.

### Added — Community governance
- `CONTRIBUTING.md` — Developer Certificate of Origin sign-off
  requirement and a contributor checklist for new alpha PRs (purity,
  lookahead, `__alpha_meta__` shape, LaTeX-matches-code, per-zoo
  LICENSE.md, DCO).
- `NOTICE` (repo root) — Apache-2.0 attribution for Qlib and a
  declaration that the bundled formulas from Kakushadze, GTJA, and the
  academic baselines are mathematical content (paper prose, tables, and
  figures are not reproduced here).
- Per-zoo `LICENSE.md` for each of `qlib158/`, `alpha101/`, `gtja191/`,
  and `academic/`, plus an upstream `NOTICE` for `qlib158/`.

### Changed
- `agent/src/tools/factor_analysis_tool.py` extracted its IC/IR and
  layered-backtest helpers to `agent/src/factors/factor_analysis_core.py`
  so the new `alpha_bench_tool` reuses the same maths. Public tool
  signature is unchanged; `_compute_ic_series` and `_compute_group_equity`
  remain importable as backward-compatible aliases.
- `agent/cli.py` grew by 7 lines to register the `alpha` subcommand;
  all handler logic lives in `agent/src/factors/cli_handlers.py`.
- Packaging: `pyproject.toml` now ships `zoo/**/*.yaml`, `zoo/**/*.md`,
  and `zoo/**/NOTICE` as package data; `MANIFEST.in` recursively
  includes `agent/src/factors`.

### Known limitations
- The `btc-usdt` universe is single-asset; cross-sectional IC requires
  ≥2 instruments, so the bundled `alpha101_btc` bench run returns
  alive/reversed/dead = 0/0/0 by construction. Use a multi-symbol crypto
  basket (e.g. BTC + ETH + SOL + the top-N perpetuals) for meaningful
  cross-sectional results; a curated `crypto-majors` universe is planned
  for 0.2.

### Internal
- `wiki/alpha-library/manifest.json` and `wiki/alpha-library/content/`
  are generated artifacts and gitignored. Run
  `vibe-trading alpha export-manifest --out wiki/alpha-library/manifest.json
  --force` followed by `python wiki/scripts/build_alpha_library.py` to
  regenerate the static site.
