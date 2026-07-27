# Swarm Presets Catalog (30)

Total: **30**.

## `commodity_research_team` — Commodity Research Team

Parallel deep-dive on supply and demand, synthesized by a cycle strategist into an investment thesis — DAG workflow

- agents (3): `supply_analyst`, `demand_analyst`, `cycle_strategist`
- tasks (3): `task-supply-research`, `task-demand-research`, `task-cycle-strategy`
- depends_on:
  - `task-cycle-strategy` ← ['task-supply-research', 'task-demand-research']
- variables: [{'name': 'commodity', 'description': 'Commodity type, e.g.: crude oil / gold / copper / iron ore / natural gas / soybeans / aluminum / rebar', 'required': True}, {'name': 'horizon', 'description': 'Investment horizon, e.g.: 1 month / 3 months / 6 months / 1 year', 'required': True}]

## `convertible_bond_team` — Convertible Bond Research Team

Parallel three-dimensional analysis — bond floor, equity optionality, and embedded option value — synthesized into a convertible bond investment strategy

- agents (4): `bond_analyst`, `equity_analyst`, `option_analyst`, `cb_strategist`
- tasks (4): `task-bond`, `task-equity`, `task-option`, `task-strategy`
- depends_on:
  - `task-strategy` ← ['task-bond', 'task-equity', 'task-option']
- variables: [{'name': 'market', 'description': 'Target market (default: A-share convertible bonds)', 'required': True}, {'name': 'goal', 'description': 'Research focus (e.g.: uncover undervalued convertibles, position for conversion price reset candidates)', 'required': True}, {'name': 'strategy_type', 'description': "Strategy type (low-price / dual-low / high-convexity / rotation; leave blank for strategist's discretion)", 'required': False}]

## `credit_research_team` — Fixed Income Credit Research Team

Credit quality + interest rate environment + sector credit three-dimensional parallel analysis → fixed income strategist synthesizes a complete bond investment strategy

- agents (4): `credit_analyst`, `rate_analyst`, `sector_credit_analyst`, `fixed_income_strategist`
- tasks (4): `task-credit`, `task-rate`, `task-sector-credit`, `task-strategy`
- depends_on:
  - `task-strategy` ← ['task-credit', 'task-rate', 'task-sector-credit']
- variables: [{'name': 'target', 'description': 'Research subject or sector (e.g.: a specific LGFV platform, the property sector, steel bonds, AA-rated credit bond portfolio)', 'required': True}, {'name': 'market', 'description': 'Bond market (default: China bond market; options: credit bonds / LGFV bonds / rate bonds / convertible bonds)', 'required': False}]

## `crypto_research_lab` — Crypto Asset Research Lab

On-chain data + DeFi protocol + market sentiment three-dimensional parallel analysis → Alpha synthesizer converges investment recommendations

- agents (4): `onchain_analyst`, `defi_analyst`, `crypto_sentiment_analyst`, `alpha_synthesizer`
- tasks (4): `task-onchain`, `task-defi`, `task-sentiment`, `task-alpha`
- depends_on:
  - `task-alpha` ← ['task-onchain', 'task-defi', 'task-sentiment']
- variables: [{'name': 'target', 'description': 'Target asset (e.g.: BTC / ETH / SOL; default BTC/ETH/SOL)', 'required': True}, {'name': 'timeframe', 'description': 'Analysis time horizon (short-term 1–4 weeks / medium-term 1–3 months / long-term 3–12 months)', 'required': True}]

## `crypto_trading_desk` — Crypto Trading & Risk Desk

Execution-oriented crypto desk: funding/basis analyst + liquidation/microstructure analyst + on-chain/flow analyst + risk manager. Goes beyond research into position sizing, execution timing, and risk gating.

- agents (4): `funding_basis_analyst`, `liquidation_analyst`, `flow_analyst`, `desk_risk_manager`
- tasks (4): `task-funding`, `task-liquidation`, `task-flow`, `task-risk-decision`
- depends_on:
  - `task-risk-decision` ← ['task-funding', 'task-liquidation', 'task-flow']
- variables: [{'name': 'target', 'description': 'Target asset (e.g., BTC-USDT, ETH-USDT, SOL-USDT)', 'required': True}, {'name': 'timeframe', 'description': 'Trading horizon (intraday / swing 1-2 weeks / position 1-3 months)', 'required': True}]

## `derivatives_strategy_desk` — Derivatives Strategy Desk

Volatility analysis → strategy design → Greeks risk management: sequential options trading desk workflow

- agents (3): `vol_analyst`, `strategy_designer`, `greeks_manager`
- tasks (3): `task-vol`, `task-strategy`, `task-greeks`
- depends_on:
  - `task-strategy` ← ['task-vol']
  - `task-greeks` ← ['task-strategy']
- variables: [{'name': 'target', 'description': 'Underlying (e.g.: BTC, CSI 300 ETF, AAPL)', 'required': True}, {'name': 'view', 'description': 'Market view (bullish / bearish / neutral / long volatility / short volatility)', 'required': True}]

## `earnings_research_desk` — Earnings Research Desk

Earnings-focused research team: fundamental analyst + earnings revision tracker + options/event analyst + earnings strategist. Deep-dives into company financials, consensus revisions, earnings event trades, and post-earnings drift.

- agents (4): `fundamental_analyst`, `revision_tracker`, `event_options_analyst`, `earnings_strategist`
- tasks (4): `task-fundamental`, `task-revision`, `task-options-event`, `task-earnings-strategy`
- depends_on:
  - `task-earnings-strategy` ← ['task-fundamental', 'task-revision', 'task-options-event']
- variables: [{'name': 'target', 'description': 'Target stock (e.g., AAPL.US, NVDA.US, 700.HK, 600519.SH)', 'required': True}]

## `equity_research_team` — Equity Research Team

Macro → sector → stock three-tier deep research → research editor consolidates into a complete report

- agents (4): `macro_analyst`, `sector_analyst`, `stock_picker`, `aggregator`
- tasks (4): `task-macro`, `task-sector`, `task-stock`, `task-aggregate`
- depends_on:
  - `task-sector` ← ['task-macro']
  - `task-stock` ← ['task-sector']
  - `task-aggregate` ← ['task-stock']
- variables: [{'name': 'market', 'description': 'Target market (e.g.: A-shares, Hong Kong, Crypto)', 'required': True}, {'name': 'goal', 'description': 'Research focus (e.g.: Q2 2026 outlook, opportunities in the new energy sector)', 'required': True}]

## `etf_allocation_desk` — ETF Allocation Desk

ETF screening + macro allocation + risk budgeting three-dimensional parallel analysis → portfolio optimizer constructs the final ETF portfolio and backtests

- agents (4): `etf_screener`, `macro_allocator`, `risk_budgeter`, `portfolio_optimizer`
- tasks (4): `task-etf-screen`, `task-macro-alloc`, `task-risk-budget`, `task-optimize`
- depends_on:
  - `task-optimize` ← ['task-etf-screen', 'task-macro-alloc', 'task-risk-budget']
- variables: [{'name': 'risk_profile', 'description': 'Risk profile (conservative / balanced / aggressive)', 'required': True}, {'name': 'market', 'description': 'Target market (default: A-shares; options: global multi-asset, HK/US equities, A-shares + HK)', 'required': False}]

## `event_driven_task_force` — Event-Driven Task Force

Event scanning → deep impact analysis → strategy construction: sequential deep-dive chain replicating an event-driven hedge fund special investigation unit workflow

- agents (3): `event_scanner`, `impact_analyst`, `strategy_builder`
- tasks (3): `task-event-scan`, `task-impact-analysis`, `task-strategy-build`
- depends_on:
  - `task-impact-analysis` ← ['task-event-scan']
  - `task-strategy-build` ← ['task-impact-analysis']
- variables: [{'name': 'market', 'description': 'Target market, e.g.: A-shares / Hong Kong / US equities / Chinese ADRs', 'required': True}, {'name': 'event_type', 'description': "Event type filter, e.g.: M&A / insider trading / earnings / policy / litigation / management change; enter 'all types' for no filter", 'required': False}]

## `factor_research_committee` — Factor Research Committee

Factor mining + factor validation running in parallel → factor combination construction → backtest review: quant fund internal research review workflow

- agents (4): `factor_miner`, `factor_validator`, `factor_combiner`, `backtest_reviewer`
- tasks (4): `task-mine`, `task-validate`, `task-combine`, `task-review`
- depends_on:
  - `task-combine` ← ['task-mine', 'task-validate']
  - `task-review` ← ['task-combine']
- variables: [{'name': 'market', 'description': 'Target market (e.g.: A-shares, Hong Kong, US equities)', 'required': True}, {'name': 'factor_type', 'description': 'Factor type (value / momentum / quality / growth / alternative)', 'required': True}]

## `fund_selection_panel` — Fund Selection Panel

Multi-dimensional quantitative screening → Brinson performance attribution and style analysis → FOF portfolio weight optimization, sequential professional review chain

- agents (3): `fund_screener`, `attribution_analyst`, `fof_optimizer`
- tasks (3): `task-fund-screen`, `task-performance-attribution`, `task-fof-optimize`
- depends_on:
  - `task-performance-attribution` ← ['task-fund-screen']
  - `task-fof-optimize` ← ['task-performance-attribution']
- variables: [{'name': 'fund_type', 'description': 'Fund type, e.g.: equity / bond / balanced / index-enhanced / quant hedge / QDII', 'required': True}, {'name': 'goal', 'description': 'Investment objective, e.g.: build a steady FOF portfolio with annualized return >10% and max drawdown <15%', 'required': True}]

## `fundamental_research_team` — Fundamental Deep Research Team

Financial / valuation / quality three-dimensional parallel analysis → research editor consolidates into a buy-side deep research report

- agents (4): `financial_analyst`, `valuation_analyst`, `quality_analyst`, `report_editor`
- tasks (4): `task-financial`, `task-valuation`, `task-quality`, `task-report`
- depends_on:
  - `task-report` ← ['task-financial', 'task-valuation', 'task-quality']
- variables: [{'name': 'target', 'description': 'Research subject (stock code or name, e.g.: 600519 Kweichow Moutai)', 'required': True}, {'name': 'market', 'description': 'Market (e.g.: A-shares, Hong Kong, US equities)', 'required': True}]

## `geopolitical_war_room` — Geopolitical Risk War Room

Geopolitical analysis, energy shock, and supply-chain impact run in parallel, then feed into the Chief Strategist for synthesis, producing emergency asset-allocation playbooks for geopolitical crises.

- agents (4): `geopolitical_analyst`, `energy_analyst`, `supply_chain_analyst`, `chief_strategist`
- tasks (4): `task-geopolitical`, `task-energy`, `task-supply-chain`, `task-strategy`
- depends_on:
  - `task-strategy` ← ['task-geopolitical', 'task-energy', 'task-supply-chain']
- variables: [{'name': 'crisis', 'description': 'Crisis narrative (e.g., Taiwan Strait escalation, Hormuz blockade, full Red Sea Houthi disruption)', 'required': True}, {'name': 'market', 'description': 'Focus market (e.g., A-shares, Hong Kong, global multi-asset)', 'required': True}]

## `global_allocation_committee` — Global Allocation Committee

Parallel A-shares + crypto + HK/US analysts; allocator synthesizes cross-market allocation with data-driven weighting, scenario analysis, and rebalancing rules.

- agents (4): `a_share_analyst`, `crypto_analyst`, `us_hk_analyst`, `allocator`
- tasks (4): `task-ashare`, `task-crypto`, `task-ushk`, `task-allocate`
- depends_on:
  - `task-allocate` ← ['task-ashare', 'task-crypto', 'task-ushk']
- variables: [{'name': 'goal', 'description': 'Investment objective (e.g., Q2 2026 multi-asset allocation)', 'required': True}, {'name': 'risk_tolerance', 'description': 'Risk tolerance (conservative / moderate / aggressive)', 'required': False}]

## `global_equities_desk` — Global Equities Research Desk

Cross-market equity research: A-share analyst + HK/US analyst + crypto analyst + global strategist. Covers fundamental screening, earnings analysis, ETF flows, and cross-listing arbitrage for multi-market stock selection.

- agents (4): `a_share_researcher`, `us_hk_researcher`, `crypto_researcher`, `global_strategist`
- tasks (4): `task-ashare`, `task-ushk`, `task-crypto`, `task-strategy`
- depends_on:
  - `task-strategy` ← ['task-ashare', 'task-ushk', 'task-crypto']
- variables: [{'name': 'goal', 'description': 'Investment objective (e.g., Q2 2026 global equity allocation, tech sector deep-dive)', 'required': True}, {'name': 'risk_tolerance', 'description': 'Risk tolerance level (conservative / moderate / aggressive)', 'required': False}]

## `investment_committee` — Investment Committee

Long–short debate → risk review → PM final call: buy-side fund investment committee workflow.

- agents (4): `bull_advocate`, `bear_advocate`, `risk_officer`, `portfolio_manager`
- tasks (4): `task-bull`, `task-bear`, `task-risk`, `task-decision`
- depends_on:
  - `task-risk` ← ['task-bull', 'task-bear']
  - `task-decision` ← ['task-risk']
- variables: [{'name': 'target', 'description': 'Security (e.g., 600519.SH Kweichow Moutai, BTC-USDT, AAPL)', 'required': True}, {'name': 'market', 'description': 'Market (e.g., A-shares, Hong Kong, US, crypto)', 'required': True}]

## `macro_rates_fx_desk` — Macro / Rates / FX Desk

Cross-asset macro desk: global rates analyst + FX strategist + commodity/inflation analyst + macro portfolio manager. Covers central bank policy, yield curve dynamics, currency positioning, and macro-driven asset allocation.

- agents (4): `rates_analyst`, `fx_strategist`, `commodity_inflation_analyst`, `macro_pm`
- tasks (4): `task-rates`, `task-fx`, `task-commodity-inflation`, `task-macro-allocation`
- depends_on:
  - `task-macro-allocation` ← ['task-rates', 'task-fx', 'task-commodity-inflation']
- variables: [{'name': 'goal', 'description': 'Macro investment objective (e.g., Q2 2026 cross-asset positioning, rate cycle trade)', 'required': True}, {'name': 'timeframe', 'description': 'Investment horizon (tactical 1-3 months / strategic 6-12 months)', 'required': True}]

## `macro_strategy_forum` — Macro Strategy Forum

Global + domestic + policy perspectives run in parallel; chief strategist delivers integrated cross-asset allocation guidance.

- agents (4): `global_economist`, `domestic_economist`, `policy_analyst`, `chief_strategist`
- tasks (4): `task-global`, `task-domestic`, `task-policy`, `task-strategy`
- depends_on:
  - `task-strategy` ← ['task-global', 'task-domestic', 'task-policy']
- variables: [{'name': 'market', 'description': 'Focus market (e.g., A-shares, Hong Kong, global multi-asset, crypto)', 'required': True}, {'name': 'horizon', 'description': 'Horizon (e.g., monthly, quarterly, annual)', 'required': True}]

## `ml_quant_lab` — Machine Learning Quant Lab

Feature engineering and model design in parallel; flows into the backtest engineer for strict out-of-sample validation.

- agents (3): `feature_engineer`, `data_scientist`, `backtest_engineer`
- tasks (3): `task-features`, `task-model`, `task-backtest`
- depends_on:
  - `task-backtest` ← ['task-features', 'task-model']
- variables: [{'name': 'market', 'description': 'Target market (e.g., A-shares, Hong Kong/US equities)', 'required': True}, {'name': 'target_variable', 'description': 'Prediction target (return / direction / volatility)', 'required': True}, {'name': 'goal', 'description': 'Research focus (e.g., build a monthly stock-selection model, forecast daily volatility)', 'required': True}]

## `pairs_research_lab` — Pairs Trading Research Lab

Correlation scan and cointegration testing in parallel → converge into the pair strategist for strategy design → final microstructure review for execution feasibility.

- agents (4): `correlation_scanner`, `cointegration_tester`, `pair_strategist`, `microstructure_reviewer`
- tasks (4): `task-correlation-scan`, `task-cointegration-test`, `task-pair-strategy`, `task-microstructure-review`
- depends_on:
  - `task-pair-strategy` ← ['task-correlation-scan', 'task-cointegration-test']
  - `task-microstructure-review` ← ['task-pair-strategy']
- variables: [{'name': 'market', 'description': 'Target market (e.g. A-shares, Hong Kong, US, crypto)', 'required': True}, {'name': 'sector', 'description': 'Sector filter (e.g. banks, consumer, semis); empty = full market', 'required': False}]

## `portfolio_review_board` — Portfolio Review Board

Performance attribution, risk review, and execution quality in parallel; CIO synthesizes into rebalance decisions.

- agents (4): `attribution_analyst`, `risk_inspector`, `execution_analyst`, `chief_investment_officer`
- tasks (4): `task-attribution`, `task-risk`, `task-execution`, `task-cio-decision`
- depends_on:
  - `task-cio-decision` ← ['task-attribution', 'task-risk', 'task-execution']
- variables: [{'name': 'portfolio', 'description': 'Portfolio name or description (e.g., value-growth blend, CSI 300 enhanced)', 'required': True}, {'name': 'review_period', 'description': 'Review cadence (monthly / quarterly)', 'required': True}, {'name': 'goal', 'description': 'Focus of this review (e.g., assess Q1 performance, diagnose recent NAV drawdown)', 'required': True}]

## `quant_strategy_desk` — Quant Strategy Desk

Stock screening + factor research in parallel → strategy backtest → risk audit.

- agents (4): `screener`, `factor_miner`, `backtester`, `risk_auditor`
- tasks (4): `task-screen`, `task-factor`, `task-backtest`, `task-risk`
- depends_on:
  - `task-backtest` ← ['task-screen', 'task-factor']
  - `task-risk` ← ['task-backtest']
- variables: [{'name': 'market', 'description': 'Target market', 'required': True}, {'name': 'goal', 'description': 'Strategy objective (e.g., momentum + value dual factor)', 'required': True}]

## `risk_committee` — Risk Committee

Drawdown, tail risk, and market regime reviews run in parallel; head of risk signs off.

- agents (4): `drawdown_analyst`, `tail_risk_analyst`, `regime_detector`, `aggregator`
- tasks (4): `task-drawdown`, `task-tail`, `task-regime`, `task-aggregate`
- depends_on:
  - `task-aggregate` ← ['task-drawdown', 'task-tail', 'task-regime']
- variables: [{'name': 'goal', 'description': 'Audit target (e.g., BTC position risk, CSI 300 strategy risk)', 'required': True}]

## `sector_rotation_team` — Sector Rotation Research Team

Economic cycle + prosperity + capital flows in parallel → rotation strategist builds and backtests a sector rotation strategy.

- agents (4): `cycle_analyst`, `prosperity_analyst`, `flow_analyst`, `rotation_strategist`
- tasks (4): `task-cycle`, `task-prosperity`, `task-flow`, `task-strategy`
- depends_on:
  - `task-strategy` ← ['task-cycle', 'task-prosperity', 'task-flow']
- variables: [{'name': 'market', 'description': 'Target market (default A-shares; can specify HK/US)', 'required': True}, {'name': 'goal', 'description': 'Focus theme (e.g. new energy, tech growth, high dividend, exporters)', 'required': True}]

## `sentiment_intelligence_team` — Market Sentiment Intelligence Unit

News intel / social sentiment / capital flows in parallel → sentiment signal synthesizer outputs composite score and reversal signals.

- agents (4): `news_analyst`, `social_analyst`, `flow_analyst`, `signal_synthesizer`
- tasks (4): `task-news-intel`, `task-social-sentiment`, `task-flow-analysis`, `task-signal-synthesis`
- depends_on:
  - `task-signal-synthesis` ← ['task-news-intel', 'task-social-sentiment', 'task-flow-analysis']
- variables: [{'name': 'market', 'description': 'Target market, e.g. A-shares / HK / US / crypto / CSI 300', 'required': True}, {'name': 'timeframe', 'description': 'Horizon: daily or weekly', 'required': True}]

## `social_alpha_team` — Social-Media Alternative Data Team

Twitter, Telegram, and Reddit analyzed in parallel → Alpha synthesizer extracts tradable social sentiment factors.

- agents (4): `twitter_analyst`, `telegram_analyst`, `reddit_analyst`, `alpha_synthesizer`
- tasks (4): `task-twitter`, `task-telegram`, `task-reddit`, `task-alpha-synthesis`
- depends_on:
  - `task-alpha-synthesis` ← ['task-twitter', 'task-telegram', 'task-reddit']
- variables: [{'name': 'target', 'description': 'Focus name or market (e.g. BTC, Tesla, A-share tech, Nasdaq)', 'required': True}, {'name': 'timeframe', 'description': 'Horizon (real-time / daily / weekly)', 'required': True}]

## `statistical_arbitrage_desk` — Statistical Arbitrage Desk

Pair scanning and microstructure analysis in parallel → converge into the arbitrage strategist to build the strategy → final risk-control review.

- agents (4): `pair_scanner`, `microstructure_analyst`, `arb_strategist`, `risk_monitor`
- tasks (4): `task-pair-scan`, `task-microstructure`, `task-strategy`, `task-risk-review`
- depends_on:
  - `task-strategy` ← ['task-pair-scan', 'task-microstructure']
  - `task-risk-review` ← ['task-strategy']
- variables: [{'name': 'market', 'description': 'Target market (e.g. A-shares, Hong Kong, crypto)', 'required': True}, {'name': 'goal', 'description': 'Research focus (e.g. CSI 300 pair book, crypto arb ideas)', 'required': True}, {'name': 'sector', 'description': 'Sector filter (e.g. banks, consumer); empty = full market', 'required': False}]

## `technical_analysis_panel` — Technical Analysis Panel

Classic TA + Ichimoku + harmonic patterns + Elliott Wave + SMC run in parallel → signal aggregator scores consensus and resonance.

- agents (6): `classic_ta_analyst`, `ichimoku_analyst`, `harmonic_analyst`, `wave_analyst`, `smc_analyst`, `signal_aggregator`
- tasks (6): `task-classic-ta`, `task-ichimoku`, `task-harmonic`, `task-wave`, `task-smc`, `task-aggregate`
- depends_on:
  - `task-aggregate` ← ['task-classic-ta', 'task-ichimoku', 'task-harmonic', 'task-wave', 'task-smc']
- variables: [{'name': 'target', 'description': 'Symbol (e.g. 600519.SH Kweichow Moutai, BTC-USDT, AAPL)', 'required': True}, {'name': 'timeframe', 'description': 'Interval (e.g. daily, weekly, monthly, 4H)', 'required': True}]

## `value_investing_committee` — Value Investing Committee (Buffett / Munger / Duan / Li Lu)

Four adversarial master perspectives — Buffett (moat & price), Munger (inversion & risk), Duan Yongping (good business & trustworthy management), Li Lu (10-year certainty & civilizational trend, incl. demographic/consumption macro) — run in parallel on one company, then a chair synthesizes consensus and contradictions into a verdict. Inspired by the ai-berkshire master-视角 framework. Use for deep v

- agents (5): `buffett`, `munger`, `duan_yongping`, `li_lu`, `chair`
- tasks (5): `task-buffett`, `task-munger`, `task-duan`, `task-li`, `task-chair`
- depends_on:
  - `task-chair` ← ['task-buffett', 'task-munger', 'task-duan', 'task-li']
- variables: [{'name': 'company', 'description': 'Target company name or ticker (e.g.: Tencent, NVDA, Moutai)', 'required': True}, {'name': 'market', 'description': 'Market (e.g.: A-shares, Hong Kong, US)', 'required': True}]
