# Installation and providers

## Installation details

For an installed PyPI copy, `vibe-trading update` upgrades the package. Editable and version-control installations receive instructions for updating their checkout. To start just the HTTP API, run `vibe-trading serve --port 8899`.

If an upgrade from a pre-0.1.10 install fails on a LangChain or LangGraph import, recreate the virtual environment or run `pip install --force-reinstall vibe-trading-ai`.

### Prerequisites

- An **LLM API key** from any supported provider — or run locally with **Ollama** (no key needed)
- **Python 3.11+** for Path B
- **Docker** for Path A
- OpenAI Codex can also be used with ChatGPT OAuth: set `LANGCHAIN_PROVIDER=openai-codex`, then run `vibe-trading provider login openai-codex`. This does not use `OPENAI_API_KEY`.
  In Web Settings, the Codex model picker discovers available models and reasoning levels from the authenticated ChatGPT session. If discovery is unavailable, the default model and manual model entry remain available.
- GitHub Copilot can be used with an active Copilot subscription instead of a separately billed LLM API key. See [GitHub Copilot SDK provider](#github-copilot-sdk-provider).
- A local Claude Code login can drive the agent without an API key. See [Claude Code CLI provider](#claude-code-cli-provider).

> **Supported LLM providers:** OpenRouter, OpenAI, Anthropic (native Messages API), DeepSeek, OpenCode (Go / Zen), Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, SiliconFlow (CN + Global), Xiaomi MIMO, Novita AI, iFlytek Spark, Z.ai, NVIDIA NIM, ModelScope, GitHub Copilot, Claude Code CLI, Ollama (local). When no `*_BASE_URL` is set, each provider falls back to its canonical endpoint, so just a key is enough. See `.env.example` for config.

MiniMax onboarding defaults to `MiniMax-M3.1-Flash`, with `MiniMax-M3` as the alternative in Settings. Both the global and China API endpoints are supported. Saved model IDs and custom endpoints remain editable; official MiniMax endpoints suggest the current pair, while gateways retain every discovered route, including paid variants. MiniMax uses the API's default thinking depth, and Flash's reasoning is preserved across tool turns.

> **Market data:** Public sources cover many common requests, including A-shares via Tencent, US and HK equities via Yahoo, and crypto via OKX. For futures, AKShare supplies supported Chinese contracts. Supply local bars for global contracts. Check the [data-source table](capabilities.md#-data-sources--smart-fallback) for credentials and coverage.

### Custom model endpoints

Settings → Custom OpenAI-compatible providers tests a chat-completions endpoint,
saves its API key in the OS credential vault (`pip install "vibe-trading-ai[keyring]"`),
and activates it for new runs. Testing sends a short model request and may incur
the provider's normal API charge. Active profiles are immutable; save a changed
endpoint under a new ID and activate it after testing. Switch back through the
normal model provider selector. Keys are never stored in the profile JSON.

The same flow is available from `vibe-trading provider custom list`,
`vibe-trading provider custom add --id example --label Example --base-url https://api.example.com/v1 --model example-model`
(the key is prompted privately), and `vibe-trading provider custom activate example`.
The configured provider is used by CLI, API, Web, and agent runs alike.

### GitHub Copilot SDK provider

The official GitHub Copilot SDK ships as an optional extra, so install it alongside Vibe-Trading with `pip install "vibe-trading-ai[copilot]"`; installing the Copilot CLI is optional. Authenticate with any one of these supported methods:

```bash
gh auth login                         # use GitHub CLI credentials
# or run `copilot` and sign in         # stores credentials in the OS keychain
# or export COPILOT_GITHUB_TOKEN=gho_xxx
```

Then configure `agent/.env`:

```dotenv
LANGCHAIN_PROVIDER=copilot
LANGCHAIN_MODEL_NAME=claude-sonnet-5
# COPILOT_GITHUB_TOKEN=gho_xxx         # optional; recommended for Docker/CI
```

Start Vibe-Trading normally. Its preflight reports whether the SDK can authenticate:

```bash
vibe-trading
```

Authentication priority is `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, stored Copilot CLI credentials, then `gh` credentials. Vibe-Trading does not copy or persist SDK credentials. Host keychain credentials are not automatically available inside Docker, so containers should receive `COPILOT_GITHUB_TOKEN`.

### Claude Code CLI provider

The `claude-cli` provider uses the [Claude Code](https://claude.com/claude-code) CLI you already have installed and logged in. Each agent step runs one headless `claude -p` process that only chooses the next step — call these tools, or give the final answer. Vibe-Trading runs the tools itself, so the evidence ledger, grounding checks and swarm deliverable checks behave exactly as with an API provider. It does not read `ANTHROPIC_API_KEY`. Native CLI tools stay disabled. If the model tries one, Vibe-Trading feeds the refusal back and asks for a host tool call instead of accepting a claim that the tools are unavailable.

Log in once with Claude Code, then check that Vibe-Trading can see the login:

```bash
claude auth login
vibe-trading provider login claude-cli   # reports the login; it does not start a new one
```

Then configure `agent/.env`:

```dotenv
LANGCHAIN_PROVIDER=claude-cli
LANGCHAIN_MODEL_NAME=claude-opus-5-5
# LANGCHAIN_REASONING_EFFORT=high                   # low|medium|high|xhigh|max; passed as --effort
# CLAUDE_CLI_PATH=/opt/homebrew/bin/claude          # when `claude` is not on PATH or in ~/.local/bin
# VIBE_TRADING_DENY_TOOL_PREFIXES=trading_,etoro_  # any provider; empty offers every tool
# VIBE_TRADING_BASH_POLICY=python-only             # any provider, or `off`
# CLAUDE_CLI_DENY_TOOL_PREFIXES=trading_,etoro_     # legacy alias when the generic name is unset
# CLAUDE_CLI_BASH_POLICY=python-only                # legacy alias when the generic name is unset
```

- `VIBE_TRADING_DENY_TOOL_PREFIXES` hides tools whose names start with these prefixes from every provider. An explicitly configured `CLAUDE_CLI_DENY_TOOL_PREFIXES` remains the fallback alias across providers. With neither configured, other providers retain their existing tool surface; Claude CLI retains its previous `trading_,etoro_` default (including broker reads).
- `VIBE_TRADING_BASH_POLICY=python-only` applies the same rule to every provider: `bash` may run only `python <relative script>.py`, `python -c ...`, and read-only `ls`/`cat`/`head`/`tail`/`wc`/`pwd` on non-hidden relative paths (so not `.env`); refused calls are returned to the model so it can choose again. `CLAUDE_CLI_BASH_POLICY` remains the fallback alias. `vibe-trading provider doctor` reports the active policy and which variable supplied it.

> **Warning:** Both settings are convenience filters, not a security boundary. `python -c` can still run arbitrary code, and external MCP tools (`mcp_<server>_<tool>`) are not covered by the default prefixes. Live orders stay bound by the mandate gate and kill switch whatever these settings allow.

> **Note:** When Settings shows this provider, it loads the models your Claude Code login can run (cached for 5 minutes; **Load models** refreshes), and the reasoning effort menu offers only the levels the selected model accepts. The chosen level is passed to each `claude -p` call as `--effort`; it does not read or change `~/.claude/settings.json`, and "Provider default" means the model's own default. Base URL, temperature and `MAX_RETRIES` have no effect with this provider, and `TIMEOUT_SECONDS` is raised to at least 600 seconds per decision. Image input is not supported. The CLI returns each decision in one piece; while it runs, provider waiting events keep the Web UI active. Transport keepalives alone do not suppress `VIBE_TRADING_SSE_TIMEOUT` (default 90 seconds), and cancellation and the per-decision deadline remain enforced.

### Path A: Docker (zero setup)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

Open `http://localhost:8899`. Backend + frontend in one container.

> [!NOTE]
> **OpenAI Codex OAuth with Docker:** the browser login needs a terminal so you
> can paste the callback URL. Run it through Compose, which allocates an
> interactive terminal automatically:
>
> ```bash
> docker compose exec vibe-trading vibe-trading provider login openai-codex
> ```
>
> If you use `docker exec` directly, pass `-it` before the container name.

Docker publishes the backend on `127.0.0.1:8899` by default and runs the app as a non-root container user. If you intentionally expose the API beyond your own machine, set a strong `API_AUTH_KEY` and send `Authorization: Bearer <key>` from clients.

> [!NOTE]
> **Using Ollama with Docker:** the container reaches a host-side Ollama via `host.docker.internal`, not `localhost` (inside the container `localhost` is the container itself). `docker-compose.yml` defaults `OLLAMA_BASE_URL` to `http://host.docker.internal:11434`; export `OLLAMA_BASE_URL` (or set it in a top-level `.env`) to point elsewhere. This relies on the `host-gateway` mapping in `extra_hosts`, which requires **Docker Engine ≥ 20.10 / Compose v2** (provided automatically on Docker Desktop).

Your data survives updates: persistent memory, the cross-session search index, user-created skills, shadow accounts, broker connector config, web sessions, backtest runs, swarm history, and uploads all live in named Docker volumes, so `git pull && docker compose up --build` keeps them. In-progress Web replies are checkpointed too, so a restart restores the partial response and marks the attempt interrupted instead of silently dropping it. Data is deleted only by `docker compose down -v`.

### Path B: Local install

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate.bat       # Windows CMD
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

> [!NOTE]
> **On Windows:** `cp` is a PowerShell alias for `Copy-Item`, so the snippets above work as-is in PowerShell. CMD has no `cp` — use `copy agent\.env.example agent\.env` instead (this applies to the Docker snippet above too). If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first; it applies to that shell session only.

<details>
<summary><b>Start web UI (optional)</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev  # requires Node >= 22.22
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

See [MCP Plugin](mcp.md#-mcp-plugin) section below.

### Path D: ClawHub (one command)

```bash
npx clawhub@latest install vibe-trading --force
```

The skill + MCP config is downloaded into your agent's skills directory. See [ClawHub install](mcp.md#-mcp-plugin) for details.

---

## 🧠 Environment Variables

Copy `agent/.env.example` to `agent/.env` and uncomment the provider block you want. Each provider needs 3-4 variables:

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Yes | Provider name (`openrouter`, `deepseek`, `groq`, `ollama`, etc.) |
| `<PROVIDER>_API_KEY` | Yes* | API key (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, etc.) |
| `<PROVIDER>_BASE_URL` | Yes* | API endpoint URL |
| `LANGCHAIN_MODEL_NAME` | Yes | Model name (e.g. `deepseek-v4-pro`) |
| `LANGCHAIN_REASONING_EFFORT` | No | Reasoning effort (`none`, `low`, `medium`, `high`, or `max`; `claude-cli` takes `low` through `max` plus `xhigh`, and no `none`) |
| `LANGCHAIN_USE_RESPONSES_API` | No | Responses transport override: literal `true` uses `/v1/responses` when the endpoint supports it; native adapters retain their own transport; all other values use Chat Completions |
| `TUSHARE_TOKEN` | No | Tushare Pro token for A-share data (falls back to AKShare) |
| `TIMEOUT_SECONDS` | No | LLM call timeout, default 120s |
| `CLAUDE_CLI_PATH` | No | `claude` executable for the `claude-cli` provider when it is not on PATH or in `~/.local/bin` |
| `VIBE_TRADING_DENY_TOOL_PREFIXES` | No | Explicit tool-name filter across every provider; empty offers every tool; unconfigured retains prior provider defaults |
| `VIBE_TRADING_BASH_POLICY` | No | Explicit `python-only` or `off` across providers; unconfigured retains prior defaults (`python-only` for Claude CLI, `off` otherwise) |
| `CLAUDE_CLI_DENY_TOOL_PREFIXES` | No | Legacy alias for `VIBE_TRADING_DENY_TOOL_PREFIXES`, used when the generic name is unset |
| `CLAUDE_CLI_BASH_POLICY` | No | Legacy alias for `VIBE_TRADING_BASH_POLICY`, used when the generic name is unset |
| `API_AUTH_KEY` | Recommended for network deployments | Bearer token required when the API is reachable from non-local clients |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | No | Explicit opt-in for shell-capable tools in remote API/MCP-SSE style deployments |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | No | Extra comma-separated roots for document and broker-journal imports |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | No | Extra comma-separated roots for generated-code run directories |
| `VIBE_TRADING_ALLOWED_WRITE_ROOTS` | No | Extra comma-separated roots the agent may write or edit (e.g. `~/Documents` for report exports) |
| `VIBE_TW_STOCK_DB` | No | Path to a Taiwan-market SQLite snapshot; the read-only `taiwan_stock_data` tool registers only when it is schema-valid |
| `VIBE_TRADING_EXTRA_CORS_ORIGINS` | No | Comma-separated origins **added** to the loopback CORS defaults (`CORS_ORIGINS` replaces them instead) |
| `CONTENT_FILTER_WARNING_THRESHOLD` | No | Content-filter warning ratio threshold (default 0.05 = 5%). When the ratio of LLM responses blocked by content moderation exceeds this, the run card warns you to switch providers. |

<sub>* Ollama does not require an API key. OpenAI Codex uses ChatGPT OAuth and stores tokens via `oauth-cli-kit`, not in `agent/.env`. GitHub Copilot authentication is handled by the official SDK. Claude Code CLI uses the local `claude` login and needs no API key or base URL.</sub>

**Free data (no key needed):** A-shares via AKShare, HK/US/Canada/UK equities via Yahoo/yfinance, crypto via OKX, 100+ crypto exchanges via CCXT. The system automatically selects the best available source for each market.

**PDF reports:** Ask the agent to save a report as PDF. `write_file` renders a
`.pdf` target from Markdown/text with an embedded font; it does not need system
Pango/Cairo or a font download. The Web chat provides an authenticated download
link, and IM channels that support files receive the PDF as an attachment.
External folders must be listed in `VIBE_TRADING_ALLOWED_WRITE_ROOTS`. Successful
writes return the resolved path and byte count; a rejected path does not forbid
other allowed folders. Generated downloads are staged under
`~/.vibe-trading/generated_reports/` (or `VIBE_TRADING_HOME/generated_reports/`).

### 🎯 Recommended Models

Vibe-Trading is a tool-heavy agent — skills, backtests, memory, and swarms all flow through tool calls. Model choice directly decides whether the agent *uses* its tools or fabricates answers from training data.

| Tier | Examples | When to use |
|------|----------|-------------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | Complex swarms (3+ agents), long research sessions, paper-grade analysis |
| **Sweet spot** (default) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | Daily driver — reliable tool-calling at ~1/10 the cost |
| **Avoid for agent use** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | Tool-calling is unreliable — the agent will appear to "answer from memory" instead of loading skills or running backtests |

The default `agent/.env.example` uses OpenRouter + `deepseek/deepseek-v4-pro`; for the DeepSeek official API, select `LANGCHAIN_PROVIDER=deepseek` and `deepseek-v4-pro`.
