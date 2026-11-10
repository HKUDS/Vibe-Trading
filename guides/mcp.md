# MCP integration

## 🔌 MCP Plugin

Vibe-Trading exposes 83 MCP tools for any MCP-compatible client. Runs as a stdio subprocess — no server setup needed. Core research tools work with zero API keys for HK/US/crypto; trading connector tools use the selected connector profile, and `run_swarm` needs an LLM key.

**Environment variables:** the client spawns the server itself, so a shell `export` never reaches it — set them in the client's `env` block. Generated backtest code is sandboxed to the allowed run roots, so writing results into a workspace of your own needs `VIBE_TRADING_ALLOWED_RUN_ROOTS`:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp",
      "env": { "VIBE_TRADING_ALLOWED_RUN_ROOTS": "C:\\Users\\me\\research" }
    }
  }
}
```

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

**MCP tools exposed (83):** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `update_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `alpha_zoo`, `alpha_bench`, `analyze_options`, `analyze_options_payoff`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `read_run_artifact`, `list_backtest_runs`, `list_strategies`, `query_strategies`, `get_strategy_evidence`, `refresh_strategy_evidence`, `adapt_strategy`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_southbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `get_institutional_holdings`, `etf_holdings`, `prediction_market`, `research_papers`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `quantlib_call`, `cashflow_performance`, `orderbook_depth`, `sentiment`, `technical_indicators`, `get_fundamentals`, `get_fund_nav`, `get_cn_macro_series`, `get_cn_announcements`, `search_broker_reports`, `paper_trade_step`, `paper_trade_reconcile`, `research_lab`.

`web_search` tries its existing Sogou and Bing China fallbacks when ddgs returns
no results or fails. Set `VIBE_TRADING_SEARCH_BING_FALLBACK=0` to disable both.
This chain returns an empty result only when its enabled sources finish without
an unresolved error; an unavailable source produces an actionable error if no
other source returns results.

To try [Parallel's hosted search MCP](https://docs.parallel.ai/integrations/mcp/quickstart)
inside `web_search`, set `VIBE_TRADING_SEARCH_PARALLEL=1`. This is off by default.
When enabled, searches try IQS first if `ALIYUN_IQS_API_KEY` is set, then Parallel,
then the existing ddgs and regional fallbacks. Parallel receives the search query;
no account or API key is required. Anonymous searches use Fast mode at lower rate
limits intended for personal agents and exploration. Initialisation and tool-call
timeouts are 5 and 10 seconds respectively, with no retry; these are not an overall
time limit. Errors, invalid responses, and empty results fall through to the
existing sources. Results keep
the same title, URL, snippet, and security-warning format; Parallel snippets are
capped at 300 characters. Unset `VIBE_TRADING_SEARCH_PARALLEL` or set it to `0`
to restore the existing search path. `VIBE_TRADING_SEARCH_BACKENDS` still controls
only the ddgs engine list.

`quantlib_call` attribution requires finite sector weights and returns, finite Carino return inputs, and a finite non-negative weight-sum tolerance. Invalid data is rejected explicitly rather than returned as an attribution result containing `NaN`. Missing returns for a zero-weight sector may still be inferred from the other side.

`quantlib_call` maximum-drawdown analysis measures underwater duration from the latest visit to the peak before the worst trough. An earlier drawdown that already recovered is excluded from that duration.

`quantlib_call` VaR backtests count finite return/forecast pairs for coverage. Missing pairs break the consecutive-observation chain for independence testing; they never create a transition between the observations on either side of a gap.

`quantlib_call` option analytics use an absolute **price** tolerance for implied-volatility inversion. A finite result must reprice the quote within that tolerance; the underlying analytics function returns `NaN` for an unconverged or volatility-unidentifiable quote rather than an asserted volatility.

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

All 89 finance skills are published on [open-space.cloud](https://open-space.cloud) and evolve autonomously through OpenSpace's self-evolution engine.

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

OpenSpace will auto-discover all 89 skills, enabling auto-fix, auto-improve, and community sharing. Search for Vibe-Trading skills via `search_skills("finance backtest")` in any OpenSpace-connected agent.

</details>

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
      "url": "https://api.ibkr.com/v1/api/mcp-public",
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

`research_lab` shares the Web and CLI experiment service: frozen-input execution-cost scenarios, training-only parameter selection with sealed OOS/holdout execution, factor-history audits and deterministic task replay. Use `catalog` first; see [Research Lab](research-lab.md).
