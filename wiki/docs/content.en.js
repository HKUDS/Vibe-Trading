// English documentation. Every page id and section id here must also exist in
// content.zh.js — wiki/scripts/check_docs_parity.mjs fails CI otherwise.
// Counts are measured from the code at the version in content.js; re-measure
// them before a release instead of editing a number by hand.

export const DOCS_STRUCTURE = [
  {
    id: "getting-started",
    label: "Getting started",
    pages: [
      {
        id: "getting-started/vibe-trading-overview",
        title: "Vibe-Trading overview",
        description: "What Vibe-Trading is, what it can do, and the boundary it keeps.",
        lead: "Vibe-Trading is an open-source finance research agent. You ask in plain language; it fetches market data, runs backtests and analysis tools, and answers with figures it can trace back to that data.",
        sections: [
          {
            id: "what-it-is",
            title: "What it is",
            body: `
              <p>Vibe-Trading connects an agent loop to finance tools: market-data loaders, strategy generation, backtest engines, document readers, trade-journal analysis, persistent memory and multi-agent research teams.</p>
              <p>You can reach the same agent from four places:</p>
              <ul>
                <li><strong>Terminal</strong> — <code>vibe-trading</code> opens an interactive session; <code>vibe-trading run -p "…"</code> runs one prompt.</li>
                <li><strong>Web UI</strong> — chat, run history, portfolio, Alpha Zoo, scheduled research and settings in the browser.</li>
                <li><strong>MCP server</strong> — <code>vibe-trading-mcp</code> gives Claude Desktop, Cursor, OpenClaw and other MCP clients the same tools.</li>
                <li><strong>IM channels</strong> — Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeCom, email and more run the same session runtime.</li>
              </ul>
            `
          },
          {
            id: "capabilities",
            title: "What is in 0.1.16",
            body: `
              <ul>
                <li><strong>28 market-data sources</strong> behind one call, with a fallback chain per market. Most markets need no API key.</li>
                <li><strong>11 backtest engines</strong>: China A-shares, global equities, India, Korea, Vietnam, crypto, China futures, global futures, forex, a composite engine for cross-market portfolios, and an options portfolio engine.</li>
                <li><strong>90 finance skills</strong> in 9 categories, and <strong>30 swarm presets</strong> for committee-style research.</li>
                <li><strong>Alpha Zoo</strong>: 462 alphas you can benchmark on your own universe with one command.</li>
                <li><strong>74 MCP tools</strong> for other agents.</li>
                <li><strong>18 broker connectors</strong>, read-only by default, plus a read-only multi-broker portfolio page.</li>
                <li><strong>Checked numbers</strong>: figures in an answer are checked against the tool data of the session before you see them.</li>
                <li>A web UI in nine languages.</li>
              </ul>
            `
          },
          {
            id: "where-to-start",
            title: "Where to start",
            body: `
              <ol>
                <li><a data-doc-link="getting-started/quick-start">Quick start</a> — install and run a first task.</li>
                <li><a data-doc-link="getting-started/configuration">Configuration</a> — pick a model provider and set the key.</li>
                <li><a data-doc-link="core-concepts/research-workflow">Research workflow</a> — what happens between your question and the answer.</li>
                <li><a data-doc-link="getting-started/troubleshooting">Troubleshooting</a> — when a run fails or a figure is cut.</li>
              </ol>
            `
          },
          {
            id: "research-only",
            title: "Boundaries",
            body: `
              <p>Vibe-Trading is built for research, simulation and backtesting. Live trading is opt-in and read-only by default: it runs only through a broker you authorize yourself, inside a mandate whose limits you set, and a kill switch halts it at once. Vibe-Trading holds no funds, runs no execution venue, and is not investment advice.</p>
            `
          }
        ]
      },
      {
        id: "getting-started/quick-start",
        title: "Quick start",
        description: "Install from PyPI, configure a model, and run a first research task.",
        lead: "Three commands give you a working agent in the terminal. The web UI takes one more step, because the PyPI package does not ship the built front end.",
        sections: [
          {
            id: "install",
            title: "Install",
            body: `
              <p>You need Python 3.11 or newer and an API key for a model provider (or a local Ollama model, which needs none).</p>
              <pre><code>pip install vibe-trading-ai
vibe-trading init
vibe-trading</code></pre>
              <p><code>vibe-trading init</code> asks for your provider, model, key and, optionally, a Tushare token, and writes them to <code>~/.vibe-trading/.env</code>. <code>vibe-trading</code> then opens the interactive terminal; type <code>/help</code> for the command list.</p>
            `
          },
          {
            id: "first-run",
            title: "First run",
            body: `
              <p>Ask a question in the interactive session, or run one prompt and exit:</p>
              <pre><code>vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"</code></pre>
              <p>The agent fetches the bars, writes the strategy, runs the backtest and answers with the metrics. The run's code, trades and metrics stay on disk; <code>vibe-trading --list</code> shows past runs.</p>
            `
          },
          {
            id: "web-ui",
            title: "Open the web UI",
            body: `
              <p><strong>With Docker</strong> — no local Python or Node needed:</p>
              <pre><code>git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env   # uncomment your provider, set the key
docker compose up --build</code></pre>
              <p>Then open <code>http://127.0.0.1:8899</code>. Memory, sessions, runs and connector settings live in Docker volumes and survive <code>git pull &amp;&amp; docker compose up --build</code>.</p>
              <p><strong>From a source checkout</strong> — needs Node.js 22.22 or newer:</p>
              <pre><code>git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
pip install -e .
vibe-trading setup                 # install and build the front end
vibe-trading serve --port 8899</code></pre>
              <p>After a plain <code>pip install</code>, <code>vibe-trading serve</code> starts the API only and prints <code>No frontend build found</code>. That is expected; use one of the two paths above for the browser UI.</p>
            `
          },
          {
            id: "upgrade",
            title: "Upgrade",
            body: `
              <pre><code>pip install -U vibe-trading-ai
vibe-trading --version</code></pre>
              <p><code>vibe-trading update</code> checks PyPI and installs the latest release for you. If imports break after upgrading an install older than 0.1.10, recreate the virtual environment or run <code>pip install --force-reinstall vibe-trading-ai</code>.</p>
            `
          },
          {
            id: "other-agents",
            title: "Use it from another agent",
            body: `
              <p>The same package installs <code>vibe-trading-mcp</code>, a stdio MCP server. See <a data-doc-link="reference/mcp-server">MCP server</a> for the client configuration.</p>
            `
          }
        ]
      },
      {
        id: "getting-started/configuration",
        title: "Configuration",
        description: "Where settings live, which variables matter, and how to size long runs.",
        lead: "Everything is configured through environment variables. Secrets stay in a .env file or the OS keyring, never in a prompt or a source file.",
        sections: [
          {
            id: "env",
            title: "Where settings are read from",
            body: `
              <p>Vibe-Trading reads the first of these files that exists, and only that one:</p>
              <ol>
                <li><code>~/.vibe-trading/.env</code> — written by <code>vibe-trading init</code></li>
                <li><code>agent/.env</code> in a source checkout</li>
                <li><code>.env</code> in the current directory</li>
              </ol>
              <p>A variable exported in your shell always wins over the file. The Settings page of the web UI edits the model and data-source values for you.</p>
            `
          },
          {
            id: "provider",
            title: "Model provider",
            body: `
              <table>
                <thead><tr><th>Variable</th><th>Meaning</th></tr></thead>
                <tbody>
                  <tr><td><code>LANGCHAIN_PROVIDER</code></td><td>Provider name: <code>openrouter</code>, <code>deepseek</code>, <code>openai</code>, <code>anthropic</code>, <code>gemini</code>, <code>ollama</code>, … (25 built in)</td></tr>
                  <tr><td><code>LANGCHAIN_MODEL_NAME</code></td><td>Model id, for example <code>deepseek-v4-pro</code></td></tr>
                  <tr><td><code>&lt;PROVIDER&gt;_API_KEY</code></td><td>The key, for example <code>DEEPSEEK_API_KEY</code></td></tr>
                  <tr><td><code>&lt;PROVIDER&gt;_BASE_URL</code></td><td>The API endpoint</td></tr>
                  <tr><td><code>LANGCHAIN_REASONING_EFFORT</code></td><td>Optional: <code>none</code>, <code>low</code>, <code>medium</code>, <code>high</code> or <code>max</code></td></tr>
                </tbody>
              </table>
              <pre><code>LANGCHAIN_PROVIDER=deepseek
LANGCHAIN_MODEL_NAME=deepseek-v4-pro
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1</code></pre>
              <ul>
                <li><strong>ChatGPT sign-in (Codex)</strong>: set <code>LANGCHAIN_PROVIDER=openai-codex</code> and run <code>vibe-trading provider login openai-codex</code>. No <code>OPENAI_API_KEY</code> is used; the default model is <code>gpt-6-sol</code>.</li>
                <li><strong>GitHub Copilot</strong>: <code>pip install "vibe-trading-ai[copilot]"</code>, then <code>LANGCHAIN_PROVIDER=copilot</code>; it signs in with your <code>gh</code> or Copilot CLI credentials.</li>
                <li><strong>Ollama</strong>: no key needed.</li>
              </ul>
            `
          },
          {
            id: "models",
            title: "Choosing a model",
            body: `
              <p>Everything the agent does goes through tool calls, so the model decides whether it uses its tools or answers from memory. Use a strong tool-calling model for long research runs, swarms and multi-step backtests. Avoid <code>*-nano</code>, <code>*-flash-lite</code> and small distilled models: their tool calls are unreliable, and the answer will look fluent while no data was fetched.</p>
            `
          },
          {
            id: "keys",
            title: "Market-data keys (optional)",
            body: `
              <p>A-shares, Hong Kong, US, Canada, UK, India, Korea, crypto and forex all work without a key. Keys add sources or depth:</p>
              <ul>
                <li><code>TUSHARE_TOKEN</code> — richer A-share, fund and macro data.</li>
                <li><code>GILDATA_TOKEN</code> — Hundsun Juyuan commercial A-share feed.</li>
                <li>Finnhub, Alpha Vantage, Tiingo and FMP keys — extra US sources.</li>
                <li>QVeris — a paid marketplace, used only when you ask for it; switch with <code>vibe-trading data mode</code>.</li>
              </ul>
              <p>See <a data-doc-link="tools/data-sources">Data sources</a> for which source serves which market.</p>
            `
          },
          {
            id: "long-runs",
            title: "Long runs and timeouts",
            body: `
              <table>
                <thead><tr><th>Variable</th><th>Default</th><th>Meaning</th></tr></thead>
                <tbody>
                  <tr><td><code>VIBE_TRADING_CONTEXT_WINDOW</code></td><td>see below</td><td>Your model's context window in tokens. Without it, the window comes from a limit the provider reported during the run, else the built-in model catalog, else 128K.</td></tr>
                  <tr><td><code>VIBE_TRADING_CONTEXT_MAX_TOKENS</code></td><td>200000</td><td>The most one request may send, whatever the window. It caps cost.</td></tr>
                  <tr><td><code>TIMEOUT_SECONDS</code></td><td>120</td><td>Timeout of one model request.</td></tr>
                  <tr><td><code>VIBE_TRADING_TOOL_TIMEOUT_SECONDS</code></td><td>1800</td><td>Hard timeout of a read-only tool or a backtest; 0 disables it.</td></tr>
                </tbody>
              </table>
              <p><code>TOKEN_THRESHOLD</code> was removed in 0.1.16. It is ignored with a warning; delete it from your <code>.env</code>.</p>
            `
          },
          {
            id: "deployment",
            title: "Serving beyond your own machine",
            body: `
              <p>Without <code>API_AUTH_KEY</code>, the API answers sensitive requests only from the same machine. To use the web UI from another device, set a strong <code>API_AUTH_KEY</code>, send <code>Authorization: Bearer &lt;key&gt;</code> from clients, and enter the same key once in the web UI's Settings. <code>VIBE_TRADING_EXTRA_CORS_ORIGINS</code> adds allowed browser origins.</p>
              <p>Shell tools are enabled only in the local interactive terminal. The API and the MCP server keep them off unless you set <code>VIBE_TRADING_ENABLE_SHELL_TOOLS=1</code>.</p>
            `
          },
          {
            id: "paths",
            title: "Files and folders",
            body: `
              <ul>
                <li><code>VIBE_TRADING_HOME</code> — where runs, sessions, memory, connectors and the audit ledger live; default <code>~/.vibe-trading</code>.</li>
                <li><code>VIBE_TRADING_ALLOWED_FILE_ROOTS</code> — extra folders, comma-separated, from which documents and broker journals may be imported.</li>
                <li><code>VIBE_TRADING_ALLOWED_RUN_ROOTS</code> — extra folders in which generated strategy code may run.</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "getting-started/troubleshooting",
        title: "Troubleshooting",
        description: "What the common failure messages mean, and what to do about them.",
        lead: "Most failures name their cause. This page maps the messages you are likely to see to what happened and what to do next.",
        sections: [
          {
            id: "version",
            title: "Check your version first",
            body: `
              <pre><code>vibe-trading --version
pip install -U vibe-trading-ai</code></pre>
              <p>Several of the failures below were fixed in 0.1.16. Upgrade before digging further.</p>
            `
          },
          {
            id: "no-progress",
            title: "Failed · no_progress",
            body: `
              <p>The agent stops when eight tool-call rounds in a row bring no new successful result. It is a budget against loops, not a crash. Since 0.1.16 the stop message lists each call that produced nothing, with its reason and how often it happened. Typical causes:</p>
              <ul>
                <li><strong>A data source was down or rate-limited.</strong> Try again later, or name another source in the prompt ("use Yahoo").</li>
                <li><strong>The model kept guessing file paths.</strong> Fixed in 0.1.16: <code>read_file</code> now names the folders it may read and lists directories.</li>
                <li><strong>A long comparison forgot what it had fetched</strong> and fetched it again. Fixed in 0.1.16: compaction follows the model's real context window.</li>
              </ul>
              <p>The same failing call is refused from its second failure. Changing the request, or starting a new run, clears that.</p>
            `
          },
          {
            id: "zero-steps",
            title: "A failed run shows 0 steps",
            body: `
              <p>Before 0.1.16, only a completed run saved its tool trail, so a failed or cancelled run showed "0 steps" in the history. From 0.1.16 every run keeps its steps.</p>
            `
          },
          {
            id: "omitted",
            title: "(omitted※) in an answer",
            body: `
              <p>A figure that could not be matched to the data fetched in this session was cut from the answer, and the ※ footnote says how many were. Ask the agent to fetch the data or run the backtest first, then ask again. <a data-doc-link="core-concepts/checked-numbers">Checked numbers</a> explains the rules.</p>
            `
          },
          {
            id: "context",
            title: "Context-length errors",
            body: `
              <p>Since 0.1.16, a context-length error from the provider is compacted and retried, and the limit it reports is used for the rest of the run. If your model is not in the built-in catalog, set <code>VIBE_TRADING_CONTEXT_WINDOW</code> to its real window. Remove any <code>TOKEN_THRESHOLD</code> line; it is ignored.</p>
            `
          },
          {
            id: "us-ticker",
            title: "A US ticker returns an error",
            body: `
              <p>US symbols need the <code>.US</code> suffix: <code>AAPL.US</code>, not <code>AAPL</code>. The error says so: <code>US equity symbols must include the .US suffix</code>. Other markets have their own suffixes; see <a data-doc-link="tools/data-sources">Data sources</a>.</p>
            `
          },
          {
            id: "web-ui",
            title: "No frontend build found",
            body: `
              <p>You installed from PyPI, which ships the API but not the built web UI. Use Docker, or a source checkout with <code>vibe-trading setup</code>, as described in <a data-doc-link="getting-started/quick-start">Quick start</a>.</p>
            `
          },
          {
            id: "remote-403",
            title: "403 from another device",
            body: `
              <p>Without <code>API_AUTH_KEY</code>, sensitive endpoints answer only requests from the same machine. Set the key and enter it in Settings on the other device.</p>
            `
          },
          {
            id: "codex",
            title: "Codex refuses the model",
            body: `
              <p>With ChatGPT sign-in, <code>gpt-5.4</code> is refused for ChatGPT accounts. 0.1.16 defaults to <code>gpt-6-sol</code>; if your <code>.env</code> names an older model, change <code>LANGCHAIN_MODEL_NAME</code>.</p>
            `
          },
          {
            id: "report",
            title: "Reporting a problem",
            body: `
              <p>Open an issue on <a href="https://github.com/HKUDS/Vibe-Trading/issues">GitHub</a> with the version, the provider and model, and the stop message. <code>vibe-trading --trace RUN_ID</code> replays what the run did. Never paste an API key or a broker credential.</p>
            `
          }
        ]
      }
    ]
  },
  {
    id: "core-concepts",
    label: "Core concepts",
    pages: [
      {
        id: "core-concepts/research-workflow",
        title: "Research workflow",
        description: "How a run moves from your question to an answer with evidence.",
        lead: "Each request takes the same path: plan, fetch evidence, run tools, check the result, and deliver it together with the files it came from.",
        sections: [
          {
            id: "pipeline",
            title: "Pipeline",
            body: `
              <ol>
                <li><strong>Plan</strong> — pick the skills, tools, data sources and, when useful, a swarm preset.</li>
                <li><strong>Ground</strong> — fetch market bars, filings, documents, web pages, broker journals or local files at run time.</li>
                <li><strong>Execute</strong> — write strategy code, run backtests, factor analysis, options checks or reports.</li>
                <li><strong>Validate</strong> — add metrics, benchmark comparison, Monte Carlo, bootstrap and walk-forward checks, and run-card warnings.</li>
                <li><strong>Check</strong> — compare every figure in the draft answer with the session's tool data (<a data-doc-link="core-concepts/checked-numbers">Checked numbers</a>).</li>
                <li><strong>Deliver</strong> — return the answer with the run's artifacts.</li>
              </ol>
            `
          },
          {
            id: "progress",
            title: "Progress budget",
            body: `
              <p>A run stops, visibly and marked failed, after eight tool-call rounds in a row without a new successful observation. Repeating a read that returns the same result, or a call that fails, does not count as progress. An identical call is refused from its second failure, so one retry after a rate limit or a timeout still runs; changed arguments always run. A separate wall-clock watchdog stops runs that hang.</p>
            `
          },
          {
            id: "context",
            title: "Long conversations",
            body: `
              <p>When a conversation outgrows the model's context window, older material is compacted in three layers: clear the oldest tool results, fold long text, then summarize. The layers start at 80%, 90% and 100% of what the system prompt and tool definitions leave free, and only clear down to that line, so recent evidence stays in view.</p>
            `
          },
          {
            id: "artifacts",
            title: "Runs and artifacts",
            body: `
              <p>Every backtest writes a run directory under <code>~/.vibe-trading/runs/</code>:</p>
              <ul>
                <li><code>code/</code> and <code>config.json</code> — the strategy and its settings.</li>
                <li><code>run_card.json</code> and <code>run_card.md</code> — what ran, on which data, with which warnings.</li>
                <li><code>artifacts/metrics.csv</code>, <code>equity.csv</code>, <code>trades.csv</code>, <code>positions.csv</code> — results.</li>
                <li><code>artifacts/validation.json</code>, <code>risk_xray.json</code> — validation and risk breakdown.</li>
                <li><code>logs/</code> — engine output, kept even when a run times out.</li>
              </ul>
              <pre><code>vibe-trading --list
vibe-trading --show RUN_ID
vibe-trading --code RUN_ID
vibe-trading --pine RUN_ID     # TradingView Pine Script
vibe-trading --trace RUN_ID    # replay the agent's steps</code></pre>
            `
          },
          {
            id: "memory",
            title: "Sessions and memory",
            body: `
              <ul>
                <li><strong>Persistent memory</strong> in <code>~/.vibe-trading/memory/</code> carries preferences and findings across sessions (<code>/memory</code>, <code>vibe-trading memory</code>).</li>
                <li><strong>Search</strong> across all past sessions with <code>/search</code>; resume one with <code>/history</code>.</li>
                <li><strong>Goals</strong> (<code>/goal</code>) keep a longer research question, its evidence and its status across runs.</li>
                <li>Restart-safe: a run interrupted by a restart is recorded as interrupted, with the text streamed so far.</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "core-concepts/checked-numbers",
        title: "Checked numbers",
        description: "How the figures in an answer are checked against the data the agent fetched.",
        lead: "Before an answer reaches you, each figure in it is checked against the tool results of the session. A figure that cannot be traced goes back for correction, and is cut if it still fails.",
        sections: [
          {
            id: "how",
            title: "How it works",
            body: `
              <p>For every figure, the model declares where it came from:</p>
              <ul>
                <li><strong>observed</strong> — a value a tool returned;</li>
                <li><strong>derived</strong> — computed from observed values, with the formula written out;</li>
                <li><strong>proposed</strong> — a target or an assumption, not a measurement;</li>
                <li><strong>cited</strong> — taken from a source named on the same line;</li>
                <li><strong>count</strong> — how many of something.</li>
              </ul>
              <p>The check verifies each figure by its role: an observed value must match a tool result, a derived value must follow from its operands, a cited value must name its source. The declarations are removed before the answer is shown.</p>
            `
          },
          {
            id: "scope",
            title: "Which numbers are checked",
            body: `
              <p>Decimals, percentages, currency amounts and numbers in table cells are measurements and are checked. Dates, years, codes, ordinals and plain integers in a sentence are not, except integer prices of instruments quoted at 1,000 or more. A rounded figure must be the tool value correctly rounded to the digits it shows, and within 0.5% of it: 30.2052% may be written 30.21% or 30.2% but not 30.20%, and 0.82467 may be written 0.825 but not 0.82.</p>
            `
          },
          {
            id: "backtests",
            title: "Backtest reports",
            body: `
              <p>Since 0.1.16, what a backtest wrote about itself counts as evidence for the report about it: every value in the run card, the metrics, the risk X-ray, the Monte Carlo validation and the rebalance summary. A per-bar table counts only for the rows the agent actually read. A file the model wrote itself never counts, and a value from one backtest does not support a figure attributed to another.</p>
            `
          },
          {
            id: "what-you-see",
            title: "What you see",
            body: `
              <ul>
                <li>While it runs: <em>Checking the figures in this answer (round N)…</em></li>
                <li>A figure that fails is sent back with a specific correction, at most twice.</li>
                <li>A figure that still fails is replaced by <code>(omitted※)</code>, and a footnote says how many were cut. The rest of the answer is released.</li>
                <li>The whole answer is replaced by a short refusal only when a price question had no fetched price, when the answer described a different instrument than the one fetched, or when cutting the failing figures still does not pass.</li>
              </ul>
            `
          },
          {
            id: "tips",
            title: "Getting your figures through",
            body: `
              <ul>
                <li>Ask the agent to fetch the data before it quotes numbers.</li>
                <li>When comparing backtests, let it name the run each figure comes from.</li>
                <li>When you supply a number yourself, say where it comes from ("per the 2025 annual report").</li>
                <li>Assumptions such as a discount rate are shown as proposals, not as measurements.</li>
              </ul>
            `
          },
          {
            id: "limits",
            title: "Limits",
            body: `
              <p>The check shows that a figure matches the data of the session. It does not show that the data is right or that the analysis is sound. Plain integers in prose, units written as words, and a correct value quoted under the wrong name are not caught.</p>
            `
          }
        ]
      },
      {
        id: "core-concepts/backtesting",
        title: "Backtesting",
        description: "Engines, intervals, portfolio construction, validation and outputs.",
        lead: "Strategies are written as code, run on an engine that applies the market's own rules, and saved with their metrics, trades and validation for later inspection.",
        sections: [
          {
            id: "engines",
            title: "Engines",
            body: `
              <table>
                <thead><tr><th>Market</th><th>Rules modelled</th></tr></thead>
                <tbody>
                  <tr><td>China A-shares</td><td>T+1, no retail shorting, ±10% / ±20% / ±5% price limits, 100-share lots</td></tr>
                  <tr><td>Global equities (US, Hong Kong, Canada, UK, indices)</td><td>Per-market trading rules and costs</td></tr>
                  <tr><td>India (NSE / BSE)</td><td>Delivery segment on daily bars, circuit bands, statutory cost stack</td></tr>
                  <tr><td>Korea (KOSPI / KOSDAQ)</td><td>KRX tick grid, ±30% band, long-only</td></tr>
                  <tr><td>Vietnam (HOSE)</td><td>Whole-VND tick grid and price band</td></tr>
                  <tr><td>Crypto</td><td>Perpetuals: maker/taker fees, funding every 8 hours, liquidation</td></tr>
                  <tr><td>China futures</td><td>CFFEX, SHFE, DCE, ZCE, INE, GFEX: T+0, margin, price limits</td></tr>
                  <tr><td>Global futures</td><td>CME, ICE, Eurex: margin, contract multipliers</td></tr>
                  <tr><td>Forex and metals</td><td>Spread, leverage, lot sizes</td></tr>
                  <tr><td>Composite</td><td>Several markets in one shared capital pool</td></tr>
                  <tr><td>Options portfolio</td><td>Black-Scholes with an IV smile, European and American, multi-leg</td></tr>
                </tbody>
              </table>
              <p>Argentine symbols (<code>.BA</code>) have market data but no backtest engine yet; a backtest on them is refused rather than run under another market's rules.</p>
            `
          },
          {
            id: "intervals",
            title: "Bar intervals",
            body: `
              <p><code>1m</code>, <code>5m</code>, <code>15m</code>, <code>30m</code>, <code>1H</code>, <code>4H</code>, <code>1D</code>, <code>1W</code>, <code>1M</code>. Weekly and monthly bars are built from daily bars. Case matters: <code>1M</code> is a month and <code>1m</code> a minute. Minute bars depend on what the source serves.</p>
            `
          },
          {
            id: "portfolio",
            title: "Portfolio construction",
            body: `
              <p>Built-in optimizers: equal volatility, risk parity, mean-variance, maximum diversification and turnover-aware rebalancing.</p>
            `
          },
          {
            id: "validation",
            title: "Validation",
            body: `
              <p>A run can add benchmark comparison, a Monte Carlo test, a bootstrap confidence interval for the Sharpe ratio and walk-forward analysis. The run card warns when the data's bar spacing does not match the declared interval or when price adjustments differ between sources. Treat these as evidence, not guarantees.</p>
            `
          },
          {
            id: "example",
            title: "Example",
            body: `
              <pre><code>vibe-trading run -p "Compare risk parity and equal weight on 600519.SH, 000858.SZ and 000001.SZ for 2023-2025, monthly rebalancing, with a Monte Carlo test"</code></pre>
            `
          }
        ]
      },
      {
        id: "core-concepts/swarm-teams",
        title: "Swarm teams",
        description: "Preset teams of specialist agents for committee-style research.",
        lead: "A swarm preset turns one question into a small team of specialist agents that work in dependency order, stream their progress and write one final report.",
        sections: [
          {
            id: "presets",
            title: "Presets",
            body: `
              <p>30 presets ship with 0.1.16:</p>
              <p><code>investment_committee</code>, <code>quant_strategy_desk</code>, <code>risk_committee</code>, <code>crypto_trading_desk</code>, <code>crypto_research_lab</code>, <code>macro_rates_fx_desk</code>, <code>macro_strategy_forum</code>, <code>global_allocation_committee</code>, <code>global_equities_desk</code>, <code>equity_research_team</code>, <code>fundamental_research_team</code>, <code>earnings_research_desk</code>, <code>value_investing_committee</code>, <code>factor_research_committee</code>, <code>ml_quant_lab</code>, <code>statistical_arbitrage_desk</code>, <code>pairs_research_lab</code>, <code>derivatives_strategy_desk</code>, <code>convertible_bond_team</code>, <code>credit_research_team</code>, <code>commodity_research_team</code>, <code>etf_allocation_desk</code>, <code>fund_selection_panel</code>, <code>portfolio_review_board</code>, <code>sector_rotation_team</code>, <code>event_driven_task_force</code>, <code>geopolitical_war_room</code>, <code>sentiment_intelligence_team</code>, <code>social_alpha_team</code>, <code>technical_analysis_panel</code>.</p>
            `
          },
          {
            id: "run",
            title: "Running a preset",
            body: `
              <pre><code>vibe-trading --swarm-presets
vibe-trading --swarm-inspect investment_committee
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'</code></pre>
              <p>Variables are passed as one JSON object. In the interactive terminal use <code>/swarm</code>; the web UI shows each worker's progress live.</p>
            `
          },
          {
            id: "manage",
            title: "Managing runs",
            body: `
              <pre><code>vibe-trading --swarm-list
vibe-trading --swarm-show RUN_ID
vibe-trading --swarm-cancel RUN_ID
vibe-trading --swarm-retry RUN_ID --swarm-resume   # keep finished tasks</code></pre>
            `
          },
          {
            id: "keys",
            title: "Model requirements",
            body: `
              <p>Each worker is a full agent, so a swarm needs a model key and costs several single runs. Workers fetch their own market data, and a preset's list of skills is enforced: a worker cannot load a skill its preset does not name.</p>
            `
          }
        ]
      }
    ]
  },
  {
    id: "tools",
    label: "Tools",
    pages: [
      {
        id: "tools/data-sources",
        title: "Data sources",
        description: "Which source serves which market, symbol formats, and how to pick a source.",
        lead: "One get_market_data call reaches 28 sources. With source auto, each symbol is routed by its market and walks that market's fallback chain, with the sources least likely to block you first.",
        sections: [
          {
            id: "providers",
            title: "Fallback chains",
            body: `
              <table>
                <thead><tr><th>Market</th><th>Chain, in order</th></tr></thead>
                <tbody>
                  <tr><td>China A-shares</td><td>tencent, mootdx, eastmoney, baostock, akshare, tushare, gildata, local</td></tr>
                  <tr><td>US equities</td><td>yahoo, stooq, sina, eastmoney, yfinance, tiingo, fmp, finnhub, alphavantage, longbridge, akshare, local</td></tr>
                  <tr><td>Hong Kong</td><td>tencent, eastmoney, yahoo, futu, akshare, yfinance, tushare, longbridge, local</td></tr>
                  <tr><td>India</td><td>yahoo, yfinance, india_broker, local</td></tr>
                  <tr><td>Korea</td><td>pykrx, yahoo, yfinance, local</td></tr>
                  <tr><td>Canada, UK, Vietnam, Argentina, indices</td><td>yahoo, yfinance, local</td></tr>
                  <tr><td>Crypto</td><td>okx, binance, ccxt, yfinance, local</td></tr>
                  <tr><td>China futures</td><td>akshare, local</td></tr>
                  <tr><td>Forex and metals</td><td>mt5, akshare, yfinance, local</td></tr>
                  <tr><td>Funds</td><td>tushare, akshare, local</td></tr>
                  <tr><td>Macro</td><td>akshare, tushare, local</td></tr>
                </tbody>
              </table>
              <p>Four sources are used only when you name them: <code>qveris</code> (paid marketplace), <code>tickerall</code> (hosted MT5 feed), and <code>nobitex</code> / <code>wallex</code> (Iranian Toman pairs). Set <code>MARKET_DATA_ORDER_&lt;MARKET&gt;</code>, for example <code>MARKET_DATA_ORDER_US_EQUITY</code>, to reorder a chain.</p>
            `
          },
          {
            id: "symbols",
            title: "Symbol formats",
            body: `
              <table>
                <thead><tr><th>Market</th><th>Examples</th></tr></thead>
                <tbody>
                  <tr><td>China A-shares</td><td><code>600519.SH</code>, <code>000001.SZ</code></td></tr>
                  <tr><td>Hong Kong</td><td><code>0700.HK</code></td></tr>
                  <tr><td>US</td><td><code>AAPL.US</code>, <code>SPY.US</code> — the suffix is required</td></tr>
                  <tr><td>Crypto</td><td><code>BTC-USDT</code> (uppercase, hyphen)</td></tr>
                  <tr><td>Korea / India / UK / Canada</td><td><code>005930.KS</code>, <code>RELIANCE.NS</code>, <code>VOD.L</code>, <code>SHOP.TO</code></td></tr>
                  <tr><td>Vietnam / Argentina</td><td><code>VNM.VN</code>, <code>GGAL.BA</code></td></tr>
                  <tr><td>China futures</td><td><code>RB0</code> (main continuous), <code>IF2412</code></td></tr>
                  <tr><td>Forex and metals</td><td><code>EURUSD</code>, <code>XAUUSD</code></td></tr>
                  <tr><td>Your own files</td><td><code>local:</code> prefix — CSV, Parquet or DuckDB</td></tr>
                </tbody>
              </table>
              <p>A suffix names the exchange, not the currency. A London line must declare GBP or GBp, and a Hong Kong counter is priced by the currency its stock code belongs to.</p>
            `
          },
          {
            id: "choosing",
            title: "Choosing a source",
            body: `
              <p>Ask in plain language ("use Longbridge to fetch QQQ.US") or set <code>"source"</code> in a backtest config. An explicit <code>local:</code> symbol never falls back to a network source.</p>
            `
          },
          {
            id: "beyond-prices",
            title: "Beyond prices",
            body: `
              <p>22 read-only data tools cover fund flow, dragon-tiger lists, northbound flow, margin trading, block trades, shareholder counts, lock-up expiries, sectors, research reports, news, SEC filings, financial statements, option chains, company profiles, market screening, symbol search, macro series, iwencai, 13F institutional holdings, ETF look-through, prediction markets and research papers.</p>
            `
          }
        ]
      },
      {
        id: "tools/shadow-account",
        title: "Shadow Account",
        description: "Turn a broker journal into behavior diagnostics and a rule-based shadow strategy.",
        lead: "Shadow Account starts from your real trades, extracts the rules you actually follow, and compares your trading with a strategy that follows those rules without exception.",
        sections: [
          {
            id: "flow",
            title: "Workflow",
            body: `
              <ol>
                <li><strong>Read your journal</strong> — exports from 同花顺 (THS), 东方财富 (Eastmoney), 富途 (Futu), or a generic CSV.</li>
                <li><strong>Profile your behavior</strong> — holding days, win rate, PnL ratio, drawdown, and checks for the disposition effect, overtrading, momentum chasing and anchoring.</li>
                <li><strong>Extract your rules</strong> — recurring entries and exits become an explicit strategy profile.</li>
                <li><strong>Run the shadow</strong> — backtest those rules and show rule breaks, early exits and missed signals.</li>
                <li><strong>Deliver the report</strong> — an HTML or PDF report you can keep and refine later.</li>
              </ol>
            `
          },
          {
            id: "example",
            title: "Example",
            body: `
              <pre><code>vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"</code></pre>
              <p>In the interactive terminal, <code>/journal</code> analyzes a journal and <code>/shadow</code> trains or shows the shadow account.</p>
            `
          }
        ]
      },
      {
        id: "tools/finance-skills",
        title: "Finance skills",
        description: "Knowledge modules the agent loads when a task needs them.",
        lead: "Skills are Markdown documents of domain method — how to screen for ST risk, how to build a DCF, how a data source behaves. The agent loads the ones a task needs instead of carrying all of them in every prompt.",
        sections: [
          {
            id: "library",
            title: "Library",
            body: `
              <p>90 skills in 9 categories:</p>
              <table>
                <thead><tr><th>Category</th><th>Skills</th></tr></thead>
                <tbody>
                  <tr><td>Analysis</td><td>23</td></tr>
                  <tr><td>Strategy</td><td>19</td></tr>
                  <tr><td>Data sources</td><td>10</td></tr>
                  <tr><td>Tools</td><td>10</td></tr>
                  <tr><td>Asset classes</td><td>9</td></tr>
                  <tr><td>Flow</td><td>8</td></tr>
                  <tr><td>Crypto</td><td>7</td></tr>
                  <tr><td>Research</td><td>3</td></tr>
                  <tr><td>Risk analysis</td><td>1</td></tr>
                </tbody>
              </table>
            `
          },
          {
            id: "using",
            title: "Using skills",
            body: `
              <pre><code>vibe-trading --skills     # list them
/skill                    # list, load or unload in the interactive terminal</code></pre>
              <p>Skills are plain files, so you can edit them or ask the agent to write a new one for a routine you repeat. Formulas live in the tested finance-math library, which skills call instead of carrying their own copies.</p>
            `
          },
          {
            id: "institutional",
            title: "Institutional research commands",
            body: `
              <p><code>/comps</code> comparable companies, <code>/dcf</code> discounted cash flow with a sensitivity grid, <code>/attrib</code> Brinson-Fachler attribution, <code>/memo</code> investment memo, <code>/earnings</code> earnings review from revenue to EPS, <code>/screen</code> systematic idea screen.</p>
            `
          },
          {
            id: "examples",
            title: "Examples",
            body: `
              <ul>
                <li>Dividend analysis and yield-trap checks.</li>
                <li>A-share pre-ST risk screening.</li>
                <li>Investor lenses: reasoning frameworks of named investors as overlays.</li>
                <li>Pine Script, TDX and MetaTrader 5 exports.</li>
                <li>Factor research, macro analysis, correlation regimes and technical patterns.</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "tools/alpha-zoo",
        title: "Alpha Zoo",
        description: "462 ready-made alphas you can benchmark on your own universe.",
        lead: "The Alpha Zoo is a registry of published alpha formulas. One command scores a whole zoo on a universe and period and sorts each alpha into alive, reversed or dead.",
        sections: [
          {
            id: "zoos",
            title: "Zoos",
            body: `
              <table>
                <thead><tr><th>Zoo</th><th>Alphas</th></tr></thead>
                <tbody>
                  <tr><td><code>gtja191</code> — Guotai Junan 191</td><td>191</td></tr>
                  <tr><td><code>qlib158</code> — Microsoft Qlib Alpha158</td><td>154</td></tr>
                  <tr><td><code>alpha101</code> — Kakushadze 101 Formulaic Alphas</td><td>101</td></tr>
                  <tr><td><code>academic</code> — factors from the literature</td><td>12</td></tr>
                  <tr><td><code>fundamental</code> — point-in-time SEC fundamentals</td><td>4</td></tr>
                </tbody>
              </table>
            `
          },
          {
            id: "commands",
            title: "Commands",
            body: `
              <pre><code>vibe-trading alpha list
vibe-trading alpha show gtja191_001
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
vibe-trading alpha compare
vibe-trading alpha export-manifest</code></pre>
              <p>Universes: <code>csi300</code>, <code>sp500</code>, <code>btc-usdt</code>. <code>--strict</code> adds same-universe random controls and, with <code>--oos-split</code>, an out-of-sample confirmation. The web UI has the same bench and compare under Alpha Zoo, and this site's <a href="/alpha-library/">Alpha Library</a> browses the formulas.</p>
            `
          },
          {
            id: "missing-data",
            title: "Missing data",
            body: `
              <p>An alpha emits no value on a bar where one of its inputs is missing, rather than a signal made from a filled-in zero. Recursive smoothers skip the missing observation and continue.</p>
            `
          }
        ]
      },
      {
        id: "tools/brokers-and-live-trading",
        title: "Brokers and live trading",
        description: "Broker connectors, the read-only portfolio, and bounded live trading.",
        lead: "Broker connections start read-only. A live order is possible only through a broker you authorize, inside a mandate you set, with a kill switch that stops everything.",
        sections: [
          {
            id: "connectors",
            title: "Connectors",
            body: `
              <p>18 connectors with 55 profiles. A profile is paper or live, and read-only or order-enabled.</p>
              <table>
                <thead><tr><th>What orders can do</th><th>Brokers</th></tr></thead>
                <tbody>
                  <tr><td>Live orders inside a mandate, plus paper</td><td>Alpaca, Binance, eToro, Futu, MetaTrader 5, OKX, Tiger</td></tr>
                  <tr><td>Live orders inside a mandate</td><td>Robinhood (Agentic Trading, via the broker's MCP)</td></tr>
                  <tr><td>Paper orders only</td><td>Dhan, KIS, Longbridge, Shoonya, Upbit, Zerodha</td></tr>
                  <tr><td>Read-only</td><td>IBKR, Scalable Capital, Toss Securities, Trading 212</td></tr>
                </tbody>
              </table>
              <p>A broker that exposes no way to tell a paper account from a live one at run time is capped at paper and read-only.</p>
            `
          },
          {
            id: "setup",
            title: "Connecting a broker",
            body: `
              <pre><code>vibe-trading connector list
vibe-trading connector setup okx-live-sdk-readonly --connection-id main-okx --label "Main OKX"
vibe-trading connector check</code></pre>
              <p>The terminal asks for secrets in a hidden prompt and stores them in the OS keyring, then runs a read-only check. In the web UI: Portfolio → Manage accounts → connection center. Never paste broker keys into a chat.</p>
            `
          },
          {
            id: "portfolio",
            title: "Portfolio",
            body: `
              <p>The read-only Portfolio page combines the holdings of the connections you pick. Every holding names its source; a source that fails is shown as an error and left out of the totals, never carried forward from an old snapshot. The same view is in the terminal: <code>vibe-trading portfolio show</code>, <code>refresh</code>, <code>sources</code>.</p>
            `
          },
          {
            id: "mandate",
            title: "The live-trading mandate",
            body: `
              <ol>
                <li>When you ask for live trading, the agent proposes two to four mandate profiles, each clamped to what your account allows.</li>
                <li>You pick one and commit it yourself, in the web UI's confirm dialog or in the terminal. Where one broker login reaches several accounts, you also choose the account it binds to.</li>
                <li>The mandate fixes the maximum order size, total exposure, leverage, instrument types, trades per day, the eligible universe and an expiry date.</li>
                <li>Inside it the agent trades without asking per order. An order that would break a limit is refused and pauses for your re-authorization.</li>
              </ol>
            `
          },
          {
            id: "kill-switch",
            title: "Kill switch and audit",
            body: `
              <p><code>/halt</code> (or <code>/stop</code>) in the terminal, or the halt control in the web UI, stops all live activity at once; <code>/resume</code> clears it. Every live action is written to a hash-chained audit ledger, so an edited or deleted record is detectable.</p>
            `
          }
        ]
      }
    ]
  },
  {
    id: "reference",
    label: "Reference",
    pages: [
      {
        id: "reference/cli",
        title: "CLI reference",
        description: "Subcommands, one-shot flags and interactive slash commands.",
        lead: "The terminal is the quickest way to run repeatable research. vibe-trading --help lists everything below.",
        sections: [
          {
            id: "commands",
            title: "Subcommands",
            body: `
              <table>
                <thead><tr><th>Command</th><th>Does</th></tr></thead>
                <tbody>
                  <tr><td><code>run -p "…"</code></td><td>Run one prompt</td></tr>
                  <tr><td><code>chat</code></td><td>Interactive chat (same as plain <code>vibe-trading</code>)</td></tr>
                  <tr><td><code>init</code></td><td>Create <code>~/.vibe-trading/.env</code> interactively</td></tr>
                  <tr><td><code>serve --port 8899</code></td><td>Start the API server (and the web UI when built)</td></tr>
                  <tr><td><code>setup</code></td><td>Install and build the web UI from a checkout</td></tr>
                  <tr><td><code>dev</code></td><td>Start backend and front-end dev servers together</td></tr>
                  <tr><td><code>update</code></td><td>Install the latest release from PyPI</td></tr>
                  <tr><td><code>provider</code></td><td>OAuth sign-in for providers such as Codex</td></tr>
                  <tr><td><code>data</code></td><td>Data routing mode: <code>status</code>, <code>mode</code>, <code>usage</code></td></tr>
                  <tr><td><code>list</code> / <code>show</code></td><td>List runs / show one run</td></tr>
                  <tr><td><code>memory</code></td><td>Inspect persistent memory</td></tr>
                  <tr><td><code>channels</code></td><td>IM channels: <code>status</code>, <code>start</code>, <code>stop</code>, <code>login</code>, <code>pairing</code></td></tr>
                  <tr><td><code>connector</code></td><td>Broker connector profiles and connections</td></tr>
                  <tr><td><code>portfolio</code></td><td>Read-only multi-broker portfolio</td></tr>
                  <tr><td><code>alpha</code></td><td>Alpha Zoo: <code>list</code>, <code>show</code>, <code>bench</code>, <code>compare</code>, <code>export-manifest</code></td></tr>
                  <tr><td><code>hypothesis</code></td><td>Hypothesis registry: <code>list</code>, <code>show</code>, <code>invalidate</code></td></tr>
                  <tr><td><code>playbook</code></td><td>Scheduled research templates</td></tr>
                  <tr><td><code>strategy-evidence</code></td><td>Refresh strategy evidence from backtest runs</td></tr>
                </tbody>
              </table>
            `
          },
          {
            id: "flags",
            title: "One-shot flags",
            body: `
              <pre><code>vibe-trading -p "prompt"            # run a prompt
vibe-trading -f prompt.txt          # read the prompt from a file
vibe-trading --json -p "prompt"     # machine-readable output
vibe-trading --continue RUN_ID "follow-up"
vibe-trading --upload report.pdf
vibe-trading --list                 # runs; also --show, --code, --pine, --trace RUN_ID
vibe-trading --sessions             # sessions; --session-chat SESSION_ID continues one
vibe-trading --skills
vibe-trading --max-iter 40 -p "prompt"</code></pre>
            `
          },
          {
            id: "interactive",
            title: "Interactive slash commands",
            body: `
              <table>
                <thead><tr><th>Command</th><th>Does</th></tr></thead>
                <tbody>
                  <tr><td><code>/help</code></td><td>Keyboard shortcuts and commands</td></tr>
                  <tr><td><code>/model</code></td><td>Switch provider and model</td></tr>
                  <tr><td><code>/memory</code>, <code>/history</code>, <code>/search</code></td><td>Memory, past sessions, full-text search</td></tr>
                  <tr><td><code>/goal</code></td><td>Start or inspect a research goal</td></tr>
                  <tr><td><code>/swarm</code>, <code>/skill</code></td><td>Swarm presets, skills</td></tr>
                  <tr><td><code>/show</code>, <code>/pine</code>, <code>/export</code></td><td>Show a run, export Pine Script, export the session</td></tr>
                  <tr><td><code>/journal</code>, <code>/shadow</code></td><td>Trade journal, Shadow Account</td></tr>
                  <tr><td><code>/comps</code>, <code>/dcf</code>, <code>/attrib</code>, <code>/memo</code>, <code>/earnings</code>, <code>/screen</code></td><td>Institutional research</td></tr>
                  <tr><td><code>/playbook</code></td><td>Scheduled research templates</td></tr>
                  <tr><td><code>/connector</code>, <code>/data</code></td><td>Broker profiles, data routing</td></tr>
                  <tr><td><code>/halt</code>, <code>/resume</code></td><td>Kill switch on and off</td></tr>
                  <tr><td><code>/debug</code>, <code>/clear</code>, <code>/quit</code></td><td>Token and latency panel, clear, exit</td></tr>
                </tbody>
              </table>
            `
          }
        ]
      },
      {
        id: "reference/mcp-server",
        title: "MCP server",
        description: "Give Claude Desktop, Cursor, OpenClaw and other MCP clients Vibe-Trading's tools.",
        lead: "vibe-trading-mcp runs as a stdio subprocess of your MCP client and exposes 74 tools. Research tools work without a model key; run_swarm needs one.",
        sections: [
          {
            id: "config",
            title: "Client config",
            body: `
              <pre><code>{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp",
      "env": { "VIBE_TRADING_ALLOWED_RUN_ROOTS": "/path/to/your/research" }
    }
  }
}</code></pre>
              <p>The client starts the server itself, so a variable exported in your shell does not reach it: put keys and paths in the <code>env</code> block. <code>VIBE_TRADING_ALLOWED_RUN_ROOTS</code> is needed only if backtests should write into a folder of your own.</p>
            `
          },
          {
            id: "tools",
            title: "Tool surface",
            body: `
              <ul>
                <li><strong>Research</strong>: skills, research goals, web search, URL and document reading, file read and write.</li>
                <li><strong>Market data</strong>: <code>get_market_data</code> and 22 fundamentals and flow tools.</li>
                <li><strong>Analysis</strong>: backtest, factor analysis, Alpha Zoo, options, patterns, technical indicators, sentiment, order-book depth, quantlib functions, cash-flow performance.</li>
                <li><strong>Strategies</strong>: list, query and refresh strategy evidence.</li>
                <li><strong>Brokers</strong>: <code>trading_connections</code>, <code>trading_check</code>, account, positions, orders, quotes and history — read-only.</li>
                <li><strong>Swarms and runs</strong>: presets, <code>run_swarm</code>, status, results, retry.</li>
                <li><strong>Shadow Account</strong>: journal analysis, rule extraction, shadow backtest, report.</li>
              </ul>
              <p>Shell tools stay off on every MCP transport unless you pass <code>--enable-shell-tools</code> or set <code>VIBE_TRADING_ENABLE_SHELL_TOOLS=1</code>.</p>
            `
          }
        ]
      },
      {
        id: "reference/web-ui-and-api",
        title: "Web UI and API",
        description: "The browser UI, the REST API, IM channels and scheduled research.",
        lead: "vibe-trading serve runs the FastAPI server that the web UI, IM channels and scheduled jobs all use.",
        sections: [
          {
            id: "pages",
            title: "Web UI pages",
            body: `
              <ul>
                <li><strong>Agent</strong> — chat with streaming tool steps and the swarm dashboard; up to five files per message.</li>
                <li><strong>Reports</strong> and run detail — past runs, metrics, charts and code; <strong>Compare</strong> runs side by side.</li>
                <li><strong>Portfolio</strong> — read-only holdings across your broker connections.</li>
                <li><strong>Alpha Zoo</strong> — browse, bench and compare alphas.</li>
                <li><strong>Options</strong> lab and <strong>Correlation</strong> regimes.</li>
                <li><strong>Scheduled</strong> — recurring research jobs.</li>
                <li><strong>Settings</strong> — model, data sources, IM channels and the API key.</li>
              </ul>
            `
          },
          {
            id: "auth",
            title: "Access and security",
            body: `
              <p>On the same machine the UI works with no configuration. For any other client, set <code>API_AUTH_KEY</code> and send <code>Authorization: Bearer &lt;key&gt;</code>. Interactive API docs are at <code>/docs</code> only in keyless local mode; with a key, fetch <code>/openapi.json</code> with the header.</p>
            `
          },
          {
            id: "channels",
            title: "IM channels",
            body: `
              <p>WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ/NapCat, WeChat/WeCom, Feishu/Lark, DingTalk, Microsoft Teams, email and Mochat run the same sessions. Configure and start them from Settings → IM Channels, or with <code>vibe-trading channels status | start | stop</code>. A sender who is not on a channel's <code>allow_from</code> list gets a pairing code in a direct message and is ignored until you approve it with <code>vibe-trading channels pairing approve</code>.</p>
            `
          },
          {
            id: "scheduled",
            title: "Scheduled research",
            body: `
              <p>Run a prompt or a backtest on an interval or a cron schedule. The executor is off by default; start the server with <code>VIBE_TRADING_ENABLE_SCHEDULER=1</code>. Five templates are ready to schedule: pre-market brief, earnings-season tracker, portfolio check-up, A-share money flow and institutional-holdings diff.</p>
              <pre><code>vibe-trading playbook list
vibe-trading playbook show premarket-brief
vibe-trading playbook create premarket-brief</code></pre>
            `
          },
          {
            id: "endpoints",
            title: "Main endpoints",
            body: `
              <table>
                <thead><tr><th>Endpoint</th><th>Does</th></tr></thead>
                <tbody>
                  <tr><td><code>POST /sessions</code>, <code>POST /sessions/{id}/messages</code></td><td>Create a session, send a message</td></tr>
                  <tr><td><code>GET /sessions/{id}/events</code></td><td>Server-sent event stream</td></tr>
                  <tr><td><code>POST /sessions/{id}/cancel</code></td><td>Stop the run in flight</td></tr>
                  <tr><td><code>GET /runs</code>, <code>GET /runs/{run_id}</code></td><td>Runs</td></tr>
                  <tr><td><code>POST /upload</code></td><td>Upload a document, data file or image</td></tr>
                  <tr><td><code>POST /swarm/runs</code></td><td>Start a swarm run</td></tr>
                  <tr><td><code>POST /alpha/bench</code></td><td>Start an Alpha Zoo bench</td></tr>
                  <tr><td><code>/scheduled-runs</code></td><td>Scheduled jobs and templates</td></tr>
                  <tr><td><code>POST /live/halt</code>, <code>POST /live/resume</code></td><td>Kill switch</td></tr>
                </tbody>
              </table>
            `
          }
        ]
      },
      {
        id: "reference/cloudflare-pages",
        title: "Cloudflare Pages",
        description: "How this wiki is built, deployed and edited.",
        lead: "The wiki is a static site. Cloudflare Pages serves it straight from the repository, with no build step.",
        sections: [
          {
            id: "settings",
            title: "Pages settings",
            body: `
              <ul>
                <li>Project root: <code>wiki</code></li>
                <li>Build command: leave empty</li>
                <li>Output directory: <code>.</code></li>
                <li>Custom domain: <code>vibetrading.wiki</code></li>
              </ul>
              <p>A push to <code>main</code> that touches <code>wiki/</code> or <code>agent/src/factors/</code> deploys it; the deploy generates the Alpha Library pages first.</p>
            `
          },
          {
            id: "editing",
            title: "Editing the docs",
            body: `
              <p>English pages live in <code>wiki/docs/content.en.js</code>, Chinese pages in <code>wiki/docs/content.zh.js</code>. Both must have the same pages and sections in the same order. English is served at <code>/docs/latest/…</code>, Chinese at <code>/docs/zh/…</code>.</p>
              <p>Every page of the site shares one header, footer and head block from <code>wiki/partials/</code>. The rest of the site is English HTML with Chinese in <code>wiki/locales/zh.json</code>. English is the default; the header button switches the whole site and remembers the choice. CI runs:</p>
              <pre><code>node wiki/scripts/check_docs_parity.mjs
python3 wiki/scripts/sync_site_chrome.py --check
python3 wiki/scripts/check_i18n.py</code></pre>
            `
          },
          {
            id: "why-static",
            title: "Why static",
            body: `
              <p>Docs, landing copy, redirects, theme, language and search all work as static files. No VPS, database or server process is needed; the only server-side code is an anonymous page-view counter.</p>
            `
          }
        ]
      }
    ]
  }
];
