# Skills Catalog (88)

Total: **88** skills under `agent/src/skills/`.

## By category

### analysis (22)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `behavioral-finance` | Behavioral finance applications: theories of overreaction and underreaction, behavioral explanations for momentum and reversal, investor sentiment cycles, cognitive-bias checklists, and debiasing quantitative strategies. | 1 |  |
| `commodity-analysis` | Commodity analysis (oil supply-demand balance / gold pricing / copper as an economic predictor / inventory cycles / futures premium-discount structure / seasonality), generating directional commodity signals. | 1 |  |
| `correlation-analysis` | Correlation and cointegration analysis — co-movement discovery, deep return-correlation analysis, sector clustering, realized correlation, Engle-Granger / Johansen cointegration, half-life, Kalman dynamic hedge ratio, cross-market linkage analysis, and pair-trading signal generation | 1 |  |
| `correlation-regime` | Correlation-regime detection and crisis attribution — edge-density regime states with hysteresis, causal (no look-ahead) smoothing, regime-aware exposure context, first-mover crisis attribution with honest NAME / MACRO / AMBIGUOUS / ABSTAIN verdicts, and a correlation-rewiring leaderboard that catches slow bleed-outs | 1 |  |
| `credit-analysis` | 固收与信用分析：信用债评级、利差分析、违约风险评估、城投债研究、可转债定价与策略。 | 1 |  |
| `deep-company-series` | Write a publication-grade 8-part deep-dive series on a single company (~120k words total): cognitive reset / moat / profit engine / hidden assets / era variable (e.g. AI) / financials Buffett-style / management / valuation+redlines. The core IP is NOT writing but REVISING — a strict fact-check checklist catches pseudo-precision (probability-weighted expectations, third-party MAU discrepancies, lin | 1 |  |
| `dividend-analysis` | Dividend stock analysis for income, dividend-growth, and shareholder-return strategies, including yield quality, payout sustainability, ex-dividend mechanics, and yield-trap checks. | 1 |  |
| `earnings-forecast` | 盈利预测与一致预期分析（自上而下/自下而上预测法/SUE/PEAD/分析师预期修正），捕捉业绩超预期交易机会。 | 1 |  |
| `earnings-revision` | Earnings estimate revisions, guidance analysis, and post-earnings drift (PEAD) — track analyst consensus changes, earnings surprise patterns, and management guidance shifts for US/HK equities. | 1 |  |
| `factor-research` | Factor research framework with IC/IR analysis, quantile backtesting, and factor combination. Suitable for cross-sectional factor evaluation across multiple instruments. | 1 |  |
| `global-macro` | Global macro analysis framework (central bank policy transmission / FX forecasting / geopolitical risk / capital flows), used to build macro factor signals that drive cross-asset allocation. | 1 |  |
| `macro-analysis` | Macroeconomic cycle positioning and central-bank policy interpretation, including GDP/CPI/PMI/rates/FX analysis, with output in the form of major-asset allocation tilts. | 1 |  |
| `management-deep-dive` | Deep management assessment — the 'buying a stock is buying a person' layer. For a company or a named executive, evaluate integrity (promise-vs-delivery tracking, crisis behavior, stakeholder treatment), ability (strategic foresight, execution, capital-allocation record) and governance (equity structure, compensation, related-party deals). Outputs a weighted score across integrity / ability / capit | 1 |  |
| `market-microstructure` | Market microstructure: bid-ask spread analysis, order-flow toxicity metrics (VPIN / Kyle lambda), liquidity measures (Amihud / Roll), price-impact models, limit-order-book analysis, and China A-share call auction / block trade mechanics. | 1 |  |
| `performance-attribution` | Performance attribution analysis — Brinson sector/stock-selection attribution, factor alpha/beta decomposition, market-timing evaluation, and benchmark comparison framework. | 1 |  |
| `private-company-research` | Deep research framework for pre-IPO / private companies (Ant Group, SpaceX, Stripe, ByteDance...). Six analyst lenses — business model, financial forensics, competitive landscape, risk & governance, tech & IP, alternative-data signals — run in parallel via run_swarm, then cross-validated for signal consistency before any verdict. Built around the core challenge of private-company work: information | 1 |  |
| `quant-statistics` | Quantitative statistical methods: ADF unit-root / cointegration tests, GARCH volatility modeling, regression diagnostics (heteroskedasticity / autocorrelation), Bootstrap, and hypothesis testing. | 1 |  |
| `research-discipline` | A short self-bias checklist to run at the START of any investment research task (stock screen / sector study / company deep-dive). Four biases that systematically warp AI research — leader-bias (only big caps), English-bias (miss JP/KR/TW players), narrative-bias (chase concept labels), confirmation-bias (only bullish evidence) — plus recency-bias. Load this first, then research with the correctio | 1 |  |
| `risk-analysis` | Risk measurement and stress testing — VaR/CVaR/max drawdown calculation, Monte Carlo simulation, extreme-value tail-risk analysis, and historical scenario stress testing. | 1 |  |
| `sentiment-analysis` | 市场情绪分析——恐贪指数/Put-Call Ratio/融资融券/北向资金信号解读、社交媒体舆情量化框架 | 1 |  |
| `shadow-account` | Shadow Account — 从用户交割单提炼盈利模式（3-5 条人话规则）→ 跨 A股/港股/美股/crypto 多市场回测 → 差值归因 → 8-section PDF 报告。叙事：你的影子，没有情绪噪音。 | 1 |  |
| `valuation-model` | Valuation methodology — absolute valuation with DCF / DDM / SOTP, relative valuation with PE-Band / PB-ROE / EV-EBITDA, sensitivity analysis, and valuation-trap detection. | 1 |  |

### asset-class (9)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `asset-allocation` | Asset allocation theory and optimizer usage — MPT / Black-Litterman / risk budgeting / all-weather strategy, including guides for 5 optimizers and rebalancing rules. | 1 |  |
| `convertible-bond` | A股可转债分析——转股/纯债/期权三维估值、下修/强赎/回售博弈、双低策略与转债轮动选债框架 | 1 |  |
| `etf-analysis` | ETF分析：产品筛选、费率对比、跟踪误差、流动性评估、策略应用与中国市场ETF量化配置框架。 | 1 |  |
| `fund-analysis` | 基金分析与筛选：晨星评级/夏普比率/信息比率、Sharpe风格箱分析、风格漂移检测、基金经理评价、FOF组合构建、ETF选择 | 1 |  |
| `hedging-strategy` | Hedging strategy design (beta hedge / option protection / tail risk / cross-asset hedging), including hedge-ratio calculation and cost evaluation. | 1 |  |
| `options-advanced` | Advanced options strategies: volatility-surface modeling (SABR / Local Vol), dynamic Greeks rebalancing, calendar spreads, volatility arbitrage and skew trading, and option market-making basics. | 1 |  |
| `options-payoff` | Option P&L analysis methodology: payoff diagrams, breakeven calculation, multi-leg strategy visualization, and Greeks-based scenario analysis. | 1 |  |
| `options-strategy` | Options strategy framework supporting Black-Scholes pricing, Greeks analysis, and multi-leg backtesting. Suitable for cryptocurrency and equity options. | 1 |  |
| `sector-rotation` | 行业轮动分析——申万行业景气度评分、行业动量排名、产业链传导、估值/盈利/资金流多维比较框架 | 1 |  |

### crypto (7)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `crypto-derivatives` | Crypto-derivatives strategies — perpetual funding-rate arbitrage, futures term-structure contango/backwardation trading, and option volatility-smile / Greeks analysis. | 1 |  |
| `defi-yield` | DeFi yield analysis and optimization — lending rates, LP yields, staking returns, yield farming strategies, risk-adjusted yield comparison, and protocol-level sustainability assessment. | 1 |  |
| `liquidation-heatmap` | Liquidation level analysis and heatmap interpretation — identify leveraged position concentration, liquidation cascades, stop-hunt zones, and use liquidation data as support/resistance signals. | 1 |  |
| `onchain-analysis` | On-chain data analysis — active addresses / whale tracking / TVL / DEX liquidity, interpretation and signal generation using on-chain valuation metrics such as MVRV / NVT / SOPR. | 1 |  |
| `perp-funding-basis` | Perpetual futures funding rate analysis and cash-carry basis trading — funding rate regimes, annualized basis signals, carry trade construction, and funding rate arbitrage between exchanges. | 1 |  |
| `stablecoin-flow` | Stablecoin supply and flow analysis — USDT/USDC mint-burn signals, exchange stablecoin reserves, on-chain stablecoin velocity, and capital rotation indicators for crypto market timing. | 1 |  |
| `token-unlock-treasury` | Token unlock schedule analysis and project treasury tracking — vesting cliffs, linear unlocks, team/investor/ecosystem token releases, treasury diversification, and sell pressure forecasting. | 1 |  |

### data-source (10)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `akshare` | AKShare financial data aggregator (18k+ stars). Free, no API key. Covers A-shares, US, HK, futures, macro, forex. Primary fallback for tushare and yfinance. | 1 |  |
| `ccxt` | CCXT unified crypto exchange library (100+ exchanges). Free public market data. Fallback when OKX is unavailable. | 1 |  |
| `data-routing` | The single ROUTER for every data need. Load this skill BEFORE any backtest, data-fetch, or research task to pick the best available source/tool, honour auth (env) requirements, and avoid ban-risk providers. | 1 |  |
| `eastmoney` | 东方财富（Eastmoney）免费免鉴权数据接口，覆盖资金流向、龙虎榜、融资融券、大宗交易、股东户数、限售解禁、行业概念板块、券商研报、财经新闻、A股/港股三大报表+主要指标、全市场选股与代码搜索；美股财报由 get_financial_statements 转 SEC EDGAR。东财请求经共享 IP 限速层节流（东财按源 IP 限流并临时封禁突发请求），通过 Vibe-Trading 工具直接调用，无需 token。 | 17 |  |
| `mootdx` | Mootdx A-share market data via TCP-direct 通达信 servers. Free, no API key, no IP rate limits. Use as the stable A-share OHLCV fallback when akshare's East Money scrape is throttled. | 1 |  |
| `okx-market` | OKX cryptocurrency market data interface. Uses the OKX V5 REST API to retrieve spot, derivatives, index, and other crypto market data, including real-time prices, candlesticks, funding rates, open interest, and more. No authentication required, free to use. | 16 |  |
| `qveris` | Paid capability marketplace for global multi-asset data; use it when free Vibe-Trading sources lack coverage, depth, or provider quality, and keep free sources as the default for routine OHLCV. | 3 |  |
| `sec-edgar` | U.S. SEC EDGAR fetch interface — resolve a ticker to its CIK, list recent filings (10-K / 10-Q / 8-K and friends) with primary-document URLs, and pull XBRL companyfacts financial series. Free, no API key; rate-limited by IP so every request is throttled and carries a contact User-Agent. United States only. | 6 |  |
| `tushare` | tushare是一个财经数据接口包，拥有丰富的数据内容，如股票、基金、期货、数字货币等行情数据，公司财务、基金经理等基本面数据。该模块通过标准化API方式统一了数据资产的对外服务方式，以帮助有需要的技术用户更实时、简洁、轻量的使用相关数据。 | 232 |  |
| `yfinance` | yfinance global market data interface — retrieve OHLCV, financials, insider transactions, and institutional holdings for US stocks, HK stocks, ETFs, and indices via Yahoo Finance. Free, no API key required. | 7 |  |

### flow (8)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `adr-hshare` | ADR/H-share/A-share cross-listing premium analysis — track pricing gaps between US-listed ADRs, HK-listed H-shares, and A-shares for arbitrage signals, dual-listing valuation, and delisting risk assessment. | 1 |  |
| `corporate-events` | 公司事件驱动分析：并购套利价差计算、大股东增减持信号、股权激励解读、定增配股影响评估、A股ST/退市预警 | 1 |  |
| `edgar-sec-filings` | SEC EDGAR filing analysis — 10-K, 10-Q, 8-K, proxy statements, insider Form 4. Extract key financials, risk factors, management discussion, and generate investment signals from US public company filings. | 1 |  |
| `financial-statement` | 财报三表深度解读——三表勾稽关系、盈利质量(应计vs现金流)分析、杜邦分解、10+财务造假红旗指标 | 1 |  |
| `fundamental-filter` | Fundamental factor screening — filter stocks by PE/PB/ROE, financial statement fields, and other metrics for value or growth selection. Supports A-shares (via tushare extra_fields or fundamental_fields) and HK/US stocks (via yfinance Ticker info). | 2 | Y |
| `hk-connect-flow` | Stock Connect (Shanghai/Shenzhen-Hong Kong) fund flow analysis — Northbound (foreign into A-shares), Southbound (mainland into HK), sector allocation tracking, and cross-border arbitrage signals. | 1 |  |
| `research-goal` | Goal-driven finance research workflow: attach a research-only objective, track criteria, and add evidence while avoiding live trading execution. | 1 |  |
| `us-etf-flow` | US ETF fund flow analysis, sector rotation breadth, and style factor flows — track institutional capital movement via ETF creation/redemption, sector breadth signals, and thematic momentum. | 1 |  |

### research (2)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `alpha-zoo` | Browse and bench the bundled alpha zoos — prebuilt cross-sectional factor libraries (Kakushadze 101, GTJA 191, Qlib 158, Fama-French / Carhart). Use when the user asks "which alphas exist", wants metadata on a named alpha, or wants to run IC/IR on a whole zoo over a universe. | 1 |  |
| `strategy-dev-manager` | Strategy Development Manager: convert academic papers and research reports into validated factors and strategies with automated backtesting, persistent storage, and decay monitoring. | 9 |  |

### risk-analysis (1)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `ashare-pre-st-filter` | A 股 ST/*ST 风险预测框架 — 基于最新中报/三季报或业绩预告/快报，预测下一财年是否会因营收、利润、净资产、分红不达标而被风险警示，并将新浪监管处罚记录作为独立证据面纳入风险等级。仅适用于 A 股，不预测财务造假。 | 2 |  |

### strategy (19)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `bottleneck-hunter` | Supply-chain bottleneck arbitrage. Given a super-trend (AI infra, energy transition, defense, semiconductor reshoring, space economy), decompose its physical supply chain down to Layer 2/3 choke points (optics, lasers, InP/SOI substrates, IC substrates, probe cards, specialty fiberglass...) and surface under-the-radar listed companies sitting on each bottleneck. Scores each link on 6 scarcity crit | 1 |  |
| `candlestick` | Candlestick pattern recognition engine, pure pandas vectorized implementation of 15 classic candlestick patterns (5 single-candle + 5 double-candle + 4 triple-candle + 1 trend confirmation), generating a composite signal from bullish/bearish pattern scores. | 2 | Y |
| `chanlun` | 基于缠论（缠中说禅）的形态识别引擎，使用czsc库自动检测K线分型、笔、中枢，并生成一买/一卖/二买/二卖/三买/三卖等买卖点信号。支持多周期分析和形态分类（3/5/7/9/11笔形态）。 | 8 | Y |
| `cross-market-strategy` | Write signal_engine.py for portfolios spanning multiple markets (A-shares + crypto, equity + forex, etc.) | 2 | Y |
| `elliott-wave` | Elliott Wave Theory signal engine. Detects swing points through Zigzag, matches 5-wave impulse and 3-wave corrective structures, validates them with Fibonacci wave relationships, and generates trend-top / correction-complete signals. Pure in-house pandas implementation. | 4 | Y |
| `event-driven` | Event-driven strategy based on sentiment-scored signals from news, announcements, and macro events. The LLM acts as the NLP engine, and event data follows a CSV schema. | 2 | Y |
| `execution-model` | Trade execution modeling (backtest only) — slippage formulas (linear / square-root impact), VWAP/TWAP execution logic, market-impact cost estimation, and execution-assumption configuration. | 1 |  |
| `harmonic` | Harmonic Patterns signal engine. Identifies XABCD five-point structures such as Gartley/Bat/Butterfly/Crab based on Fibonacci geometry, and generates trading signals in the PRZ (Potential Reversal Zone). | 4 | Y |
| `ichimoku` | Ichimoku Kinko Hyo five-line system signal engine. A standalone Japanese technical-analysis school that generates trading signals from Tenkan/Kijun crossovers, cloud position, and Chikou confirmation. Pure pandas implementation. | 4 | Y |
| `minute-analysis` | Minute-level data analysis and backtesting. Retrieves minute candlesticks through OKX/Tushare/yfinance and can be used both for analysis and as input to the backtest engine. | 2 | Y |
| `ml-strategy` | Machine-learning predictive strategy based on sklearn walk-forward training, feature engineering, and signal generation. Suitable for any OHLCV data. | 1 |  |
| `multi-factor` | Multi-factor cross-sectional stock ranking. Combines factor standardization, equal-weight or IC-weighted scoring, and TopN portfolio construction. Suitable for multi-instrument portfolio strategies. | 3 | Y |
| `pair-trading` | Pair trading strategy. Trades mean reversion using the spread/ratio Z-score of two correlated instruments. Requires at least two instruments. | 2 | Y |
| `seasonal` | Seasonal/calendar-effect strategy. Generates trading signals from time-based patterns such as month-of-year effects and day-of-week effects. Suitable for any OHLCV data. | 2 | Y |
| `smc` | Smart Money Concepts (ICT) signal engine. Uses the smartmoneyconcepts library to implement institutional-trading-school analysis of BOS, ChoCH, FVG, and order blocks (OB). | 4 | Y |
| `strategy-generate` | Create, modify, and optimize quantitative trading strategies, then backtest and evaluate them. | 2 |  |
| `technical-basic` | Core technical indicator collection (trend EMA/ADX + mean-reversion BB/RSI + volume-price OBV/volume ratio), generates a composite signal via three-dimensional voting. Pure pandas implementation for any OHLCV data. | 2 | Y |
| `thesis-tracker` | Buy-side discipline system. For each holding, maintain a written investment thesis — core thesis in 5 sentences, falsifiable assumptions, red lines, valuation anchors — and re-check it each quarter against new earnings/events. Scores thesis health 1-10 from assumption breakage and red-line triggers, and recommends hold / add / trim / exit. Use it right after buying a stock (to write the thesis) an | 1 |  |
| `volatility` | Volatility strategy. Trades mean reversion based on percentile ranking of historical volatility (HV). Suitable for any OHLCV data. | 2 | Y |

### tool (10)

| id | description | files | example_engine |
|----|-------------|------:|:--------------:|
| `backtest-diagnose` | Diagnose failed or underperforming backtests, locate the root cause, and fix the issue | 1 |  |
| `doc-reader` | Read any common document/data file — PDF, Word (.docx), Excel (.xlsx/.xls), PowerPoint (.pptx), images (OCR), CSV/TSV, plain text, JSON/YAML/TOML, HTML/XML, and most source-code files. Use the `read_document` tool. | 1 |  |
| `geopolitical-risk` | Geopolitical risk analysis: quantify crisis signals, identify precursors, and build event-driven strategies for war, sanctions, and supply disruption scenarios. | 1 |  |
| `pine-script` | Export backtest strategies to indicator/strategy code for major trading platforms — TradingView, 通达信, 同花顺, 东方财富, MT5. | 1 |  |
| `regulatory-knowledge` | 金融监管知识库：A股涨跌停/ST退市新规/融券、港股T+0/做空机制、美股PDT/熔断、加密监管政策、跨境税务基础 | 1 |  |
| `report-generate` | Professional financial research report generation — standard structure (summary / views / main body / risks / recommendation), Markdown formatting standards, rating system, and terminology guide. | 1 |  |
| `social-media-intelligence` | Social media intelligence: financial signal extraction from Twitter/X, Telegram, Discord, and Reddit for sentiment-driven trading strategies. | 1 |  |
| `trade-journal` | Analyze a user's trade journal (CSV/Excel broker export). Parses 同花顺/东方财富/富途/generic formats, produces a trading profile and 4 behavior diagnostics (disposition effect, overtrading, chasing, anchoring). Use the `analyze_trade_journal` tool. | 1 |  |
| `vnpy-export` | Export a Vibe-Trading backtest strategy to a runnable vnpy CtaTemplate Python class — supports A-share equities, futures, and crypto via BarGenerator + ArrayManager. | 2 |  |
| `web-reader` | Read web pages, articles, and document links by converting URLs into Markdown text. Use the `read_url` tool directly, without bash. Sends the full URL to the third-party Jina Reader (r.jina.ai). | 1 |  |
