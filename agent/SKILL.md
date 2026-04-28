---
name: vibe-trading
version: 0.1.6
description: Professional finance research toolkit — backtesting (7 engines + benchmark comparison panel), factor analysis, options pricing, 72 finance skills, 29 multi-agent swarm teams, Trade Journal analyzer, and Shadow Account (extract → backtest → render) across 6 data sources (tushare, yfinance, okx, akshare, ccxt, futu).
dependencies:
  python: ">=3.11"
  pip:
    - vibe-trading-ai
env:
  - name: TUSHARE_TOKEN
    description: "Tushare API token for China A-share data (optional — HK/US/crypto work without any key)"
    required: false
  - name: OPENAI_API_KEY
    description: "OpenAI-compatible API key — only needed for run_swarm (multi-agent teams). All other tools work without it."
    required: false
  - name: LANGCHAIN_MODEL_NAME
    description: "LLM model name for run_swarm (e.g. deepseek/deepseek-v3.2). Only needed if using run_swarm."
    required: false
mcp:
  command: vibe-trading-mcp
  args: []
---

# Vibe-Trading

Professional finance research toolkit with AI-powered backtesting (7 engines), multi-agent teams, 72 specialized skills, and the Shadow Account loop — extract your implicit trading rules from a journal, backtest them across A股/港股/美股/crypto, then see where they would have served you better.

## Setup

```bash
pip install vibe-trading-ai
```

> **Package name vs commands:** The PyPI package is `vibe-trading-ai`. Once installed, you get:
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | Interactive CLI / TUI |
> | `vibe-trading serve` | Launch FastAPI web server |
> | `vibe-trading-mcp` | Start MCP server (for Claude Desktop, OpenClaw, Cursor, etc.) |

Add to your agent's MCP config:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

### API Key Requirements

**21 of 22 MCP tools work with zero API keys.** After `pip install`, backtesting, market data, factor analysis, options pricing, chart patterns, web search, document reading, trade journal analysis, shadow-account extraction/backtest/report, and all 72 skills are ready to use for HK/US equities and crypto.

| Feature | Key needed | When |
|---------|-----------|------|
| HK/US equities & crypto | None | Always free (yfinance + OKX) |
| China A-share data | `TUSHARE_TOKEN` | Only if you query A-share symbols |
| Multi-agent swarm (`run_swarm`) | `OPENAI_API_KEY` + `LANGCHAIN_MODEL_NAME` | Swarm spawns internal LLM workers |

## What You Can Do

### Shadow Account — flagship loop

Feed a CSV broker export (同花顺 / 东财 / 富途 / generic), and the agent will:
1. `analyze_trade_journal` — profile your behavior (holding period, win rate, disposition effect, chasing, overtrading, anchoring).
2. `extract_shadow_strategy` — distill 3-5 if-then rules that describe your profitable roundtrips.
3. `run_shadow_backtest` — backtest those rules across A/HK/US/crypto and compute delta-PnL vs your realized trades.
4. `render_shadow_report` — produce an HTML/PDF report (8 sections + charts) with today's matching signals.
5. `scan_shadow_signals` — list today's symbols that match your shadow's entry cadence (research only).

### Backtesting
Create and run quantitative strategies across 7 engines (ChinaA, GlobalEquity, Crypto, ChinaFutures, GlobalFutures, Forex + options) with 6 data sources:
- **HK/US equities** via yfinance (free, no API key)
- **Cryptocurrency** via OKX or CCXT/100+ exchanges (free, no API key)
- **China A-shares** via Tushare (token) or AKShare (free fallback)
- **Futures, forex, macro** via AKShare (free, no API key)
- **HK & A-share equities** via Futu (broker login required, optional)

Example workflow:
1. Use `list_skills()` to discover strategy patterns
2. Use `load_skill("strategy-generate")` for the strategy creation guide
3. Use `write_file()` to create `config.json` and `code/signal_engine.py`
4. Use `backtest()` to run and get metrics (Sharpe, return, drawdown, etc.)

### Multi-Agent Swarm Teams
29 pre-built agent teams for complex research:
- **Investment Committee**: bull/bear debate → risk review → PM decision
- **Global Equities Desk**: A-share + HK/US + crypto → global strategist
- **Crypto Trading Desk**: funding/basis + liquidation + flow → risk manager
- **Earnings Research Desk**: fundamentals + revisions + options → earnings strategist
- **Macro/Rates/FX Desk**: rates + FX + commodities → macro PM
- **Quant Strategy Desk**: screening → factor research → backtest → risk audit
- **Risk Committee**: drawdown, tail risk, regime analysis
- And 22 more specialized teams

Use `list_swarm_presets()` to see all teams, then `run_swarm()` to execute.

### Finance Skills (72)
Comprehensive knowledge base covering:
- Technical analysis (candlestick, Elliott wave, Ichimoku, SMC, harmonic, chanlun)
- Quantitative methods (factor research, ML strategy, pair trading, multi-factor)
- Risk management (VaR/CVaR, stress testing, hedging)
- Options (Black-Scholes, Greeks, multi-leg strategies, payoff diagrams)
- HK/US equities (SEC filings, earnings revisions, ETF flows, ADR/H-share arbitrage)
- Crypto trading desk (funding rates, liquidation heatmaps, stablecoin flows, token unlocks, DeFi yields)
- Behavioral finance, trade journal diagnostics, shadow account
- Macro analysis, credit research, sector rotation, and more

Use `load_skill(name)` to access full methodology docs with code templates.

## Available MCP Tools (22)

| Tool | Description | API Key |
|------|-------------|---------|
| `list_skills` | List all 72 finance skills | None |
| `load_skill` | Load full skill documentation | None |
| `backtest` | Run vectorized backtest engine | None* |
| `factor_analysis` | IC/IR analysis + layered backtest | None* |
| `analyze_options` | Black-Scholes price + Greeks | None |
| `pattern_recognition` | Detect chart patterns (H&S, double top, etc.) | None |
| `get_market_data` | Fetch OHLCV data across 6 sources (auto-detect + fallback) | None* |
| `web_search` | Search the web via DuckDuckGo | None |
| `read_url` | Fetch web page as Markdown | None |
| `read_document` | Extract text from PDF/DOCX/XLSX/PPTX/images | None |
| `write_file` | Write files (config, strategy code) | None |
| `read_file` | Read file contents | None |
| `analyze_trade_journal` | Parse broker CSV → profile + behavior diagnostics | None |
| `extract_shadow_strategy` | Distill 3-5 if-then rules from profitable roundtrips | None |
| `run_shadow_backtest` | Multi-market backtest + delta-PnL attribution | None* |
| `render_shadow_report` | HTML/PDF shadow report (8 sections + charts) | None |
| `scan_shadow_signals` | Today's symbols matching the shadow's cadence | None |
| `list_swarm_presets` | List multi-agent team presets | None |
| `run_swarm` | Execute a multi-agent research team | LLM key |
| `get_swarm_status` | Poll swarm run status without blocking | None |
| `get_run_result` | Get final report and task summaries | None |
| `list_runs` | List recent swarm runs with metadata | None |

<sub>*A-share symbols require `TUSHARE_TOKEN`. HK/US/crypto are free.</sub>

## Quick Start

```bash
pip install vibe-trading-ai
```

That's it — no API keys needed for HK/US/crypto markets. Start using `backtest`, `get_market_data`, `analyze_options`, `analyze_trade_journal`, `extract_shadow_strategy`, `web_search`, and all 72 skills immediately.

## Examples

**Backtest a MACD strategy on Apple:**
> Backtest AAPL with MACD crossover strategy (fast=12, slow=26, signal=9) for 2024

**Analyze my trade journal and build a Shadow Account:**
> Call analyze_trade_journal on ~/Downloads/tonghuashun.csv, then extract_shadow_strategy with min_support=3, then run_shadow_backtest for the last year, then render_shadow_report.

**Run an investment committee review:**
> Use run_swarm with investment_committee preset to evaluate NVDA. Variables: target=NVDA.US, market=US

**Factor analysis on CSI 300:**
> Run factor_analysis on CSI 300 stocks using pe_ttm factor from 2023 to 2024

**Options analysis:**
> Use analyze_options: spot=100, strike=105, 90 days, vol=25%, rate=3%
