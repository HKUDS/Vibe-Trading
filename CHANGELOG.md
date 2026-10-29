# Changelog

All notable changes to Vibe-Trading are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Versioned research artifacts** can be saved, searched and explicitly revised
  through agent tools, CLI, API and Web (all 11 locales). Revisions preserve
  content, evidence references and data-as-of identity; unchanged saves are
  idempotent and changed research defaults to unverified. Saving is not
  automatic evidence verification or freshness renewal (#2079, #1909).
- **BYMA cash-equity backtests** support ARS shares and declared CEDEAR ratio
  histories, settlement cash netting, credit-date protection and explicit tick
  table/panel assumptions. Settlement is approximated from observed sessions;
  fees and lots are labelled assumptions. No blanket holding-period ban is
  imposed on acquired ordinary shares (#2071).
- **Codex OAuth model discovery** uses account-returned model and effort metadata
  in Web Settings, including OAuth-only visible models. A failed catalog request
  keeps the configured/default model and manual entry available (#2080).
- **Factor research provenance** adds explicit mode, stage and lineage metadata
  to bench/compare results across CLI, API, agent tools and MCP. It records
  declarations and does not certify an evaluation lock (#2067).

- **`list_backtest_runs` finds the backtests earlier turns and sessions already
  ran**, so a follow-up turn reads their artifacts with `read_run_artifact`
  instead of re-running them. It lists runs from `req.json` and `run_card.json`
  (paged, current session by default, also over MCP) with each backtest's
  absolute `run_dir`. Assistant replies in the history now carry
  `[prev_run: <id>]` from the message metadata, and the grounding ledger adopts
  a prior run read through `read_run_artifact` (run card and `metrics.csv` must
  agree, metrics and summary artifacts must match the run card manifest). The session filter is not an
  access control: runs have no owner. A run forged by the model in an earlier
  turn is not detected.

### Fixed

- **Document figure grounding** accepts document-scoped currency restatements
  and magnitude-aware arithmetic, including percentage-point declarations.
  Ratios, wrong values and wrong currencies remain distinct; undeclared
  evidence is not broadened. Missing `read_document.file_path` now gives an
  actionable uploaded-file handle example (#2050).
- **Spot crypto backtests** no longer apply implicit perpetual funding. Explicit
  perpetual codes/mode and a nonzero configured funding proxy retain it.
  Generic commission applies unless a side-specific fee overrides it, and
  signed `crypto_funding_pnl` makes applied funding visible (#2088).
- **Binance all-symbol open orders** acknowledge CCXT's symbol-less warning while
  preserving rate limiting and exchange/authentication/network failures. Fill
  history still reports its symbol requirement explicitly (#2090).
- **Paper strategies use a fresh process with private stdio pipes**, so an MCP
  host blocked reading stdin cannot capture the worker's bootstrap. Startup and
  per-day deadlines, sandboxing and hard teardown remain enforced. Native
  Windows confirmation remains pending (#2089).
- **Background ownership** isolates task reads, cancellation and completion
  notices by host-supplied session/worker scope. Shared queue mutation preserves
  other owners' notices and later attempts can read prior tasks in their session.
  Cancellation/shutdown cleanup and durable restart reconciliation remain
  separate roadmap stages (#2092, #2091).
- **Explicit tool deny-list and bash policies** apply at registry execution
  across Agent, Swarm and MCP, and advertised schemas match them. Other
  providers keep their prior unconfigured defaults; Claude keeps its legacy
  defaults. Generic settings and explicit legacy aliases work across providers
  (#2087, #2085).
- **GTJA191 alpha 17** preserves the signed five-day exponent, with an independent
  golden calculation and NaN-safe power (#2051). WhatsApp voice notes use the
  existing media fallback (#2078), and the Windows heredoc refusal no longer
  blocks POSIX shells (#2077).

- **Forex symbol detection** no longer depends on AKShare's module layout:
  `akshare.forex` was deleted in 1.20.0 and the symbol map moved to
  `akshare.fx.cons_forex`, so the single hard-coded import turned every FX pair
  into an A-share lookup. Both layouts are now probed, and a wholly missing map
  degrades to "not a forex pair" instead of silently matching nothing.
- **Bare US ETF and fund symbols** such as `QQQ` and `SPY` now resolve to
  `QQQ.US` / market `us` instead of a suffix-less `global` candidate. The fetch
  layer already routed bare US tickers as US equities, so the resolver was the
  only place that disagreed: the identity lock then rejected the follow-up call
  ("consumer symbol/venue differs from the locked resolver identity"). ETFs and
  mutual funds on non-US venues keep their native form (#2084).
- **`etf_holdings` accepts the `.US` market suffix** on US symbols, so the
  identity locked as `QQQ.US` still reaches the SEC series/class ticker `QQQ`
  instead of being reported as an unknown share class.
- **JSONP-wrapped provider bodies** decode instead of raising: the throttled
  JSON GET helper unwraps a `callback(...)` envelope when `response.json()`
  cannot parse the body, so A-share news search keeps working when Eastmoney
  switches to JSONP (#2081).
- **Degraded Eastmoney news indexes** get one throttled browser-TLS retry before
  an actionable error instead of
  reading as an empty article list: the Guba user index (`passportWeb`) can no
  longer masquerade as "this stock has no news" (#2081).
- **Global futures routing and pricing**: digit-bearing contracts such as
  `M2K=F` and `6EZ2026.CME`, including `local:` inputs, reach the global
  futures engine with their full product code. OJ and ZR use quote-unit
  multipliers of 150 and 2,000; MYM and M2K use the existing micro-contract
  commission convention. Missing pricing-table entries are recorded in run
  diagnostics instead of silently appearing to be verified prices (#1965,
  #1966, #1968).
- **Longbridge cash disclosures** now preserve each currency's available,
  withdrawable, frozen and settling cash, plus reported financing limits,
  through account reads, Portfolio snapshots, the CLI, API, agent context and
  the Web account card. Negative balances and unavailable values remain
  distinct (#1940).
- **Portfolio errors** redact credential-bearing URLs and error text on
  refresh, progress and historical snapshot reads. Binance's regional HTTP
  451 restriction has an explicit, localized explanation (#1937).
- **Audit rotation** verifies the complete segmented chain on repeated
  rotations, allocates archive numbers past gaps and four-digit counters,
  and refuses to overwrite an existing archive (#1962).
- **Research data quality**: a single IC observation has no sample standard
  deviation; repeated decimal grouping is accepted only with valid digit
  groups, preserving explicit separator choices and refusing malformed
  amounts (#1963, #1964).
- **Weixin attachments** use exclusively created local files so repeated
  names, identical URLs and concurrent downloads cannot overwrite earlier
  attachments (#1967).
- **MiniMax Flash** is the default for direct MiniMax endpoints, with
  reasoning history retained across tool calls. Official gateway model
  lists prefer discovered current routes while keeping paid variants and
  other available models selectable (#1936).

- **A retried provider error no longer halts live model decisions for the
  day**. 0.1.18 announced every failed stream, compaction call or cancelled
  response that reported no usage as missing usage, which the live decision
  budget treats as a reason to halt; a connection reset followed by a
  successful retry stopped live decisions until the next UTC day. Such calls
  are now counted as `unreported_calls` in `llm_usage.json`; an ordinary
  response without usage still halts the runner as before.
- **A research goal's final answer is delivered even when it crosses the
  goal's token budget**. 0.1.18 discarded a finished text answer whose own
  usage reached `token_budget` — the text had already streamed — and reported
  the run as failed. The answer is now released and the run succeeds with the
  budget reason; a tool call from a response past the budget is still not
  executed, and the exhausted goal still refuses further spending. The
  message says to end the goal, since a budget cannot be raised after the
  goal is created.

## [0.1.18] — 2026-10-21

Same-day follow-up to 0.1.17: 12 commits (10 non-merge), no new external pull
requests. It ships the fixes made on main after 0.1.17 — `mcp>=1.30` so the
HTTP MCP transport reclaims sessions, connect-time checks for custom model
endpoints (including fake-IP proxy hosts), grounding of `run_dir/…` refs and
signed amounts, Beijing codes in correlation, the macOS timeout fix and the
sdist contents — together with a leaner agent runtime: tool schemas load on
demand through `load_tools`, oversized tool results stay readable in the run
directory, Swarm sizes its context by the model window, and usage accounting
covers compaction, cancelled responses and failed streams. On the 0.1.17
pre-release verification prompt (DeepSeek V4 Pro, a 20/60 SMA backtest on
AAPL.US) a run took 7 model calls instead of 12 and 152K input tokens instead
of 706K, and reported the same figures.

### Known issues

- A retried provider error (a connection reset or rate limit) can halt live
  model decisions until the next UTC day, and a research goal's final answer
  that crosses its token budget is discarded. Both are fixed on main (see
  Unreleased) and ship with the next release.

### Changed

- Reduce agent request overhead with on-demand tool schemas while keeping the
  complete tool catalog and existing execution permissions. Ordinary backtests
  no longer request extra attribution automatically. Automatic summary titles
  remain available after the first chat exchange.
- Preserve oversized tool results in readable run artifacts and stop Swarm from
  clearing new observations before the model sees them. Context pressure uses
  the model window and includes tool schemas.
- **README credits cover every cycle again**: contributor lines for the
  0.1.13, 0.1.15, 0.1.16 and 0.1.17 cycles in all seven READMEs, each PR
  attribution checked against GitHub. The data-tools list counts the 29
  read-only data tools the MCP server serves (it said 22). The 0.1.13 notes
  below credit ModelScope (#1011) to @yrk111222 and #676 to the session
  lifecycle entry it fixed.

### Fixed

- Keep the custom-endpoint guard lazy-loaded for minimal installations and align
  the Windows desktop MCP lock with the updated package requirement.
- Include compaction, cancelled responses and failed streams in usage accounting;
  stop further work when a research goal exhausts its token budget. Forward the
  configured output cap to both DeepSeek adapters.
- Redact credentials before tool results reach model context or replay caches,
  and reject incomplete compatible-provider streams instead of releasing a
  truncated answer or tool call.
- **`vibe-trading-mcp --transport http` reclaims its sessions**
  (CVE-2026-59951 / GHSA-84m7-p3x7-pcfv). `mcp` is now `>=1.30.0` instead of
  capped below 1.30: an idle session closes after 30 minutes, at most 10,000
  exist and an ended session is dropped, so a client can no longer grow
  server memory without bound. 0.1.15–0.1.17 held the cap because 1.30's
  RFC 8414 issuer check refused IBKR's OAuth metadata; IBKR's
  protected-resource document now names the same issuer as its metadata
  (checked 2026-10-21) and Robinhood's already did. The Docker lock pins
  `mcp` 1.30.0.
- **Custom model endpoints are checked again on every connection**. Saving a
  profile resolved its host once; a name that later re-resolved to a private
  address (DNS rebinding), or a redirect to one, was not checked again. The
  provider test and the running model now resolve each direct connection
  once, refuse it unless every address is public and connect to the address
  they checked (TLS still verifies the host name). When an environment proxy
  carries the request the proxy resolves the name, so this check does not
  apply there.
- **Custom providers can be saved behind fake-IP proxies**. Clash, Surge and
  sing-box in TUN mode answer every lookup from 198.18.0.0/15, which 0.1.17
  refused, so no custom provider could be saved on such a host. A looked-up
  198.18.x address is accepted now (the proxy resolves the real name); the
  same address written into the URL is still refused.
- **Grounding reads the run's own files under the names models use**. A
  figures-block ref naming the active run as `run_dir/…` or by its directory
  name (`20261021_…/artifacts/metrics.csv`) resolves to that run's
  engine-written file, and a sign written before a currency mark
  (`−$1,847.78`, `(−$5.00)`, `PnL: -$3.20`) is the number's sign in both prose
  and declarations. A live DeepSeek backtest report had its final value,
  trade count and losing trade's PnL cut for these two reasons. Model-written
  files and paths outside the run still never resolve, and a hyphen joining
  two figures (`$10-$20`) or a spaced one (`$10 - $20`) is not a sign.
- **Correlation analysis puts bare Beijing, Shanghai-fund and B-share codes on
  their exchange**. `920xxx` resolved to `.SZ`, as did Shanghai `5xxxxx`
  funds and `9xxxxx` B shares; the rule now matches the Tushare fallback's
  (4/8/920 → `.BJ`, 5/6/9 → `.SH`, otherwise `.SZ`).
- **A timed-out background command is reported as a timeout on macOS**.
  macOS answers EPERM rather than ESRCH when a process group holds only
  exited, unreaped processes, so the final kill of a timed-out tree raised
  and the task was marked `error` on a loaded host.
- **Paper accounts say when nothing can be settled yet**. Advancing an
  account before its first session closed reported a date range that ran
  backwards ("between 2026-10-21 and 2026-10-20"); it now names the first
  execution date and the settlement time in the market's time zone.
- **The sdist carries what its tests need**: the test packages'
  `__init__.py` files and CSV / JSON fixtures, and no untracked
  `test_e2e_*.py` harness.

## [0.1.17] — 2026-10-21

Rolls up 638 commits / 228 merged pull requests since 0.1.16, plus 41 pull
requests whose work landed through maintainer commits, from 33 contributors.

The headline is daily paper trading. A `paper_trade_step` tool for the agent
and MCP, and saved paper accounts through `vibe-trading paper`,
`/api/paper-accounts` and a Web page, match orders or a strategy against
completed daily bars without ever reaching a broker; saved accounts move
forward only. Most of
the rest of the cycle is correctness, and much of it has one shape: a value
that cannot be computed now says so instead of turning into a plausible
number. A profit factor with no losing trade, an undefined correlation, a
factor benchmark with too few IC observations, an upside at a zero price and
an unbounded ratio come back as `null` or a refusal rather than 0; a missing
price no longer bridges a return pair, a VaR transition or a lag pair; an
after-close SEC filing no longer reaches the IC a bar early; and a misspelled
backtest setting is reported in the run card instead of silently ignored.
Brazil (B3) joins as a market, the Alpha Zoo grows from 462 to 478 factors,
Slack and Discord join the guided channel setup, scheduled reports can
arrive by Email as HTML or a password-protectable PDF, token usage shows in
Run Detail, chat and swarm, a `claude-cli` provider runs the agent on a local
Claude Code login, and the Web UI adds Persian and Turkish for 11 languages.

### Added

- **Daily paper trading with saved accounts** (#1939, thanks @shadowinlife). A
  new `paper_trade_step` agent and MCP tool matches explicit orders, or the
  per-day orders of a strategy file, against completed daily bars for `cn_a`,
  `hk` and `us`; nothing in it can reach a broker order path. The same
  stateless step is served as `vibe-trading paper step` and
  `POST /api/paper-trade/step`. Saved paper accounts are built on it and
  reachable three ways: `vibe-trading paper create|list|show|history|advance`,
  authenticated REST under `/api/paper-accounts` (list, create, read,
  history, `POST .../{id}/advance`) and a **Paper trading** page in the Web
  sidebar in all eleven UI languages.
  An account starts from the cash and positions you enter, today or at the
  next session, and moves forward only: an advance settles sessions whose
  regular close is at least 30 minutes past and carries the revision it read,
  so a stale or concurrent request is refused (HTTP 409 over REST) instead of
  committing twice, and a failed step leaves the ledger unchanged. Ledgers
  live in `<runtime_root>/paper-trading/accounts.db`; there is no background
  scheduler. A strategy under `<runtime_root>/strategies/` runs in a child
  process that sees only bars strictly before the execution day and the ledger
  after earlier fills; orders fill at that day's close, and any strategy
  failure discards the whole call. Matching is daily-close and all-or-none,
  with simplified fees, price limits, board lots and A-share T+1. Execution
  prices must be raw: adjusted or unknown price calibers and non-finite prices
  are rejected, A-shares need a complete ClickHouse trading calendar, and a
  split-like jump returns `PAPER_DATA_NOT_READY` rather than rescaling
  holdings. Corporate-action reconciliation and cash dividends are not
  modelled and NAV is not total return; intraday, margin, options and
  cross-market phases remain open under #1938.

- **Live runner model calls have their own cadence and daily budget**
  (closes #1854). Safety checks still run every minute, but a model
  decision now defaults to every 15 minutes, each in a fresh conversation,
  with at most 26 decisions and 1,000,000 reported tokens per broker per
  UTC day; an optional once-daily time, timezone and operator-priced USD
  limit are set in Runtime → Model schedule and spending limits, the chat
  runner panel, `vibe-trading connector runner-settings` or
  `GET`/`PUT /live/runner/settings`. Spending history survives restarts.
  Limits are checked after each provider response, so one response can
  overshoot; estimates ignore cache discounts and auxiliary calls and are
  not a provider billing cap. Exhaustion or missing usage trips the
  existing kill switch and its cancel/flatten behaviour, and a decision
  left unfinished by a crash is blocked for inspection.

- **Strategy adaptation runs from preparation to evidence**. A registered
  strategy with adequate, non-stale evidence can be adapted to a new name,
  universe, date window and position sizing through `adapt_strategy` (agent
  and MCP), `vibe-trading strategy-evidence adapt`, authenticated `POST
  /api/strategy-adaptations` and a Web welcome prompt. The SDM child keeps the
  parent's signal, entry and exit definitions and gets its own run directory,
  SignalEngine and backtest; it never inherits parent metrics. Refreshing with
  `scope=strategies` (`strategy-evidence refresh --scope strategies`, or `POST
  /api/strategy-adaptations/evidence`) replaces only the named strategies'
  evidence, and refuses an adapted run unless its config, code, metrics,
  equity and trades match the hashes sealed in its run card. The hash binds
  evidence to the persisted run; it does not certify that the generated code
  implements its description.

- **extraETF holdings exports feed the portfolio, with allocation proposals**.
  `vibe-trading portfolio import-extraetf`, `POST
  /api/portfolio/imports/extraetf` and **Portfolio → Manage accounts → Import
  extraETF Investments** store an Investments CSV as a local source. The whole
  import fails on an unreadable row, a holdings count that differs from the
  one you confirm, a missing price, a future file time or an export older than
  the freshness limit you choose; transactions, dividend and X-Ray exports are
  refused. `Portfolio ID` keeps accounts apart when they hold the same ISIN.
  Totals are exported quantity × price and exclude cash and assets absent from
  the export. EUR joins USD, CNY and HKD as a display currency, valued at
  Frankfurter reference rates whose date is shown apart from the fetch time.
  An allocation proposal (`portfolio rebalance --snapshot-id`, `POST
  /api/portfolio/rebalance`, `portfolio_summary(snapshot_id=...,
  target_weights=...)`, or the Web page) shows value changes for target
  percentages that total 100%; it creates no orders, quantities, tax or fee
  estimates, and an incomplete snapshot or stale cached rates cannot produce
  one. Imported holdings stay out of historical risk tools until their trading
  venue is resolved.

- **Portfolio research can stay on one snapshot** (#1769, thanks @zeus229).
  `portfolio_summary` returns `snapshot_id` and `read_identity` and accepts a
  `snapshot_id` back, so a multi-step analysis keeps reading the same stored
  observation after a later refresh. `vibe-trading portfolio show
  --snapshot-id ID` and `GET /api/portfolio/analysis-context?snapshot_id=`
  read the same way, and the Web Portfolio page exports the sanitized research
  snapshot it displays as JSON. An unknown snapshot, one valued under an older
  valuation version, or one containing a source that is no longer enabled is
  reported as unavailable and never replaced by newer data.

- **mStock (India) read-only connector** (#1675, thanks @Jackzigen). The
  `mstock-live-rest-readonly` profile sends only GET requests for the Type B
  holdings, net-position and fund-summary resources, with the API key and
  current session token kept in the connection's OS credential vault; it never
  logs in, refreshes a session or calls an order endpoint, and both order
  entry points refuse before any network call. Holdings and net positions stay
  separate books. Fund limits are shown raw because they are not cash or net
  liquidation, so the profile withholds `account.read` and is not a portfolio
  source. `connector account` and `connector positions` gain
  `--connection-id`. Tests replay the documented reply shapes; no real mStock
  account was available.

- **Five example options strategies and a candidate study** (#1774, thanks
  @mdb1230). The options-strategy skill ships covered call, cash-secured put,
  iron condor, volatility-gated short strangle and protective put
  `OptionsSignalEngine`s, and `agent/scripts/options_candidates_backtest.py`
  picks one parameter per strategy on 2016–2020 SPY/QQQ, then reports 2021
  onward on SPY, QQQ, AAPL and MSFT with those parameters fixed. This is
  research code for choosing what to paper-trade; no engine changed and no
  order path exists.

- **Custom OpenAI-compatible model endpoints** (#1264, thanks @Emad211).
  Settings gains a custom-provider manager and the CLI gains `vibe-trading
  provider custom list|add|activate`. A profile is saved only after a test
  chat completion with the same URL, model and key succeeded in the last five
  minutes; the key goes to the OS credential vault (the `[keyring]` extra),
  never to the profile JSON or argv, and activation needs an explicit
  confirmation. An active profile cannot be edited: save the changed endpoint
  under a new id. Base URLs carrying credentials, and hosts that are or
  resolve to any non-public address (loopback, private, link-local, reserved,
  or the shared 100.64.0.0/10 range that holds Alibaba Cloud's metadata
  service), are refused, so a model served on localhost cannot be registered
  this way. The host is checked when the profile is tested and saved; a name
  that later re-resolves to a private address is not re-checked. The test is
  a real request and may be billed. `LANGCHAIN_MAX_TOKENS`, when set, now caps
  output tokens on the OpenAI-compatible adapter. The PR's per-channel
  configuration API was not merged; channel settings stay where 0.1.16 put
  them.

- **Persian and Turkish join the Web UI, which now has 11 languages** (#1264,
  #1616, thanks @Emad211 and @bygordon130-hub). Persian (`fa`, right-to-left)
  and Turkish (`tr`) are registered in `SUPPORTED_LANGUAGES` and the language
  switcher, and all 11 locale files carry the same keys. The Turkish file
  arrived with English placeholders and UTF-8 decoded as Windows-1252; both
  were replaced before release, and a test now rejects copied-English Turkish
  strings and that mojibake in `tr` and `fa`. The custom-provider strings,
  first merged in English in every locale, are translated in all 11. Chat
  messages, the composer and error lines take their direction from their own
  text, so a Persian or Arabic message reads right-to-left inside an English
  UI and the reverse. Some strings are still English in some locales.

- **Pixel Office, a shared manual research-task board** (#1616, thanks
  @bygordon130-hub). The `/pixel-office` page, the `vibe-trading office` CLI,
  authenticated `GET /api/pixel-office` and `POST /api/pixel-office/actions`,
  and the `pixel_office` agent tool share one transactional SQLite board
  (`pixel-office.sqlite3` under the runtime root, mode 0600), so separate
  processes see the same tasks. Tasks are created, assigned to a role,
  completed with a required result, and roles carry Operator / Senior / Lead
  ranks. Assigning a task does not start an agent or place an order, ranks
  grant no trading permission, and a recorded result is not an execution
  audit. The PR proposed a JSON file plus browser state; the merge replaced it
  with this shared store. The unsigned Windows review installer now builds the
  bundled Python backend before packaging.

- **Scheduled jobs are edited in place, with channel-aware destinations**
  (#1649, thanks @zeus229). `PATCH /scheduled-runs/{id}` and the Scheduled
  page change a job's prompt, cadence, timezone, end date and delivery without
  deleting it, so its id and history stay. A job that is running, or whose
  delivery is being sent, refuses edits with 409. Each channel adapter
  describes the destination it accepts (label, placeholder, input type), and
  Telegram suggests numeric private-chat ids already in its `allow_from`; a
  suggestion only fills the manual target field. Changing the destination
  clears the old delivery receipt but keeps the session link, and a
  timezone-only edit does not move an interval schedule's next run.

- **Scheduled Email reports as HTML or a PDF attachment** (#1680, thanks
  @zeus229). Email delivery takes a format: plain text (the default),
  sanitized HTML (Markdown rendered by mistune and cleaned by `nh3`), or a PDF
  attachment with a short notice in the body. It is chosen on the Web
  Scheduled page, in CLI playbooks (`--delivery-format`) and in agent
  proposals, whose confirmations show it. A PDF that fails to render fails the
  send instead of going out as plain text. Where WeasyPrint's native libraries
  are missing, the PDF comes from the bundled ReportLab renderer with embedded
  fonts, so desktop installs get PDFs too. A scheduled send now fails visibly
  when the Email channel lacks consent or an SMTP host instead of being
  skipped with a log line. The format selector is translated in every UI
  locale.

- **Password-protected PDF reports** (#1709, thanks @zeus229). An operator
  sets a private `pdf_password` on the Email channel; a PDF Email job can then
  request protection, and the attachment is encrypted with AES-256 through
  `pypdf`. Web, CLI playbooks (`--protect-pdf`) and agent proposals store only
  the yes/no choice, a job config containing `pdf_password` is rejected,
  confirmations show the choice, and creating, editing or confirming a
  protected job without a configured password is refused. An encryption
  failure never echoes the password.

- **The agent can save a report as a real PDF**. Before this, `write_file`
  wrote Markdown text into a file named `.pdf`. A `.pdf` path now renders the
  Markdown into a paginated PDF with ReportLab, without Pango or Cairo. Text
  uses a bundled Noto Sans CJK subset (`VibeCJK-Regular.ttf`, OFL) covering
  Latin, Greek, Cyrillic, CJK, kana and Hangul; Arabic lines are shaped with
  `arabic-reshaper` and `python-bidi` (now base dependencies) in
  matplotlib's DejaVu Sans and wrap across pages without clipping. A
  character neither font covers fails the render instead of printing empty
  boxes, and the write is atomic, so a failed render leaves an existing file
  untouched. The result carries the path, the real byte count and an
  authenticated `/api/reports/{id}` link, which the reply adds even when the
  model leaves it out and the Web chat downloads; IM channels that accept
  files receive the PDF as an attachment, taken only from this attempt's
  staged reports, never from a path the model wrote. Staged copies live
  under `generated_reports/` in the runtime root; if staging fails, the
  written file is kept and the result reports `download_error`. The bundled
  font adds about 19.9 MB to the package.

- **Shadow Account reports render a PDF without WeasyPrint** (#1683, thanks
  @he-yufeng). When WeasyPrint is missing or fails, the report renders the
  same eight sections and charts through ReportLab in a simpler layout, and
  only then falls back to HTML-only; the payload's `engine` can now read
  `reportlab`. A process no longer loses the fallback after its first render
  on a host without a CJK font. The PR used Helvetica when no CJK font was
  found; the bundled font is now tried first, and a host where no embeddable
  font loads gets HTML-only, because an unembedded face can print blank pages.

- **Feishu joins the guided Web UI channel setup** (#1572, closes #1614,
  thanks @shadowinlife). The Feishu panel gets field hints and a setup guide
  in every UI locale. **Test connection** is a standalone probe that requests
  a tenant access token from feishu.cn or larksuite.com, whichever the
  config's domain names, without starting the bot. `stop()` now closes the
  lark WebSocket and stops its dedicated event loop, so a hot reload no longer
  leaves the old connection answering messages beside the new one.

- **Slack and Discord join the guided Web UI channel setup** (#1757, #1758,
  #1764, #1777, closes #1763 and #1776, thanks @shadowinlife). Both get
  localized forms and read-only credential probes. Slack checks the bot token
  with `auth.test`, requiring a bot identity so a user token is refused, then
  the app token and Socket Mode with `apps.connections.open`; only Socket Mode
  is supported. Discord requires a bot identity from `users/@me`; privileged
  intents cannot be checked over REST, so the setup guide covers them. The
  shared token probe, also behind DingTalk, QQ and Feishu, now reports HTTP
  408 and 429 as a temporary network failure rather than rejected credentials,
  and a failed probe leaves saved settings unchanged. Discord's allowlists,
  group policy and emoji settings, and Slack's allowlist and emoji, refresh
  without reconnecting. #1757 and #1758 landed through #1764.

- **Token usage in Run Detail, chat and swarm** (#1890, closes #1889, thanks
  @shadowinlife). Run Detail gains a Token usage tab built from the run's
  existing `llm_usage`, chat shows a live counter from the `llm_usage` stream
  event (replay cannot double-count), and swarm cards and the dashboard show
  run and per-agent totals. `GET /swarm/runs/{id}` now returns token totals,
  provider and model, and swarm workers record prompt-cache tokens and whether
  a count is provider-reported or estimated; an estimate is labelled as one
  and a missing label reads "unlabeled". A reported zero stays zero beside a
  nonzero count, and a missing cache field is never shown as 0. These are
  token counts, not cost or cross-run totals.

- **`get_southbound_flow` serves the Stock-Connect net flow that is still
  published** (#1486, closes #1483, thanks @shadowinlife). The new read-only
  agent and MCP tool returns market-wide southbound daily net buy into Hong
  Kong, split into the Shanghai and Shenzhen channels, in 100M HKD. Eastmoney's
  datacenter report is the primary source; Eastmoney's `NET_DEAL_AMT` arrives
  in million HKD and is scaled to the envelope unit, and a rejected report is
  an error rather than an empty history. The keyless fallback is HKEX's
  official daily statistics (Buy minus Sell turnover), which serves only the
  latest trading day. There is deliberately no Tushare path: its southbound
  fields now carry the cumulative stock, not a daily flow.

- **Gildata research tools and off-exchange fund NAV** (#1485, thanks
  @sambazhu). With `GILDATA_TOKEN` set, three tools wrap Gildata's
  natural-language endpoint: `get_cn_macro_series` (China macro, regional and
  industry series), `get_cn_announcements` (A-share, HK and fund
  announcements) and `search_broker_reports`. Each echoes the vendor APIs its
  query was routed to and returns at most 200 rows (default 50);
  `GILDATA_SRV_TOOL_URL` overrides the endpoint. `get_fund_nav` returns unit,
  accumulated and adjusted NAV for funds such as `110022.OF`, and only those
  three NAV fields count as price evidence for grounding. The Gildata loader
  now also serves Hong Kong equities, stamped `raw`, and CN indices, each
  resolved only when the vendor's `ref_code` matches the symbol exactly. It
  stays at the tail of each chain so paid quota is spent last. Without a token
  none of this registers.

- **Run cards flag backtests that may sit inside the model's training data**
  (#1618, closes #1613, thanks @lorenzozanee). Strategy writes record the
  provider and model that produced `config.json` and `code/signal_engine.py`,
  and the run card shows them. Set `model_training_cutoff` (an ISO date) in
  `config.json`: a window ending before it is marked as exposed, and an unset
  or invalid cutoff is reported as unknown and treated as exposed. No cutoff
  is inferred from the model name. `vibe-trading alpha bench --strict` takes
  `--training-cutoff` to start the out-of-sample segment after that date, and
  now returns an error instead of `ok` when no alpha rows qualify.

- **Loader-health reports say why a source came back empty** (#1643, #1698,
  thanks @cgycorey). The weekly public loader-health lane attaches up to three
  of the loader's own warnings to an unhealthy row, so an anti-bot refusal and
  a broken loader no longer look identical. The report is a public artifact:
  each message is capped at 200 characters, URLs and credential-shaped values
  are redacted (including a labelled `Authorization: Bearer token: VALUE`),
  and a warning that contains a filesystem path is omitted in full. The
  health tests now register real loaders before stubbing one, so running a
  single test no longer reaches the network.

- **A free BaoStock fallback for A-share `val:*` panels** (#1799, thanks
  @Jackzigen). Without a Tushare token, or when Tushare returns nothing for a
  field, `val:pe_ttm`, `val:pb` and `val:ps_ttm` come from BaoStock's daily
  `peTTM` / `pbMRQ` / `psTTM`. `val:pe` and `val:dv_ttm` have no BaoStock
  counterpart and stay NaN rather than being filled from another field. A
  BaoStock outage or login failure degrades to NaN panels, not an exception.
  Token holders see no change.

- **Hong Kong orders are sized on each symbol's board lot** (#1813, thanks
  @alexwan02). A backtest config may carry `hk_lot_sizes: {symbol: lot}`;
  `00700.HK`, `0700.HK` and `700.hk` share one entry and five-digit counters
  such as `80700.HK` stay distinct. Any HK symbol without a configured lot is
  sized on 100 shares and listed under `lot_assumptions` in the run metrics,
  also when no table is given. Mixed-market runs carry each sub-engine's
  assumptions under `market_diagnostics`.

- **Brazil (B3) market data and an opt-in ZimaOS template** (#1783, thanks
  @incorpore). A `.SA` symbol is market `br_equity`, quoted in BRL and served
  by `yahoo` → `yfinance` → `b3_cotahist` → `local`, with `BOVA11.SA` as the
  default benchmark. The Brazil engine applies configurable B3 fees, R$0.01
  ticks and a default lot of one share (`br_lot_size=100` for round lots); it
  does not model income tax, stock-borrow cost or settlement cash locks.
  `python -m src.br_data sync` stores official B3 COTAHIST, CVM, Banco
  Central and Tesouro Direto data outside the checkout, and the
  `get_br_market_data` agent tool reads it. COTAHIST bars are raw, and CVM
  statements are latest revisions, not point-in-time inputs. `zimaos/` holds
  a Compose file and a fork publishing example that each need explicit setup;
  upstream gains no scheduled publishing job.

- **A complete pip + Telegram quick start in the README** (#1954). It covers
  installing the Telegram extra, sender authorization with `allow_from`,
  matching the API port between `serve` and `channels start`, and recovering
  when `vibe-trading channels` is missing because the package was installed
  into a different environment.

- **Thirteen fundamental and valuation factors** (#1787, #1788, thanks
  @shadowinlife). Ten read point-in-time SEC XBRL filings: accruals,
  book-to-market, cash-to-assets, CFO yield, earnings growth, FCF yield,
  leverage, operating margin, revenue growth and ROA. Growth is year over year
  through a 365-day as-of lag, and earnings growth divides by the absolute
  prior value, so a loss turning into a profit reads as growth. Three read a
  new `val:*` namespace of daily A-share valuation data (`fund_pb`,
  `fund_ps_ttm`, `fund_dividend_yield`). Those are keyed by trade date and
  attached only on the CSI 300 universe; a nonpositive P/B or P/S is excluded
  rather than ranked as cheap. XOM keeps its current SEC filer, and filings by
  its pre-reorganisation filer that predate the change extend its history.
  Basic shares never stand in for missing diluted shares, and
  price-times-diluted-shares ratios are valuation proxies, not reported market
  capitalisation.

- **Industry-neutral A-share value factors** (#1802, closes #1789, thanks
  @shadowinlife). `fund_pb_ind_neutral`, `fund_ps_ttm_ind_neutral` and
  `fund_dividend_yield_ind_neutral` z-score each name against its Shenwan
  (SW2021) level-1 peers on each date instead of the whole cross-section. A
  CSI 300 benchmark attaches a point-in-time sector tag built from Tushare
  `index_member_all` membership dates, and only when at least 90% of names
  carry a label. A name with no label, or a group too small for a statistic,
  stays NaN; there is no fallback to a whole-market z-score. Membership is
  point-in-time, but the SW2021 taxonomy itself is applied retroactively, and
  each factor's notes say so. With #1787 and #1788 the registry holds 478
  factors, 20 of them fundamental (462 and 4 in 0.1.16).

- **Factor benchmarks at a longer horizon** (#1801, #1802, thanks
  @shadowinlife).
  `alpha bench --horizon N` (1 to 252, also on the tool and MCP wrapper)
  measures IC against N-bar forward returns, sampled without overlap and
  anchored at the end of the panel; a missing close never bridges the
  horizon. `horizon=1` is the previous next-bar formula. Result envelopes now
  state their horizon, sampling and `universe_excluded` list. SEC-fundamental
  factors requested on a universe other than the S&P 500 are listed as
  excluded instead of failing the whole run, and `alpha compare` shows them
  as skipped with the reason. The alive/dead thresholds were calibrated on
  daily IC and are not re-derived for N > 1.

- **Factor benchmarks feed `fund:*` factors their SEC inputs**. Benchmarks
  now load each selected factor's declared fundamental fields as
  point-in-time SEC panels; before, those inputs never reached the benchmark.
  This needs the S&P 500 universe. The S&P 500 price panel goes through the
  shared fallback chain and reports requested, fetched and missing
  instruments and the price sources used.

- **Factor neutralisation and PCA in the quant library** (#1817, thanks
  @BHhhh-123). `neutralization.neutralize_factor` regresses a factor on named
  numeric and categorical controls (OLS or WLS) separately at every time on
  the panel, at any bar frequency. Controls are either all required or
  selected greedily on coverage, rank and sample size, and every time records
  what was dropped and the exposure before and after. `pca_factors` fits
  cross-sectional PCA per time. Neither function fills, pools or resamples
  rows, and a rank-deficient time is skipped instead of being demeaned. The
  caller has to supply exposures known at that time. The finishing commit
  rescales inputs before squaring so very large or very small units neither
  overflow nor change the answer, keeps covariance PCA in common units, and
  breaks equal-loading sign ties by input order. Reachable through
  `quantlib_call` and MCP.

- **Technical indicators can be read as of a date** (#1768, thanks @zeus229).
  `technical_indicators` accepts an optional `end_date` (strict `YYYY-MM-DD`;
  anything else is an error) as the acquisition boundary. Every response
  carries `read_identity`: the boundary mode, requested end date, bar count,
  serving provenance and a SHA-256 fingerprint of the exact interval, dates,
  closes and volumes used, so two reads can be shown to have used the same
  bars.

- **A `claude-cli` provider that runs on the local Claude Code login**
  (#1804, closes #1800, thanks @alexwan02). Each turn runs one
  `claude -p --restricted --strict-mcp-config --tools ""` subprocess that only
  picks the next step (call tools or answer); Vibe-Trading executes the tools
  itself, so the evidence ledger, the grounding gate and swarm delivery checks
  run as they do for any other provider. No API key is needed.
  `CLAUDE_CLI_DENY_TOOL_PREFIXES` (default `trading_,etoro_`) hides tools from
  the model and `CLAUDE_CLI_BASH_POLICY` (default `python-only`, or `off`)
  limits bash to `python` scripts and read-only listing commands; refused calls
  are fed back at most three times. Both are convenience filters, not a
  security boundary: a Python script can still do anything, and live orders
  stay behind the mandate gate. Settings lists the models the login can run
  and offers only the reasoning efforts the chosen model accepts. A decision
  can take minutes, so the provider emits a waiting signal every second;
  the idle timeout no longer discards an answer still on its way, the stop
  button kills the child process, and progress consumers see `llm_waiting`.

- **The backtest tool returns a structured summary** (#1646, closes #1644,
  thanks @shadowinlife). A successful result carries `summary`: the run
  card's scalar metrics, `structured_metrics` and `validation`, run metadata,
  an equity preview of at most 50 points with the first and last bar always
  kept, and artifact paths including each symbol's `ohlcv_<CODE>.csv`. The
  metrics no longer reach the model only as JSON inside a `stdout` cut to its
  last 2,000 characters. A missing or corrupt run card omits the summary and
  leaves the run successful, as does one whose artifacts resolve outside the
  run directory. When the envelope would exceed the 10,000-character
  tool-result cap, logs are dropped first, then the preview is thinned, and
  anything still omitted is named in the result.

- **`read_run_artifact` reads run artifacts as structured pages** (#1647,
  closes #1645, thanks @shadowinlife). An agent and MCP tool with three
  modes: `rows` (offset pages of whole records with `next_offset`),
  `downsample` (equal-stride sample, endpoints kept) and `meta` (columns, row
  count, size and the run card's sha256 for the file). Aliases (`equity`,
  `trades`, `metrics`, `positions`, `target_positions`, `ohlcv:<CODE>`,
  `run_card`) resolve by a fixed map; any other path is served only if the
  run card's artifact manifest lists it, and paths or symlinks that leave the
  run directory are refused. Pages fit the same 10,000-character cap the agent
  and swarm apply, CSVs are scanned without loading the whole table, and
  zero-padded codes such as `000001` stay strings. Rows shown this way ground a
  report only while the file is an unchanged engine-written table; a file the
  model wrote never does.

- **Grounding checks are declared in one registry, and each validation names
  the checks that fired** (#1628, #1661, #1691, thanks @he-yufeng). Each
  check has a stable name, its issue codes, a description, a severity and a
  phase. Fifteen are declared: the identity, answer and declaration checks
  from these PRs, plus the per-figure role checks (observed, derived,
  proposed, cited, count) and the price-provenance checks, which a
  maintainer follow-up registered. Every attempt recorded in
  `grounding_evidence.json` carries `fired_checks` and `check_findings`,
  taken from the predicates that actually returned a finding, so role checks
  that share `numeric_claim_conflict` do not implicate each other.
  Predicates and their order moved unchanged, so verdicts are the same.
  `CONTRIBUTING.md` describes how to add a check with its passing and failing
  answer pair.

- **The session iteration cap is configurable** (#1833, thanks @sambazhu).
  `VIBE_TRADING_AGENT_MAX_ITERATIONS` sets how many ReAct iterations a session
  run (Web UI, API) may take before it stops with "reached max iterations".
  The default stays 50 and values below 1 are rejected. The no-progress
  budget and spending limits still apply.

### Changed

- **The live runtime scheduler runs on the shared scheduler kernel** (#1899,
  thanks @shadowinlife). It keeps its public surface, its interval and
  one-shot job syntax and its sleep-until-the-earliest-deadline wakeups; the
  mandate gate, kill switch and market-hours layers are unchanged. A second
  concurrent `stop()` now waits for the first one's teardown instead of
  returning at once.

- **Broker connector documentation and tests** (#1770, #1793, #1809,
  closes #1724, thanks @lorenzozanee, @alexwan02 and @he-yufeng). The broker bring-up
  checklist in `CONTRIBUTING.md` asks for options evidence: write-side
  argument names and types recorded apart from read shapes, unsupported shapes
  kept gated, and supported ones tested against mandate caps on premium ×
  multiplier. The `readonly` field on nine SDK connector configs is documented
  as what it is: the order methods do not read it, and order access is decided
  by the connector profile. IBKR's pool reset test no longer depends on test
  order.

- **Tencent, Eastmoney and AKShare A-share prices move to the multiplicative
  forward-adjusted basis when they can** (#1551, closes #1541, thanks
  @he-yufeng). These sources serve dividend-additive qfq series, so returns on
  them are not total returns. The loaders now also fetch the raw series and,
  when `qfq - raw` forms valid per-action plateaus, rebuild the series with
  `(prev_close - dividend) / prev_close` factors and stamp it
  `split_dividend`. Any inconsistency (misaligned calendars, drifting
  offsets, implausible dividends, a failed raw fetch) keeps the additive
  series with its stamp and warning. A window with no corporate action keeps
  its static stamp, and the series is anchored at the window's end, so
  absolute levels depend on the requested range while returns do not.

- **mootdx is retired from the default A-share chain and the public canary**
  (#1730, closes #1729, thanks @he-yufeng). The TDX servers stopped answering
  mootdx's protocol in 2026-07, and every automatic A-share fetch spent about
  ten seconds there before falling through. The loader stays registered for
  explicit `source="mootdx"`. A saved source-order override that still lists
  it is no longer a permutation of the default chain, so it is ignored with a
  warning and the default order applies.

- **Every per-loader test suite checks the health lane's OHLCV contract**
  (#1725, closes #1723, thanks @Jackzigen). `agent/tests/loader_contract.py`
  holds the column, index, dtype, finiteness and OHLC-ordering checks the
  loader-health lane applies, and each loader's canonical-frame test calls
  it, so a drifting source fails its own suite instead of waiting for the
  weekly run.

- **An MCP tool result reaches the agent once, not up to four times** (#1634,
  thanks @zeus229). A structured result used to arrive as `data`, an
  identical `structured_content`, a text block restating it and the joined
  `text`. Only exact copies of `data` are dropped, and only from what the
  agent reads; `MCPServerAdapter.call_tool` still returns every surface to
  programmatic callers, and error or text-only results are unchanged.

- **The system prompt is byte-stable across runs** (#1708, closes #1707,
  thanks @Jackzigen). The workspace state (the run directory and tool
  counters) changed the system prompt on every turn and tool call, which
  invalidated a provider's prefix cache from that point on. The state now
  rides in the first user message inside an `<agent-state>` envelope, next to
  `<recalled-memories>`; the token count is the same.

- **`loop.py` is split into modules, first slices** (#1636, #1631, #1662,
  thanks @Jackzigen, @he-yufeng and @Mikesad). Tool-result helpers moved to
  `src/agent/tool_results.py`, context compaction and message repair to
  `src/agent/context_compact.py`, and LLM usage accounting to
  `src/agent/llm_usage.py`, byte-identical and re-exported from `loop`. Log
  records from the moved code now come from the `src.agent.tool_results` and
  `src.agent.llm_usage` loggers. A test that monkeypatches `loop.X` no longer
  reaches a function that now lives elsewhere; patch the module that holds it.

- **`loop.py` is split into modules, remaining slices** (#1641, #1678, #1791,
  thanks @Jackzigen). The final-status ladder moved to `run_outcome.py`, the
  tuning getters and `TOKEN_THRESHOLD` to `tuning.py`, and written-file
  tracking with its pending-write directive to `write_targets.py`.
  Maintainer follow-ups moved the tool-call lifecycle (`tool_lifecycle.py`,
  still logging as `src.agent.loop`), per-turn streaming callbacks
  (`loop_streaming.py`) and final-answer grounding orchestration
  (`loop_grounding.py`). `loop.py` went from 3,761 lines at 0.1.16 to 1,628.
  One stated difference: the `degraded` flag on the end event and result now
  comes only from success branches, so a run cancelled or stalled between a
  fallback release and the status decision is no longer marked degraded.

- **Scheduled research, the Brazil data sync and memory consolidation run on
  one scheduler kernel** (#1893, thanks @shadowinlife). `agent/src/scheduling/`
  holds the trigger grammar, the next-due arithmetic (pinned by 133 golden
  vectors recorded before the move) and a tick loop with bounded retry backoff.
  The scheduled-research executor uses it, and its REST contract is unchanged.
  The FastAPI lifespan now owns the scheduler, and the unused `cron_service`
  parameter is gone. The live-trading scheduler was not part of this change.
  The kernel also adds protected `system:` jobs. They are seeded at startup,
  a user cannot create an id with that prefix, and REST and CLI refuse to edit
  or delete one. Both system jobs are opt-in and need
  `VIBE_TRADING_ENABLE_SCHEDULER=1`:
  - `system:memory-consolidation` runs daily at 04:00 UTC when
    `VT_MEMORY_CONSOLIDATION` is on. `VT_MEMORY=on/full` does not turn it on,
    and it does nothing unless `VT_MEMORY_GC` is also on.
  - `system:br-data-sync` needs `VIBE_BR_SYNC_ENABLED=1` and replaces
    `python -m src.br_data daemon`, which now prints a migration notice and
    exits 0. `VIBE_BR_SYNC_TIME` sets the slot only when the job is first
    seeded, and the first sync waits for that slot. The ZimaOS sidecar
    container is gone. Its Compose file leaves both flags off by default
    (`068ec3bd`; the PR had turned them on).

  Since `068ec3bd`, a source that fails inside the sync fails the attempt, so
  the scheduler's retry budget applies. Before, the sync was recorded as a
  success. Before downgrading to a version without system jobs, delete the
  `system:` rows from `scheduled_research_jobs.json`. Older readers reject
  those rows and quarantine the whole file.

- **A chat message can be up to 100,000 characters** (#1701, thanks @mminkus).
  The limit used to be 5,000 characters, while scheduled-run prompts had no
  limit. A longer message was refused before reaching the model, the Web UI
  showed only "Failed to send message, please retry", and the 422 response
  repeated the whole prompt. Since `f6e72428`, the 422 returns a short
  `message_too_long` body naming the limit, without the prompt. The Web
  composer checks the length before sending, counting code points as the
  server does. Goal prompts stay limited to 5,000 characters.

- **Agent chat loads small run previews instead of full runs** (#1853, closes
  #1852, thanks @alexwan02). `GET /runs/{run_id}/preview` returns only the
  metrics, the first 1,000 equity points and whether the run deserves a card.
  Agent chat requests previews for a whole session at once. Before, it fetched
  each full run one at a time; the PR measured about 70 MB for a session with
  one backtest card.
  `GET /runs/{run_id}` now builds and encodes its response off the event loop,
  so other requests no longer stall; its bytes are unchanged. One run type
  loses its chat card: a run whose only output was price data that the full
  response rebuilt online, with no metrics, equity, trades, positions,
  validation, strategy, price or OHLCV files and no run card.

- **Dependency updates** (#1665, #1666, #1667, #1668, #1692). Python:
  46 packages in `requirements-lock.txt` moved, including `langchain` 1.4.3,
  `langchain-core` 1.6.6, `langchain-openai` 1.6.7, `fastapi` 0.142.2,
  `starlette` 1.7.0, `uvicorn` 0.54.0, `pyjwt` 2.15.1 and `akshare` 1.19.1.
  The loader-health environment uses `baostock` 0.9.4. Frontend: React 19.3,
  Vite 8.3, react-router 8.4 and Vitest 5.0.2, with `@vitest/coverage-v8`
  moved to 5.0.2 to match.
  CI: the Docker build actions, `cloudflare/wrangler-action` 4.1.3 and
  `actions/upload-artifact` 7.0.1. `uuid-utils` stays at 0.17.0 because 1.0.0
  (#1670, not merged) conflicts with the `uuid-utils<1.0` requirement of
  `langchain-core` and `langsmith`.

- **Docker image pins move past known advisories**. `requirements-lock.txt`
  and `requirements-channels-lock.txt`, which the Docker image installs with
  `--require-hashes`, now pin `aiohttp` 3.14.5, `certifi` 2026.10.19,
  `urllib3` 2.8.0, `multidict` 6.9.1 and `pillow` 13.0.0 (`ccxt` 4.5.89
  comes along so the newer `certifi` resolves). A plain `pip install`
  already resolved newer releases. `mcp` stays below 1.30 for the IBKR OAuth
  constraint, so CVE-2026-59951 (Streamable HTTP sessions are never
  reclaimed) remains open for `vibe-trading-mcp --transport http`.

- **For contributors running the suite: symlink tests skip where symlinks are
  unavailable** (#1803, thanks @hunters1011-ctrl). Three positions/sectors API
  tests used to fail on Windows hosts that refuse to create symlinks
  (WinError 1314). They now skip there and still run everywhere else.

- **Channel edits to live-read settings apply without reconnecting** (#1737,
  closes #1734 and #1736, thanks @shadowinlife). Each adapter declares the
  settings it reads per message (allowlists, emoji and similar); an edit that
  changes only those refreshes the running channel in place. The comparison
  uses validated values, so a full Web form echoing unchanged connection
  fields does not count as an edit. A refresh copies only the declared fields
  and keeps connection state resolved at login, such as WeChat's authenticated
  server address, and Signal refreshes its writable `dm` / `group` policies
  rather than its computed allowlist. The Web result now says whether the
  channel was refreshed, reconnected, restarted with the others, or will pick
  the change up when channels start, in every UI locale. When a hot swap
  degrades to a full reset, the reason is returned with URL userinfo and old
  and new secret values removed, and a best-effort notice goes to the changed
  channel's last chat.

- **Channel status records runtime failures** (#1738, closes #1735, thanks
  @shadowinlife). A failure to start a channel, to send after the last retry,
  or to stop the old adapter during a reload is recorded on that channel's
  status entry as a one-line `error` of at most 200 characters with URL
  userinfo removed, plus `error_context` (`start`, `send` or `reload_stop`)
  and `error_at`. The traceback stays in the log. A successful rebuild clears
  it.

- **New channels are checked against the authoring contract** (#1630, thanks
  @he-yufeng). A test walks every discovered channel and fails when one leaves
  a `BaseChannel` abstract unimplemented, has a scalar config key without a
  field hint, or has a credential-shaped key that would reach the browser
  unmasked. `CONTRIBUTING.md` gains an "Adding a Channel" recipe.

- **Web UI navigation is grouped and explains each page**. The sidebar groups
  pages into everyday research, specialized analysis and automation & setup,
  with plainer names ("Research assistant", "Backtest reports", "Trading
  status"). Every page except the chat has a collapsible "How to use" panel,
  and the welcome screen offers three editable starter tasks (research a
  stock, test a strategy, review holdings). Math and code highlighting load
  only for completed answers. API requests time out after 120 seconds
  (`VITE_API_TIMEOUT_MS` at build time; 15 seconds for the session list) and
  say whether a timed-out write may still be processing; writes are never
  retried automatically. Session-list, rename and delete failures are shown
  instead of ignored.

- **Analysis pages keep their work across navigation**. Alpha Zoo, Correlation
  and Options Lab keep their inputs for the browser session. An Alpha Zoo
  evaluation runs as a server job the page can reconnect to after leaving or
  reloading; a resubmitted request with the same id returns the existing job
  rather than starting another, and a job lost to a server restart says so.
  Before running, the page states each universe's data requirements: CSI 300
  needs a Tushare token and permissions, S&P 500 uses public data, and
  BTC-USDT is refused as a single asset.

- **The runtime page lists connectors by status** (#1845, thanks @alexwan02).
  Connected connectors come first, then those needing attention, then the
  rest; peers keep the backend's alphabetical order, so the 15-second poll
  never reshuffles them. Only the order changes. The page header no longer
  calls the page read-only, since model cadence and spending limits can be
  edited there while a runner is stopped.

- **Report rendering dependencies** (#1680, #1683, #1709, thanks @zeus229 and
  @he-yufeng). The base install now requires `mistune`, `nh3` (previously only
  in extras), `pypdf`, `reportlab`, `arabic-reshaper` and `python-bidi`. The
  Docker image adds `fonts-noto-core` and `fonts-noto-cjk` so WeasyPrint
  renders CJK and Arabic reports.

- **Update the Windows desktop PyJWT pin to 2.15.1**. This matches the main
  lock and includes the fix for
  [GHSA-ffc3-869f-jxw9](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9).
  Artifact hashes are verified against PyPI; other Windows dependency pins
  stay unchanged.

### Fixed

#### The grounding gate

- **Indexed and container field refs resolve, and a miss lists the refs that
  would work** (#1633, thanks @zeus229). `a.0.b` and `a[0].b` now name the
  same evidence element; an unindexed field still selects none. When a
  `call::field` ref matches nothing, the correction lists exact
  `call_id::path[i]` refs, value matches first. A ref naming a container lists
  its numeric descendants that hold the figure's value, and a tool name shared
  by several calls ranks those calls by value match, most recent first.
  These are hints only: no hint authorizes a value, and a maintainer
  follow-up keeps them to the figure's own instrument and to the element an
  indexed ref names.

- **A ref naming no call of the session gets real refs to copy** (#1638,
  thanks @zeus229). A `scope::field` ref whose scope names no call, tool or
  run stays rejected, now with the `unknown_call_id` reason and up to five
  exact `call_id::field` candidates. The system prompt tells the model to copy
  `tool_call_id` verbatim instead of inventing a short alias. A maintainer
  follow-up applies the same instrument and figure-kind limits a real ref
  has, so a candidate is never one that would be refused.

- **A correction keeps the figures that already passed** (#1702, thanks
  @he-yufeng). The correction prompt listed only what failed, and a model
  facing 65 issues rewrote whole numeric sections as prose, deleting valid
  Risk X-Ray values and a benchmark table that had no issue. It now also
  lists up to 24 measured figures that checked clean and tells the model to
  keep them as written. A value that fails anywhere in the draft is not
  listed, and bare integers never are. When more than 24 issues exist, the
  prompt says how many are not shown and that unlisted figures are not
  assumed to pass.

- **Only the engine's own output grounds a backtest report** (#1685, thanks
  @cgycorey). The active run's `metrics.csv` could credit an earlier run's
  Sharpe to the current call; that archived copy now counts only when its
  manifest names the full directory the call declared and the exact call id,
  and a model-written manifest is ignored. A `metrics.csv` or `metrics.json`
  the model wrote is no longer engine evidence, a date cell with an explicit
  year must match that year, and a resolver step that failed, was refused or
  came back empty no longer erases a locked or conflicting identity.

- **A derived figure's ref must name evidence that exists** (#1835, #1837,
  thanks @zeus229). A comma- or semicolon-separated ref is resolved member by
  member, and an empty or unknown member fails with `no_evidence` instead of
  falling back to every value in the session. A single ref that names no call,
  tool, field, artifact or observed symbol is refused the same way rather
  than borrowing a coincidentally equal value. Unattributed multi-symbol
  arithmetic keeps its `no_symbol` diagnostic.

- **Derived notes after a label parse, and process metadata is not evidence**
  (#1728, #1767, thanks @zeus229). A note such as `scenario result: 125 /
  10000 * 100` was not evaluable because only the full-width `：` was a
  separator; the ASCII `:` now is too. Top-level `exit_code`, `returncode`,
  `elapsed_seconds` and `duration_seconds` of a code-running tool's result are
  no longer recorded as observed values, so a backtest's runtime cannot
  ground a figure.

- **Percent-named fields are read as percentage points** (#1823, closes #1820,
  thanks @he-yufeng). A-share rows carry `changepercent` values that are
  already points, so `0.52 - 1.41` refused the correct "-0.89%" and passed
  "-89%". When every data operand anchors only to fields named `percent`,
  `pct` or ending in `%`, the result is read in points; an operand whose
  value also appears under a plain field keeps the fraction reading. A
  maintainer follow-up converts the operands before evaluating, so ratios and
  compound factors of two point values come out right.

- **Every data operand of a derived figure must be observed.** Only added or
  subtracted terms were checked, so a numerator or denominator the session
  never fetched could pass. A chosen multiplier or divisor (a discount factor,
  a weight) now needs a `count` declaration and its value and label on the
  same visible line of the answer. Literal 1 and square or cube exponents are
  structural, and an explicit trailing `*100` on a percent claim is read as a
  unit conversion without exempting any other operand.

- **Instrument identity survives matrices and ticker-keyed results** (#1850,
  #1851, thanks @zeus229). In a square Markdown matrix with an empty top-left
  header (a correlation table), each row's symbol is taken from its first
  cell, bold removed, when the row and column symbol sets are complete,
  unique and equal; anything else stays unscoped. A result keyed by
  instrument (`risk_contribution_pct.ABC.US`) keeps each value's instrument
  and exact ref, so the same number cannot ground a claim about another
  instrument. List-indexed scalars such as `positions[0].contribution_pct`
  keep their indexed-ref meaning.

- **A figure that names its currency must match evidence in that currency**
  (#1905, thanks @ThreeTima). An ISO code or an unambiguous mark (`€`, `£`,
  `₩`, `₹`, 人民币, 美元, 円) fixes the figure's currency for observed,
  derived and proposed checks, and SEC XBRL amounts carry their declared unit
  (CHF, NZD, BRL, ARS and VND included). A scaled amount such as `1.2B USD`
  keeps its code. Bare `$` and `¥` stay ambiguous and match any currency.

#### Agent loop, providers and swarm

- **A restored read-only result stays visible until the model has seen it**
  (#1635, thanks @zeus229). Compaction could clear a result replayed from
  the run cache before the next model request carried it, so the restore was
  wasted. Replayed results are now held back from microcompaction, text
  collapse and the summary layer until one successful model request has
  included them.

- **Writing a strategy file no longer fails with `AttributeError`** (#1673,
  closes #1672, thanks @tomaszkubiak-courses). After the model-provenance
  writer landed, every run that wrote a strategy file crashed reading
  `_active_model_id`. The loop now sets it from the runtime snapshot and,
  before each batch of tool calls, from the provider-reported model, falling
  back to the configured one. This regression never reached a release.

- **Codex tools may omit optional arguments** (#1785, thanks @zeus229). The
  Codex Responses endpoint treats a tool without an explicit `strict` as
  strict, so the model filled every optional property, sending `""` for an
  optional string. Tool schemas now go out with `strict: false`.

- **Skills load and save under the names they advertise** (#1797, closes
  #1795; #1858, closes #1855; thanks @Shizoqua). Two section headings that
  differ only by case could not be loaded, and the path the error suggested
  repeated the error; an exact-case match is now tried first. Saving a skill
  whose own frontmatter carried another name left it unreachable under its
  slug and let each lookup append a duplicate; the `name:` line is now
  rewritten to the slug on every save, and a fallback read never duplicates
  a loaded skill.

- **Research-goal evidence keeps its provenance inside the run** (#1688;
  #1895, closes #1894; thanks @zeus229 and @Shizoqua). The goal tool and
  skill tell the model to copy a result's `tool_call_id` verbatim and never
  to use a ledger `evidence_id` (`ev_...`) as a grounding ref;
  `tool_call_id` stays optional for manual evidence. An absolute artifact
  path outside the current run directory is now rejected, as a relative
  escape already was, instead of being verified against another run's file.

- **Each swarm task gets its own artifact directory** (#1455, thanks
  @Shizoqua). Artifacts were keyed by agent alone, so when one agent ran
  several tasks, a later task could read an earlier task's `report.md` back
  as its own output. They now live under `artifacts/<agent>/<task>/`, and
  earlier tasks' reports, summaries and message logs stay in place;
  sequential and parallel runs are covered through the real runtime.

- **Swarm presets take their variables from the prompt** (#1674, thanks
  @Mikesad). Seven presets ran on fixed defaults whatever was asked: a copper
  request ran every commodity worker on gold, a bearish options request used
  a neutral view, and crypto, factor, event, fund and macro prompts were
  replaced the same way. These variables are now extracted from the prompt,
  an explicit duration ("3 months", "两周") is used as stated, and
  `run_swarm` accepts a `variables` object whose values override extraction.
  Prompts that match nothing keep the old defaults.

- **A half-written last line no longer breaks a swarm event stream** (#1908,
  thanks @rudycelekli). `read_events` raised on an `events.jsonl` whose final
  line was still being appended or was cut short by a crash, which killed the
  SSE stream and run recovery. An unterminated last line that is not yet
  valid JSON, including a cut UTF-8 sequence, is skipped until the next poll;
  a complete invalid line still raises.

#### Market data and loaders

- **`get_northbound_flow` stops returning an empty success off a dead feed**
  (#1484, closes #1481, thanks @shadowinlife). Eastmoney's northbound
  endpoint still answers but has carried no net flow since HKEX's 2024
  disclosure change. When both its realtime and history sides are empty or
  all zero, the tool now uses the Tushare fallback or returns `ok: false`
  naming both failures. The fallback no longer multiplies every row by 100:
  values stay in million CNY, rows before 2024-08-19 are net buy, and later
  rows, which are turnover, come back under `turnover_*` fields with their
  net-flow fields `null`.

- **Daily fund-flow fallback covers empty responses and labels its source**
  (#1954). An A-share daily request now tries Tushare when Eastmoney returns
  no usable rows, not only when the request or symbol resolution fails. Each
  symbol names the provider that served it, and a batch served by both
  reports `mixed`. Tushare's `main` is now large plus super-large net flow;
  `net_mf_amount`, which is total net flow, is returned separately as
  `net_total`. A missing or non-finite buy or sell amount stays `null`
  instead of becoming zero, and the result states its methodology because
  provider bucket definitions differ. Minute requests never fall back to
  daily data, and a missing token or permission remains a per-symbol error.

- **A blocked Stooq costs one request** (#1637, #1640, closes #1648, thanks
  @cgycorey). Once Stooq refuses the client, the loader stops requesting
  further symbols instead of only silencing its warning, so the fallback
  chain moves on at once. The refusal is detected from the response before
  parsing: the proof-of-work page, a 403 or 429, or the plain-text daily-hits
  message. Concurrent callers serialize on the check, and the latch lasts 300
  seconds instead of the life of the process. A 5xx is still a per-symbol
  failure and `N/D` is still "no data".

- **FMP and Tiingo series never mix adjusted and raw prices** (#1684, #1689,
  thanks @cgycorey and @he-yufeng). The price basis is decided once per
  response from bars that can actually be emitted. A bar whose adjusted
  prices are missing or invalid is dropped, with a warning, rather than
  filled with raw prices beside adjusted neighbours. Bars with unparseable
  dates or non-positive prices are dropped too. Each frame carries its actual
  `adjustment` stamp, the loader cache keeps it (the cache format version
  was raised, so older entries are refetched), and tests pin the stamp on both paths and through a
  warm cache hit.

- **Local data files load every bar they should** (#1651, #1825, #1819,
  thanks @rudycelekli and @he-yufeng). The end-date filter is half-open at the
  next midnight, so bars stamped in the last fractional second of the end day
  are no longer dropped. A Parquet file whose dates live on a
  `DatetimeIndex` loads with or without a configured `date_format`; before,
  setting a format silently dropped every bar. An explicitly mapped date
  column takes precedence over the index, which also removes a crash when
  both share a name.

- **The opt-in loader cache follows changes to local sources** (#1650,
  #1747, #1879, thanks @rudycelekli). Local cache entries are keyed by the
  file, query, date format and column mapping as well as the range, so
  repointing a symbol no longer serves the previous source's bars. Correcting
  or deleting a CSV, Parquet or DuckDB file (including a DuckDB WAL change)
  refreshes the entry on the next fetch, reusing the same cache paths. Cache
  metadata that is missing, malformed or unusable is a cache miss that the
  loader repairs, not an exception. An edit that preserves every observed
  filesystem identity field is still not detected.

- **The Longbridge loader works on SDK 4.0 and later** (#1805, #1847, thanks
  @alexwan02). SDK 4 refuses `Config(app_key, app_secret, access_token)`, so
  every Longbridge fetch failed and auto mode fell through even with valid
  credentials. The loader and the trading connector now share one helper that
  uses `Config.from_apikey` when the SDK has it, and the initialization error
  names the exception type. One loader test covers both SDK shapes through
  windowing and caching.

- **BaoStock 0.9.4 connections keep their timeout.** The bounded connection
  wrapper accepts the new API-key argument and routes `bs-` keys to the VIP
  host while staying compatible with 0.9.3.

- **Data tools honour their row limits** (#1676, #1927, thanks @cgycorey and
  @rudycelekli). `get_macro_series` reports `observations_available`,
  `truncated`, the effective `limit` and a hint when it caps a series, and
  trims whole observations to fit the tool-result budget so `count` is what
  was delivered. A FRED response covering only part of the requested window
  is an error. `get_fund_nav` clamps an explicit `limit=0` to one row instead
  of returning the 2,000-row default.

- **Symbol suffixes resolve to the right exchange** (#1907, #1914, thanks
  @rudycelekli). `get_etf_holdings` treats Yahoo's `510050.SS` like
  `510050.SH` instead of sending it down the US/SEC path. Symbol search labels
  Beijing codes (`920xxx` and legacy `4xxxxx` / `8xxxxx`) `.BJ` instead of
  `.SZ`, and the Tushare fallback no longer maps `920xxx` to `.SH`.

- **RSSHub event enrichment keeps calendar dates and share classes** (#1829,
  #1830, thanks @rudycelekli). A timezone-aware `as_of` no longer raises, and
  aware daily bar labels keep their displayed date instead of shifting to the
  UTC day. Configured `bare` and `exchange_prefix` routes split only the final
  venue suffix, so `BRK.B.US` requests `BRK.B` rather than `BRK`. Intraday
  publication instants are not converted between markets.

- **SEC quarterly statements derive fiscal Q4 only for currency flows**
  (#1917, thanks @rudycelekli). `period="quarter"` built Q4 as FY minus three
  quarters for every concept, which produced negative weighted-average share
  counts and EPS figures no filing reports. Q4 is now derived only for
  three-letter currency units that match across all four periods; share
  counts, per-share values and dimensionless ratios are left out of the
  derived row.

- **Correlation matches the data it compares** (#1710, #1711, #1746, #1933,
  closes #1932, thanks @rudycelekli, @cgycorey and @Jackzigen). Daily
  histories from sources in different time zones are joined on each source's
  local calendar date in both correlation and regime analysis. Equity tickers
  that end like a quote asset (`ABNB`) are no longer routed to crypto
  sources. `700`, `0700`, `700.HK` and `00700.HK` are one instrument for the
  duplicate-asset guard, while five-digit counters such as `80700.HK` stay
  distinct. A pair whose correlation is undefined (a zero-variance leg) is
  `null` from `/correlation` and `/correlation/analysis`, not 0.0, and the
  heatmap shows a muted dash with an explanation.

- **Correlation analysis reports per-symbol coverage.**
  `/correlation/analysis` computes the matrix and the optional regime timeline
  from one price snapshot, rejects two spellings of the same asset before any
  fetch, and returns which symbols are missing with every source tried and why
  it failed. The fetch honours saved source-order overrides and tries Yahoo
  first for `^`, `=F` and `=X` identifiers.

#### Backtest runner, engines and metrics

- **Profit factor is undefined when no trade lost** (#1602, thanks
  @davidalmeida90). `profit_factor` and `profit_loss_ratio` were 0.0 for a
  run whose trades all won, which ranked it below every run with a loss.
  Both are now `None` (an empty `metrics.csv` cell, `null` in JSON) in the
  daily metrics and the options engine. A run with no closed trade, or only
  losing trades, keeps 0.0.

- **Sortino uses zero-target downside deviation over every period** (#1693,
  #1727, thanks @MetaAviator). The denominator was the sample standard
  deviation of the losing returns, so equal losses looked riskless and a
  single loss left the ratio huge or undefined. It is now the root mean square
  of negative returns divided by the full return count, in the shared metrics
  and in the options engine.

- **The first bar's result counts against initial capital everywhere**
  (#1750, #1818, #1844, closes #1749 and #1843, thanks @he-yufeng and
  @DrDLyuan). The options engine's drawdown peak and the `drawdown` column in
  `artifacts/equity.csv` start from initial cash, so a first-bar loss shows up
  and the column agrees with `max_drawdown`. Per-bar returns measure the first
  bar from initial cash too, so Sharpe and Sortino see it, the `ret` column
  compounds to `total_return`, and bootstrap validation uses the same series.

- **Calmar stays finite and zero-bar trades count in holding periods**
  (#1901, #1876, thanks @Bortlesboat and @MetaAviator). Calmar falls back to
  0.0 when an overflowed annual return makes it non-finite, like the other
  ratios; `annual_return` itself is unchanged. Completed same-bar trades now
  count in the average holding period. `avg_holding_days` remains the
  engine's bar-based measure, not calendar days.

- **Options legs are priced on the run's bar cadence** (#1753, thanks
  @remote-controlled-man). Historical volatility was always annualised at 252
  bars a year, so a crypto or hourly options run priced its legs on one
  cadence and reported metrics on another. Pricing now receives the run's
  factor. A cross-market run estimates each bar's cadence from the intervals
  observed up to that bar, so extending a run cannot change earlier option
  prices.

- **`trades.csv` reports the opening fill and keeps break-even exits**
  (#1779, #1780, thanks @MetaAviator and @alexwan02). Each entry and exit row
  carries an `event` column. The entry row shows the price and size of the
  fill that opened the position, not the weighted cost after later scale-ins;
  those stay in `fills.jsonl`. Validation and run-artifact readers pick exits
  by the event column, so zero-PnL exits are no longer dropped. Unmarked
  older files keep the previous convention.

- **Benchmarks follow the symbol's exchange and the run's source** (#1712,
  #1781, thanks @rudycelekli and @alexwan02). `.SH`, `.SS`, `.SZ` and `.BJ`
  symbols take the CSI 300 benchmark whatever the source; local, BaoStock and
  yfinance runs could fall through to SPY. A source that forbids network
  fallback, `local` included, fetches its benchmark through that same loader.
  When the declared benchmark cannot be resolved, the run card says that
  benchmark-relative metrics were graded against the equal-weight basket.

- **Crypto spellings get crypto rules** (#1740, #1748, #1861, #1862, #1864,
  closes #1751 and #1863, thanks @he-yufeng, @rudycelekli and @Jackzigen).
  `BTC/USD`, `ETH/USD` and four other known slash-USD pairs are classified
  before the forex rule, in backtests, correlation and Agent/MCP data routing,
  while `XAU/USD` stays forex. Digit-leading bases (`1INCH-USDT`,
  `1000PEPE-USDT`), separated USDC and BUSD quotes (`BTC-USDC`, `ETH/USDC`)
  and `BASE-USDT-PERP` perpetuals no longer fall through to A-share rules,
  where board-lot rounding rejected every order. Signal alignment uses the
  same classification. The same CI repair reads the alpha-readiness Tushare
  token through the config layer and treats a whitespace-only token as unset.

- **A-share price limits cover every board's codes** (#1913, thanks
  @rudycelekli). ChiNext `301xxx` and STAR `689xxx` codes get the ±20% band,
  and Beijing `920xxx` and legacy `4xxxxx` / `8xxxxx` codes get ±30%; they had
  fallen back to ±10% and blocked legal fills. ST status and listing-day
  exemptions still cannot be inferred from a code.

- **Contract specs for Yahoo forex pairs and ICE softs** (#1930, #1944,
  thanks @wavebyrd). `EURUSD=X`-style symbols, and `.FX` in any case, are
  normalised before the spread and swap tables are read, so they stop paying
  the default 2-pip spread and swap. Coffee, sugar and cotton multipliers are
  dollars per cent (375, 1120, 500), like the grains; they were full contract
  pounds, a hundred times too large.

- **Backtests warn about config keys that nothing reads** (#1935, #1947,
  thanks @he-yufeng and @rudycelekli). A key no reader on the backtest path
  recognises (`initial_capital` instead of `initial_cash`) adds a run-card
  warning with a did-you-mean hint. A key that only another engine reads,
  such as `commission_rate` on a crypto run that uses `maker_rate` and
  `taker_rate`, is named as unused by the selected engine, including the
  sub-engines of a mixed-market run. Runs still proceed. This resolves #1934.

#### Validation and run artifacts

- **Monte Carlo path metrics start from initial capital** (#1664, thanks
  @MetaAviator). Actual and shuffled paths both begin at the starting
  capital, so the first trade's return and loss enter Sharpe and the
  drawdown high-water mark. Monte Carlo statistics and p-values change
  accordingly; the chart payload is unchanged.

- **Validation stops inventing returns across missing equity** (#1754,
  thanks @MetaAviator). Bootstrap and walk-forward returns use only observed
  adjacent equity values, so a gap no longer becomes a flat return plus one
  jump. A walk-forward window without observed endpoints or any adjacent
  return reports an error instead of a zero score.

- **Standalone revalidation reproduces the original run's settings**
  (#1815, #1915, #1842, thanks @MetaAviator and @rudycelekli).
  `python -m backtest.validation <run_dir>` uses the saved Monte Carlo,
  bootstrap and walk-forward parameters and seeds instead of defaults, still
  running all three tools. The runner records its annualisation factor in
  `run_card.json` and revalidation reuses it, including `null` for calendar
  annualisation; older cards reconstruct it from the config and equity
  timestamps. Reloaded trades recover their entry dates from marked
  entry/exit pairs, so walk-forward windows group them as the original run
  did.

#### Quant Library and analysis tools

- **Brinson attribution reads the book, not its liquidation** (#1782, thanks
  @alexwan02). A run closes every position on its last bar, so the final
  `positions.csv` row is all zeros. When it is, attribution uses the row
  before it and the report notes that row's timestamp. It steps back only
  one row: a book already flat before the close is still reported as flat.

- **Attribution annualises with the run's recorded rate** (#1948, thanks
  @rudycelekli). When the run card records `annualisation.bars_per_year`,
  attribution uses it instead of re-deriving the rate from the requested
  interval, which disagreed for crypto's 365-day year and any run whose
  served bar spacing differed from the request.

- **Attribution inputs and Carino linking** (#1659, #1943, thanks
  @rudycelekli). `brinson_fachler` and `carino_factor` reject non-finite
  weights, returns and tolerances by name instead of returning NaN effects.
  Carino's near-coincidence branch now compares the two returns relative to
  the remaining wealth. Two returns close to -100% can differ by a tiny
  absolute amount while their wealth relatives differ severalfold, and
  those used to take the limit branch.

- **VaR backtests no longer join observations across a gap** (#1658, thanks
  @rudycelekli). A pair dropped for a non-finite return or forecast still
  leaves the coverage counts, and now also breaks the Christoffersen
  independence transitions. The breaches either side of it are no longer
  counted as consecutive days.

- **Implied volatility meets its price tolerance** (#1657, thanks
  @rudycelekli). The bracketing fallback passed `tol`, a price tolerance, to
  `brentq` as a volatility tolerance. It now solves tightly and returns NaN
  unless the repriced option is within `tol` of the market price, the same
  check the Newton path applies.

- **Turnover-aware optimiser and min-weight floor** (#1652, #1653, #1885,
  thanks @rudycelekli). Turnover is measured on signed holdings: reversing a
  50% long into a 50% short counts 0.5, both the close and the reopen.
  Allocations kept without optimisation (all cash, short history, a failed
  fit) now update the prior holdings the next penalty is measured against.
  A single-asset book is checked against its per-name and group caps and
  raises when the allocation exceeds them or is not finite. When a
  `min_weight` floor cannot be funded by the names above it, the date falls
  back to equal weights over the active names, keeping their signs and gross
  exposure, instead of pushing a funding name through zero.

- **Risk X-ray returns and downside deviation** (#1717, #1875, thanks
  @rudycelekli). Returns are computed per symbol before incomplete dates are
  dropped, so a missing close no longer becomes a multi-bar move booked as
  one period. Downside deviation is the zero-target root mean square over all
  bars, as the backtest's Sortino computes it. The standard deviation of the
  losing bars alone read zero for a book that lost 1% on every losing bar.

- **Missing observations stay missing in time-series and validation helpers**
  (#1713, #1714, #1715, thanks @rudycelekli). `fit_ornstein_uhlenbeck` builds
  lag pairs before dropping missing values, so a gap is no longer fitted as a
  one-step transition. `purged_walk_forward_splits` skips a fold whose
  training set purging has emptied, as its contract states. Regime edge
  density stays unknown on a bar where any pair's correlation is undefined
  (a constant or missing series) instead of counting that pair as no edge.

- **Grouped purged K-fold purges groups whose labels reach the test block**
  (#1700, thanks @Shizoqua). `group_purged_kfold_splits` takes
  `label_end_times`. An earlier group whose labels resolve inside the test
  block is purged, as is a later group inside the test labels' horizon, and
  the embargo starts after the furthest test label ends. The finishing commit
  made the argument keyword-only, so existing positional calls keep their
  meaning. It also requires contiguous, chronological groups when the
  argument is given. Without it, only the embargo applies, as before.

- **Event-study fitting stays before the event** (#1920, thanks
  @rudycelekli). For an event window that opens after the event, for example
  `(1, 5)`, the estimation window used to end at the window's start and so
  took in the event day. With `estimation_gap=0` it also took in the days in
  between. It now ends before both the event and the window, for every
  normal-return model.

- **Credit, stochastic-volatility and factor-model inputs** (#1716, #1718,
  #1719, #1928, thanks @rudycelekli). `cds_price` keeps premium dates on the
  requested frequency and prices a final stub for a fractional maturity.
  Before, it spread the periods evenly over the tenor.
  `portfolio_style_exposure` drops an asset with any missing factor exposure
  and reports its weight as `unmatched_weight`, instead of summing NaN into a
  zero exposure. `heston_price` rejects non-finite parameters and a
  nonpositive integration limit before integrating.
  `factor_risk_decomposition` rejects a specific variance below -1e-8 instead
  of clipping it to zero idiosyncratic risk.

- **Non-finite bond and Sharpe-summary inputs are refused by name** (#1824,
  #1821, #1822, thanks @he-yufeng and @rudycelekli). An infinite coupon
  frequency used to price any bullet bond near par, and an on-coupon-date
  shortcut in `accrued_interest` turned a NaN face into 0.0. `ytm_solve`
  checks its price and bracket, `key_rate_duration` its tenors and `dv01` its
  par amount. `probabilistic_sharpe_ratio` checks all five of its inputs; a
  NaN benchmark used to come back as NaN "confidence". `expected_maximum_sharpe`
  refuses NaN or infinite trial counts. #1824 supersedes the narrower reports
  in #1821 and #1822.

- **Fund math and cash-flow ingestion refuse ambiguous inputs** (#1732,
  #1739, #1919, thanks @he-yufeng, @Shizoqua and @rudycelekli).
  `american_waterfall` refuses a bare `as_of` date, which it used to ignore
  silently; per-deal dates are a mapping. A NaN preferred rate used to hand
  every profit dollar to the LP as preferred return, and the result still
  reconciled. Hurdle and waterfall amounts must now be finite. Cash-flow and
  entity-panel ingestion refuse a single dot followed by exactly three digits
  (`12.000` is 12 in a US export and 12000 in a European one) unless
  `decimal_separator` is given. Scientific notation such as `1.2e5` is still
  accepted.

- **Drawdown duration and three-statement tolerance** (#1784, #1786, thanks
  @rudycelekli and @remote-controlled-man). `max_drawdown_analysis` dates the
  peak at the latest visit to the high-water mark before the trough, so
  revisiting a peak starts a new underwater period. `project_three_statement`
  applies the caller's `balance_tolerance` inside each projected period too;
  a widened tolerance used to fail there at the module default.

- **Portfolio-weight and copula numerics** (#1694, #1695, thanks
  @rudycelekli). Inverse-variance weights no longer overflow on very small
  positive variances. Inverse-variance weights and HRP reject a non-finite
  diagonal, and HRP now checks a single-asset matrix as well. A Gaussian
  copula fitted from a Kendall's tau that rounds to correlation ±1 is nudged
  back inside the open interval, and its CDF accepts the
  near-singular covariance.

- **`quantlib_call`, VPIN and options-payoff results** (#1826, #1836, #1897,
  thanks @rudycelekli). The 5,000-value result budget is enforced while
  encoding. Before, a long series past the budget still emitted one
  `<truncated>` string per remaining element. VPIN completes a bucket at a
  relative tolerance, so scaling volume units no longer changes which buckets
  count as full. `options_payoff` returns an error envelope when extreme
  inputs overflow to infinity instead of raising.

- **Report audit keeps the sign of a value** (#1663, #1654, thanks
  @he-yufeng and @rudycelekli). Accounting parentheses, ASCII or full-width,
  are negative: `(25.3)亿` is read as -25.3 亿 with its unit, where it used
  to read as +25.3 with no unit. `-25M`, `−25M`, `-$25M` and `$-25M` keep
  their minus sign, and `(-25)` is still a negative. In prose a bracketed number
  without a unit or currency, such as `(2024)`, is skipped as a year.
  Mismatched brackets, a unit both inside and outside, and non-finite or
  larger-than-1e15 values are rejected. Reported in #1660.

- **Financial-rigor checks stop reading undefined as agreement** (#1883,
  #1906, #1921, thanks @rudycelekli). A zero reported market cap matches
  only a zero product, and against a zero cross-source median only an exact
  zero agrees. Either way the percent deviation is `null`. A negative median
  is compared on its magnitude. Before, these read as a 0% deviation. An
  explicit `tolerance_pct=0` or `years=0` is honoured instead of falling
  back to 2% and 3 years. Three-scenario upside is `null` at a nonpositive
  price, where it used to report 0% ("fairly valued"), and negative `years`
  is an error.

- **Swing-based skill signals no longer fire before the swing is known**
  (#1873, thanks @rudycelekli). The bundled Elliott-wave and harmonic example
  engines stamped a signal on the swing bar itself, which is only confirmed
  `swing_window` bars later. They now replay the swings in order and stamp
  each signal on its confirmation bar. The optional `pyharmonics` path is
  unchanged.

- **Pattern tool extrema and arguments** (#1882, #1923, thanks
  @rudycelekli). A flat top or bottom spanning adjacent bars is one extremum,
  reported at its first bar. A missing `run_dir`, a list of patterns, a null
  or non-integer `window` now get a JSON error or their default instead of
  raising out of the tool.

- **Shadow-account RSI uses Wilder's seeded smoothing** (#1457, thanks
  @Shizoqua). The first average is the simple mean of the first 14 gains or
  losses, and the recursion runs from there. The extractor and the scanner
  share one implementation, so the RSI bounds a profile extracts are the ones
  the scanner tests.

- **Small-price indicators keep their digits** (#1925, thanks @rudycelekli).
  MACD and Bollinger values were rounded to 4 and 2 decimals, so a 1.2e-5
  crypto price came back as zeros. Each nonzero value now keeps at least four
  significant digits, including a small component next to a larger one;
  ordinary prices round as before.

- **Hypothesis search and backtest links** (#1720, #1902, thanks @Shizoqua).
  A search with `limit=0` returns nothing instead of one record, and the
  `link_backtest` tool forwards its optional `validation` results
  (walk-forward, Monte Carlo, bootstrap) to the registry instead of dropping
  them.

#### Alpha Zoo, factors and alpha bench

- **Fundamental factors no longer see after-close filings a bar early**
  (#1794, thanks @Jackzigen). SEC filings carry only a date and can arrive
  after the close, so the benchmark IC path now uses fundamental panels one
  bar later and records `fundamental_pit_lag_bars: 1`. IC measured on
  same-day filings needs to be rerun. The backtest engine's separate
  next-bar execution is unchanged.

- **Carhart momentum no longer reads today's price** (#1578, thanks
  @Shizoqua). `academic_carhart_mom` was the 12-month return minus the
  1-month return, which moves with today's close, the opposite of skipping
  the last month. It is now the return from 252 to 21 trading days ago. A
  test moves every close inside the skipped month and requires the value to
  stay put. The finishing commit corrected the factor notes, the zoo licence
  text and a strategy example that taught the old formula under a factor id
  that does not exist.

- **`decay_linear` weights the newest bar heaviest** (#1912, thanks
  @rudycelekli). Inside each window the weights ran from n on the oldest bar
  down to 1 on today, the reverse of the Alpha101 definition. Every factor
  that calls it changes value (22 Alpha101 and 19 GTJA 191 modules); windows
  stay causal and the missing-data masks are unchanged.

- **Rolling argmax/argmin ties no longer depend on the backend** (#1898,
  #1696, thanks @rudycelekli and @Mikesad). Without `bottleneck`, a tie
  resolved to the oldest bar; it now resolves to the most recent, as
  `bottleneck` does. `bottleneck` is a core dependency, so most installs
  already got the most recent bar. The registry test suite also runs on
  Windows hosts without symlink privileges.

- **Alpha benchmark arguments and environment** (#1806, #1910, #1918, thanks
  @xaritoku and @rudycelekli). `alpha bench` and `alpha compare` load the
  `.env` file before reading credentials, as other CLI commands do. `top=0`
  is rejected instead of quietly becoming 20, and boolean, fractional or
  non-numeric `top` values return an error envelope. A factor with fewer than
  two IC observations is skipped with the reason instead of being ranked
  with a NaN IC standard deviation and an IR of 0.

- **38 GTJA 191 factors show their formula**. Their `formula_latex` read
  "see body", which the Alpha Library displayed as the formula. It now holds
  the formula already quoted in each module's docstring. Metadata only; no
  computation changed.

#### Live trading, brokers and portfolio

- **Live option orders are refused before reaching a broker** (#1585, thanks
  @lorenzozanee). Robinhood's `place_option_order` is pinned as a write, so a
  remote read-only annotation cannot pass it through, and the profile says
  live order placement is equities-only. The mandate gate also refuses every
  option intent, on both the MCP and SDK paths and even when the mandate lists
  options, because share-notional limits cannot bound a contract multiplier or
  maximum loss. Live options execution is not implemented.

- **Direct-SDK positions are priced for the mandate exposure check** (#1581,
  thanks @Shizoqua). Toss, Dhan, KIS, Zerodha and Shoonya report a position's
  price as `current_price` or `ltp`, and Futu its value as `market_val`; none
  was read, and one unpriced position fails the exposure check closed, so
  every later order on those brokers was refused. A zero or negative price, a
  boolean, or a non-finite value or total now fails closed as well.

- **The kill-switch sweep survives its own failures, and stopping a runner
  stops it** (#1703, #1704, thanks @Romzhou). An audit-ledger write that
  raised used to abort the preemptive cancel/flatten sweep and latch it as
  fired, so it never ran again; it is now logged and the sweep continues. A
  resting order without an order id, or a position with a missing, malformed,
  non-finite, overflowing or boolean quantity or no symbol, is reported as an
  error instead of being cancelled blindly or closed for NaN shares. `POST
  /live/runner/stop` used to answer `was_running: false` while the scheduler
  kept firing ticks, because the driver task returned as soon as the scheduler
  started; it now lives as long as the scheduler, and stopping it cancels an
  in-flight agent decision and waits for it to end. Each broker keeps its own
  runtime job store, migrated from the shared one.

- **US equity live sessions close at 13:00 ET on half-days** (#1706, closes
  #1705, thanks @he-yufeng): 27 November and 24 December 2026 and 26 November
  2027. The calendar is still a static two-year table.

- **KIS reads see SOR and NXT fills and recover from a replaced token**
  (#1726, thanks @passionbull). Order and fill reads asked only the KRX venue,
  while most retail orders route through SOR, so an account that had traded
  read as empty. They now query KRX, SOR and NXT and merge the rows, and a
  venue that fails or a page without a row list fails the read instead of
  returning a partial one. KIS issues one token per app key, so another
  process can silently invalidate the cached one; an explicit token-expiry
  rejection (HTTP error, 401/403 or an HTTP 200 business error) now drops the
  cache and retries once. Order placement still goes to KRX only.

- **Binance balances survive clock skew, and unpriced assets mark the snapshot
  incomplete** (#1505, thanks @goatyyc). A balance or Simple Earn read
  rejected as "ahead of the server" (`-1021`) refreshes the clock offset and
  retries once. Quotes, bars and symbol search use an unauthenticated client,
  so a public ticker no longer needs a signed request. Binance's account total
  is built from priced positions, so a Binance asset without a price now marks
  the snapshot incomplete and names the asset, and "last complete" reads and
  history skip such snapshots.

- **Futu reads a saved non-HK market and reports both cost bases** (#1812,
  #1814, closes #1807, thanks @Frank-zhu2000 and @alexwan02). All four Futu
  profiles pinned `filter_trdmarket` to HK, hiding a US account saved in
  `futu.json`; HK is now only the default when nothing is saved. A
  multi-currency account's balances, which Futu labels `N/A`, carry the HKD
  they were requested in. Positions add `average_cost`, `pl_ratio_avg_cost`,
  `unrealized_pl` and `realized_pl` (`None` where Futu reports `N/A`), and the
  portfolio derives Futu unrealized P&L from the average cost, because Futu's
  `cost_price` is diluted by realized gains and can turn negative.

- **Futu `HK.00700`-style codes reach the risk x-ray and holdings merge**
  (#1922, thanks @rudycelekli). Market-prefixed codes are rewritten to the
  suffix form the loaders use (`00700.HK`, `BRK.B.US`) before risk inputs are
  built and holdings are merged across brokers. Snapshots valued before this
  change are hidden from latest and history views until the next refresh
  rebuilds them.

- **The Portfolio page's holdings and history follow the display currency**
  (#1810, thanks @rwxyx518-prog). The holdings table's value and P&L columns
  and the history chart used USD whatever currency was selected. Converted
  values use the snapshot's own rate and show a dash when that rate is
  missing, rather than an assumed one.

- **Weekly and monthly risk x-rays annualise per period** (#1656, thanks
  @rudycelekli). `portfolio_risk_xray` annualised `1W` and `1M` volatility
  with 252 bars a year; it uses 52 and 12, and `1M` is not read as a minute. A
  monthly request without a start date fetches 31 months, enough for the
  minimum sample.

#### Trade journal

- **Mixed-currency journals are reported per currency** (#1811, closes #1808,
  thanks @Jackzigen). `total_pnl`, `max_drawdown` and dividends summed HKD and
  USD round-trips without conversion. With more than one settlement currency,
  `total_pnl`, `total_dividends`, `max_drawdown` and `profit_loss_ratio`
  become currency-keyed objects with a warning, the overtrading diagnosis is
  given per currency, and `top_symbols` ranks by trade count with each
  amount's currency; no FX conversion is applied. Single-currency journals
  keep scalar values. Drawdown now starts from zero realized P&L, so a losing
  first close counts.

- **Amounts and symbols parse the way the broker wrote them** (#1766, #1871,
  #1872, #1881, #1916, thanks @remote-controlled-man and @rudycelekli). A
  generic `Date,Symbol,Side` journal is claimed as a Futu export only when
  Futu's `Quantity` or `Amount` column exists, so its quantities and prices
  are no longer read as zero. Accounting negatives such as `(1,234.50)` and
  `$(1,234.50)` keep their sign instead of becoming 0. `1.234,56` reads as
  1234.56 (a comma-only `1,234` is still thousands). Fiat pairs such as
  `EUR/USD` are no longer classified as crypto, `.US` symbols, share classes
  like `BF-B.US` included, are US equities, and `.SS` is Shanghai.

- **Dates are combined, ordered and validated before analysis** (#1900, #1941,
  #1942, thanks @MetaAviator). Separate generic `date` and `time` columns are
  combined, including Excel serial dates and day fractions, and a time alone
  never stands in for a missing date. Rows with equal timestamps keep their
  file order through FIFO matching. A journal with a missing or unreadable
  date returns an error instead of being analysed or filtered without those
  rows.

- **FIFO P&L counts reversal fees once, and unbounded ratios are valid JSON**
  (#1891, #1884, thanks @MetaAviator and @rudycelekli). A fill that closed one
  side and opened the other charged its whole fee to both; the fee is now
  split by quantity. A journal with no losing round-trip produced an
  `Infinity` profit/loss ratio that strict JSON parsers reject; it is `null`.
  When winners and losers both have zero holding time, the disposition check
  reports an undefined ratio instead of a bias.

- **Unknown analysis types and filters are rejected** (#1911, #1924, thanks
  @rudycelekli). An unrecognised `analysis_type` returned an empty `ok`
  result, and an unrecognised filter returned the whole journal as if it had
  been applied; both now return an error naming the accepted values (`full`,
  `profile`, `behavior`, `strategy`; a date range, `symbol=` or `market=`).

#### Strategy store

- **Strategy records keep their trading rules, and declared backtests feed
  decay monitoring** (#1848, #1849, thanks @alexwan02). `sdm_register` accepts
  `entry_rules`, `exit_rules` and `position_sizing` (a list is stored one rule
  per line) instead of dropping them. Nothing used to write `bench_history`,
  so `sdm_status(decay_check)` and `sdm_decay_scan` always reported
  insufficient data: a backtest whose `config.json` names an `artifact_id` now
  records its Sharpe, annual return, max drawdown and Calmar and reports a
  `bench_record` (`recorded`, `skipped` or `failed`, with a reason). Decay
  monitoring reads only `initial` and `periodic` rows, so an undeclared rerun
  (`manual`) cannot move the baseline. Failed runs, runs without trades or
  metrics, and a measurement already stored, even from a copied directory, are
  skipped, atomically across connections; a different evaluation window is a
  new measurement. Bookkeeping errors never fail a successful backtest.

- **SDM decay compares disjoint IC windows** (#1699, thanks @Shizoqua). The
  baseline and recent windows are the oldest and newest five IC observations;
  with fewer than ten they overlap (and with five or fewer they are the same
  window), which pinned `ic_ratio` near 1.0 however far the IC moved.
  `ic_ratio` is now `null` until ten observations exist.

#### Tools and documents

- **A refused file write names the setting that allows the path** (#1679,
  thanks @he-yufeng). When `write_file` or `edit_file` refused a path outside
  the allowed roots, the error said only that the path escaped. Now it lists
  the allowed roots and names `VIBE_TRADING_ALLOWED_WRITE_ROOTS`; read-side
  refusals name `VIBE_TRADING_ALLOWED_FILE_ROOTS`. The variable is also
  documented in `.env.example` and the README. The boundary itself is
  unchanged. Since `aac03fa6`, on a case-insensitive filesystem a path spelled
  differently from an allowed root (`dropbox` for `Dropbox`) is accepted when
  the filesystem confirms it is the same directory. Path names are never
  case-folded.

- **Skill file removal follows the same rules as skill file writes** (#1639,
  thanks @Shizoqua). `remove` could delete any file in a skill directory. It
  is now limited to `references/`, `templates/`, `examples/` and `assets/`,
  like `write`. Since `8ec3b80f`, both actions also refuse `..` segments and
  symlinks that resolve outside those directories, and `remove` deletes only
  regular files, never a directory.

- **`read_file` reports an unreadable directory as a structured error**
  (#1946, thanks @rudycelekli). Listing a directory inside the allowed roots
  ran outside the tool's error handler. A permission error therefore escaped
  instead of returning the usual JSON `status: error`.

- **Document reader keeps more of PDF, Word, PowerPoint and Excel files**
  (#1838, #1839, #1840, #1841, thanks @rudycelekli).
  - PDF: with no OCR engine, a page whose native text is shorter than
    `min_text_per_page` (50) used to be skipped. Its text is now kept, and the
    result is marked `no_ocr_engine`. If every selected page has only such
    short text, the read is still refused with the OCR install hint.
  - Word: paragraphs and tables come out in document order. Before, every
    table was appended after all paragraphs.
  - PowerPoint: text inside grouped shapes and tables is read; merged table
    cells appear once.
  - Excel: cells holding `NA`, `N/A`, `null` or `NaN` keep that literal text.
    Only empty cells count as missing.

- **README tables match the code** (#1671, #1733, thanks @he-yufeng and
  @Jackzigen). The Indonesian README lists `get_southbound_flow` and the
  current tool counts. The Quant Library contract table in `README.md` had
  duplicate rows for `credit`, `timeseries`, `factormodel` and
  `multipletesting`; each now has one row with the newer description.

#### Sessions, memory and search

- **Runtime files stay out of a checkout used as the runtime root**. When
  `VIBE_TRADING_HOME` points at the repository, `memory_index.db` (moved to
  the runtime root in this release, and holding memory contents), the paper
  trading `strategies/` folder and `shadow_reports/` were not git-ignored.
  They are now, and the guard test also finds names joined onto the runtime
  root inline or through `*_DIRNAME` constants, not only `*_FILENAME` ones.

- **Session search finds Chinese, Japanese and Korean text** (#1686, thanks
  @Shizoqua). SQLite's default tokenizer treated a run of East Asian
  characters as one token, so a query rarely matched anything shorter than the
  entire run. The ported fix indexes those characters split apart.
  `aac03fa6` reworked it: ideographs, kana and Hangul are indexed one
  character per token in a separate `search_content` column; queries become
  phrase matches; and the stored message keeps its original text for
  snippets. An existing `sessions.db` is upgraded and reindexed once, on first
  open.

- **Session search snippets, limits and concurrency** (#1834, #1827, #1828,
  thanks @rudycelekli). A snippet now centres on the match SQLite actually
  found and highlights that span in the original text. Before, it highlighted
  the query wherever the text contained it, so `alpha` lit up inside
  `alphabet` while `café` (matched by `cafe`) was not highlighted. The result
  limit now counts distinct conversations. Before, the search read only the
  first five matching messages per requested conversation, and one chatty
  conversation could fill them all and hide the others.
  Index writes and searches on the shared SQLite connection are serialized,
  so concurrent callers no longer interleave on one cursor.

- **Renamed conversations show their new name in search** (#1832, thanks
  @rudycelekli). The REST rename and auto-title routes now update the search
  index's title as well. Auto-titling reloads the session after the model
  answers, so updates saved meanwhile are kept, and a manual rename made
  meanwhile is kept with status `kept`.

- **Reconnecting to a session's event stream no longer repeats an event**
  (#1798, closes #1796, thanks @Shizoqua). An event published between the
  replay snapshot and the new subscription reached the client twice, once in
  the replay and once live. Both steps now happen under one lock.

- **Memory search snippets and titles read back as written** (#1682, thanks
  @Shizoqua). A CJK snippet could show its span twice ("使用用移移动…")
  because the index stores both single characters and pairs. A title mixing
  Chinese with a ticker, number or punctuation came back with extra spaces
  (`比特币A策略` became `比特币 A 策略`). Since `8ec3b80f`, highlights and
  `...` truncation markers also survive in snippets built only from character
  pairs.

- **Memory removal, links and recall** (#1697, #1771, #1772, thanks
  @Shizoqua). `remove()`, which the `remember` tool's `forget` action uses,
  accepts a filename stem as `find()` already did. Before, it reported "not
  found" for an entry that `find()` and `vibe-trading memory forget` could
  see. A blank name is refused (`f6e72428`). Semantic links match
  two-character identifiers such as `BP` or `GE`; the minimum used to be
  three. FTS recall skips index rows whose memory file was deleted outside the
  process. The PR fetched four times the requested count; `54e225de` replaced
  that with a window that doubles until enough current memories are found or
  the index runs out.

- **Verifying an archived audit ledger reports a corrupt line instead of
  crashing** (#1721, thanks @Shizoqua). `verify_chain_with_archives` parsed
  every segment with a bare `json.loads`, so a damaged line raised
  `JSONDecodeError`. It now uses the same parser as single-file verification
  and returns a `malformed_json` break at that line's position across all
  segments.

#### Credential redaction

- **Environment-style credential names and URL credentials are redacted**
  (#1765, thanks @cgycorey). `TUSHARE_TOKEN=…`, `AWS_SECRET_ACCESS_KEY=…`
  and `aws_secret_access_key` lines in `~/.aws/credentials` are now caught.
  Lowercase identifiers such as `pad_token` and `max_token` are still left
  alone. `scheme://user:password@host` becomes `scheme://[redacted]@host`, and
  a password containing `@` is handled. A bare username before `@` is redacted
  only when it is a 20-plus-character token, so `git@github.com` stays
  readable.

- **`Authorization: Basic` and other non-bearer schemes are redacted**
  (#1846, thanks @cgycorey). The key pattern used to redact the scheme word
  and leave the base64 `user:password` visible. `Basic`, `Digest`, `Token`,
  `Negotiate` and `NTLM` values are now redacted, but only right after an
  `authorization` label, so prose like "basic information" is untouched.

- **More secret formats are redacted** (#1874, #1866, #1867, #1868, #1869,
  #1870, thanks @rudycelekli). #1874 combined the five smaller PRs. These are
  now redacted:
  - unlabelled GitHub fine-grained (`github_pat_`), GitLab (`glpat-`), npm,
    Hugging Face, Stripe (`sk_`/`rk_` live and test), Google API (`AIza`) and
    AWS `ASIA` keys;
  - PEM and PGP private-key blocks, including a block cut off before its END
    line, which is redacted to the end of the text;
  - `Cookie:` and `Set-Cookie:` header values;
  - fields named like `cookie` or `private_key` in structured payloads.

  Public keys and certificates are left as they are, and running redaction
  twice changes nothing. Since `47de62de`, a quoted header such as
  `curl -H "Cookie: a=\"x\"; b=y"` is redacted up to its closing quote.

- **Telegram bot tokens, Slack and Discord webhook URLs, Groq and NVIDIA keys
  are redacted** (#1880, thanks @rudycelekli). The Telegram token is caught
  inside `https://api.telegram.org/bot<token>/…`, which HTTP error messages
  repeat in full. For a webhook URL, only the secret last path segment is
  replaced. The PR accepted only 8–10 digit Telegram bot ids and lowercase
  `hooks.slack.com`. `2c00cd20` widened that to any length of numeric id, to
  GovSlack (`hooks.slack-gov.com`) and to webhook hostnames in any letter case.

#### CLI, API and scheduling

- **`vibe-trading update` leaves a Git install alone** (#1655, thanks
  @rudycelekli). An install made from a Git URL was treated as a PyPI wheel,
  so the update replaced the user's chosen revision with a released wheel. The
  command now detects `vcs_info` in the install metadata, reports the newer
  PyPI version and tells the user to update from the original source.

- **The terminal dashboard matches parallel tool results to the right call**
  (#1859, closes #1856, thanks @Shizoqua). When several calls to the same tool
  ran at once, progress and results were matched by tool name and recency, so
  results could be swapped between calls. They are now matched by call id.
  Since `47de62de`, a result whose id matches no step gets its own step and no
  longer completes a different call that is still running.

- **CLI limits and number formatting** (#1886, #1926, thanks @rudycelekli).
  `vibe-trading list --limit` and `memory search --limit` reject zero and
  negative values instead of passing them on. Token counts, abbreviated
  numbers and durations switch unit when rounding reaches the next one:
  999,950 tokens shows as `1.0M tokens` instead of `1000.0k tokens`, 999.6 ms
  as `1.0s`, and 59.96 s as `1m 00s` instead of `60.0s`.

- **A cancelled upload leaves no partial file** (#1945, thanks @rudycelekli).
  If the upload request was cancelled while a chunk was being read, the
  half-written file stayed in the uploads directory with no reference to it.
  The file is now deleted and the cancellation is re-raised.

- **More runtime files follow `VIBE_TRADING_HOME`** (#1896, #1904, #1887,
  thanks @rudycelekli). These paths were fixed to `~/.vibe-trading` and now
  use the runtime root:
  - persistent memory and its search index (`memory/`, `memory_index.db`);
  - autopilot run directories;
  - the alpha-bench panel cache and reports;
  - the Gildata code cache.

  The Shadow Account report route also reads from the runtime root, which is
  where the report writer saves. Report links therefore work again when
  `VIBE_TRADING_HOME` is set. Existing files under `~/.vibe-trading` are not
  moved, and the memory paths are read when the process starts.

#### Channels and scheduled delivery

- **IM channels show agent progress again, without repeated lines** (#1878,
  thanks @alexwan02). Channel replies now forward the attempt's status lines
  (working, waiting for the model, using a tool, checking the figures), tool
  hints and opt-in reasoning while the agent runs, so Feishu's streaming card
  and other streaming channels update again (reported in #1792). Only those
  labels go out: answer drafts and tool results stay private, and the final
  answer still passes grounding first. #1878 applies the channel's own
  visibility settings before deduplicating, so hidden tool hints no longer
  break the dedupe and a chat no longer stacks one "Waiting for the model" per
  tool round.

- **Streamed replies are no longer lost or split** (#1860, #1903, #1929,
  closes #1857, thanks @Shizoqua). Telegram (#1860) and Matrix (#1903) dropped
  the whole answer when the live preview message could never be created; they
  now send the accumulated reply as a new message. CI installs the `matrix`
  extra so the Matrix test runs instead of skipping. WeCom (#1929) generated a
  new stream id for every chunk, so progress and the final answer arrived as
  unrelated messages; one id now covers each reply.

- **Email sender authentication cannot be satisfied by forged headers**
  (#1508, thanks @Shizoqua). SPF and DKIM checks read only the single
  `Authentication-Results` header bearing the configured
  `trusted_authserv_id`; with none configured, or with two matching headers,
  verification fails closed. A pass counts only when its domain equals the
  From domain or an aligned `dmarc=pass` is in the same header, and comments
  or quoted text cannot pose as results. The receiving provider must strip
  forged copies bearing its id; the id is not a signature. The guided Email
  setup exposes the setting, and a blank one rejects inbound mail while SPF or
  DKIM checks are on. The PR described trusting the topmost header; what
  shipped selects by configured id instead.

- **URL credentials in channel settings are neither leaked nor erased**
  (#1742, #1744, thanks @cgycorey). Status and config redaction strips
  `user:password@` even when the port is malformed or out of range or the URL
  is followed by punctuation, where it used to return the URL untouched
  (#1741). Saving or testing a form that echoes the redacted URL keeps the
  stored credential instead of overwriting it (#1743); a different URL or a
  clear flag still applies. Connection-test and reset messages, including
  raised SDK exceptions, are scrubbed too.

- **Unchanged empty fields no longer block channel saves** (#1681, thanks
  @zeus229). A nullable setting such as Email's `post_action` was submitted by
  the form as an empty string and rejected with a 422 on unrelated edits. An
  empty value now maps back to null where the adapter's default is null, for
  both Save and Test.

#### Web UI and locales

- **Run trades list every trade, newest first** (#1865, #1877, #1831, thanks
  @alexwan02 and @he-yufeng). The Trades tab and its CSV download used the
  first 500 rows of `trade_log`, which dropped the newest trades of a long
  run; they now use the full `trades.csv` rows (#1865). Rows sort newest first
  with a header toggle, keeping same-time fills in engine order, and the
  symbol filter lists codes in order (#1877). #1831 removes a race in the
  Settings effort-level test that intermittently failed frontend CI; the
  component is unchanged.

## [0.1.16] — 2026-09-29

Rolls up 492 commits / 116 merged pull requests since 0.1.15, from 16
contributors.

The theme of this cycle is a number that can show where it came from. The
final-answer grounding gate stopped guessing what a number is from the words
around it: the model declares each figure's role — observed, derived,
proposed, cited or count — the gate checks that declaration against the
session's tool evidence, and a figure that fails is cut from the answer
instead of the whole answer being refused. A backtest's own output (its
Sortino, turnover, weights and Monte Carlo p-values, not only its Sharpe)
now grounds the report written about it, run cards cite a metric only where
the saved CSV agrees, and the generated broker matrix states each profile's
permissions as declarations rather than as runtime verification. Research
runs stopped losing what they fetched: compaction follows the model's real
context window instead of a fixed 40K estimate that began clearing tool
results from the third step. The missing-data sweep reached 59 more alphas:
15 qlib158 count factors, 20 that filled a missing input with a constant
and 24 comparison gates. Argentina (BYMA), weekly and monthly bars, Bahasa
Indonesia, Gildata, OpenCode, Email and WebSocket channels and four broker
connectors (KIS, Upbit, Toss Securities, Scalable Capital) land alongside.

### Added

- **Stock profiles carry the listing's own identity** (#1577, thanks @Shizoqua).
  `get_stock_profile` returns a `listing` block beside the issuer's
  fundamentals: Yahoo's symbol, exchange, quote type and quote currency, plus
  the financial currency and underlying symbol when Yahoo declares them. A
  secondary listing no longer reads as the primary one. `GOOGL.BA` is an ARS
  line in Buenos Aires carrying Alphabet's USD financials, and `GGALD.BA` is a
  USD line whose issuer reports in ARS. Nothing is inferred from the ticker.

- **Volume statistics in `technical_indicators`** (#1571, thanks @zeus229). The
  tool returns the latest volume, its 20-bar mean and their ratio, computed from
  the bars it already fetched. The mean needs a complete 20-bar window.
  `volume.unit` is the unit the serving source declares (board lots on the
  A-share sources, shares on the Yahoo family, `null` when undeclared), because
  the two are 100x apart and nothing in the numbers tells them apart.

- **Argentina (BYMA) market data** (#1543, thanks @zeus229). A `.BA` symbol — a
  BYMA listing or a locally traded CEDEAR — is its own market `ar_equity`,
  quoted in ARS, served by `yahoo` → `yfinance` → `local`, and reported as
  market `ar` by `get_stock_profile`. Execution is deliberately not modelled: an
  Argentine backtest raises instead of borrowing US or crypto commissions, lot
  sizes, settlement and short-selling rules. The Web UI carries the market too —
  Settings source priority, the positions asset-class grouping and the sector
  union — and with it `uk_equity`, `vietnam_equity` and `index`, which had been
  missing from one or more of those three since they landed. `EnvConfig.data`'s
  per-market `MARKET_DATA_ORDER_*` fields are now guarded against
  `FALLBACK_CHAINS` instead of a hand-written list, which is why `uk_equity`
  never had one.

- **Weekly and monthly bars** (#1479). `get_market_data` and backtests take
  `1W` and `1M` (and `1w` / `1wk` / `1mo`). Loaders are still asked for daily
  bars; `loaders.base.resample_bars` builds the period bar at the three fetch
  boundaries (runner, market data, benchmark), so a weekly bar is the same
  whichever source served the days, at that source's daily caliber. A week
  runs Monday to Sunday, a month is a calendar month, and each bar is dated on
  the last trading day inside it: first open, highest high, lowest low, last
  close, summed volume and amount, volume-weighted vwap, mean funding rate.
  Annualisation is 52 / 12; a weekly perpetual bar settles 21 funding periods.
  `1M` is matched before any case fold, which read it as one minute in
  strict-100x validation and in attribution (98,280 bars a year). The
  technical-indicator tool canonicalises its documented `1wk` / `1mo` and
  fetches whole periods instead of two days per bar.

- **IM channels are configured from the Web UI** (#1520, #1529; #1519, #1530,
  thanks @shadowinlife). The Settings panel renders each built-in channel's
  fields from backend metadata, masks secrets (`****` plus the last four
  characters, never sent back), tests the unsaved form against the provider
  (`ok` / `invalid_credentials` / `network` / `unsupported`), and hot-swaps only
  the saved channel with no restart. DingTalk and QQ have guided setups; a
  shared token probe backs both. Saves write `channels.<name>` in
  `~/.vibe-trading/agent.json` atomically at mode 0600; a YAML config is shown
  read-only. Reloads of one channel are serialized in `ChannelManager`, and
  `stop_all` cancels a reload's start that is still connecting.

- **Email and WebSocket join the guided Web UI channel setup** (#1544, after
  #1519, thanks @shadowinlife). Both channels get hand-written field metadata —
  localized labels, masked secrets — plus connection tests and per-channel hot
  apply. Email's test probes the real IMAP login, mailbox select and SMTP login
  without ever sending a message; WebSocket is a server channel with no remote
  credentials, so its test validates the TLS cert/key material and binds every
  resolved address locally — an address held by the already-running server reads
  as the expected state, not a failure. Saving a WebSocket config hot-swaps the
  server: connected clients (including the Web UI chat) briefly disconnect and
  reconnect. A hand-written field hint's secret flag is now authoritative for
  the keys it covers — the regex fail-safe still masks every unhinted key — so
  token-shaped non-secrets such as `websocket_requires_token` stay visible and
  editable instead of being masked, and a form save can no longer silently flip
  the stored token requirement. The web config routes now build the WebSocket
  adapter with the gateway services it requires; previously every WebSocket save
  or test failed validation. Email's polling loop also skips stale-config
  delete/move post-actions once a stop or hot swap begins, while the
  already-fetched batch is still delivered. Both the probe and the polling loop
  now send an RFC 2971 IMAP `ID` after login: NetEase mailboxes
  (163/126/yeah.net) accept the login but reject the first `SELECT` with `Unsafe
  Login` until the client identifies itself, so without this the Email channel
  could not read the most common Chinese mailboxes. The identification is static
  and carries no user data or secrets, and servers that ignore `ID` are
  unaffected; verified end-to-end against a live 163.com account.

- **Bahasa Indonesia** UI locale and `README_id.md` (#1482, thanks @Yoruxyv).
  The README count tests cover it, and `MANIFEST.in` now ships `README_es.md`
  and `README_id.md`.

- **Portfolio valuation accepts any ISO-4217 currency** (#1510, thanks
  @zeus229). A source whose currency has no FX rate fails with the currency
  named and is excluded from the totals; the healthy sources stay in.

- **Gildata (恒生聚源) joins the A-share fallback chain as a token-gated source**
  (#1474, thanks @sambazhu). The new `gildata` loader talks to the vendor's
  raw-api MCP endpoint (one JSON-RPC POST per call, token in the Authorization
  header) and serves A-share daily OHLCV through the `StockDailyQuote` tool with
  `restorationStatus=1` — forward, split-AND-dividend adjusted bars, stamped
  `split_dividend` in the price-caliber table after being measured against a
  live payload. Volume arrives in 万股 and is converted to shares (`volume_units:
  shares`); `avgprice`/`prevcloseprice` are ignored because the vendor keeps
  them on a different adjustment basis than the adjusted OHLC. An unresolvable
  symbol answers `rows: []` (never an error), so the chain keeps walking. Auth
  is `GILDATA_TOKEN` (Settings page field or env; `GILDATA_BASE_URL` overrides
  the endpoint, `VIBE_TRADING_GILDATA_MIN_INTERVAL` the 0.3s default spacing).
  Without a token the loader reports unavailable and the chain skips it — no
  behavior change for existing users beyond one reorderable entry at the chain's
  tail. One migration note: a `MARKET_DATA_ORDER_A_SHARE` value saved before
  this change is a permutation of the old 7-source chain, so it stops validating
  once `gildata` joins — the Settings card flags it and the default order
  applies until the saved order is re-saved (one click) with the new source
  included.

- **A Robinhood account can be a read-only portfolio source** (#1428). The new
  `robinhood-live-mcp-readonly` profile uses the same MCP server and OAuth
  grant as the trading profile. Its connection reads exactly one account,
  picked from Robinhood's own `get_accounts` list in the connection center or
  with `vibe-trading connector select-account <id>`. Nothing is preselected,
  and a source with no account errors before any broker call. Holdings come
  from `get_portfolio` and `get_equity_positions` and are mapped only from the
  shapes the reporter posted. A second page of positions, a null list or item,
  or an unknown field is an error, not a shorter account. Positions show
  quantity and cost but no price until the quote reply is mapped. An account
  that also holds options, crypto, futures, event contracts, mutual funds or
  fixed income fails the source instead of showing an equity-only view.

- **A weekly health check of every keyless data source** (#1627, closes #1623,
  thanks @he-yufeng) — `python -m backtest.loader_health` fetches one liquid
  symbol from each of the 15 keyless network loaders, each in its own process
  with a temporary home, no inherited keys and the loader cache off, and
  requires normalised OHLCV whose last bar is at most 14 days old. The
  `Public loader health` workflow runs it every Monday and on demand. An
  unreachable endpoint, a missing dependency, malformed bars and a stale
  series all fail the lane; as first proposed, an unreachable endpoint counted
  as a skip. An offline test fails when a new keyless loader has no canary
  symbol.

- **OpenCode is a built-in provider, and each request carries the session id
  OpenCode Go requires** (#1416, closes #1415, thanks @tonydo) —
  `LANGCHAIN_PROVIDER=opencode` with `OPENCODE_API_KEY` / `OPENCODE_BASE_URL`,
  in Web Settings and both CLI onboarding flows. OpenCode Go refused every call
  without `x-opencode-session` (400 `MissingSessionID`); the adapter now sends
  the run's session id to any `opencode*` provider or `opencode.ai` host, and
  the compaction summary call, made on its own thread, carries the same id
  (`fd6c7c7c`) instead of reaching OpenCode as a second conversation.

- **KIS (Korea Investment & Securities) is a connector for KOSPI and KOSDAQ
  equities** (#1407, thanks @as950118) — paper (모의투자) and live sit on
  separate hosts with separate OAuth tokens, so the paper-trade profile sends
  orders to KIS's own paper server rather than a local simulator. Live is
  read-only: no `kis-live-trade` profile exists, and `place_order` /
  `cancel_order` refuse a non-paper config before anything else. A finishing
  commit (`970c235f`) pins the paper sell and cancel TR_IDs, which no test
  covered, and makes a balance or order walk that hits its 20-page cap raise
  instead of returning a short position list that reads as complete.

- **Upbit is a KRW crypto connector, capped at paper plus read-only** (#1408,
  thanks @as950118) — one key pair reads the same account whatever profile is
  declared, so there is no runtime paper/live discriminator and no live order
  path. Paper orders are simulated against a live Upbit quote: no quote means
  no fill, a limit order fills only if immediately marketable, and cancel
  acknowledges only ids the simulator issued. Needs
  `pip install "vibe-trading-ai[upbit]"`.

- **Toss Securities is a read-only connector for Korean and US equities**
  (#1409, thanks @as950118) — Toss documents no sandbox and no paper/live
  discriminator, so, like Trading 212, it refuses every order and cancel,
  paper included. Reads follow the published schema (`/api/v1/holdings`,
  `/api/v1/orders`); closed-order history is paged to completion, and a walk
  past its cap, or a `hasNext` page with no cursor (`b5ff36ba`), is an error
  rather than a silently truncated list.

- **Scalable Capital is a read-only MCP connector that declares quotes only**
  (#1417, thanks @cgycorey) — Scalable has no paper account and publishes tool
  names without argument schemas. `scalable-live-mcp-readonly` withholds
  `account.read` / `positions.read` because nothing maps the holdings reply
  yet: declaring them made it a portfolio source whose refresh stored a
  complete snapshot with zero positions. The 29 published tools are pinned
  literally as 18 read and 11 write (unknown names resolve to write), and a
  hand-enabled order tool is wrapped by the live order guard and refused.

- **The README's broker capability matrix is generated from the profile
  registry** (#1629, thanks @he-yufeng) — one row per built-in profile (55
  across 18 connectors): environment, transport, read-only or write-enabled,
  declared reads, and whether placement requires a mandate. A test fails CI
  when the block and the registry disagree; regenerate with
  `PYTHONPATH=agent python -m src.trading.capability_matrix`. As merged it
  folded each connector into one row; `dec2c0e6` renders each profile on its
  own, so a paper order capability never reads as a live permission, and
  says the rows are declarations, not runtime verification.

- **Run cards record the backtest's execution and cite metrics against the
  saved CSV** (#1612, closes #1610, thanks @lorenzozanee) — `run_card.json`
  (schema `1.0`) carries a trace with UTC start and end, status, and SHA-256
  hashes of the config and the metrics, never the payloads. As merged, every
  scalar metric was cited whenever `artifacts/metrics.csv` existed; after
  `0244ecea` a metric is cited only when its value matches the file's single
  data row and the file matches its manifest checksum. The Markdown card and
  the Run Detail page show both sections.

- **A read-only extraETF export reader** (#1406, thanks @cgycorey) — the
  Investments export becomes positions and the Transaktionen export typed
  movements, so a `Dividende` row is never read as a holding and a
  transactions file cannot pass as a portfolio. It fails closed on anything it
  cannot read without guessing (unknown header or label, US-ordered numbers,
  more than 8 decimals, one instrument twice under one Portfolio ID). Nothing
  calls it yet; the portfolio container side is still open under #1170.

- **Strategy-store adaptation substrate** (#1391, thanks @modelpath-dev) — a
  child strategy points at its parent through `derived_from` (SQLite schema 3,
  an additive nullable column), and `AdaptationPatch` can change only
  universe, name and position sizing, never `signal_definition`. The child
  starts with no evidence and `UNVALIDATED`; `a7bd2e30` also clears the
  parent's validator, approver and versions, and makes `register_adaptation`
  require the parent's evidence, refusing a stale or insufficient parent.
  Nothing outside tests calls it yet (#1149 stays open).

### Changed

- **`source="qveris"` refuses markets with splits and dividends** (#1494). It
  picks a capability by search rank, which ignores adjustment: for 600519.SH
  the top pick was FMP's non-split-adjusted EOD, and a tool named adjusted
  returned raw closes. Stocks and ETFs are refused before anything is searched
  or billed; crypto, forex, futures, macro and index bars are served as before.
  Both QVeris budget gates reserve only a flat per-call quote now:
  `1 credits/result` had reserved 1 credit for a call that billed 9.66, and
  `qveris_execute` returns `quote_not_bounded` for any other shape.

- **A price index is stamped `raw`** (#1541). Eastmoney's fqt=1 equals fqt=0 on
  every bar of the A-share indices measured, Tencent serves only `day` for the
  SSE/SZSE ones, and Yahoo's adjclose equals close on ^GSPC / ^NDX / ^HSI, but
  the per-source table stamped an A-share index additive and a Yahoo index
  dividend-adjusted. `price_caliber` takes the symbol; A-share index codes are
  matched per exchange, since 000001.SZ is Ping An Bank.

- **Portfolio valuation version 3** (#1510, thanks @zeus229): snapshots stored
  under version 2 are no longer read, so portfolio history starts again after
  upgrading.

- **Tencent, Eastmoney and AKShare A-share prices are labelled
  `split_dividend_additive`** (#1497, #1493, thanks @cgycorey). Their forward
  adjustment subtracts cash dividends from the level instead of scaling by a
  ratio (on 600519.SH, qfq minus raw takes five values over 500 bars against 367
  distinct ratios), so a basket mixing them with multiplicative sources warns,
  and a run served only by them warns that its returns are not total returns.
  Tencent's HK series is labelled `raw`: it serves no adjusted HK bars. The
  prices themselves are unchanged.

- `connector account` renders Binance spot balances as Asset / Free / Locked /
  Total, Futu's per-currency `assets`, and Trading 212's `cash` and `metadata`
  (#1539); before, Binance printed blank rows and the other two printed "No
  account summary returned."

- **The final-answer grounding gate no longer guesses what a number is from the
  words around it.** Only a number's SHAPE is inferred — a decimal point, a
  percent sign, a currency mark or a table cell makes it a measurement; dates
  (including year-less "09-14"), years, security codes, line-leading ordinals
  and code in a language-tagged fence are structure; a plain integer is checked
  only as a price of an instrument quoted in the thousands — so a sentence gets
  the same verdict in every language. A measurement that equals a price or
  volume this session's tools returned needs nothing more. Any other one is
  declared in a fenced `figures` block at the end of the answer, one line per
  figure — `value | role | note | ref` — and checked by role: `observed` must
  appear in the referenced call or tool (`ref` may name either), filtered to the
  figure's own symbol, with a currency-marked figure compared only against
  money-denominated values and a percent only against non-price ones; `derived`
  needs an evaluable formula whose added or subtracted operands are all
  observed, matching the figure at the precision and sign it was written with;
  `proposed` is a price inside its own symbol's observed range or a derivation;
  `cited` must name its source on the figure's own line, because the block is
  stripped before anyone reads the answer; `count` covers counts, weights,
  thresholds and probabilities, while a currency-marked figure, or one inside
  its instrument's price range that no derivation uses as a factor, is checked
  as observed when declared `count`. No role other than `observed` may sit in a
  price column. The block is stripped from the released answer and never
  streamed; the artifact keeps it. The price-word, level-word, derivation-phrase
  and metric-subject catalogues are deleted with it (65 compiled regexes → 12,
  all shape), and `src/agent/grounding.py` is now the `src/agent/grounding/`
  package.

- **A rejected answer costs one correction round, not four, and is then
  released with its failing figures cut rather than refused.** The correction
  prompt lists every failing figure as written, with its declared role and what
  the evidence says (the observed range, the nearest observed values, or what
  its own formula evaluates to, in the figure's units), and names the three
  ways out: declare, rewrite to an observed value, or remove. If the second
  draft still fails, each failing figure is replaced by `（略※）` /
  `(omitted※)` at its own span, bare-integer restatements of a cut figure are
  swept too, a footnote says how many were omitted and why, and the whole
  document — footnote included — must pass the same gate before release. The
  canned fallback is left for an identity finding, a run that never observed a
  price, or a cut that still fails. Drafts that triggered bounded
  `search_symbol` / `get_market_data` recovery do not spend the correction
  budget. The run stays `degraded` with a reason naming the redaction, the
  release path's rechecks are not counted as rejected drafts, and the shipped
  document is recorded under `released` in `artifacts/grounding_evidence.json`.

- **A draft missing only a source or currency word gets a data note appended,
  not another model round.** The canonical symbol is deliberately not repaired
  this way: it is the figure's subject, and a note naming it under an answer
  about another instrument would footnote a misattribution.

- **The chat shows that the answer is being checked.** The agent loop emits
  `grounding_status` (`{stage: "revising", round, issues}` after a rejection,
  `{stage: "released_redacted", removed}` before a cut release), and the chat
  page shows "Checking the figures in this answer (round N)…" until answer text
  arrives, in all eight locales.

- MetaTrader 5 no longer picks a broker alias when several match
  (`47a036d6`, with #1597 and #1598). Quotes, history, orders, symbol search
  and the backtest loader took the shortest suffixed name (`EURUSDm` over
  `EURUSDz`); they now refuse and ask for the exact native symbol. The
  connector still tries a configured `symbol_suffix` first; the backtest
  loader does not read it.

- `run_card.json` `schema_version` is `1.0` (was `0.1`), with the optional
  `tool_traces` and `citations` keys from #1612.

- Broker connectors: 18, up from 14 (KIS, Upbit, Toss Securities, Scalable
  Capital). `test_readme_counts.EXPECTED_BROKERS` is checked against the
  profile registry, not incremented by hand.

- The opt-in loader cache is at version 7 (#1411, thanks @shadowinlife). Entries
  written under version 6, which include Tencent series the forward walk
  truncated, are never matched again and are fetched afresh.

- `VIBE_TRADING_BAOSTOCK_TIMEOUT` (default 30 seconds) bounds each BaoStock lock
  wait, connection and complete message (#1615, thanks @he-yufeng). It is not a
  deadline for a whole multi-symbol fetch.

- The `a_share` fallback chain is `tencent`, `mootdx`, `eastmoney`,
  `baostock`, `akshare`, `tushare`, `gildata`, `local` (#1474, thanks @sambazhu).

- Factor values change for 23 alphas, so an IC, bench or comparison stored
  before this release is not comparable with one computed after it:
  `qlib158_cntp*` / `cntn*` / `cntd*` (15 factors; the first value lands one
  bar later and windows touching a gap are NaN, #1459), `qlib158_wvma5` …
  `wvma60` (5; every value, #1594), and `gtja191_103` / `133` / `177` (3;
  direction and scale, #1604). Patell z for `market_adjusted` and
  `mean_adjusted` event studies moves slightly as well (#1449, thanks @Shizoqua).

- **A grounding correction turn is offered no tools** (#1600, thanks @zeus229)
  — after a rejected draft the model was handed every tool again, so revising
  a figure could restart research. Unless the gate asks for recovery (an
  unresolved symbol or a missing price), the correction turn gets none. A call
  made anyway is not run and, since `47a036d6`, spends one of the two
  correction rounds; at the cap the last real draft goes through the existing
  cut-and-recheck release.

### Removed

- **The Requesty built-in provider.** Its capabilities were OpenRouter's, with
  no adapter of its own. Same request shape: `LANGCHAIN_PROVIDER=openrouter`,
  `OPENROUTER_BASE_URL=https://router.requesty.ai/v1`, and the Requesty key as
  `OPENROUTER_API_KEY`.

### Fixed

#### Long research runs stop losing what they fetched

A user's two runs on the Codex provider (GPT-6 Sol) failed as "0 steps ·
no_progress": a risk-parity backtest after 1m03s and a comparison of A-share
and Hong Kong game companies after 4m50s. They were two different failures.

- **Context compaction follows the model's real context window** — compaction
  fired at a fixed estimate of 40,000 tokens (characters / 4 of the messages,
  not counting tool definitions), while the system prompt alone is about
  12,500 of them. From the third step it cleared every tool result but the
  last three, so a comparison across a dozen companies re-fetched the same
  filings until the no-progress stop: reproduced on v0.1.15 with DeepSeek V4
  Pro, seven A-share issuers' filings fetched four to five times each, stop at
  iteration 16; with a larger budget the re-fetches went from 54 to 0. The
  window now comes from `VIBE_TRADING_CONTEXT_WINDOW`, else a limit learned
  from the provider's own context-length error during the run, else
  `src/providers/context_windows.json` (272K for the Codex GPT-6 / GPT-5.6
  models, 1M for DeepSeek V4, each entry naming its source), else 128K, and
  `VIBE_TRADING_CONTEXT_MAX_TOKENS` (200K) caps what a prompt may cost. Usage
  is read from the input tokens the provider reports. The three layers fire at
  80 / 90 / 100% of what the system prompt and tool schemas leave, and clear
  the oldest results first, only down to the line. A context-length error is
  compacted and retried instead of failing the run. `TOKEN_THRESHOLD` is
  deprecated and ignored with a warning; remove it from `.env`.

- **`read_file` says where the agent may read, and lists a directory** — the
  1m03s failure: on the same prompt, a live DeepSeek V4 run went looking for
  the backtest engine's source (`../../agent/src/backtest`, the checkout's
  absolute path, `skills/../backtest/engine.py`) and every attempt got the same
  "File not found or path escapes workspace". Each spelling was a new call and
  none an observation, so eight rounds exhausted the no-progress budget in 93
  seconds, before any backtest ran. The refusal now names the case
  (`outside_readable_roots` or `not_found`), the readable roots (the run
  directory and `skills/`) and where the engine's contracts are documented
  (`load_skill`); a directory inside those roots returns its entries. The
  boundary itself is unchanged.

- **A failed or cancelled run keeps its steps** — only a completed run saved
  its tool trail, so the Web history showed "0 steps" for exactly the runs
  someone would want to inspect.

- **A no-progress stop says which calls produced nothing, and why** — each
  failing or repeated call is listed with its reason and count ("read_file
  failed (… not found) ×3"), instead of a message about previous summaries
  and artifact paths written for a different failure.

- **`get_market_data` fails when no requested symbol returned data** — an
  envelope holding only `_unresolved` was a success, so a run whose sources
  were all down counted it as progress. It is now `error_code:
  no_market_data`; a partial result is still a success, and grounding still
  records every symbol as unavailable.

- **Codex (ChatGPT sign-in) keeps the system prompt, its reasoning and its
  call ids** — a system message the loop adds mid-run (a retry hint, a
  write-the-file reminder) replaced the whole 49,000-character system prompt
  for every later request; it is now sent as a developer message, as the
  Codex CLI does. Reasoning items are carried from turn to turn the way the
  Codex CLI replays them, and resent without them if the backend refuses;
  tool calls keep the item ids the backend issued instead of a fabricated
  `fc_0`; the prompt-cache key is stable for the session instead of changing
  on every request. The default Codex model is `gpt-6-sol`: `gpt-5.4` is
  refused for ChatGPT accounts.

#### A backtest report is checked against the backtest

A risk-parity versus equal-weight report ended in the canned refusal in 12 of
15 replayed runs. Replaying all 26 stored drafts through the gate (880 of 882
recorded rejections reproduced) showed that four in five refused figures were
values the backtest itself had written.

- **A backtest's own output grounds the report about it** — only metrics
  whose names the gate knew (Sharpe, return, drawdown, volatility, win rate)
  were evidence. Every scalar of the run card, the metrics row, the risk
  X-ray, the Monte Carlo validation and the rebalance summary now is (lists
  such as the 1,000 simulated Sharpes are not descended, and a file other than
  the metrics must match the run card's SHA-256 manifest). A per-bar table
  counts only for the rows a `read_file` showed, while it is still byte for
  byte what the engine wrote; a file the model wrote is never evidence. A
  figure may name the run it came from — `rp`, `rp/artifacts/metrics.csv`,
  `risk_parity target_positions.csv`, `rp::sortino` — and a value from one
  backtest does not ground a figure declared from another. Replayed:
  `value_mismatch` 196 → 1, `not_in_referenced_call` 167 → 7. On the same
  runs a real value declared with its run passes 97% of the time and the
  same value moved 2–10% passes 0.7%; the undeclared path was deliberately
  not widened (the whole metrics row there would have passed 16% of invented
  values).

- **A comparison's arithmetic is read as it is written** — a formula glued to
  its labels ("等权 Sortino 1.2115 − 风险平价 1.1329") or followed by a
  bracketed aside was "not arithmetic"; an operand written as a percent was
  read as a whole number, so "13.28% − 12.98%" anchored on nothing and
  "0.666 × (1 − 3%)" computed the wrong value; a sum of squared weights
  (HHI) could not be written at all; a formula's negative operand (a
  drawdown) could never anchor; and a field two runs both hold anchored
  neither. All now evaluate (only a literal square or cube is accepted as a
  power), and the ones that still fail are the model's own arithmetic.
  A declared value may be a fraction (`1/3`) or a multiple (`5.5x`).

- **A report that still fails after a completed analysis is released with the
  failing figures cut** — naming a symbol made any request a market answer,
  and a market answer with no fetched price was never released cut. A
  completed analysis now is; a price question with neither prices nor an
  analysis still gets the refusal, and the refusal after an analysis no
  longer says the draft cited prices.

- **A draft ending in DeepSeek's closing tool-call tags is caught** —
  `</｜｜DSML｜｜invoke>` slipped past the pattern for opening tags and reached
  the gate as unreadable declaration lines.

- **A correction says what went wrong with a figure the model did declare** —
  `0.3897` and `38.97%` stay two assertions, and so do `−1.51pp` and a formula
  that computes `+1.51`, but the model is now told which value it declared
  (also when it has the opposite sign) and that its formula runs the other way
  round, instead of "not declared" or "its own note evaluates to 1.51%". In a
  live run after the evidence fix, eight differences were still cut because
  the second draft rewrote the numbers rather than the formulas. The
  correction also asks for the corrected answer alone, in the user's
  language: that draft had opened with "The rejection was because…", in
  English to a user writing Chinese, and the sentence was released.

#### The grounding gate

- **A tail-risk figure names its own field once a session holds more than one**
  (#1425, after #1444, thanks @he-yufeng). A call- or tool-scoped ref (`ref x1`)
  pooled every tail-risk field that call returned, and an undeclared tail-risk
  percent pooled every tail-risk value in the session, so an ES 95% could quote
  the VaR 95% value and pass. The rule is read off the evidence, never off
  prose: `tail_risk_identity()` takes (measure, confidence) from the field name
  a tool returned, so `var_95` and `es_95` are two identities while `cvar_99`
  and `es_99` are one. When a scope holds two or more and the figure's value
  matches one of them, it is refused with `tail_risk_needs_field_ref`, whose
  correction names every identity the session holds; a figure matching no
  tail-risk value keeps its old reason, so a fabricated number is still a
  mismatch rather than a missing ref. Accepted cost, stated in the issue: an
  undeclared VaR 95% beside a VaR 99% is correct today and now costs one
  correction round. The system prompt states the rule so a risk report declares
  the ref on its first attempt.

- **Tail-risk figures keep their identity under a field ref** (#1444, thanks
  @he-yufeng). A declared `ref` may name an evidence field by its full path
  (`data.tail_risk.var_95`) or trailing part (`var_95`), or one call's field
  (`q1::historical_var`); a VaR 99% quoting the 95% value, or ES quoting VaR, is
  rejected under such a ref. A field two calls returned with different values is
  ambiguous and the correction names the refs to choose from. A claim scoped to
  a whole call or not declared is still matched against every tail-risk value it
  can see (#1425 stays open).

- The grounding gate reads decimal commas (#1517, thanks @zeus229): `17,93 %` and
  `1.410,00 CNY` ground against tool results, two unspaced numbers such as
  `1400,1777` stay two numbers, and a written figure must match its evidence
  within half a unit of its last written digit (a truncated `30.20%` for
  30.2052% is now sent back for correction). One shape regex added (14 → 15).

- **A redacted answer keeps its row numbers and its labels** (#1471). When the
  grounding gate released a draft with its unverified figures cut, a ranked
  table came back with `(omitted※)` in place of 1, 2, 3, of the `12m` in its
  headers and of "3 names" in the prose. Every integer in a table cell was a
  measurement, so the rank column was cut; and each cut figure's digits were
  then swept out of the rest of the page, single digits included. Three shape
  rules, no word list: a column whose numbered cells read 1, 2, 3 … in row
  order is the table's index; a plain integer in a cell that also holds a
  word (`12m mean return`, `Mean beta (9 reported)`) is read as it would be
  in a sentence, while a cell that holds only a number, any decimal, percent
  or currency figure, and every cell under an OHLC column stay measurements;
  and the sweep never keys on a single digit. An integer price of an
  instrument quoted in the thousands is still checked inside a worded cell.

- **A real VaR result grounds the VaR it returned** (#1464). `quantlib_call`
  records a scalar result under the function name. For `historical_var` and
  `parametric_var` that name reduces to `var`, which the grounding gate accepts
  only as a whole field name, so the result recorded no evidence and a correct
  answer quoting it was rejected. Both names are now tail-risk aliases.
  Variances such as `residual_var` stay unmapped.

- **Plain integers in prose are not price claims.** A list number ("输出原则
  4"), a window length or a count was checked like a quoted price and could be
  cut from a released answer.

- **A drawdown against an observed high passes wherever the endpoints are
  written.** "较 5 月高点 1.053 元已回撤约 37%" was rejected when its endpoints sat
  on another line; a `derived` declaration does not depend on layout.

- **Price-denominated indicator values are evidence, by registration.**
  Moving averages, Bollinger bands and similar levels returned by
  `technical_indicators` are registered per tool as observed price evidence;
  RSI, MACD and other non-price leaves are not, and nothing is decided from a
  field name's words.

- **A year-less date is a date, and "24.6M" is 24.6 million.** Two real runs
  that followed the contract were still released redacted: "2026-09-11 /
  09-14" in a table cell shipped as "2026-09-11 /（略※）-（略※）", and
  "24.6M → 22.6M lots" as "(omitted※)M → (omitted※)M". A zero-padded MM-DD,
  or one opened by a full date in the same cell or line, is structure (an
  unpadded "| 11-12 |" is still checked, since it may be a price range). K / M
  / B / 千 / 万 / 亿 glued to a figure scale its comparison with the evidence,
  never its shape, and a cut removes the mark with the figure. Replayed on
  both runs' tool results, each second draft now passes as written.

- **Metadata counts are not metrics, and a tool's tail-risk result can ground
  a VaR** (#1420, #1426). `return_observations`, `n_returns`, `return_window`,
  `vol_lookback`, `max_drawdown_duration`, `aligned_days` and their `*_window` /
  `*_lookback` / `*_obs` / `n_*` / `*_count` / `*_days` / `*_duration` families
  no longer ground a percentage ("年化收益 81%" from 81 observations); `var`,
  `var_95`, `var_99`, `cvar`, `es` and `expected_shortfall` leaves are tail-risk
  evidence, so a correct VaR is no longer refused. A field's metric comes from
  the head of its name, so `sharpe_sample_size` and `drawdown_threshold` are
  no longer a Sharpe ratio or a drawdown.

- **A correction names the prints of the figure's own instrument** (#1433). The
  "nearest observed" values come from that symbol (and its table column or
  `ref`), not from every field of every symbol in the run.

- **A number is read the way the chat renders it** (#1418). Zero-width
  characters, a full-width or Arabic decimal point, a no-break space before "%",
  the U+2212 minus sign, a backslash escape ("0\\.888"), an HTML entity and an
  ISO code glued to the digits ("CNY0.888") no longer split a price into
  unchecked integers; a decimal comma ("0,666 CNY", "12,5 %") is a decimal while
  a valid grouping ("-1,250.00") stays grouped, and an answer that writes a
  marked decimal comma reads "2,237" and "−5,132%" beside it as decimals too.
  Fences follow CommonMark, and an unterminated code fence no longer exempts the
  rest of the answer.

- **A year is not a price shield.** "$2050", "1999 元" and a 2031 under a close
  column are checked; a price placed in a date or code column is checked; a
  compact date, a dotted date and a time are structure. 円 and 원 are currency
  marks, and "52pp" / "5200bp" are measurements.

- **A declaration cannot relocate or launder a figure.** A figure the sentence
  writes about one instrument cannot be declared another's close; a
  currency-marked result cannot be derived from an RSI or a volume; `count`,
  `derived` and `proposed` cannot sit in a price column.

- **A general answer with no tool evidence is cut, not refused.** A question
  about no instrument ("印花税怎么收") whose figures the gate cannot check is
  released with those figures omitted and a footnote, instead of a refusal
  about prices it never mentioned; a market answer that observed no price
  still falls back. A malformed figures block no longer forces the fallback
  either: the block is dropped and the draft is checked as written.

- **The tool-call-syntax fallback reaches the chat once.** When a model answered
  the forced-text iteration with tool-call markup in a run whose output is
  buffered, the replacement message was streamed by its own branch and again as
  the released answer, so the chat and the CLI showed it twice.

- **No unchecked number reaches the chat before the gate runs.** An unbuffered
  answer (no instrument asked about, no tool evidence yet) streamed its first
  draft live, numbers included, and a rejection then replaced it; the stream now
  stops at the first measurement-shaped number, and a rejected draft's shown
  prefix is cleared with `stream_reset`.

- **A trading plan in a bare code fence is checked.** Only a fence tagged with a
  language holds code; an untagged fence is read as prose.

- **An integer price of an instrument quoted in the thousands is checked**
  ("600519.SH 最新收盘 1520"), within half to twice its observed range; a
  window such as "200 日均线" stays unchecked.

- **A price declared `count` is checked.** A number inside its instrument's
  observed price range may be a `count` only when a declared derivation uses it
  as a factor.

- **A redaction footnote the model wrote itself is removed** before the real
  cuts, so a released answer never carries two contradictory footnotes or a
  marker for a cut that did not happen.

- **A figure about a second instrument is checked against that instrument's
  evidence** (#1584, thanks @zeus229) — symbol resolution saw only
  price-comparable records, so a line naming an instrument the session held
  only fundamentals for took the answer's primary symbol and failed as
  `not_in_referenced_call`. Any observed evidence with an explicit symbol now
  resolves it; `47a036d6` scopes analysis metrics likewise, so a metric from a
  call about another symbol, or several, cannot ground it.

- **A field ref may contain `|`, and a correction for an ambiguous field lists
  the exact refs to use** (#1586, thanks @zeus229) — the `figures` parser
  split on every `|`, cutting such a ref short; a declaration is four columns
  now, the last taking the rest of the line. When several calls returned a
  field, the correction lists each valid `call_id::field` (only the figure's
  own symbol's since `47a036d6`), and a `tool_name::field` ref is refused as
  `field_ref_needs_call_id` with that list.

- **A decimal-comma answer's dot-grouped integers are read as thousands**
  (#1588, thanks @zeus229) — `AR$5.165; volumen 502.408` was read as two
  decimals and failed as `figure_undeclared`. Once a document writes a decimal
  comma, now including a `0,` with two or more digits, `5.165` is 5165 and is
  still checked; without that evidence it stays 5.165. The PR's wider 1%
  rounding band was not kept (`47a036d6`): at 0.5%, 0.82467 has to be written
  `0,825`, not `0,82`.

- **Figures from `technical_indicators` keep the date the tool reported**
  (#1590, thanks @zeus229) — the tool dates its snapshot as `latest_date`, a
  key evidence ingestion did not read, so `latest_close`, the indicators and
  the volume metrics landed in `grounding_evidence.json` with
  `timestamp: null`. It is inherited now, below a row's own date fields and
  above `as_of`; an undated payload stays undated.

#### Market data

- **`get_market_data` asks for `AAPL.US` instead of returning empty frames for
  a bare US ticker** — only codes the market detector reads as US equities
  are refused; a Chinese futures code (`RB0`, `IF2412`) or a joined crypto
  pair (`BTCUSDT`) is served as written. The public-source health canary
  probes Yahoo with `AAPL.US` for the same reason.

- **A mixed-market backtest falls back per market** — a symbol missing from
  its primary source was retried along the fallback chain of the first
  symbol's market, so a Hong Kong gap in an A-share-led universe was never
  retried on a Hong Kong source. Each missing symbol now follows its own
  market's chain, and the incomplete-data error lists which symbols were
  served.

- **A dollar-quoted BYMA or TSX line, or a Hong Kong RMB or USD counter, no
  longer enters a single-currency backtest** (#1576, after #1543, thanks
  @Shizoqua, @zeus229). Both venues list USD lines beside their home-currency
  ones. On 2026-09-24 Yahoo declared USD for GGALD.BA (4.20), SPYD.BA and
  AAPLD.BA, and for DLR-U.TO and XUS-U.TO. `ar_equity` and `ca_equity` are each
  one static-currency pool, so such a line was priced as pesos or Canadian
  dollars. As on the LSE, the loaders now read the declared currency. They admit
  a `.BA` line only in ARS and a `.TO` / `.V` line only in CAD. A trailing `D`
  does not decide it: YPFD.BA is a peso line. Every other declared quote
  currency is recorded in market-data provenance, and the grounding gate asks an
  answer to name that currency rather than the one the suffix implies. Hong Kong
  is decided by the code, because the Hong Kong chain starts with sources that
  declare no currency: HKEX's Stock Code Allocation Plan assigns 80000-89999 to
  products traded in renminbi and several 09xxx ranges (plus 10900-10999 and
  41500-41599) to products traded in USD. So an RMB counter (80700.HK, 375.40
  CNY on 2026-09-24) or a USD ETF (9834.HK) is refused in a Hong Kong or
  cross-market backtest, is counted in its own currency by the mixed-currency
  guard, and is quoted in that currency by the grounding gate, whichever source
  served it. The table matched the currency Yahoo declared for all 24 codes
  probed across the ranges.

- **Grounding identity and symbol search know every market the data layer
  routes** (#1565, #1575, thanks @Shizoqua). `.BA`, `.L` and `.VN` symbols had no
  canonical-symbol scan, venue or currency in grounding. Symbol search
  labelled Indian, Korean, British, Vietnamese and Argentine results `global`.
  A parity test now takes the market list from the backtest's own currency
  table. An answer may write £, ₫ or AR$ for the currency it has to name.

- **A `local:` code in a backtest is served from your own dataset or not at
  all** (#1467). The market-data tool and the README already treated
  `local:AAPL.US` this way, but the backtest runner did not. With
  `source="local"` it counted the served `AAPL.US` as missing and sent it down
  the A-share network fallback chain. With `source="auto"` it ignored the
  prefix and fetched the symbol from network loaders. The prefix now picks the
  local loader only, a symbol the dataset lacks fails with
  `incomplete data for source=local`, and the rest of the run sees the bare
  symbol: market rules, artifacts (`ohlcv_AAPL.US.csv`, no colon in the file
  name) and the run card. A `local:` code requested from a network source, or
  one symbol requested both with and without the prefix, is refused up front.

- Block trades, margin trading and financial statements no longer read
  Eastmoney rejecting a stale query (code 9501) as an empty result; all six
  datacenter callers share `eastmoney_client.datacenter_rejection`.

- Lockup expiry: `free_shares` is the unlocking quantity
  (`CURRENT_FREE_SHARES`), not the float; units are stated (万股 / 万元) (#1513,
  #1501, thanks @lorenzozanee). The report is `RPT_LIFT_STAGE`; the old one
  rejected six columns.

- Dragon-tiger seats come from the buy/sell detail reports, surface a provider
  rejection, and rank within each listing reason (#1512, #1502, thanks
  @lorenzozanee).

- Shareholder-count history returns real periods from `RPT_HOLDERNUM_DET`,
  states each row's previous period, and warns when the average-holding join
  fails (#1518, #1503, thanks @he-yufeng).

- QVeris resolves adjusted fields as a complete set, one family per response,
  and no longer gives an unadjusted bar the adjusted volume (#1527, #1494,
  thanks @cgycorey).

- **Tencent history walks backward from the end date** (#1411, closes #1410,
  thanks @shadowinlife) — `fqkline` serves the *last* 500 bars of a window,
  not the first: `sh000300` over 2018-01-01..2026-06-30 comes back as 500 bars
  starting 2024-06-06 (verified live). The forward walk that shipped in 0.1.15
  (#1154) therefore returned only the last 500 bars of any longer window, with
  exit code 0. The cursor now moves back from `end_date`, and an error-shaped
  or mid-walk empty reply is retried instead of being read as the start of
  history.

- **A BaoStock server that stops answering no longer hangs the fetch** (#1615,
  closes #1492, thanks @he-yufeng) — baostock 0.9.3 reads its socket with no
  timeout, so a silent server blocked forever and a closed connection spun at
  100% CPU. The connection, each complete message and the wait for the session
  are now bounded by `VIBE_TRADING_BAOSTOCK_TIMEOUT` (30 seconds by default),
  and a failed call is a per-symbol miss the chain moves past. After review,
  BaoStock sessions also run one at a time per process, because the SDK keeps
  one global socket, and a socket that failed mid-reply is closed so the next
  query cannot read its late answer.

- **Concurrent first lookups no longer find an empty loader registry** (#1405,
  closes #1403, thanks @alanwilhelm) — `_ensure_registered` marked itself done
  before importing the loader modules, so a thread arriving during a cold
  start returned with nothing registered and an available symbol came back
  `_unresolved`. The flag is published after the imports now, under a lock,
  and concurrent cold callers wait for them.

- **An explicit source that must not fall back no longer has its gaps filled**
  (#1441, thanks @chiww) — `local`, `fmp`, `qveris`, `tickerall`, `nobitex`
  and `wallex` were kept from degrading only when the loader was unavailable
  as a whole. A symbol the named source lacked was still fetched down the
  market's chain, so one run could mix a local snapshot with Tencent bars
  behind two log lines. The run now fails naming the missing symbols, pinned
  by a test for every source in that set.

- **The Stooq challenge warning names a variable that exists** (#1402, thanks
  @chiww, thanks @chiww) — it told operators to set
  `VIBE_TRADING_MARKET_DATA_ORDER_*`, which nothing reads, or to drop stooq from
  the chain, which override validation refuses. It names `MARKET_DATA_ORDER_*`
  now (for example `MARKET_DATA_ORDER_US_EQUITY`), suggests moving stooq to the
  end, and says an override must be a permutation of the default chain.

- **QVeris no longer sends the end date as `indicators`** (#1496, thanks
  @lorenzozanee, thanks @lorenzozanee) — end-date parameters were recognised by
  substring, so any capability parameter containing `to`, such as `indicators`,
  was given the end date. Only exact names are mapped now (`end`, `end_date`,
  `enddate`, `to`, `to_date`, `until`, `until_date`, with hyphens folded). The
  rest of #1494 was fixed separately.

- **`get_shareholder_count` answers again** (#1490, closes #1489, thanks
  @cgycorey, thanks @cgycorey) — it asked `RPT_HOLDERNUMLATEST` for
  `AVG_HOLD_AMT`, a column the report no longer has, so Eastmoney rejected the
  whole request and the tool reported "no shareholder-count disclosure found"
  for every A-share. It requests `AVG_MARKET_CAP`, the same per-account value
  (the output key `avg_hold_amount` is unchanged), and a rejected request now
  returns the datacenter's own message instead of an empty result.

- **`get_market_data` no longer answers `1M` with one-minute bars** (#1487,
  closes #1480, thanks @shadowinlife) — intervals were matched through an
  upper-case fold under which `1m` (a minute) and `1M` (a month) share a key,
  so a monthly request was served minute bars without an error. An exact-case
  match now wins before any fold. The PR refused `1M` and `1W`; since #1479,
  in this same release, they return monthly and weekly bars built from daily
  ones.

#### Backtest runner and engines

- **Backtests align calendars at any timestamp resolution** (#1560, thanks
  @Shizoqua). The engine merged symbol calendars and placed prices through raw
  nanosecond integers, but a local duckdb source serves microseconds. Such a run
  was dated 1970-01-21, and beside a nanosecond source one symbol's closes came
  back empty. The rebalance mask had the same unit mismatch.

- **Mean-variance style optimizers size a short by its own expected return**
  (#1548, thanks @Shizoqua). The optimizers scored every position as if it were
  held long, so the strongest shorts (most negative drift) looked worst and got
  the least capital. `BaseOptimizer.optimize` now negates a short's column
  before building the context, so `mu` is the position's expected return AND
  `cov` is the position covariance `D Σ D`: a long and a short of two +0.92
  correlated names hedge instead of reading as correlated (the old objective put
  the whole book on the long, the new one splits it 0.514 / -0.486). Risk-parity
  and max-diversification contexts get the position covariance with it;
  volatility-only contexts are unchanged, since std(-r) == std(r).

- **Monte-Carlo validation annualises at the venue's bars per year** (#1546,
  thanks @Shizoqua). It hardcoded 252 while `bootstrap_sharpe_ci` and
  `walk_forward_analysis` in the same report used the resolved value, so a
  crypto (365) or forex (260) run published two disagreeing Sharpes.

- **A futures order on a negative-price bar is no longer rejected outright**
  (#1547, thanks @Shizoqua). `FuturesBaseEngine` dropped the `abs(price)` its
  base class relies on under `allow_nonpositive_prices`, so size came out
  negative and the caller's `size <= 0` guard refused every order.

- **A backtest aborted when a funding debit left cash below zero** (#1542).
  CompositeEngine and CryptoEngine subtract crypto funding from capital with
  no floor, and the next open then fitted at no scale, not even an empty plan:
  the open-basket search kept the full-scale plan and the run died with
  "planned order … exceeds available capital", and a rebalance raised
  "insufficient capital for position rebalance". Such an open is now skipped
  and reported once as `insufficient_capital`, the bar's reductions still
  run, and a close whose loss exceeds its margin still aborts the bar (#1274).

- **One cash-starved open is one rejection, not twenty-six** (#1470). In
  `position_adjustment="hold"`, the search that scales a basket down to the
  cash available re-planned every open on each step, and every step whose
  size rounded to zero booked a `zero_size` rejection for the same symbol on
  the same bar — one contract the cash could not hold read as 26 lot-rounding
  failures. The trial plans are silent now; a sleeve that was a real order at
  full scale and left the basket is reported once, after the search, as
  `insufficient_capital`, which the rebalance path's dropped sleeves now use
  too. `zero_size` means the lot rule and nothing else.

- **A-shares from a source without its own engine branch run under A-share
  rules** (#1431, thanks @chiww) — for such sources the runner followed the
  instrument's market only for US, HK, Canadian and UK equities, so
  `600519.SH` served by `local`, `tencent`, `eastmoney`, `baostock`, `mootdx`
  or `sina` ran on `CryptoEngine`: no stamp tax, T+1, price limits or
  100-share lots, and a perpetual funding fee charged against the position.
  They route to `ChinaAEngine` now.

- **The declared interval is checked against the bars that arrived** (#1432,
  thanks @chiww) — a single-market run annualised at the interval it asked
  for, but a loader can serve coarser bars (the local loader cannot turn a
  daily file into `1H`), and CAGR, Sharpe and volatility then scale by the
  ratio. The runner compares the median bar spacing of the longest price frame
  with the declared interval; past a 1.5x gap either way it annualises as the
  interval the spacing matches, or from the calendar when bars four or more
  days apart match none, and the report is written to the run card beside the
  caliber warning. Median spacing replaced a bars-per-calendar-year count,
  which measures five daily bars starting on a Monday at 456 a year.

- **Options annual return is annualised over the elapsed bars** (#1458, thanks
  @Shizoqua, thanks @Shizoqua) — the options engine raised growth to
  `bars_per_year / (n - 1)` where the shared `calc_metrics` uses `bars_per_year
  / n`, which exaggerated annual return in both directions, most on short runs.
  Both use `n` now.

- **An India short is covered against the buy-side circuit band** (#1608,
  thanks @Shizoqua) — the India engine never passed the held position's
  direction to the shared band check, so covering a short, which is a buy, was
  tested against the lower band a long's sale uses, and a cover at a locked
  upper circuit filled. The direction is passed now, in single-market and
  composite runs alike.

#### The backtest tool and what a run leaves behind

- **The backtest tool honours `VIBE_TRADING_TOOL_TIMEOUT_SECONDS` and keeps a
  timed-out run's output** — the engine subprocess had a hardcoded 300-second
  limit regardless of the setting (default 1,800; 0 disables it), and a
  timeout discarded everything the engine had printed. The partial stdout and
  stderr are now written to the run's `logs/` and the last 2,000 characters
  returned with the error.

- **Runs from the `backtest` tool record `state.json`** (#1413, closes #1412,
  thanks @shadowinlife) — only the agent runtime wrote it and
  `refresh_strategy_evidence` refuses a run without one, so every run from the
  `backtest` tool, or the MCP tool that delegates to it, was rejected as run
  status unknown despite complete artifacts. The tool now records success,
  failure with the exit code, or a timeout, through the same `RunStateStore`
  writer; a config that fails validation records nothing, since the engine
  never ran.

- **The `backtest` tool names the directory it looked in** (#1429, thanks
  @cgycorey, thanks @cgycorey) — a missing `config.json` or
  `code/signal_engine.py` was reported with no path, so a caller whose `run_dir`
  resolved somewhere unexpected could not tell that from an empty directory.
  Both errors now name the resolved directory and say where the file belongs.

- **Dict- and list-valued metrics reach the run card** (#1424, thanks
  @cgycorey, thanks @cgycorey) — the card kept only scalar metrics, so
  `unfilled_plan_rejections_by_symbol`, which names the rejected sleeve and
  the reason, was dropped while the anonymous count beside it stayed.
  Non-scalar metrics now go to a `structured_metrics` block, shown in the Run
  Card tab and the Markdown card, with `metrics` unchanged; a value over 4 KiB
  of card JSON, or one that cannot be serialised, is left out and named under
  `_omitted`.

- **A text column in `metrics.csv` no longer drops a run's metrics from the
  reply** (#1579, thanks @Shizoqua) — the session service converted the whole
  row at once and swallowed the error, so a run with an explicit benchmark,
  whose `benchmark_ticker` is text, lost every metric without a log line. Each
  field is converted on its own now, and only the unconvertible one is
  skipped.

#### Alpha Zoo

- **24 alphas emitted a value computed from a missing bar** (#1463, #1523,
  #1534, #1452, thanks @Shizoqua). A comparison over an operand that is NaN
  because its window holds the gap is False, and the #1463 sweep, which nudged
  the bar by a tick, could not see that. A second oracle compares the gapped run
  with the gap-free one. Comparison gates and `np.fmin`/`np.fmax` now mask on
  their inputs' reach (`factors.base.observed_over`) rather than on their
  operands' NaN, so a correlation undefined on complete data keeps its old
  verdict; the six fmax/fmin alphas converted on 2026-09-18 had lost up to 87%
  of their post-warmup values in a 5-symbol universe that way and are restored.
  On gap-free data no finite value changed.

- **Twenty alphas no longer fill a missing input with a constant** (#1463).
  A halt left a comparison reading 0 or False, a `.where(cond, 0)` reading a
  flat day, or an `np.fmax` returning the other side, and the value then fed
  every rolling window that reached back to the gap. Those cells are NaN now.
  On gap-free data every finite value is bit-identical to before. A
  perturbation sweep over all 462 alphas counts 35 still carrying a missing
  bar forward, down from 55, and every one of them is accounted for: 28 are
  recursive statistics (the GTJA `SMA(A, n, m)` smoothers and one running
  product), which by the policy set on #1463 skip a missing observation and
  continue from their last state — the operator layer's header now states
  that exception, and a test pins it; 3 declare their own partial window; 4
  are the sweep's own rank-tie artifact. Nothing rewarms a smoother after a
  gap, and the registry's look-back mask was measured and rejected: it hid
  4,270 legitimate cells to remove 41% of the fabricated ones.

- **Asset growth is year over year on the daily panel** (#1564, thanks
  @Shizoqua). Derived fundamentals run on a panel densified to the price
  calendar, where a one-row lag compared yesterday with today: 0% on ordinary
  days and a one-day spike at each filing. The lag is now 365 days, as-of.

- **A factor's IC ratio is unset for a negative baseline** (#1549, thanks
  @Shizoqua). Dividing two negative IC means gives a positive ratio, so a
  rolling IC that got further below zero reported as improvement. The signal
  itself took the worst of the available metrics and was not fooled; the
  published number was.

- **qlib158 `CNTP` / `CNTN` / `CNTD` stop counting a missing close as a flat
  day** (#1459, thanks @cgycorey) — the 15 factors (three families × 5 / 10 /
  20 / 30 / 60 windows) turn `close > prev close` into 0/1 and average it,
  and a NaN comparison reads `False`. The registry mask from #1377 blanks the
  gap bar itself, but every later window that still held the gap counted the
  halt as a day that neither rose nor fell, so `cntd` read closer to zero
  than the observed days say. The comparison is NaN now wherever either close
  is missing: a gap blanks `window + 1` rows and the value returns, equal to
  the gap-free run, once it scrolls out. The same rule moves the first value
  from row `window - 1` to row `window`, matching each factor's
  `min_warmup_bars`, because the first bar has no prior close. On sparse
  panels this can trip the registry's >95% NaN guard; each factor's `notes`
  states from what missing-bar fraction.

- **qlib158 `WVMA` takes the absolute return in its numerator, as upstream
  does** (#1594, thanks @Shizoqua) — `wvma5` … `wvma60` computed
  `ts_std(ret·v) / ts_mean(|ret|·v)`, a signed numerator over an absolute
  denominator, where qlib's formula takes `Abs` on both. Every value of the
  five factors changes. The finishing commit (`a5d47c20`) points the
  attribution header at the upstream file that actually defines WVMA
  (`qlib/contrib/data/loader.py`, MIT) instead of `handler.py`, and pins the
  formula against an independent scalar oracle, a gap and all-zero volume.

- **GTJA alphas 103, 133 and 177 score a fresh extreme high, not low**
  (#1604, thanks @Shizoqua) — `HIGHDAY` / `LOWDAY` count bars since the
  extreme, but the port put the 0-based window index, counted from the oldest
  bar, in their place. Alpha 103 read a low set today as 5 and a low 19 bars
  old as 100: the recency signal was inverted. The PR restored the direction
  one bar off (95 and 0). The finishing commit (`0244ecea`) counts days since
  the extreme with today as 0, so alphas 103 and 177 run from 5 to 100 over
  a 20-bar window, and takes the most recent bar on a tie. It also corrects
  `gtja191/LICENSE.md` to cite the Guotai Junan report of 2017-06-15 by Li
  Chen and Liu Fubing, where the zoo had named a 2014 report.

- **A custom zoo root no longer replaces the bundled alpha of the same name**
  (#1468, fixes #1465, thanks @cgycorey) — `Registry(zoo_root=...)` loaded
  custom alpha files into `sys.modules` under the bundled module's own name.
  Once a custom root had computed its own `qlib158/cntp5.py`, a default
  `Registry()` in the same process computed the custom code too. The import
  cache is keyed by module path and zoo root now; module names and relative
  imports inside a custom root are unchanged. No shipped caller passes
  `zoo_root`; it is the path tests and plugins use.

#### Quant Library and analysis tools

- **A strict-bench OOS split needs two IC observations on each side** (#1559,
  thanks @Shizoqua). A split outside the loaded prices is refused. An alpha
  whose IC series leaves fewer than two observations on either side is skipped,
  with the counts in the reason. The IC series ends one forward-return horizon
  before the prices, so a split one bar from the end used to publish verdicts
  measured on nothing.

- **Quant inputs are checked before they are used** (#1555-#1558, thanks
  @Shizoqua). HRP aligns a supplied correlation matrix, and the covariance's own
  rows, to the covariance's column labels; swapping two rows used to move the
  weights with no error. Purged cross-validation refuses an unordered or
  duplicated timestamp index, and a label that ends before it starts. Impact
  models and every fixed-income entry point refuse NaN and infinities instead of
  returning NaN prices, durations and curves.

- **Shadow-account overtrading uses the whole trading window** (#1563, thanks
  @Shizoqua). A long hold that closed before later short trades no longer
  shrinks the span.

- **Event-study z-statistics no longer over-reject** (#1466). A CAR's standard
  error summed each day's variance, ignoring that every day is forecast with
  the same estimated parameters, so the days' abnormal returns are correlated.
  On null data, the standardised CAR's variance was 1.11 with a 120-day
  estimation window and 1.41–1.46 with a 30-day one. It is now 1.02 and 1.07,
  which is only the t correction for an estimated residual variance. Patell and
  BMP inherit the fix; `market_adjusted` was already right.

- Shadow account: an `other`-market rule no longer matches every symbol (#1538,
  thanks @Shizoqua), and overtrading PnL no longer double-counts trades already
  explained (#1475).

- Quantlib: comps refuses negative bridge magnitudes like the DCF bridge (#1535,
  thanks @Shizoqua); accrued interest is exact on coupon dates under 30/360 and
  rejects an unknown day count there too (#1509); Kyle's lambda fits an
  intercept (#1477).

- ML strategy: a single-class training window is skipped and the previous model
  keeps predicting (#1522, thanks @Shizoqua). Memory: two entries with one title
  and different types keep separate index rows, and `forget` names the type when
  ambiguous (#1525). Swarm run and task files use unique temp names (#1536).

- **Patell z uses each normal-return model's own degrees of freedom** (#1449,
  thanks @Shizoqua) — the `df / (df - 2)` correction in `event_study`
  assumed the market model's two estimated parameters for every event, so
  `market_adjusted` (none estimated) and `mean_adjusted` (one) over-stated
  the variance and reported a slightly smaller |z|, and a larger p-value,
  than their own fits support. The market model is unchanged. The finishing
  commit (`844b13b9`) has `estimate_market_model` read its residual degrees
  of freedom from the same table, so the two cannot drift apart.

- **Microstructure estimators refuse NaN and infinite inputs** (#1451,
  thanks @Shizoqua) — a non-finite price came back from
  `roll_effective_spread` as a `0.0` spread, `kyles_lambda` returned `nan`,
  and `vpin` produced a series from NaN or negative volumes. All three raise
  now, and `vpin` also refuses a non-finite `bucket_size`.
  `amihud_illiquidity` drops an infinite row the way it already dropped a NaN
  one; before, an infinite return made the ratio infinite and an infinite
  volume counted as a zero-illiquidity day. The accept side is pinned too
  (`c6010208`): constant prices are a zero spread, all-zero order flow a zero
  lambda, and zero-volume bars leave VPIN unchanged.

- **Copula pseudo-observations give ties one rank and leave NaN missing**
  (#1453, thanks @Shizoqua) — the double `argsort` ranked tied values by
  position (`[1, 1, 3]` became 0.25 / 0.5 / 0.75) and sorted a NaN last,
  handing it the column's top rank and counting it in the normaliser.
  `pseudo_observations` uses average ranks now, keeps a NaN as NaN with each
  column normalised by its own count of observations, and refuses infinite
  values.

- **`spread_term_structure` keeps tenor `5` and `5.0` in one column** (#1507,
  thanks @Shizoqua) — the column name was built from the raw key, so issuers
  quoting the same tenor as an int and as a float were split across
  `5Y_spread_bp` and `5.0Y_spread_bp`, each NaN for the other group. The
  reference-curve lookup already treated the two as one tenor.

- **Purged cross-validation refuses a timestamp label index it cannot map**
  (#1556, thanks @Shizoqua) — label end times passed as a Series are turned
  into positions with `searchsorted`, which assumes a sorted index. An
  unordered or duplicated index mapped label ends to the wrong rows with no
  error, so the purge protected the wrong rows; it raises now. The finishing
  commit (`250ef746`) closes the neighbouring gap: a timestamp label ending
  before its own start was clipped up to it (ends at positions `[1, 0, 3, 3]`
  came back as `[1, 1, 3, 3]`) and now raises, as the positional form already
  did. A `NaT` end stays allowed and purges through the last observation.

- **Market-impact models refuse infinite inputs** (#1557, thanks @Shizoqua)
  — NaN was already refused, but positive infinity passed every positivity
  check: an infinite ADV priced a `linear_impact` or `sqrt_impact` order at
  zero impact, and an infinite price, traded volume or `bps` returned an
  infinite buy fill. Price, volume, ADV, `bps`, impact coefficient,
  volatility and `eta` must all be finite now.

- **The correlation-analysis cointegration examples call the Quant Library**
  (#1404, thanks @Shizoqua) — the skill's Engle-Granger example carried its
  own statsmodels fit and raised `KeyError` on an unnamed Series, because it
  looked the hedge ratio up by the series' name. The PR named the regressor;
  the finishing commit (`bd29a187`) replaced the local fit with
  `find_hedge_ratio`, `cointegration_test` and `adf_test` from
  `src.quantlib.timeseries`, and the half-life example with
  `compute_half_life`. The example now inherits their refusal to pair two
  legs on different indices positionally, keeps its result keys and adds
  `half_life`.

- **`portfolio_risk_xray` works on windows longer than 250 bars** (#1462,
  closes #1461, thanks @he-yufeng) — the tool fetched prices under the shared
  250-row cap. Above it `fetch_market_data` returns a sampled envelope rather
  than the bar list the tool parses, so a window of 251 bars or more failed
  with "no close prices returned for any requested symbol", which is about
  anything over a year of daily bars. It requests every row now
  (`max_rows=0`, as `technical_indicators` does); volatility, VaR/ES and
  drawdown need consecutive bars regardless.

- **`benford_check` reads the leading digit from the number as written**
  (#1591, thanks @Shizoqua) — `financial_rigor`'s Benford check took the
  digit from `10 ** frac(log10(v))`, which lands just under an integer for
  some exact round values, so `5000` counted as a leading 4. Among the
  integers 1 to 100,000, twelve were misread (8, 30, 40, 50, 80, 500, 600,
  900, 5000, 6000, 9000, 50000). The PR rounded before truncating, which
  would have read `4999.9999999` as a 5; the finishing commit (`d0ef98a6`)
  takes the first significant digit of a `Decimal` built from the supplied
  value instead, with no float round-trip. Zero, NaN and infinite values are
  still skipped.

- **The sentiment scorer reads "low" as bearish only** (#1448, thanks @Shizoqua,
  thanks @Shizoqua) — "low" was in both the bullish and the bearish word lists,
  so it cancelled itself and `shares tumbled to a new low today` scored neutral.
  It was the only word in both; a test now keeps the lists disjoint.

- **Head-and-shoulders detection checks shoulder symmetry on negative
  series** (#1456, thanks @Shizoqua) — the `pattern` tool divided the
  shoulder gap by the signed shoulder average. On a series below zero the
  ratio went negative and always passed the 5% test, so clearly asymmetric
  shoulders were flagged as a pattern. It divides by the absolute average
  now, as `double_top_bottom` already did.

#### Live trading, brokers and the strategy store

- **Robinhood live trading reads and trades the account the mandate names**
  (#1442). The runner, the pre-trade gate and the commit-time ceiling fetch
  called Robinhood with no `account_number`, and read replies one level too
  shallow (`data.positions` where Robinhood nests `data.data.positions`). So
  every reconciliation aborted, and the gate refused every order because it
  could not read positions. The tests stayed green only because their fake
  replies had a shape Robinhood never sends. A Robinhood mandate is now bound
  at commit to one account from `get_accounts`: listed, not deactivated, and
  open to agentic trading. The Web confirm dialog and the CLI both ask for
  it, and never take it from the agent-written proposal. Every runner and gate
  call sends that account, and an order naming another account is refused.
  Held positions, which Robinhood reports without a price, are priced the way
  a quantity order already was, and one that cannot be priced fails the
  exposure check closed. Existing Robinhood mandates must be committed again
  with an account.

- **SDM decay metrics treat NaN and infinite bench results as missing**
  (#1447, thanks @0xouzm) — three stored `sharpe=inf` rows read as `healthy`,
  so a non-dry `sdm_decay_scan` moved a strategy in monitoring back to active,
  and `-inf` read as critical. SQLite keeps infinities as written, so the
  persistent store was affected too. `compute_decay_metrics` now drops
  non-finite values, independently for IC and Sharpe, before the
  three-observation minimum.

- **A mandate narrowed to zero exposure is stored as zero** (#1593, thanks
  @Shizoqua, thanks @Shizoqua) — narrowing `max_total_exposure_usd` or
  `account_funding_usd` to `0` at commit is legal, but the cap mapping used `x
  or default`, so the saved mandate got the order cap back as its exposure
  limit: the commit widened what the user had just narrowed. An explicit zero
  now persists, and an order checked against that mandate breaches
  `max_total_exposure_usd`.

- **A malformed Robinhood `buying_power` is a shape error, not an unknown**
  (#1526, thanks @lorenzozanee) — a non-null `buying_power` that was not an
  object (a bare number, string or list) was read as unknown and passed; it
  now raises, so the portfolio source errors instead of carrying the reply.
  An omitted or null value stays unknown and zero stays valid. As merged the
  PR also refused an omitted `buying_power`; `46892136` restored that case to
  unknown, which is what the PR description specified.

- **Interval and event triggers carry `market=None` again** (#1599, thanks
  @woshi77777stars, thanks @woshi77777stars) — `Trigger.market` was both a
  dataclass field and a classmethod factory, so every non-market trigger carried
  the bound method as its `market`, and `dataclasses.asdict()` + `json.dumps()`
  raised on it. `due_now()` was unaffected. The factory is bound after the class
  body (`d0ef98a6` keeps subclass binding intact), and a repo-wide static test
  fails on any dataclass or NamedTuple field shadowed this way.

- **With an MT5 profile selected, `search_symbol` resolves the broker's own
  symbols** (#1597, closes #1589, thanks @lorenzozanee) — it returned no MT5
  candidate for an explicit symbol such as `XAUUSD`, so the identity gate
  blocked `trading_quote`, `trading_history` and `get_market_data`. Search
  now reads the configured terminal's catalog by `terminal_path` with no login
  credentials. After `47a036d6` every query is answered from that terminal
  while MT5 is selected, a web-search hit is never substituted, and an
  ambiguous alias is refused.

- **Backtests attach to the running MT5 terminal without seeing its
  credentials** (#1598, thanks @he-yufeng) — the sandbox's ephemeral HOME had
  no `mt5.json`, so the loader attached bare and a forex backtest could fall
  through to akshare while `get_market_data` used MT5 in-process. The sandbox
  now gets only `terminal_path` and `timeout` (validated by `47a036d6`), never
  `login`, `password` or `server`, and a bare attach warns that the SDK may
  pick another installation logged into another account.

- **Dhan paper orders reject fractional share quantities** (#1595, thanks
  @Shizoqua, thanks @Shizoqua) — `0.5` passed the positive check and truncated
  to `0`, returning a successful simulated fill for zero shares, and `1.5`
  silently became `1`. Only whole numbers of at least one share are accepted;
  `a5d47c20` parses with `Decimal`, so `1.00000000000000001` is refused too, and
  NaN, infinity or text return an error instead of raising.

#### Swarm workers

- **A swarm worker can load only the skills its spec lists** (#1414, thanks
  @shadowinlife, thanks @shadowinlife) — `SwarmAgentSpec.skills` was read only
  to filter the prompt, so `load_skill` loaded any skill a worker named. The
  worker's `load_skill` now refuses a skill outside the list and names the ones
  allowed. An empty list stays unrestricted, as the prompt filter treats it; the
  main agent is unchanged.

- **A swarm tool that declares `run_dir` gets the directory the model named,
  confined to the agent's workspace** (#1430, thanks @cgycorey) — the worker
  overwrote every call's `run_dir` with the workspace, so `backtest`, exposed
  to 19 preset agents, never saw the directory it was given. A relative path
  now resolves under the workspace, an absolute one inside it is kept, and one
  outside is refused with an error naming the workspace. Tools that do not
  declare `run_dir` still get the workspace.

- **Every swarm worker that writes its summary also writes its message log**
  (#1439, thanks @cgycorey) — `messages.json` is the only record of the
  arguments the model asked a tool for, and the completed, token-limit,
  content-filter and incomplete exits wrote `summary.md` without it, so the
  most common outcome left no log. Both files now go through one writer. A
  failed LLM call still writes neither.

#### Agent loop, providers and goals

- **An explicit provider header survives an ambient twin** (#1573, #1568, thanks
  @zeus229). When `OPENAI_CUSTOM_HEADERS` names a header the provider also sets
  (a `user-agent` beside the Kimi / NVIDIA / OpenCode `User-Agent`), openai
  3.19.2's case-insensitive merge dropped the provider's value. That turned CI
  red for every PR on 2026-09-24. The first fix proposed would have sent both
  headers under openai 2.53, the version the lock file and the Docker image
  install. Every ambient spelling is now omitted and the explicit value re-set
  after the omits, which holds under both.

- **Read-only results lost to context compaction are restored, not refetched**
  (#1488, thanks @zeus229). A successful read-only call whose payload compaction
  removed is replayed from the run's own cache, at most six times a run; past
  the cap it runs again, as it did before, instead of being refused with "use
  the previous result" for a payload the model cannot see. The cap is checked
  per restore, and any successful write empties the cache, so a regenerated file
  is read afresh. `read_url` opts in; `no_cache=true` always fetches.

- **OpenAI's gpt-5.6 models run with their reasoning on the agent's default
  configuration** (#1473). `/v1/chat/completions` refuses function tools for
  `gpt-5.6-terra` and `gpt-5.6-luna` unless `reasoning_effort` is `none`,
  including when no effort is configured and the model applies its own
  default, so a plain `LANGCHAIN_PROVIDER=openai` setup failed on its first
  tool call with `Function tools with reasoning_effort are not supported`.
  The adapter now treats that refusal the way it treats a rejected
  `temperature` or `stream_options`: the request is retried on
  `/v1/responses`, where the effort travels as `reasoning.effort`, and the
  model is remembered for the rest of the process so later calls go there
  first. Nothing changes for a model whose chat endpoint accepts tools, and
  `LANGCHAIN_USE_RESPONSES_API=true` still selects the route up front and
  skips the one failed request.

- **A research goal that is an order is still refused** (#1562, thanks
  @Shizoqua). The execution filter no longer rejects research that mentions
  shares or coins ("should the fund sell its GOOGL shares"). It refuses an
  objective that opens with buy or sell, puts a quantity right after the verb,
  or writes 买入 / 卖出 with a quantity and a unit. The first version of the change
  had made "Buy 100 shares of NVDA" an accepted goal.

- **Research goals refuse an order that puts "now" or "immediately" before
  the verb** (#1605, thanks @Shizoqua) — the execution filter matched only
  the verb-then-cue order, so `Immediately buy TSLA`, `Now sell GOOGL` and
  `Please immediately short TSLA` were accepted as research objectives. The
  mirrored rule requires the cue to sit directly before the verb, with only
  separators and an optional `please` between them. The first version allowed
  up to 40 characters there and also refused `Now research whether to buy
  AAPL`; the finishing commit (`0244ecea`) keeps that and similar research
  phrasings accepted. The check runs on a goal's objective, on each of its
  criteria and on an objective update.

- **The tail a full compaction keeps counts a thinking model's reasoning**
  (#1582, thanks @Shizoqua) — the layer-3 tail is sized to a 20K-token budget,
  but the sizing read `content` and tool-call arguments and skipped
  `reasoning_content`, so on reasoning-heavy turns the kept tail could run far
  past its budget and compaction freed less than intended. The reasoning text
  is counted now, as the loop's token estimate already counted it.

- **`technical_indicators` results are restored after compaction instead of
  fetched again** (#1601, thanks @zeus229) — the tool is read-only but
  `repeatable`, and a repeatable tool is replayed from the run's memory only if
  it opts in; it did not, so an identical request after compaction re-ran the
  market-data fetch. It opts in now, like `web_reader`, within the loop's
  existing replay budget.

- **Token counts and Polymarket CLOB token ids are no longer redacted as
  credentials** (#1606, thanks @Shizoqua) — the `token` credential marker is a
  substring match, so `token_budget`, `token_usage`, `total_input_tokens`,
  `total_output_tokens` and `clob_token_id` read `[redacted]` in traces, event
  previews and the live audit ledger. Since `0244ecea` each is released only in
  its expected shape (a non-negative integer, a map of counts, a decimal
  uint256 id); any other value under those names stays redacted.

- **A remote MCP tool with a malformed `properties` schema still gets a valid
  one** (#1607, thanks @Shizoqua) — `normalize_mcp_tool_schema` dropped a
  non-object `properties` such as a string or a list and then skipped the `{}`
  fallback, so the tool reached the model as an object schema with no
  `properties` key at all. It gets `{}` now, unless the top level composes
  `anyOf` / `oneOf` / `allOf`.

- **The Copilot credential fallback re-reads the token after 60 seconds**
  (#1619, closes #1617, thanks @lorenzozanee) — when neither
  `COPILOT_GITHUB_TOKEN` nor `OPENAI_API_KEY` is set, `get_llm_credentials`
  falls back to `GH_TOKEN` / `GITHUB_TOKEN` or `gh auth token`, and it cached
  that answer for the life of the process. The cache now expires after 60
  seconds. Its consumer is provider diagnostics: Copilot requests go through
  the SDK client, which resolves credentials each time it is created.

#### Channels, memory and configuration

- **The Email channel verifies TLS certificates by default** (#1544, thanks
  @shadowinlife). The implicit-SSL paths (`IMAP4_SSL` / `SMTP_SSL`) in both the
  connection probe and the polling/send adapter used Python's default unverified
  context (`CERT_NONE`, no hostname check), so the mailbox password travelled to
  a server whose certificate was never checked — an active network attacker
  between the operator and their mail provider could harvest it. All four call
  sites now build their context through a shared `email_tls_context()` that
  verifies the certificate and hostname against the system CA bundle, matching
  the STARTTLS path, which already did. A new `verify_tls` field (default
  `true`, surfaced in the guided Email setup in all nine locales) is the
  documented opt-out for self-signed or internal-CA servers. **Upgrade note:** a
  mail server with such a certificate connected before this change and now fails
  the TLS handshake until `verify_tls` is set to `false` for it.

- **Plain IMAP no longer sends the mailbox password in clear text** (after
  #1544). With `imap_use_ssl` off, the Email channel and its connection test
  logged in over an unencrypted connection, and the guided setup put that
  switch one click away. A new `imap_use_tls` (on by default, the IMAP twin of
  `smtp_use_tls`) upgrades the connection with STARTTLS before `LOGIN`; a
  server that offers no STARTTLS is reported as a network failure before the
  password is sent. `verify_tls` now governs STARTTLS on IMAP and SMTP as well
  as implicit SSL, so a self-signed server can opt out on any path. **Upgrade
  note:** an `imap_use_ssl: false` setup against a server without STARTTLS
  stops connecting until `imap_use_tls` is set to `false` for it, which sends
  the password in plain text again.

- **Settings-write routes reject cross-site browser requests** (#1544, thanks
  @shadowinlife). `require_settings_write_auth` did not apply the cross-site
  guard that its siblings `require_auth` and `require_event_stream_auth` enforce
  on unsafe methods, so a malicious web page could attempt a CSRF write against
  any settings route — including the new `POST /channels/email/test`, which
  merges stored credentials with a caller-supplied patch and could be steered to
  send the stored mailbox password to an attacker-chosen host. The guard now
  runs first on every settings-write route; same-origin Web UI calls and
  non-browser clients (CLI/curl, no `Origin`) are unaffected.

- Channel adapters log through stdlib again: `{}` placeholders, napcat's 17
  sites and loguru-only `.opt()` calls lost their messages (signal's
  `_safe_handle` raised instead of swallowing) (#1533, #1531, thanks
  @shadowinlife). Slack DMs from unapproved senders get a pairing code (#1524,
  thanks @Shizoqua); Discord no longer pings `@everyone` or roles (#1537);
  duplicate-reply suppression covers integer message ids and is bounded (#1476);
  the WebSocket channel starts again (from #1521).

- **Two memories sharing a title keep separate index rows and links** (#1545,
  thanks @Shizoqua). Under `VT_MEMORY_HIERARCHY` an entry lives at
  `{memory_type}/{slug}.md`, so two entries with one title had the same
  `path.name`: the second `add()` overwrote the first's `MEMORY.md` row, and the
  semantic-link block beside it excluded the other entry as "self" and wrote an
  ambiguous target. Both key on the path relative to the memory dir now; a
  sidecar written earlier, with a bare filename or an absolute path, is still
  read.

- `/agent.json`, `/agent.yaml` and `/agent.yml` are gitignored at the runtime
  root; the Feishu QR login already wrote channel credentials there.

- **Signal channel: stripping the bot's mention no longer removes the wrong
  character after an emoji** (#1478, thanks @Shizoqua) — Signal reports a
  mention's `start` and `length` in UTF-16 code units, and the channel sliced
  the Python string with them directly. Each character outside the Basic
  Multilingual Plane (most emoji) before the mention shifted the slice by
  one, so the mention placeholder stayed in the text handed to the agent and
  the neighbouring character was cut instead. Offsets are converted to string
  indices before a mention is stripped or tested as a leading mention.

- **A file received over DingTalk is saved inside its download directory
  whatever it is named** (#1506, thanks @Shizoqua) — the adapter joined the
  inbound `fileName` to the per-sender download path unsanitized, so a name
  with `../` segments, or an absolute path (which replaces the whole path when
  joined), could write outside it. The name goes through `safe_filename` now,
  as the other adapters already sanitize a remote file name.

- **A channel that fails to load logs which one and why** (#1580, thanks
  @Shizoqua, thanks @Shizoqua) — two channel-registry log calls had two `%s`
  placeholders and one argument, so an external plugin that failed to import, or
  a built-in channel skipped for a missing SDK (at debug level), printed `---
  Logging error ---` instead of its name and the exception.

- **The README says which process owns Telegram polling** (#1583, closes
  #1553, thanks @lorenzozanee) — Telegram allows one `getUpdates` poller per
  bot token. `vibe-trading serve` owns the channel runtime, and
  `channels start` asks the running server (`VIBE_TRADING_API_URL`, default
  `http://127.0.0.1:8000`) to start it rather than polling itself, so the
  conflict to avoid is a second server process with the same token enabled.

- **Memory garbage collection no longer compresses an entry it just archived**
  (#1450, thanks @Shizoqua) — the compression pass reused the entry list read
  before archiving, so an entry just moved to `archive/` was compressed from a
  path that no longer existed and logged a failure. `451c554a` skips by whether
  the file still exists, not by id: ids are six hex characters two files can
  share, and an archive step that failed leaves its file to be compressed.

- **An unparseable optional numeric setting falls back to its default instead
  of failing config load** (#1592, thanks @Shizoqua) — the coercion that drops
  a bad `int` / `float` env value skipped `int | None` fields, so
  `ANTHROPIC_MAX_TOKENS=not_a_number` raised while building `EnvConfig`.
  Optional fields get the same fallback now; a parseable value outside the
  field's bounds (`ANTHROPIC_MAX_TOKENS=0`) is still rejected.

#### Web UI and locales

- **Leaving a chat cancels its pending history scrolls** — a scroll scheduled
  while a conversation's history loaded could still fire after leaving it,
  and a history load still in flight could schedule another.

- **A welcome-screen quick action stays highlighted after you click it**
  (#1500, thanks @shadowinlife) — the first chip was styled as selected by its
  position, whatever had been clicked, so the chip you chose never lit up. The
  highlight now follows the click and moves with the next one, and each chip
  reports `aria-pressed`.

- **Broker SDK diagnostics no longer name Longbridge for every broker**
  (#1436, thanks @tingkk) — the shared `sdk_missing` and `network_unreachable`
  messages on the Runtime page and in the chat connector status said
  Longbridge whichever broker raised them, so an unreachable Futu OpenD gateway
  sent the user to check Longbridge. They now name the affected broker's SDK,
  service or local gateway, in every locale.

## [0.1.15] — 2026-09-09

Rolls up 551 commits / 162 merged pull requests since 0.1.14, from 35
contributors.

The theme of this cycle is data that says what it is. A price frame now
carries the adjustment caliber it was served under. A factor propagates the
gaps in its inputs instead of filling them. A loader that cannot serve a
market no longer claims it, and a source that fails to refresh is an error
rather than a smaller portfolio. Three of those were the same bug wearing
different clothes: a default that silently substitutes a plausible value for
a missing one, which is indistinguishable downstream from a real
observation. Three new markets, a fourteenth broker and fifteen Quant
Library additions land alongside.

### Added

- **UK equity market** (#1206, thanks @cgycorey) — LSE `.L` and `.IL`
  symbols end to end: market data, Yahoo-backed financial statements and
  indicators, trade-journal inference into `uk_equity`, and its own engine
  path. SDRT is modelled as what it actually is — a 0.5% duty on the
  **purchase** side only, not a symmetric round-trip cost. Charging both
  sides overstated the cost of every round trip by half, which is exactly
  the size of edge a mean-reversion strategy lives on.
- **Zerodha Kite Connect** (#1193, thanks @ashutoshsinghpr7) — a fourteenth
  broker connector for Indian equities. Kite exposes no runtime paper/live
  discriminator — no account-id format, host separation, demo flag or trade
  environment — so under the red line it is capped at paper plus read-only:
  `place_order` and `cancel_order` hard-refuse any non-paper config at the
  first line, and no `*-live-trade` profile exists to select. That now
  covers Longbridge, Dhan, Shoonya and Zerodha; Trading212 goes further and
  refuses all order placement including paper.
- **Read-only multi-broker portfolio** (#1072, thanks @goatyyc; onboarding
  contracts in #1250) — one aggregated snapshot across every enabled
  connection instance, reachable four ways: the Web `/portfolio` page, REST
  under `portfolio_routes.py`, the `portfolio_summary` agent tool, and
  `vibe-trading portfolio show | refresh | sources`. Three design points
  that are not incidental: a source that fails to refresh is an **error
  excluded from the totals** (status `error`, `last_success_at`,
  `complete=false`), never a carried-forward cache, so a partial snapshot
  cannot read as a smaller portfolio; every `remote_mcp` read passes
  `interactive_oauth=False`, so aggregation can never pop an auth prompt;
  and `analysis_context()` carries `risk_xray_args` so `portfolio_risk_xray`
  is *fed* rather than reimplemented. Eligibility is one rule —
  `is_portfolio_connection_profile` requires readonly **and** account.read
  **and** positions.read — under which the IBKR official-MCP profile, which
  advertises only discovery, is correctly not a portfolio source.
- **Quant Library, fifteen additions** (thanks @santhreal) — Heston (1993)
  stochastic volatility option pricing (#1195); Hierarchical Risk Parity
  allocation (#1196); Archimedean and Gaussian copula analytics (#1197);
  market-microstructure analytics — VPIN, Roll spread, Amihud illiquidity,
  Kyle's lambda (#1198); analytical single-barrier options with cash-rebate
  handling (#1163) plus finite-difference sensitivity Greeks for them
  (#1203); an ISDA standard-model single-name CDS valuation engine with
  hazard-rate conversions (#1164); Key Rate Duration decomposition across
  benchmark tenors (#1165); the Vasicek credit portfolio loss model and
  spread DV01 (#1167); cross-sectional factor Information Coefficient time
  series (#1166); Ornstein-Uhlenbeck exact calibration with half-life
  (#1161); drawdown distribution analytics with the Ulcer and Pain indices
  (#1162); Corrado rank and Cowan generalized sign non-parametric
  event-study tests (#1160); multi-factor risk decomposition with Euler
  marginal contributions, reporting `unmatched_weight` rather than
  normalising it away (#1159); and group-purged k-fold cross-validation for
  panel data (#1168). The layer's rule holds throughout: a formula has
  exactly one implementation, and skills import it rather than carrying the
  source in a `SKILL.md` code block.
- **Brazilian Portuguese locale** (#1327, thanks @nandofmike) — the eighth
  shipped language, landing with full key parity. The parity suite globs
  `locales/*.json` instead of listing languages, so a new locale is covered
  the day its file lands; German had previously shipped with perfect parity
  and zero coverage because that list was hand-written.
- **Nobitex and Wallex** (#1263, thanks @Emad211) — read-only Iranian
  exchange sources on keyless public UDF endpoints, explicit-source only.
  Both sit in `_NO_NETWORK_FALLBACK_SOURCES` and are barred from the crypto
  fallback chain on purpose: they are the only Toman-quoted sources and
  declare `markets={"crypto"}` purely to be reachable, so degrading an
  unavailable `BTCIRT` request into that chain would hand back a
  USDT-quoted series as if it were Toman.
- **Binance USD-M evidence path** (#1229, #1230, thanks @honginp; #1248,
  thanks @lorenzozanee) — read-only USD-M account snapshots, drift evidence
  artifacts comparing simulated fills against recorded ones, and
  deterministic tolerance calibration derived from those recordings rather
  than assumed. The point is that the tolerance has a provenance: it is
  measured against real fills, not chosen.
- **Offline evals harness** (#1271, thanks @AirHua-byte) — verifies a run's
  *persisted* artifacts (prompt preservation, tool calls and results,
  identity, evidence, provider usage, iteration budget, `RunManifest`
  integrity) against a versioned case/verdict schema, with no LLM, network,
  broker or MCP call: it reads files only. Absent instrumentation emits
  `NOT_EVALUABLE` rather than passing, which is the whole point — a missing
  field must not read as good behaviour.
- **Anthropic prompt caching** (#1366, thanks @averatec0773) — an explicit
  cache breakpoint on the system block so the static tools+system prefix is
  read from cache instead of resent at full price, with cache usage recorded
  in the usage envelope. Native adapter only, behind
  `VIBE_TRADING_ANTHROPIC_PROMPT_CACHE`; set it to 0 if a compatible proxy
  rejects the `cache_control` request parameter.
- **Per-market data-source priority** (#1231, thanks @sambazhu) — a Settings
  card and `MARKET_DATA_ORDER_*` env overrides that reorder a market's
  fallback chain. Validated as a multiset permutation of the default, so
  reordering passes while adding, dropping or duplicating a source is
  refused and the default stands. The override is applied as a setitem on
  the same dict object, because `runner.py` and `market_data.py` import
  `FALLBACK_CHAINS` by name and a rebind would leave them on the old order.
- **Calendar-triggered partial rebalancing** (#1277, thanks @thisisjun786)
  and a **data window separated from the evaluation window**, so warm-up
  bars stop counting as evaluation and a strategy is not graded on the bars
  it needed to become defined.
- **Agent-confirmed scheduled research** (#1187, thanks @AirHua-byte) and
  each monitor's latest verdict rendered on the job list (#1156, thanks
  @he-yufeng), so a recurring job's state is legible without opening it.
- **Swarm replay and retry** (#1158, thanks @cgycorey; `vibe-trading swarm
  retry --resume` in #1194, thanks @SiMinus) — resume a failed or cancelled
  DAG run while keeping the artifacts of tasks that already completed,
  rather than paying for the whole graph again.
- **Order-plan rejection reporting** (#1245, thanks @lorenzozanee) — an `_on_plan_rejected` hook plus a run-level report of
  the trades the engine wanted but could not take. A rejected plan
  previously vanished, so a strategy that was being silently throttled by
  buying power looked identical to one that simply had no signal.
- **Read-only Binance-connector crypto identity** (#1242, thanks
  @pengpengyi92) and public venue-catalog pair resolution, so a crypto pair
  resolves without requiring a broker connection at all.
- **Multi-file drag-and-drop and paste uploads** in the Web chat (#1179,
  thanks @AirHua-byte).

### Fixed

#### Missing data stops being filled with plausible values

- **The Alpha Zoo NaN contract, enforced at the registry** (#1377, closes
  #1376, thanks @cgycorey) — `factors/base.py` states the contract in its own
  header: NaN is preserved through warm-up and missing data, no silent
  `fillna(0)`. An alpha that branches with `np.where` on a **comparison**
  violates it without looking like it does, because a NaN comparison is
  `False` and the ternary falls through to its constant. Blanking every
  declared input on one bar across the whole zoo, **84 of 462 alphas returned
  a number anyway** — and since `dropna()` is the mechanism that keeps a gap
  out of an IC, each fabricated ±1 was consumed as a real signal.
  `Registry.compute` now masks the output to NaN wherever a declared
  dependency is missing on that bar, and the same sweep afterwards finds
  **none**. Individually fixed on the way there: gtja191_004 (#1371),
  gtja191_003 and gtja191_059 (#1372), gtja191_069 (#1373), gtja191_019 and
  gtja191_086 (#1379), alpha101_007 and alpha101_051 (#1380), alpha101_009
  and alpha101_046 (#1381), alpha101_021 and alpha101_024 (#1382),
  alpha101_010/023/027 (#1383), and alpha101_049's warm-up mask (#1374) —
  thanks @Shizoqua. **Stated rather than quietly carried:** the warm-up half
  is still open. Measured the same way, **52 alphas still emit a value inside
  their own declared `min_warmup_bars`** (`gtja191_154` declares 198 and
  emits at row 0), because on those bars the inputs are present and only the
  rolling window is undefined. A registry-level warm-up mask would also blank
  rows for alphas whose declaration merely over-declares by two or three
  bars, so that half needs a direction call rather than 52 pull requests.
- **`pct_change()` forward-fills by default** (#1397, #1398, #1399, #1400,
  thanks @Shizoqua; #1172) — pandas still defaults `pct_change()` to
  forward-filling, so a missing close becomes a **0.0% return that never
  happened**, and the next bar reports a two-day move as one day. Four PRs
  each fixed one call site; sweeping the skills exhaustively found **24 sites
  across 10 files**, two of them inside the very files those PRs were
  editing. The class is closed repo-wide now: the SDM strategy template
  (#1397), cross-market volatility weights (#1398), multi-factor TopN
  selection which now excludes assets with no factor observations rather than
  ranking them at zero (#1399), and sentiment-factor orthogonalization which
  no longer regresses on zeros it filled in itself (#1400). Alpha Zoo returns
  stopped forward-filling gaps in #1172.
- **Survivorship-bias disclosure reaches the report** (#1289, thanks
  @bonyohana) — the flag was computed and then not rendered in the HTML bench
  report, which is the same failure mode one level up: a caveat that exists
  in the data and not in what the reader sees.

#### Prices say which caliber they are

- **Adjustment caliber stamped on served frames** (#1317, closes #1301,
  thanks @he-yufeng) — a frame now carries what its prices actually mean.
  A caliber is recorded only where it was measured against a live payload or
  pinned by the loader's own endpoint choice; anything unmeasured resolves to
  `unknown` on purpose, because origin-side adjustment is invisible from
  loader code — Yahoo serves split-adjusted quotes with zero adjustment logic
  in this repo.
- **The loaders that still booked a dividend as a loss** (#1287, #1288,
  thanks @he-yufeng; #1320, thanks @lorenzozanee) — Yahoo, FMP and Tiingo
  paths serve adjusted prices, and an unresolved symbol now retries down the
  fallback chain instead of stopping at the first source that lacks it.
- **Explicit sources answer as themselves** (#1276, #1342, #1185, #1316,
  thanks @lorenzozanee, @he-yufeng, @cgycorey) — FMP moved to the Stable
  endpoint and no longer silently falls back when named explicitly; stooq's
  anti-bot challenge is flagged rather than parsed as data, which is the
  difference between "no data" and "a JavaScript page interpreted as prices";
  codes, date range and source are validated before the fetch rather than
  after it; and symbol search is aligned with fetch for FX pairs and indexes,
  so the thing you searched is the thing you get.
- **Tencent history pagination** (#1154, thanks @BigFishEmily) — long ranges
  were silently truncated to the first page.

#### Futures reach the right engine, and now have a source at all

- **Classification** (#1369, #1389, thanks @Shizoqua; #1396, thanks
  @he-yufeng; and `349bf202` on the global side) — digit-prefixed and
  month-code-colliding product codes, Tushare's own exchange spellings
  (`SHF`/`CZC`/`CFX`/`GFE`), case folding at extraction rather than per
  lookup, and dated global contracts carrying their venue (`CL2412.NYMEX`,
  `ESZ4.CME`) each fell through every pattern to the `a_share` default. A US
  crude contract was therefore run under T+1, with no shorting, settled in
  CNY.
- **Coverage** (#1395) — the loader chain was the last link, and it was
  empty. It named `tushare` and `akshare`, and **neither implemented a
  futures endpoint**: `tushare._fetch_daily_frame` branches on ETF / index /
  HK and sends everything else to `daily()`, the A-share equity endpoint,
  while `akshare._fetch_one` ends with `# Default: try A-share`. AKShare now
  serves Chinese contracts off the token-free Sina daily endpoints, dated and
  main-continuous, verified live across SHFE (RB2601, RB0), CFFEX (IF2512,
  T2512), GFEX (SI2601) and ZCE (MA2605). A global contract returns empty and
  reaches `local` rather than being priced as an equity. Trimming tushare's
  `markets` set alone would not have worked: `resolve_loader` walks the chain
  and never consults `markets`, so tushare would have stayed first in line.
  The main continuous contract (`RB0`) is routed too — a dated contract lives
  about one year, so any backtest longer than a contract cycle has to name
  the rolled series.
- **China-futures margin provenance** (`306aca2c`, closes #1393) — a run now
  states which products were priced on a generic default instead of a table
  entry. `rb`'s real margin rate is 0.10, the same number as the default, and
  "looked up" must not read like "assumed".

#### Live trading fails closed

- **Broker reads that are not answers** (#1212, #1232, thanks @he-yufeng;
  #1244, #1254, thanks @cgycorey) — a position read returning an API error,
  and error envelopes arriving mid halt-sweep, were both treated as
  successful empty results. The sweep now latches only the episodes it
  actually swept, under per-episode latch files, and only after attempted
  side effects.
- **State that has to survive a restart** (#1233, thanks @he-yufeng; #1213,
  #1221, #1222, thanks @Elfsa-Miranda) — the flatten latch persists across
  runner restarts, and unresolved Alpaca submissions are owned before broker
  writes and recovered by **exact client ID**, including fills, so a restart
  mid-submit cannot produce a duplicate or an orphan.
- **Order sizing and timing** (#1312, #1361, #1253, thanks @he-yufeng and
  @cgycorey; #1209) — buy-limit orders are sized at the worse of quote and
  limit on both transports, market-triggered ticks are skipped while the
  market is closed, and Alpaca position quantity is signed by side before it
  reaches the mandate gate.
- **The mandate gate narrows in both directions** (#1285, thanks @Jackzigen)
  — the change enforcing narrowing semantics for non-numeric and list
  adjustments also rejected `"none"` as an invalid type, which made the most
  conservative mandate unsubmittable. Nine CI checks were green over it: the
  eight new tests were all `raises` assertions, and a one-way suite cannot
  see that something which should have been allowed was refused.
- **Four connector gaps from the #1207 minor batch** (#1388, thanks
  @he-yufeng) — an MT5 order above the symbol's volume cap was silently
  clamped and sent while the below-minimum side errored (it fails closed
  naming the cap now); an eToro limit order with no `limit_price` went out as
  an MIT with no `TriggerRate` and rested untriggered while reading as
  accepted; futu K-lines inherited an undeclared adjustment caliber; and bare
  `BTCUSDT` was routed through A-share rules — T+1 and no shorting, on a
  perpetual.
- **Report audit fails closed when nothing was verified** (#1362, thanks
  @cgycorey) — an audit that checked zero claims returned PASS.

#### Backtest execution semantics

- **Options** (#1299, #1305, thanks @cgycorey; #1306, thanks @he-yufeng;
  #1177) — signals fill on the **next** bar rather than on the date they were
  computed from, which had let a strategy trade at the price that generated
  its own signal; HV warm-up bars use the configured default IV instead of
  an undefined one; short option legs hold margin and gate opens on buying
  power, so a naked short could no longer sell premium it could never cover;
  and an explicit expiration is validated against the dates actually
  available rather than silently resolved to a neighbour.
- **Shorts, rebalancing and accounting** (#1298, #1344, #1281, thanks
  @cgycorey) — 1x shorts liquidate on adverse moves in non-strict mode; an
  over-committed rebalance basket scales to fit instead of aborting on a
  commission overdraft; and requested target changes are separated from
  executed rebalance fills (closes #1275), so the rebalance count shown to a
  reader is the number of fills rather than the number of intentions.
- **Market rules through composite state** (#1309, #1332, #1370, thanks
  @he-yufeng and @Shizoqua) — A-share and India rules are enforced through
  composite state rather than per-engine, a halted position marks at the last
  traded close instead of entry cost, and the sub-engine's active symbol is
  synced before **every** composite dispatch rather than once per bar.
- **Perpetuals and forex** (#1307, thanks @he-yufeng; #1226, thanks
  @P1Piyush) — funding settles by bar span on 8h+ intervals rather than once
  per bar, and forex metals are treated as metals for pip size, lot size and
  spreads. A 50-ounce gold order had been rounded down to zero.
- **Symbol routing into the engines** (#1351, thanks @cgycorey) — dotted US
  class shares (`BRK.B.US`, `BF.B.US`) fetched an empty chart.
- **Cross-market annualization** (#1239, thanks @cgycorey) — risk x-ray
  honours `bars_per_year=None` instead of assuming a trading calendar that
  does not apply.
- **ML walk-forward label leakage** (#1392, thanks @Shizoqua) — future labels
  were not purged from the training window in the example pipeline.
- **Intraday fundamentals lookahead** (closes #1387) — an announcement date
  carries no time of day, so on an intraday frame a filing became visible
  from the first bar of its own announcement day: a full session of
  lookahead. Sub-daily frames are refused now, with
  `fundamental_subdaily="next_day"` as the explicit opt-in.

#### Shadow account

- (#1217, #1310, #1311, #1314, #1356, thanks @he-yufeng) — PnL is derived
  from runner metrics and fails closed when unknown rather than reporting a
  number it cannot support; attribution is scoped to the pool currency with
  mutually exclusive buckets; short lots are modelled in FIFO pairing with
  legs restated across corporate actions; the result cache is keyed by window
  **and** journal hash rather than by shadow alone, so editing a journal no
  longer returns the previous answer; and cash-dividend journal rows are
  parsed and booked into real PnL.

#### Grounding gates

- **Both directions** (#1326, #1338, #1375, #1378, thanks @cgycorey) —
  full-width brackets no longer split a clause; analysis metrics are gated on
  a *completed* analysis result (#1336); a metric claim formatted as a
  generic `| Metric | Value |` table no longer escapes the gate that rejects
  the same claim in prose; and the mirror-image error is fixed too — a price
  word used as a formula variable is not a price claim, so `close/SMA50 > 1`
  is no longer read as an asserted price (#1354).
- **Vocabularies completed on both sides** (#1346, #1357, thanks @saju01) —
  percentage-point deltas (`3.6pp`, `3.6 个百分点`, `250 基点`) were read as
  quoted prices, and the adjacent-CJK boundary is now exercised directly.
  The English gate had been the leaking side: `\bclose\b` does not match
  "closed", so a fabricated `The stock closed at 412.35.` passed while the
  identical Chinese claim was correctly rejected. Both vocabularies are
  complete now and a language-parity suite asserts the two reach the **same**
  verdict per case instead of checking each in isolation.
- **Identity** (#1265, #1280, #1282, thanks @aminak58; #1384, thanks
  @laiyierjiangsu; #1269, thanks @AirHua-byte; #1333, thanks @Shizoqua) —
  bare joined crypto pairs (`BTCUSDT`) went unrecognised while spot platinum
  resolved to a crypto pair that does not exist; FX, metals and futures
  symbols route through the right identity path (`GC=F` and `XAUUSD` had been
  classified as China A-shares); `search_symbol("XAUUSD")` returned exactly
  one candidate — a Swedish Bitcoin ETP — which then locked the run's
  instrument identity, so a metal or FX query is an exact instrument
  assertion now; a pasted broker code (`HK.00700`, `US.AAPL`, `SH.600519`)
  scanned as no symbol at all; market context stated earlier in a
  conversation can narrow resolution behind
  `VIBE_CONTEXTUAL_IDENTITY_CONSTRAINTS`; and generic evidence timestamps are
  preserved rather than dropped.

#### The agent loop keeps what it still needs

- (#1341, #1358, thanks @saju01; #1349, thanks @he-yufeng; #1352, thanks
  @cgycorey) — the loop discarded tool results the model was still using, and
  microcompaction cleared pairs it then could not reconcile. A session that
  had successfully fetched fundamentals, fund flow, margin and research data
  had those results cleared to free context, and the de-duplication ledger
  went on refusing to re-fetch them: **44 blocked retries in one run**, ending
  in "fundamental data not retrieved" for data the model had already
  received. Clearing a result now re-opens that tool, the ledger keys on
  arguments rather than tool name, results are reconciled by exact call
  identity, and the token budget counts tool-call arguments instead of
  scoring a 100 KB payload as ten tokens.
- **The no-progress budget counts observations, not activity** (#1363,
  thanks @be-student) — a run that keeps issuing tool calls without a new
  successful observation stops after `NO_PROGRESS_LIMIT` iterations with a
  visible recovery answer and a `failed` terminal state. An identical call
  identity is refused from its **second** failure, not its first: only a
  successful *mutating* call clears the ledger and a research run may have
  none, so refusing on the first failure made a transient rate limit or
  timeout permanent for the whole run.
- **Run-stall watchdog and bash tree-kill timeout** (#1169, thanks @wiliao)
  — plus a compaction verification ledger, so a stalled run is detected
  rather than waited on.

#### Providers and transports

- (#1225, thanks @he-yufeng; #1246, #1247, thanks @lorenzozanee; #1330,
  thanks @averatec0773; #1334, #1348, thanks @Shizoqua; #1182, thanks
  @AirHua-byte) — real token usage is requested on streamed calls instead of
  being estimated; a temperature rejection self-heals on the
  OpenAI-compatible path, and the Anthropic self-heal strips the *relocated*
  `extra_body.temperature` rather than only the original position; stream
  retry delays escalate and honour `Retry-After`; Codex token usage and
  response model metadata are propagated rather than discarded; and shared
  HTTP clients survive cleanup instead of being closed out from under an
  in-flight request.
- **Dependency caps that were load-bearing** (#1313, thanks @he-yufeng;
  `4abd6cc2`) — fastmcp is capped below 4.0.0 until the constructor/snapshot
  adaptation lands, and mcp below 1.30, which broke IBKR OAuth discovery. The
  second was diagnosed as a red CI on tests nothing in the diff had touched;
  adapting the fixtures would have hidden a genuinely broken broker path.

#### Web UI, CLI and surfaces

- (#1257, #1258, #1259, thanks @iagop03; #1319, thanks @guestccc) — a stale
  `streamingSessionId` is cleared on session reopen, the main region scrolls
  and long run prompts collapse, a non-backtest run points at Studio instead
  of a blank dashboard, and the Vite dev server proxies `/api` so a fresh
  checkout works without a manual proxy step.
- **Session recovery across restart** (#1180, thanks @AirHua-byte; #1340,
  thanks @averatec0773) — streamed assistant text is checkpointed to
  `partial_response.json` at ≥0.25s intervals with an atomic `os.replace`,
  and every pending or running attempt on disk is reconciled at service
  construction into an explicit `interrupted` transcript entry. The reply is
  committed before `attempt.json` so recovery can finish either side of that
  write. The attempt start persists too, so the elapsed clock survives
  navigation, reload and history.
- **Windows and desktop** (#1261, thanks @Emad211; #1284, thanks
  @lorenzozanee; #1359, thanks @birdxs) — cross-platform locks and path
  handling, EPERM handled in the desktop updater's shutdown checks, and
  Docker actions moved to Node.js 24 compatible versions.
- **Swarm and MCP plumbing** (#1175, #1331, #1176, #1335, thanks @Shizoqua;
  #1210, thanks @pengpengyi92; #1173; #1345, thanks @cgycorey) —
  `cancel_run()` is threaded into the in-flight worker rather than only
  marking the DAG; goal sessions are isolated per MCP connection rather than
  per process; `goal_id`/`expected_goal_id` default to the current goal;
  `beginTime`/`endTime` are forwarded through `get_research_reports`; worker
  retries use bounded backoff; the MCP stdio registry path has coverage; and
  investment-committee researchers get the fundamental data panel their
  prompts already assumed (#1343).
- **Portfolio OAuth lifecycle** (#1211, #1251, thanks @goatyyc) — the
  reconnect lifecycle is isolated, and reconnect failures are classified
  rather than collapsed into one opaque error.
- **IBKR** (#1186, thanks @sykuang; #1190, thanks @goatyyc; #1178, thanks
  @c020627) — public MCP OAuth flow support, verified read tools enabled, and
  the official read-only seed pointed at `/mcp-public`.
- **Futu HKD valuations** (#1228, thanks @JaxonHu1024) and futu
  `connection_state` handling.
- **Feishu QR login credentials persist** (#1188, thanks @AirHua-byte).
- **Persistent memory cleans up after itself** (#1174, thanks @Shizoqua) —
  garbage collection and compression left the FTS index and the semantic
  links pointing at entries that no longer existed, so a cross-session recall
  could surface a row whose body had been collected.
- **Strategy store and discovery** (#1347, thanks @ethanstoner; #1368,
  thanks @Shizoqua) — `created_at` ties are broken so history is really
  newest-first, and position size is resolved per regime rather than once for
  the whole run.
- **Valuation and credit refuse non-finite inputs** (#1184, #1215, #1386,
  thanks @Robin1987China) — comps, three-statement inputs and every
  credit-risk function reject non-finite values rather than propagating them.
  The three Archimedean copula CDFs returned wrong extreme values under
  strong dependence — Clayton `0.0`, Gumbel `1.0`, Frank `inf` — and are
  computed in log space now, verified against a 2500-digit reference across
  θ ∈ [-5000, 5000] (closes #1385). Note that the first fix covered only
  θ > 0; θ < 0 overflowed to `nan` from |θ| ≈ 355 and the rewrite dipped
  below the Fréchet bound as θ → 0, both caught before merge.
- **Cross-validation edges** (#1204, #1220, thanks @santhreal and
  @he-yufeng) — multi-segment test sets are supported, empty training
  partitions are guarded, and rows between combinatorial test blocks are
  pinned as still trainable.
- **Skill and documentation links** (#1252, #1328, thanks @ethanstoner;
  #1189, thanks @youngjincho02-arch) — a skill-relative reference link
  resolves in `read_file`, the skill-name prefix is dropped so links resolve
  on GitHub, and the `historical_var` quantile formula in the risk-analysis
  skill is corrected. Verification note for the first two: the agent reads
  through `ReadFileTool` rooted at `src/skills/`, not through GitHub's
  renderer, so the two conventions had to be checked against the real
  consumer.
- **Dependencies** (#1321, #1322, #1323, #1324) — dockerhub-description
  4.0.2 → 5.0.0, docker/login-action 3.7.0 → 4.6.0, 15 npm minor/patch
  updates and 43 pip minor/patch updates, via Dependabot.

### Changed

- The `futures` fallback chain is now `["akshare", "local"]`.
  `resolve_loader` walks `FALLBACK_CHAINS` and never consults a loader's
  `markets` set — the only `.markets` read is the explicit-source fallback —
  so trimming that set alone would have left `tushare` first in line,
  constructed and available on any `TUSHARE_TOKEN`, returning empty frames
  before `akshare` was ever asked.
- `tushare` no longer declares the `futures` market. Serving it needs
  `pro.fut_daily`, which sits behind a points tier nothing here implements.
- China futures main continuous contracts (`RB0`, `IF0`) now classify as
  `futures` rather than falling to the `a_share` default. The rule is
  generated from the product whitelist rather than from a width heuristic,
  so an ordinary ticker ending in `0` keeps its own market.
- `test_release_version_consistency.py` did the job it was written for. The
  bump missed the `app.version` mock in
  `frontend/src/components/layout/__tests__/Layout.test.tsx`, and the guard
  named it — that site has been in its enumeration since it shipped with
  0.1.14, which is the point of enumerating declaration sites rather than
  spot-checking the ones somebody remembers. The locale check globs its
  directory, so `pt-BR.json` was covered the day it landed without anyone
  extending the test. The version named in a `test_cli_update.py` comment is
  de-versioned here — a version string in a comment has no guard at all and
  goes stale at the next bump.
- Reader-facing counts were re-measured against the code rather than
  incremented by hand: 74 MCP tools, 107 registry tools, 10 backtest engines,
  90 bundled skills, 462 alphas, 27 data sources, 30 swarm presets, 14 broker
  connectors. None had drifted this cycle.

## [0.1.14] — 2026-08-20

Rolls up 272 commits / 74 merged pull requests since 0.1.13.

### Added

- **Options Lab** (#1096, closes #1095, thanks @shadowinlife) — a Web UI page
  with four surfaces: expiry payoff diagram, spot×IV scenario P&L matrix,
  portfolio Greeks cards, and a live US options chain. The math is not new: two
  read-only HTTP endpoints wrap the existing `options_payoff` /
  `get_options_chain` tools, so the page and the MCP surface compute from the
  same test-pinned `src/quantlib/options.py`. Research only — it places no
  orders.
- **Factor Research tab** in Run Detail (#1099, thanks @shadowinlife) — IC
  statistics cards, the daily IC series with its mean line, quantile-group
  equity curves, and an IC correlation heatmap, all rendered from the
  `factor_analysis` artifacts a run already writes. The new read-only
  `GET /runs/{run_id}/factor` endpoint scans the run's `artifacts/` tree and
  computes the pairwise IC time-series correlation matrix, which existed
  nowhere before; a `has_factor_artifacts` flag gates the tab so runs without
  factor output do not show an empty panel.
- **Positions tab** in Run Detail (#1097, closes #1098, thanks @shadowinlife) —
  portfolio-book structure from the existing `positions.csv`: a per-symbol
  weight pie/treemap with a date slider, sector and asset-class net-exposure
  bars, and a weight-evolution stacked area. The pie is **gross** composition
  (absolute weights including shorts and cash) while the bars are **net**
  exposure per industry, so a long/short pair in one sector nets to zero on the
  bars while both legs stay visible on the pie. The two charts answer different
  questions on purpose.
- **Tearsheet tab** in Run Detail (#1091, closes #1090, thanks @shadowinlife) —
  monthly-returns heatmap (years × months with a full-year column), annual
  returns bar chart, top-5 drawdown table, and an equity curve annotated with
  the ranked drawdown zones. Everything is derived client-side from the
  `equity.csv` rows the run response already carries: no backend change, no new
  dependency, and month axis labels come from `Intl.DateTimeFormat` rather than
  per-locale month keys.
- **Interactive backtest research dashboard** (#1084, thanks @AndyLongest) — an
  optional report-style view for a completed backtest alongside the existing
  candlestick and trade-detail views: headline return/risk/trading KPIs,
  normalized equity versus benchmark, drawdown with rolling Sharpe, realized
  trade P&L, a trade ledger, and the complete metric table. CLI backtests get a
  quiet local report-server bootstrap so `Full Report` routes to the dashboard
  without a manual server step.
- **Strategy Discovery** (#978 Phase 1 and #1007 Phase 2, refs #969, thanks
  @shadowinlife) — a read-only facade answering "what strategies exist and what
  state are they in?" across the Alpha Zoo and the SDM strategy store, with
  per-`(strategy, regime)` evidence rows rather than scenario tags. Ships
  `list_strategies` / `query_strategies` / `get_strategy_evidence` as agent and
  MCP tools behind an evidence gate (minimum-trade, coverage and
  cost-breakeven thresholds, each with an explicit warning), plus a startup
  guard that drops the routing text when any advertised tool is not actually
  registered. Phase 2 adds the population path — `refresh_strategy_evidence`
  as an agent tool, an MCP wrapper and
  `vibe-trading strategy-evidence refresh --manifest` — with the
  `backtest-diagnose` Hard-Gate Checklist as the ingestion gate (stable
  `hard-gate:*` skip tokens) and atomic rebuilds. Freshness is computed at read
  time from the evidence-window age (`fresh`/`aging`/`stale`); stale rows fail
  closed out of default recommendations behind an `include_stale` opt-out, and
  `sdm:*` rows mirror the SDM lifecycle.
- **Scheduled research now delivers itself.** A finished briefing leaves the
  run through an outbox rather than waiting to be read: the outbox row is
  claimed under a lease before sending so a crash mid-delivery cannot double
  post, the send is wired to both the session and the channel runtimes, and the
  push happens on the terminal event. Delivery is configured and watched from
  Market Watch.
- **Each monitor's latest verdict is persisted on its job** (#1152, refs #943,
  thanks @he-yufeng) — the run's terminal briefing is parsed server-side into a
  structured `last_verdict` record and the `/scheduled-runs` list carries it
  inline, so the list renders a verdict without re-parsing free text per row or
  going N+1 on sessions. The five research playbooks grow a strictly additive
  `## Verdict` tail — one `- SYMBOL: STATE - reason` line per tracked symbol,
  each playbook declaring its own state vocabulary. Parsing is deliberately
  strict: an ad-hoc prompt lands permanently at `no_verdict_section` and renders
  as nothing rather than a warning, a run that tracked nothing is a real "no
  calls" answer rather than an absence, and a malformed section degrades to
  `contract_violation` instead of showing a wrong verdict. The prior record is
  embedded one level deep at write time and no deeper.
- **Futu connector — seven extended read-only endpoints** (#1135, thanks
  @549236606-oss) closing the gap between what the SDK exposes and what the
  connector consumed: `get_rehab` (dividend/split/rights adjustment factors, so
  backtests stop reading dividend gaps as price moves), `get_capital_flow`
  (historical super/big/mid/small inflow buckets), `get_capital_distribution`
  (today's in-flow versus out-flow snapshot), `get_history_deals` (fill records
  for true cost-basis reconstruction, capped at the SDK's 360-day window),
  `get_acc_cash_flow`, `get_financials` (income/balance/cash-flow statements),
  and `get_earnings_calendar` with EPS and revenue consensus. Each routes
  through the same `_quote_ctx` / `_trade_ctx` / `_assert_gateway` envelope as
  the original five, so missing data, missing privileges and a missing OpenD all
  degrade to a clean fail-closed payload instead of an SDK stack trace. The
  `futu-api` SDK stays lazily loaded.
- **Vietnam equities (HOSE)** as a backtest market (#1033, thanks @ngoanpv).
  `.VN` matched no entry in `_MARKET_PATTERNS`, so `_detect_market` fell back to
  `a_share` and executed Vietnamese bars under China A-share rules — and asking
  for Yahoo explicitly did not help, because both Yahoo loaders gated on suffix
  and rejected `.VN` before building the request. `.VN` now resolves through the
  Yahoo loaders with a `["yahoo", "yfinance", "local"]` fallback chain and runs
  on a dedicated `VietnamEquityEngine`.
- **Offline USD-M account reconciliation** (#1106, relates #1030, thanks
  @honginp) — immutable Binance USD-M account and position snapshot contracts
  that compare an exchange observation against the existing `AccountState` and
  `RiskSnapshot` without mutating either, reporting numeric, structural,
  missing-symbol and unexpected-symbol drift deterministically. Liquidation-engine
  validation is explicitly left unassessed rather than silently assumed. This is
  the Shadow 1 slice: contracts and fixture-only offline reconciliation.
- **Novita AI** as a built-in OpenAI-compatible provider (#1059, thanks
  @jax-novita) — registered in the provider registry with `NOVITA_API_KEY` /
  `NOVITA_BASE_URL` and wired through capabilities, CLI onboarding,
  `.env.example` and the README provider list, so it is selectable from the
  built-in list instead of hand-configured as a custom endpoint.
- **GitHub Copilot** as a provider through the official `github-copilot-sdk`
  (#990, supersedes #899, thanks @sykuang), with SDK-managed authentication from
  `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, stored Copilot CLI
  credentials or `gh` credentials, plus LangChain-compatible invoke, streaming,
  reasoning and tool-call handling and Settings/preflight integration. This
  implements the boundary #899 was closed on: no borrowed OAuth client ID and no
  editor-impersonation headers.
- **tickerall hosted MetaTrader 5 data source** (#968, closes #897, thanks
  @miguelangelo78) — a broker's MetaTrader 5 candle feed over the hosted
  TickerAll HTTP API, so forex and metals backtests run on any OS with no local,
  logged-in MetaTrader 5 terminal. Purely opt-in: `is_available()` is False
  unless `TICKERALL_API_KEY` and `TICKERALL_ACCOUNT_ID` are set, and the loader
  never joins an automatic chain.
- **A drift tolerance band for rebalance mode** — a rebalance that would move
  the book by less than the band is skipped rather than executed for a rounding
  difference.
- **Spanish and German locales** (#1087 thanks @daviddaco1, #1117 thanks
  @1psconstructor). Spanish ships a full key-for-key `es.json` plus
  `README_es.md`, making Spanish the sixth README; German ships `de.json` with
  the full UI key set. Both register in `SUPPORTED_LANGUAGES` and
  `localeLoaders` on the existing lazy-loading path, and the locale-parity and
  interpolation-variable tests cover them.
- **Desktop update safety boundary** (#1101, refs #1016, thanks @QCYTSN) — a
  strict PID-scoped backend/watchdog shutdown result for a future update
  handoff, dormant Windows candidate verification, interrupted-attempt recovery
  primitives, and a documented, tested rejection matrix for tampered, unsigned,
  invalid-signature, wrong-publisher and downgraded candidates. The signed
  `0.3.0 → 0.3.1` run itself remains blocked on a signing identity; this is the
  part that could be made executable before a certificate exists, including the
  proof that desktop cleanup never kills unrelated Python processes.
- **Docker images carry the Feishu and Telegram channel dependencies** (#1088,
  thanks @birdxs), with a manually triggered workflow that builds and pushes to
  both GHCR and Docker Hub and syncs the project description to the Docker Hub
  page.
- **Strict alpha t-stats** in the bench JSON and HTML report (#1085, thanks
  @jay79-boop), so the strict-mode number is readable from the artifact instead
  of only the console.
- **Offset paging on the MCP surface** for SEC filings and financial statements
  (#1138), and `load_skill` routed through the registry so an oversized skill
  pages instead of being truncated at the transport limit (#1137).

### Changed

- **The MCP surface grows to 74 tools** (from 70 in 0.1.13).
- **`smartmoneyconcepts` is now an opt-in `[smc]` extra, not a base
  dependency** — and the stale `<3.14` cap is gone from both the project
  metadata and the distribution manifest. The package pulled in
  `numba` → `llvmlite`, and llvmlite ships no macOS x86_64 wheel from 0.46
  onward, so as a base dependency it turned every Intel-Mac install into a
  source build that needs CMake (discussion #1035). It backs exactly one skill
  example, whose `SKILL.md` already tells the reader to install it. Intel-Mac
  users on Python 3.11–3.13 can now `pip install vibe-trading-ai` without a
  toolchain.
- **CI runs the test job on both the floor and the ceiling of
  `requires-python`**, so a version-specific break at either end is caught
  before release rather than by a user.
- **Vite moves from 6.4.3 to 8.2.0** in the frontend dev toolchain (#1022).
- **Market-data provenance now declares per-market volume units** (#1065,
  #1131, thanks @shadowinlife), and `get_market_data` carries that provenance
  over MCP rather than dropping it at the transport boundary.
- **The Ollama runtime URL is normalized at source** (#1074) instead of being
  patched at each call site.

### Fixed

- **A run's grounding gate stops refusing answers it can support.** The
  identity/price recovery path now re-fetches missing evidence within a bounded
  budget instead of rejecting outright (#1092, thanks @Shizoqua); identity
  constants in rate formulas are no longer read as unsupported quotes (#1083,
  thanks @AndyLongest); line-leading ordered-list markers are masked before
  number extraction (#1063, thanks @zzz607); ISO dates that run straight into
  CJK text are recognised as dates (#1132, thanks @Robin1987China); a
  report-style date cell parses as a date and a US CSV stem resolves; a
  dash-form trading day reads as a date and both bounds of a ranged level are
  masked; an order line is read as an instruction rather than an observed
  quote; and an "@" level is masked only when a quantity or an order label
  accompanies it, so a bare price is still held to the evidence standard.
- **Agent run reliability** (#1105, thanks @wiliao) — grounding
  false-rejections, the final-answer gate and LLM timeouts, together with
  prompt wording and support/resistance masking (#1060).
- **`build_registry()` no longer returns a partial registry in silence**
  (#1129, thanks @er-s-an): a construction failure is reported instead of
  leaving the caller with a short tool list that looks complete.
- **Backtest correctness**: `excess_return` stays consistent with the corrected
  `benchmark_return` (#1058, thanks @Shizoqua) and the corrected benchmark
  fields are rounded to the metrics contract; the engine reports actual
  post-fill positions rather than the requested ones (#1082, thanks
  @AndyLongest); hold mode says so when it drops a requested resize; the
  archive no longer mixes two runs' artifacts into one bundle; and importing
  the runner module no longer loads `.env` as a side effect.
- **Quantlib numerics**: `xirr` and money-weighted return survive long-horizon
  discount underflow instead of crashing (#1119, thanks @pengpengyi92); DCF
  refuses non-finite inputs rather than returning a silently negative share
  price (#1121, thanks @Robin1987China); a zero-volatility option discounts its
  forward value (#1066), the fixed-income curve keeps decay inside the
  requested bounds (#1076), event studies anchor to the prior session (#1078),
  and cross-validation aligns label ends to the prior observation (#1079) — all
  thanks @pengpengyi92. `technical_indicator` RSI uses Wilder EWM smoothing
  (#1056, thanks @Shizoqua).
- **Swarm**: worker prompts are ordered for prompt-cache-friendly prefixes
  (#1057, thanks @Echoandelementwebsites); worker artifacts are isolated between
  retry attempts (#1053) and a path-shaped agent id is rejected before the retry
  `rmtree`; raw `ok`/`success` tool-result envelopes are rejected (#1052) and
  oversized tool results truncate with the shared notice (#1110) — thanks
  @Shizoqua; tool-less agents are no longer instructed to call `write_file`
  (#1144, thanks @Echoandelementwebsites); and the per-task `ChatLLM` is closed
  to stop a pooled-connection leak (#1145, thanks @cgycorey), with the same
  treatment for the one-shot clients in auto-title and image vision (#1153).
- **Connectors and market data**: baostock volume is normalized to board lots
  behind a cross-source consistency guard (#1067, thanks @shadowinlife); the
  IBKR market-data tier is selectable and starved quotes report as `no_data`
  (#1075, thanks @jay79-boop), with the requested and the applied tier reported
  separately; eToro gains runtime UI parity for SDK connector status (#1051) and
  fixes crypto browse and flat market-data quotes (#1070, thanks @ofeksh-tr);
  the `tencent` loader builds its SSL context from the certifi CA bundle, since
  the new GlobalSign Atlas R3 root is absent from Python's default store and HK
  quotes failed every retry (#1113, thanks @x-lambda); and the East Money
  research-report endpoint gets the time parameters it now requires (#1077,
  thanks @zzz607).
- **CLI**: `connector orders` renders broker_sdk rows — the renderer only knew
  the nested IBKR shape, so a flat row left every column but Account empty — and
  stringified SDK enums print as `BUY` rather than `OrderSide.BUY`, while
  class-B tickers such as `BRK.B` and decimal values are left intact (#1150,
  thanks @nstavros); direct SDK account diagnostics render (#1073); the `show`
  subcommand dispatches its `run_id` instead of the `--show` flag (#1147, thanks
  @cgycorey); and a Docker Codex OAuth EOF explains itself (#1054, thanks
  @zhiwuyazhe-fjr).
- **Providers**: reasoning effort is honoured in chat completions (#1025, thanks
  @cgycorey) and passed through to the Anthropic adapter (#1115, thanks
  @straun-repo).
- **A remote MCP failure reports the server's own explanation** instead of a
  bare status code, so a rejected token reads as a rejected token (refs #1126).
- **Scheduled research**: an in-flight delivery is no longer overwritten
  (#1140, thanks @Shizoqua), and the `scheduled-runs` DELETE returns an empty
  `Response` for its 204 (#1068, thanks @ofeksh-tr).
- **Tools and agent**: unsupported ticker-plus-name symbol queries are marked
  skipped rather than failed (#1114) and recovery steering is delivered as user
  messages with inline system tags (#1112) — thanks @lorenzozanee;
  prediction-market fields reject non-finite values and the envelope stays
  strict JSON (#1136, thanks @Shizoqua); `gross_profit` is derived from revenue
  minus COGS when the SEC tag is absent (#1111, thanks @cgycorey); every
  compacted message folds through the summarizer; and the autopilot preserves
  backtest validation evidence when linking hypotheses (#1139, thanks
  @Shizoqua).
- **Onboarding**: `.env.partial` is created with owner-only permissions (#1086,
  thanks @lukiod) and written atomically, so a failed save cannot destroy
  recovery state.
- **Memory**: the fallback tokenizer's minimum is aligned with the FTS5
  sanitizer (#1071, thanks @Shizoqua).
- **Research reports** reject a reversed window instead of reporting it as
  missing coverage.
- **Web**: inferred strategy labels are marked as inferred in the run dashboard
  (#1134, part 1 of #1094, thanks @fixXxerTech).
- **The test suite no longer escapes its sandbox into the real config root**
  (#1118, closes #1116, thanks @lorenzozanee). A full run had been appending
  synthetic `order_rejected` records to the live, hash-chained audit ledger at
  `~/.vibe-trading/live/audit.jsonl` and writing a `live/audit_chain.jsonl`
  holding a single NUL byte. It was reported on Windows, but the escape was not
  Windows-specific — a default macOS environment leaked the same way. The
  config root is now sandboxed before collection, through one knob at the tail
  of the resolution chain rather than a per-test override, and `os` patches are
  confined to the module under test.
  hash locks are portable across supported platforms (#1102); Windows desktop
  packaging inputs are stabilized (#1104); the Docker build workflow is pinned
  and the image stays on hash-locked dependencies; the alpha-bench SP500 panel
  carries the GICS sector through; a frontend test waits on the sector
  re-render rather than on the spinner disappearing; and the Spanish locale says
  "demo", not "papel", for paper trading.

## [0.1.13] — 2026-08-10

Rolls up 408 commits / 162 merged pull requests since 0.1.12.

### Added
- **`src/quantlib` — a tested finance-math layer** (265 functions across 19
  modules): one
  implementation each of Black-Scholes price/greeks/IV inversion, bond math +
  Nelson-Siegel/Svensson, Altman Z + Merton/KMV, stationarity/cointegration/
  GARCH/bootstrap, VaR/CVaR/EVT, Brinson-Fachler attribution, event studies,
  multiple-testing control, and purged cross-validation. Skills now *import*
  these instead of carrying formulas inside markdown code blocks. Reachable
  from the CLI, the Web UI, the REST API and MCP through the read-only,
  pure-compute `quantlib_call` tool, so the finance math works where `bash` is
  gated off — module allowlist, `__all__`-only, `export_*` refused.
  `attribution` and `impact` were allowlisted but carried no `__all__`, so the
  tool listed zero functions for them; both now export, and a guard test fails
  when any allowlisted module exposes nothing. Econometrics needs the
  `stats` extra (`statsmodels`/`arch`), which the functions lazy-import and
  name.
- **Valuation engine** (`src/quantlib/valuation/`): `run_dcf` (FCFF bridge,
  WACC build, dual terminal value that cross-checks each method against the
  other's implied multiple and implied g, mid-year discounting, net-debt
  bridge, WACC×g grid), `run_comps` (EV bridge, LTM + calendar-year
  calendarisation, multiple matrix — a peer with a non-positive denominator is
  *excluded and reported*, never averaged in as a negative multiple), a linked
  three-statement projection with a hard balance assertion, explicit revolver
  plug and an iterated interest↔debt circularity that must converge or raise,
  plus input-hashed versioned artifacts with xlsx/pptx export. One shared rule
  in `contracts.py`: **a missing input makes a model NOT RUNNABLE and is never
  silently defaulted.**
- **Typed entity + irregular dated cash-flow substrate** (`src/entities/`) —
  the non-bar ingestion path for NAVs, capital calls and coupons, deliberately
  parallel to the bar engines so a `nav` column can never reach one and get
  priced as a close. Surfaced by the read-only `cashflow_performance` tool
  (XIRR / MOIC / DPI / TVPI / TWR / Modified Dietz / MWR over an irregular
  dated series).
- **`orderbook_depth`** (read-only): crypto L2 ladder via ccxt — spread bps,
  depth imbalance, and the impact cost of a stated notional walked through the
  real book in both directions. `fully_filled` and `timestamp_source` must be
  read before quoting anything; equities still have no depth source.
- **Governance wired into every run** (`src/governance/`): a run manifest hashes
  the prompt, skill contents, tool registry and package versions so "what
  methodology produced that number" is answerable, and the audit ledger is
  hash-chained + fsynced so editing or deleting a record is detectable (an edit
  that recomputes its own hash is caught one record later via
  `prev_hash_mismatch`). All 30 swarm presets were re-audited — a deliverable
  no granted tool can compute is now declared as such instead of invented.
- **Four read-only data tools, all on free public sources**:
  `get_institutional_holdings` (SEC 13F-HR; manager / ticker-holders /
  top-managers modes with quarter-over-quarter position diffs, and cover-page
  unit detection because pre-2023 filings report in thousands),
  `etf_holdings` (cross-market look-through — SEC N-PORT for US, and for
  A-shares the semi-annual/annual reports that carry the *full* book rather
  than the quarterly top ten: 510300 returns 342 rows / 98.66% of net assets
  vs 10 rows / 22.74%; `coverage` distinguishes `full_portfolio` from
  `top_n_disclosed` and every response stamps the report period),
  `prediction_market` (event-contract search/event/market/history with prices
  surfaced as labelled implied probability), and `research_papers`
  (arXiv + OpenAlex search/read with source-anchored claim extraction that
  marks what a source does not state instead of inferring it).
- **Institutional research surface**: six slash commands — `/comps` `/dcf`
  `/attrib` `/memo` `/earnings` `/screen` — each carrying a step skeleton and
  an arithmetic-consistent worked example (the Brinson decomposition sums
  exactly to active return; the earnings bridge sums exactly to the EPS delta).
- **Investor lenses** as a standalone skill (`src/skills/investor-lenses/`):
  named-investor reasoning frameworks as stackable analysis overlays, decoupled
  from the data layer. Each lens is an operating procedure — priority signals,
  disqualifying conditions, typical misuse — not a biography, and names no tool.
- **Five ready-to-schedule research playbooks** (premarket brief, earnings-season
  tracker, portfolio checkup, A-share money flow, institutional-holdings diff),
  reachable three ways: auth-gated REST routes beside the existing CRUD, a
  `vibe-trading playbook` CLI subcommand, and a `/playbook` slash command.
  Templates state their data needs in natural language rather than naming
  tools, so coverage can grow without editing them, and every one mandates
  naming a missing input instead of filling it from memory.
- **Desktop shell** — a source-first Electron host that owns the existing
  backend lifecycle (random loopback port, per-launch secret, five-locale
  startup recovery, owned-process cleanup) (#923). Windows packaging assembles
  a checksum-pinned embedded Python 3.12 runtime with x64 NSIS review/signing
  paths, plus Electron `safeStorage` for an allowlisted credential set — the
  renderer can set or clear secrets but never read them, plaintext config
  migrates once, decrypted values reach only the owned backend, and both
  unsigned-review and signed builds fail closed on the wrong signature state
  (#1015). No installer artifact was published from that PR.
- **Canadian equities end to end** (#1024, #1019, #1037, closes #952): `.TO`/`.V`
  symbols classified in CAD, routed Yahoo → yfinance → local, executed under
  Canada-specific GlobalEquity rules, benchmarked against `XIC.TO`, with
  mixed-currency aggregation refused.
- **Korea equity (KRX: KOSPI/KOSDAQ)** as the 9th backtest engine (#693, thanks
  @JungHoonGhae) — execution-time ±30% band on a unified tick grid, structurally
  long-only, config-driven 2026 0.20% securities transaction tax, optional
  `pykrx` loader that rejects non-daily intervals so the runner falls through.
- **eToro connector** with path-separated demo/real profiles (#989); live
  risk-increasing actions remain mandate-gated and audited.
- **OpenBB Workspace bridge** (#817, thanks @shugaoye) — optional `openbb`
  extra registering `/agents.json` + an authenticated `/v1/query`, each request
  replaying the supplied history in an ephemeral session. `pro.openbb.co` is
  not a default CORS origin; opt in via `VIBE_TRADING_EXTRA_CORS_ORIGINS`.
- **Read-only Taiwan snapshot** tool (#848, thanks @TSENGCHIENFENG), registered
  only when `VIBE_TW_STOCK_DB` points at a schema-valid snapshot.
- **Options strategy analytics** (#946, rebuilt from #883, thanks @he-yufeng) —
  analytic expiry P&L extrema, exact breakevens including continuous zero-P&L
  intervals, engine-aligned entry commissions, and spot × IV scenarios through
  Agent and MCP.
- **Read-only `sentiment` tool** (#939, thanks @Robin1987China): local lexicon
  scoring for arbitrary text plus the crypto Fear & Greed Index from
  Alternative.me's free, no-auth API.
- **Read-only `technical_indicators` tool** (#921, refs #920, thanks
  @Robin1987China) — RSI/MACD/Bollinger/SMA/EMA through the existing loaders.
- **Timezone-aware scheduled research** (#954, closes #953, thanks @ngoanpv):
  jobs take an optional IANA `timezone` and evaluate cron on that zone's wall
  clock, so a cadence survives DST — a spring-forward gap is skipped and a
  fall-back ambiguous time runs once. Cron fields gain comma lists and ranges
  (`1,3-5`); jobs without a timezone keep UTC semantics; the web UI gains a
  **Scheduled** page in all five locales.
- **`vibe-trading update`** (#1020) — checks PyPI for a newer release and
  upgrades in place, installing the exact release it checked and verifying
  fresh metadata without downgrading. Editable/source checkouts are detected
  and answered with the right manual instruction (`git pull` + reinstall)
  instead of a pip upgrade that would silently replace the dev install.
- **ModelScope** joins the built-in providers through its official
  OpenAI-compatible hosted-inference endpoint, default `Qwen/Qwen3.5-27B`
  (#1011, thanks @yrk111222).
- **Live model discovery** in Settings (#924, thanks @QCYTSN) — configured
  providers are queried on demand with stable warning codes and five-locale
  controls, and each reply records and reloads the immutable provider/model/
  reasoning identity that actually served it.
- **`alpha_zoo` + bounded `alpha_bench` on MCP** (#979, thanks @cgycorey) with
  horizon/result/output-path limits and safe report creation; **QVeris**
  discovery/inspect/execute also join the MCP surface (#976, closes #964,
  thanks @shadowinlife), with the cost quote read from the marketplace instead
  of trusted from the caller.
- **The MCP surface grows to 70 tools.** Six read-only analytics tools that had
  reached the agent but never MCP are now mirrored onto it: `quantlib_call`,
  `cashflow_performance`, `orderbook_depth`, `sentiment`,
  `technical_indicators` and `get_fundamentals`. Order-placing tools stay
  structurally un-exposed — the mirrored registration path refuses any class
  whose `is_readonly` is not `True`, so an order tool cannot reach MCP even if
  someone adds it to the source list.
- **Memory Tier 2: structural organization** (#815, thanks @shadowinlife) —
  four independently-gated modules (H-MEM hierarchical routing
  `VT_MEMORY_HIERARCHY`, A-MEM BM25 semantic linking `VT_MEMORY_LINKS`,
  TF-IDF auto-compression `VT_MEMORY_COMPRESSION`, FTS5 index with CJK bigram
  tokenization `VT_MEMORY_FTS_INDEX`), a one-line `VT_MEMORY=off|on|full`
  preset replacing seven individual flags, dependency-conflict warnings, lazy
  FTS5 rebuild on first search, and 9 integration + 23 benchmark tests. All
  off by default (#733, closes #732).
- **SDM lifecycle tools** `sdm_register` / `sdm_status` / `sdm_decay_scan`
  (#457, thanks @shadowinlife) backed by a SQLite artifact store
  (`UNIQUE(name, universe)`, WAL) and an IC/Sharpe decay state machine
  (active → monitoring → decayed → disabled).
- **`alpha bench --strict`** (#796, closes #773, thanks @he-yufeng) finally
  wires the strict same-universe random-control + OOS gate that shipped
  unreachable since 0.1.9; `alpha bench` also discloses CSI300/SP500 sources,
  counts, degraded fallbacks and survivorship bias (#859, closes #845), with
  the `_meta` disclosure forwarded to CLI/HTML (#841, closes #797, thanks
  @AmirF194).
- **Risk x-ray artifacts** (`risk_xray.json`/`.md`) emitted by every portfolio
  backtest with headline concentration/vol/drawdown metrics (#900, thanks
  @he-yufeng), plus rebalance-notes artifacts and turnover metrics (#795).
- **Composable optimizer weight constraints** (#818, thanks @he-yufeng);
  `calc_metrics` reports tracking error and benchmark beta.
- Opt-in **atomic same-direction rebalancing** in backtests with immutable fill
  evidence (#951), and opt-in `position_adjustment=rebalance` for strict USD-M
  historical backtests preserving collateral, funding, fees, realized P&L,
  liquidation behavior and fill evidence across increases and reductions
  (#1019, thanks @honginp).
- **USD-M perpetual realism**: `perpetual_strict` settles historical funding
  before fills and executes isolated/cross margin breaches as real liquidations
  (#903, #889, thanks @honginp), margin state contracts (#798), historical
  funding rates actually consumed rather than fetched-and-ignored (#819, thanks
  @g0rdonL), and ordered fill/funding/risk/liquidation event persistence plus a
  fidelity summary (#936).
- **Final report aggregator stage** for the `quant_strategy_desk` swarm preset
  (#1048, thanks @Robin1987China).

### Changed
- **Rebuilt WebUI** — the guided-minimalism overhaul: no first-frame flash, one
  durable activity object per turn with a live reasoning whisper and a
  reload-safe tool trail, LLM-written session titles, full five-locale parity.
- Sessions, runs, swarm runs and uploads now live under `~/.vibe-trading`
  (relocatable via `VIBE_TRADING_HOME`) with a one-time automatic migration
  (#925, closes #904, thanks @MuggleJinx).
- The frontend moves to **Node 22 + React Router 8**, clearing a high-severity
  advisory; Electron transitive advisories were patched separately.
- Daily price bands are judged **at execution time** — from a pre-fill base
  price against the prospective fill price — never from the decision bar's own
  close.
- A session runs **one attempt at a time** (a second concurrent send is refused
  with HTTP 409), and a user stop is its own terminal state distinct from a
  failure, both live and on reload (#676, thanks @tyj147454413-cmd).
- Trace redaction is now **sink-aware**: `content` is released only in the
  tool-RESULT sink and stays redacted in the fail-closed ARGUMENTS sink used by
  tool-call arguments and the live audit ledger (`env` is never released);
  results also get their string leaves pattern-scrubbed (#675, #913, #911,
  thanks @santhreal). Trace records are fsynced and sidecars made durable
  before the record that references them (#662).
- Oversized tool results are paged by whole record with an explicit total
  instead of being cut mid-JSON; the system prompt drops redundant tool prose.
- Dependency locks refreshed and verified across Python and the frontend
  (#949, #948, #850–#852, #1021, #1023, #1026, #1027); the breaking MCP 2.0
  bump remains unmerged pending a complete lock/runtime migration (#950).

### Fixed
- **The identity/grounding gate stops refusing answers it has the evidence
  for.** This was the single most user-visible defect in the 0.1.12 line — a
  well-formed run would spend minutes on real tool calls and then return
  *"cannot safely confirm instrument identity or price evidence"*. Root causes,
  each fixed and covered by two-sided guard tests:
  - `.SS` and `.SH` were treated as different instruments, so **every Shanghai
    ticker was permanently ambiguous**. Symbols are now canonicalized
    (`.SS`≡`.SH`, `sh600519`≡`600519.SH`, `700.HK`≡`00700.HK`,
    `BTC/USDT`≡`BTC-USDT`) before comparison, and candidates are collapsed by
    canonical symbol before the ambiguity test.
  - A **failed side query could demote an already-locked identity**; aggregate
    status now keeps a lock unless something genuinely conflicts.
  - Yahoo returns HTTP 400 for every CJK query, which was recorded as a source
    *failure* and escalated to blocking `invalidated`. Non-ASCII queries are
    now declined up front with an explicit skip marker, and a resolution with
    clean sources and no failures resolves to `not_found` rather than
    `invalidated`. All resolver skip markers were unified on one prefix, with a
    cross-module contract test.
  - A hardcoded per-tool whitelist decided which bare tickers could be matched,
    blocking 11 of the 17 documented argument spellings; matching is now by
    uniqueness against the authorized set.
  - Chinese-language answers were rejected for writing `雅虎`/`腾讯` instead of
    the ASCII loader name, and `元` instead of `人民币`. Source and currency
    aliases now cover the user's language.
  - Thousands separators split a clause mid-number, so `¥1,309.22` was compared
    as `1` against the observed range and reported as a price conflict.
  - Conceptual questions with no instrument at all, and comparison reports,
    were dead-ended by the gate.
  - Follows the narrower 0.1.12-line fixes for numbers that were never prices —
    confidence scores, indicator readings, moving-average windows, year-less
    dates like `8/5`, percentage ranges, and a plan's own trigger levels
    (`close ≥ 6.45` is a condition, not a quote) (#1001, #983, #955) — and a
    many-candidate shortlist now counts as an answer rather than a stalled
    resolution. A quote outside recorded OHLC evidence is **still refused**.
  - Ordering, evidence and serialization repairs from the same family: a
    canonical symbol/venue must be locked before a market-sensitive tool-call
    batch starts so a resolver and its consumer cannot race (#887/#886); tool
    envelopes with `ok: false` / `success: false` are no longer recorded as
    successful calls; NaN/inf volume and close no longer crash
    `format_grounding_block` (#1043, thanks @santhreal); the latest close is
    paired with its correct date; and bash-written run-dir OHLC CSVs count as
    observed evidence (#1037, thanks @wiliao).
- **Sandbox gap closed**: generated strategy code can no longer import the
  broker layer, nor reach `socket`/`subprocess`/`os.system`/`ctypes` through a
  renamed binding — both were accepted before. `src.quantlib` still imports.
- **SEC reporting periods are keyed on their `(start, end)` span.** A 10-Q files
  the true quarter and the year-to-date frame under the same end date and
  fiscal period, so `period="annual"` had been returning a single quarter for
  AAPL FY2018–2020 (a 4.2× understatement) and every fiscal-Q4 slot in a
  quarterly series carried the full-year figure. `get_fundamentals("AAPL.US")`
  no longer answers `ok:true` with an all-null panel. PIT fundamentals also
  dedup restated rows and stop the snapshot regressing to an older fiscal
  period on a late restatement (#772, closes #771, thanks @klmtseng).
- **Tushare A-share prices are corporate-action adjusted** in both the factor
  bench and backtests — a raw close-to-close return across an ex-date was off
  by up to 47 percentage points (300750.SZ, 2023-04-26) — and the CSI300 bench
  masks each date to its point-in-time index membership.
- Cross-market composite backtests **refuse a mixed-currency code set** instead
  of summing CNY, USD and KRW into one equity curve; Shadow splits mixed
  markets by settlement currency without invented FX aggregation (#997).
- Option legs are marked at the volatility they were opened at, removing a
  fabricated day-zero P&L of up to +93% of premium; options **partial-close**
  honors the requested quantity instead of flattening the lot.
- `bar_returns` no longer erases the real move across a trading halt longer
  than the forward-fill window — the resumption move was silently recorded as
  0, understating volatility and inflating Sharpe — and an `inf` prior price
  can no longer read as a clean −100% (#895, thanks @darkknight4563).
  Buy-and-hold returns are sign-safe (#872), the rolling correlation matrix no
  longer forward-fills missing closes (#873, thanks @ddy4633), indicators use
  consecutive unsampled history (#1005), negative-equity drawdown and empty
  insolvent cross accounts are handled (#958, #959), and `inf` from
  `pct_change` on zero equity is replaced (#1041, thanks @santhreal).
- **Annualisation now covers all 24 data sources** at every interval, with a
  coverage test that fails CI when a loader lands without entries (#891, closes
  #884, thanks @Robin1987China). A 19-PR **interval-normalization sweep**
  accepts lowercase `1h/4h/1d/1w` everywhere, fails fast on unsupported
  intervals instead of silently returning daily bars, maps Yahoo `4H`→`1h`, and
  keeps `1H`/`4H` as hour bars across the Tiger/Alpaca/OKX/Shoonya/Longbridge
  connectors (#812–#838, #778–#794, thanks @santhreal); lowercase `4h` returns
  true four-hour bars (#1013).
- **Market-data routing**: partial results complete the missing symbols through
  the fallback chain and fail closed instead of silently shrinking the backtest
  universe (#689, closes #681, thanks @xkam7ar); HK fallback routing repaired
  with a new Tencent HK source (#1000); yfinance crypto routes to the crypto
  engine (#970); OKX bars use `history-candles` with rate-limit retry (#644);
  a Binance loader joins the crypto fallback chain (#643).
- **Providers**: Claude models that deprecate `temperature` (opus-4-7, opus-5,
  sonnet-5) work — the adapter drops the field when the API rejects it, retries
  once, and remembers the model, so no per-release patch is needed (#890,
  closes #856, thanks @yagnikpipaliya). The whole Kimi K-series auto-forces
  `temperature=1` (#701, thanks @sambazhu); endpoint resolution falls back to
  each provider's canonical base URL; mapping-shaped Responses stream events are
  accepted (#1034, thanks @cgycorey); OpenAI Codex OAuth gets a separate
  synchronized credential store and one-shot 401 recovery (#1014); proxy opt-out
  covers sync and async clients (#995); long model slugs stay readable (#1006).
- **MCP**: dataclass results no longer crash on a false
  `Circular reference detected` (#849, #922, thanks @Echoandelementwebsites);
  `factor_analysis` is realigned to the registered tool's real CSV contract so
  calls no longer die on `KeyError` (#715, closes #635, thanks
  @Robin1987China); list/dict arguments tolerate JSON-string clients (#993);
  the network guard accepts IPv6 and case-variant hosts (#750); the specs cache
  key includes remote server identity (#1049, thanks @Shizoqua); nested results
  serialize cleanly.
- **Swarm**: `ok:false` / `success:false` tool failures are detected, not just
  `status:error` (#1028, thanks @Shizoqua); MCP discovery is cached (#704).
- **Scheduled research** isolates malformed records (#1003), fixes
  interval-timezone validation (#1004), and retries transient dispatch failures
  with capped exponential backoff.
- **Memory**: entries are written and recovered with their `.md` suffix (#984);
  FTS5 ranking applies importance decay (#1032, thanks @Shizoqua); exact
  index-anchor matching and a respected result bound (#956, #957, thanks
  @santhreal).
- **Two quantlib modules were allowlisted but unreachable.** `attribution`
  (Brinson-Fachler) and `impact` (market-impact models) carried no `__all__`,
  and `quantlib_call` dispatches on `__all__` alone, so the tool listed **zero**
  functions for both while the package docstring advertised them. Both now
  export, and a guard test fails when any allowlisted module exposes nothing —
  the previous test only asserted each module *imports*, which could never
  catch this.
- **The published MCP manifest under-reported the server.** `SKILL.md`'s tool
  count was derived by counting `@mcp.tool` decorators, which ignores every
  tool registered through the mirrored path — so four institutional-research
  tools were live over MCP and absent from the manifest, and the contract test
  asserted that absence was *correct*. Both tests now measure
  `mcp.list_tools()`.
- **Resource leaks and robustness**: the HTTP throttle sweeps stale bucket
  entries interval-aware, preserving rate-limit spacing (#1047), the rate
  limiter no longer grows unboundedly with unique client IPs (#1039), the
  event bus notifies and removes subscribers on clear (#1046), `_json_loads`
  is guarded against corrupted JSON in database columns (#1045), and Shoonya
  tolerates empty-string numeric fields (#1038) — all thanks @santhreal.
- **Connectors**: the `connector` CLI loads `~/.vibe-trading/.env` so
  env-sourced broker credentials resolve again (#902, closes #901, thanks
  @MuggleJinx); IBKR moves to a thread-local connection pool with snapshot
  quotes, fixing hangs under parallel agent runs (#636, thanks @MikeCer); MT5
  `trading_history` coerces numpy scalars so JSON serialization no longer dies
  on `int64` (#776, closes #774, thanks @shadowinlife); CLI balances show a
  real account label (#843, closes #846).
- **Docker's hash-locked install works again** with a new CI lock check (#858,
  closes #847), and saving Agent LLM settings from the Web UI no longer returns
  HTTP 500 on Windows — the POSIX-only `os.fchmod` hardening is platform-guarded
  (#561, thanks @CRui5in).
- Non-interactive `vibe-trading run` injects a host session id: research-goal
  tools previously failed on every call while the run still reported success
  (#885). The agent now stops when evidence is sufficient (#1010).
- The **vn.py export** skill is repaired for the vn.py 4.x layout, where
  `vnpy.app.cta_strategy` no longer exists upstream — templates import from
  `vnpy_ctastrategy` (#869, thanks @y85998607).
- An **encoding and parsing batch**: UTF-16 BOM decoding in the document reader
  and trade-journal CSVs, currency symbols stripped before numeric coercion,
  `BTCUSDT`-style symbols inferred as crypto, CJK characters preserved in skill
  directory slugs, Eastmoney/Futu/Tonghuashun Excel-serial dates normalized,
  blank/NaN symbol rows skipped, and skill frontmatter parsed at EOF
  (#862–#868, #811, #749, #861, thanks @santhreal and @Robin1987China).
- QQ replies retain source message IDs (#1008); Feishu/CLI markdown table edges
  and indent-preserving channel message splits are fixed (#867).
- The daily-bar validator can opt in to **non-positive prices** — opening on
  negative bars while still rejecting zero (#816, closes #571, thanks
  @darkknight4563).
- Sandboxed runs retain their canonical root (#1012, #1017); persisted run
  state is fsync-durable (#645); Portfolio Studio artifacts are surfaced in run
  detail (#980, #982, #966, #973).

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
