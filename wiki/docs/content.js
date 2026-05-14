export const DOCS_DEFAULT_VERSION = "0.1.7";
export const DOCS_LATEST_ALIAS = "latest";
export const DOCS_DEFAULT_PAGE = "getting-started/vibe-trading-overview";

export const DOCS_VERSIONS = [
  { name: "0.1.7", label: "0.1.7 (latest)" }
];

export const DOCS_STRUCTURE = [
  {
    id: "getting-started",
    label: "Getting started",
    pages: [
      {
        id: "getting-started/vibe-trading-overview",
        title: "Vibe-Trading overview",
        description: "What Vibe-Trading is, where it fits, and what boundary it keeps.",
        lead: "Vibe-Trading is an open-source finance research workspace that turns natural-language prompts into market-data pulls, backtests, reports, and reusable research context.",
        sections: [
          {
            id: "what-it-is",
            title: "What it is",
            body: `
              <p>Vibe-Trading connects an agent loop to finance tools: data loaders, strategy generation, backtest engines, document readers, trade-journal analysis, persistent memory, and multi-agent research teams.</p>
              <p>The goal is not to replace judgment. The goal is to make every research step runnable, inspectable, and easy to repeat.</p>
            `
          },
          {
            id: "research-only",
            title: "Research only",
            body: `
              <p>Vibe-Trading does not execute live trades. It is designed for simulation, backtesting, audit trails, and research workflows. Outputs are not investment advice.</p>
            `
          },
          {
            id: "capabilities",
            title: "Core capabilities",
            body: `
              <ul>
                <li>Natural-language CLI and web workflows.</li>
                <li>Seven backtest engines across equities, crypto, futures, forex, composites, and options portfolios.</li>
                <li>Market data routing across Tushare, OKX, yfinance, AKShare, CCXT, and Futu.</li>
                <li>Trade Journal and Shadow Account workflows for behavior diagnostics.</li>
                <li>Swarm presets for committee-style research reviews.</li>
                <li>MCP tools for Claude Desktop, OpenClaw, Cursor, and other MCP clients.</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "getting-started/quick-start",
        title: "Quick start",
        description: "Install Vibe-Trading, initialize configuration, and run the first research task.",
        lead: "The fastest path is PyPI install, interactive setup, then either CLI research or the local web UI.",
        sections: [
          {
            id: "install",
            title: "Install",
            body: `
              <pre><code>pip install vibe-trading-ai
vibe-trading init
vibe-trading</code></pre>
            `
          },
          {
            id: "first-run",
            title: "First run",
            body: `
              <pre><code>vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"</code></pre>
            `
          },
          {
            id: "web-ui",
            title: "Open the web UI",
            body: `
              <pre><code>vibe-trading serve --port 8899</code></pre>
              <p>The local web UI is useful when you want uploaded files, streaming swarm progress, Settings, and generated artifacts in one place.</p>
            `
          }
        ]
      },
      {
        id: "getting-started/configuration",
        title: "Configuration",
        description: "Provider, model, market-data, and deployment settings.",
        lead: "Vibe-Trading keeps secrets and deployment-specific choices in environment variables or local Settings, not in source files.",
        sections: [
          {
            id: "env",
            title: "Environment file",
            body: `
              <pre><code>LANGCHAIN_PROVIDER=deepseek
LANGCHAIN_MODEL_NAME=deepseek-v4-pro
TUSHARE_TOKEN=your-token
TIMEOUT_SECONDS=2400</code></pre>
              <p>Run <code>vibe-trading init</code> to bootstrap the local configuration interactively.</p>
            `
          },
          {
            id: "keys",
            title: "Keys and data sources",
            body: `
              <p>Many HK, US, crypto, document, journal, and static analysis workflows work without paid market-data keys. A-share fundamental enrichment and some provider-specific workflows need their matching credentials.</p>
              <p>For non-local API or web deployments, configure <code>API_AUTH_KEY</code> and send requests with <code>Authorization: Bearer &lt;key&gt;</code>.</p>
            `
          },
          {
            id: "models",
            title: "Model choice",
            body: `
              <p>Agent quality depends on tool use. Prefer strong tool-calling models for long research runs, swarms, and multi-step backtests. Avoid small distilled models for workflows where fabricated answers are costly.</p>
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
        description: "How a Vibe-Trading run moves from prompt to evidence.",
        lead: "A good run routes the request, grounds it in data, executes tools, validates outputs, and leaves artifacts behind.",
        sections: [
          {
            id: "pipeline",
            title: "Pipeline",
            body: `
              <ol>
                <li><strong>Plan:</strong> choose relevant skills, tools, data sources, and swarm presets.</li>
                <li><strong>Ground:</strong> fetch market bars, documents, URLs, broker journals, or local files at runtime.</li>
                <li><strong>Execute:</strong> run backtests, factor analysis, options checks, exports, or report generation.</li>
                <li><strong>Validate:</strong> attach metrics, benchmark comparison, Monte Carlo, Bootstrap, Walk-Forward, warnings, and run cards when applicable.</li>
                <li><strong>Deliver:</strong> return the answer plus inspectable artifacts.</li>
              </ol>
            `
          },
          {
            id: "artifacts",
            title: "Artifacts",
            body: `
              <p>Backtests and research runs can produce reports, charts, generated strategy files, run metadata, and reusable context. The artifact trail matters because finance research often needs later inspection.</p>
            `
          }
        ]
      },
      {
        id: "core-concepts/backtesting",
        title: "Backtesting",
        description: "Market coverage, engines, metrics, and validation tools.",
        lead: "Vibe-Trading backtests daily and minute strategies across multiple asset classes, then keeps outputs auditable with metrics and run cards.",
        sections: [
          {
            id: "engines",
            title: "Engines",
            body: `
              <ul>
                <li>China A-share, global equity, crypto, China futures, global futures, forex, and composite engines.</li>
                <li>Options portfolio engine for option strategy research.</li>
                <li>Minute intervals including 1m, 5m, 15m, 30m, 1H, 4H, and 1D where supported by the data source.</li>
              </ul>
            `
          },
          {
            id: "validation",
            title: "Validation",
            body: `
              <p>Research runs can include benchmark comparison, Monte Carlo, Bootstrap confidence intervals, Walk-Forward validation, and run cards. Treat these as evidence helpers, not guarantees.</p>
            `
          },
          {
            id: "example",
            title: "Example",
            body: `
              <pre><code>vibe-trading run -p "Backtest an equal-weight SPY and BTC-USDT momentum rotation strategy for 2024 with benchmark comparison"</code></pre>
            `
          }
        ]
      },
      {
        id: "core-concepts/swarm-teams",
        title: "Swarm teams",
        description: "Preset research teams for committee-style analysis.",
        lead: "Swarm presets turn a research question into a small DAG of specialist workers, then stream progress and persist the final report.",
        sections: [
          {
            id: "presets",
            title: "Presets",
            body: `
              <p>Vibe-Trading includes 29 presets such as investment committee, quant strategy desk, crypto trading desk, macro rates and FX desk, and risk committee.</p>
              <pre><code>vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'</code></pre>
            `
          },
          {
            id: "keys",
            title: "Model requirements",
            body: `
              <p>Most MCP tools work without an LLM key after install. <code>run_swarm</code> needs an LLM provider because it spawns internal worker agents.</p>
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
        description: "How Vibe-Trading routes symbols and market data providers.",
        lead: "Data routing is provider-aware: mixed symbols can use <code>source=\"auto\"</code> while each market keeps its own data rules.",
        sections: [
          {
            id: "providers",
            title: "Providers",
            body: `
              <ul>
                <li>Tushare for China market and fundamental workflows when configured.</li>
                <li>OKX and CCXT for crypto symbols such as <code>BTC-USDT</code>.</li>
                <li>yfinance for global equities and common benchmarks.</li>
                <li>AKShare and Futu for additional China, Hong Kong, and market-specific coverage.</li>
              </ul>
            `
          },
          {
            id: "symbols",
            title: "Symbol conventions",
            body: `
              <p>Crypto pairs use uppercase hyphen format, for example <code>BTC-USDT</code>. Mixed-market research should prefer automatic source routing where possible.</p>
            `
          }
        ]
      },
      {
        id: "tools/shadow-account",
        title: "Shadow Account",
        description: "Turn a broker journal into behavior diagnostics and a counterfactual strategy path.",
        lead: "Shadow Account starts with your real trading records, extracts recurring rules, and compares actual trades with a rule-based shadow strategy.",
        sections: [
          {
            id: "flow",
            title: "Workflow",
            body: `
              <ol>
                <li>Read a broker export from supported formats or a generic CSV.</li>
                <li>Profile holding time, win rate, drawdown, PnL ratio, and behavior signals.</li>
                <li>Extract recurring if-then strategy rules.</li>
                <li>Run a shadow backtest and attribute delta-PnL.</li>
                <li>Render an HTML/PDF audit report.</li>
              </ol>
            `
          },
          {
            id: "example",
            title: "Example",
            body: `
              <pre><code>vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"</code></pre>
            `
          }
        ]
      },
      {
        id: "tools/finance-skills",
        title: "Finance skills",
        description: "Reusable finance knowledge modules loaded into research runs.",
        lead: "Skills keep domain knowledge close to the agent without hardcoding every behavior into the core loop.",
        sections: [
          {
            id: "library",
            title: "Library",
            body: `
              <p>Vibe-Trading bundles specialized skills across data sources, strategy generation, analysis, options, reporting, tools, and risk workflows.</p>
              <p>Good prompts can ask the agent to load or create skills for repeated research patterns.</p>
            `
          },
          {
            id: "examples",
            title: "Examples",
            body: `
              <ul>
                <li>Dividend analysis and yield-trap checks.</li>
                <li>A-share pre-ST risk screening.</li>
                <li>vn.py export and Pine Script export workflows.</li>
                <li>Factor research, macro analysis, and technical patterns.</li>
              </ul>
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
        description: "Common commands for local research, web UI, memory, swarms, and files.",
        lead: "The CLI is the fastest operator surface for repeatable research tasks.",
        sections: [
          {
            id: "commands",
            title: "Common commands",
            body: `
              <pre><code>vibe-trading
vibe-trading init
vibe-trading run -p "your research prompt"
vibe-trading --upload report.pdf
vibe-trading memory list
vibe-trading serve --port 8899
vibe-trading-mcp</code></pre>
            `
          },
          {
            id: "interactive",
            title: "Interactive mode",
            body: `
              <p>Interactive mode supports slash commands for recent runs, swarm presets, memory, and research navigation.</p>
            `
          }
        ]
      },
      {
        id: "reference/mcp-server",
        title: "MCP server",
        description: "Expose Vibe-Trading tools to MCP-compatible clients.",
        lead: "The MCP server runs as a stdio subprocess and exposes Vibe-Trading tools to agent clients.",
        sections: [
          {
            id: "start",
            title: "Start",
            body: `
              <pre><code>vibe-trading-mcp</code></pre>
            `
          },
          {
            id: "config",
            title: "Client config",
            body: `
              <pre><code>{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}</code></pre>
            `
          },
          {
            id: "tools",
            title: "Tool surface",
            body: `
              <p>The server exposes tools for skills, market data, backtesting, factor analysis, options, web/document reading, trade journals, Shadow Account, and swarm runs.</p>
            `
          }
        ]
      },
      {
        id: "reference/cloudflare-pages",
        title: "Cloudflare Pages",
        description: "Deploy this wiki without running a server.",
        lead: "The wiki is static. Cloudflare Pages can serve it directly from the repository.",
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
            `
          },
          {
            id: "why-static",
            title: "Why static",
            body: `
              <p>Docs, landing copy, redirects, theme state, and client-side search all work as static files. No VPS, database, or server process is required.</p>
            `
          }
        ]
      }
    ]
  }
];
