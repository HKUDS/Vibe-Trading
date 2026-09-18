# Changelog

All notable changes to Vibe-Trading are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

### Changed

- **The final-answer grounding gate no longer guesses what a number is from the
  words around it.** Only a number's SHAPE is inferred — a decimal point, a
  percent sign, a currency mark or a table cell makes it a measurement; dates
  (including year-less "09-14"), years, security codes, line-leading ordinals
  and code in a language-tagged fence are structure; a plain integer is checked
  only as a price of an instrument quoted in the thousands — so a sentence
  gets the same verdict in every language. A measurement that equals a price
  or volume this session's tools returned needs nothing more. Any other one is
  declared in a fenced `figures` block at the end of the answer, one line per
  figure — `value | role | note | ref` — and checked by role: `observed` must
  appear in the referenced call or tool (`ref` may name either), filtered to
  the figure's own symbol, with a currency-marked figure compared only against
  money-denominated values and a percent only against non-price ones;
  `derived` needs an evaluable formula whose added or subtracted operands are
  all observed, matching the figure at the precision and sign it was written
  with; `proposed` is a price inside its own symbol's observed range or a
  derivation; `cited` must name its source on the figure's own line, because
  the block is stripped before anyone reads the answer; `count` covers counts,
  weights, thresholds and probabilities, while a currency-marked figure, or one
  inside its instrument's price range that no derivation uses as a factor, is
  checked as observed when declared `count`. No role other than `observed` may sit in a
  price column. The block is stripped from the released answer and never
  streamed; the artifact keeps it. The price-word, level-word,
  derivation-phrase and metric-subject catalogues are deleted with it
  (65 compiled regexes → 12, all shape), and `src/agent/grounding.py` is now
  the `src/agent/grounding/` package.
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

### Fixed

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
- **One cash-starved open is one rejection, not twenty-six** (#1470). In
  `position_adjustment="hold"`, the search that scales a basket down to the
  cash available re-planned every open on each step, and every step whose
  size rounded to zero booked a `zero_size` rejection for the same symbol on
  the same bar — one contract the cash could not hold read as 26 lot-rounding
  failures. The trial plans are silent now; a sleeve that was a real order at
  full scale and left the basket is reported once, after the search, as
  `insufficient_capital`, which the rebalance path's dropped sleeves now use
  too. `zero_size` means the lot rule and nothing else.
- **A real VaR result grounds the VaR it returned** (#1464). `quantlib_call`
  records a scalar result under the function name. For `historical_var` and
  `parametric_var` that name reduces to `var`, which the grounding gate accepts
  only as a whole field name, so the result recorded no evidence and a correct
  answer quoting it was rejected. Both names are now tail-risk aliases.
  Variances such as `residual_var` stay unmapped.
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
- **Event-study z-statistics no longer over-reject** (#1466). A CAR's standard
  error summed each day's variance, ignoring that every day is forecast with
  the same estimated parameters, so the days' abnormal returns are correlated.
  On null data, the standardised CAR's variance was 1.11 with a 120-day
  estimation window and 1.41–1.46 with a 30-day one. It is now 1.02 and 1.07,
  which is only the t correction for an estimated residual variance. Patell and
  BMP inherit the fix; `market_adjusted` was already right.
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
  characters, a full-width or Arabic decimal point, a no-break space before
  "%", the U+2212 minus sign, a backslash escape ("0\\.888"), an HTML entity
  and an ISO code glued to the digits ("CNY0.888") no longer split a price into
  unchecked integers; a decimal comma ("0,666 CNY", "12,5 %") is a decimal
  while a valid grouping ("-1,250.00") stays grouped, and an answer that writes
  a marked decimal comma reads "2,237" and "−5,132%" beside it as decimals too. Fences follow CommonMark,
  and an unterminated code fence no longer exempts the rest of the answer.
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
  (#1011, thanks @honginp).
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
  close (#676, thanks @tyj147454413-cmd).
- A session runs **one attempt at a time** (a second concurrent send is refused
  with HTTP 409), and a user stop is its own terminal state distinct from a
  failure, both live and on reload.
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
