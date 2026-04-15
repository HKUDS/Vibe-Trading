<p align="center">
  <a href="README.md">English</a> | <b>中文</b> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading：你的个人交易代理</h1>

<p align="center">
  <b>一条命令，为你的代理赋予全栈交易能力</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <img src="https://img.shields.io/badge/Skills-69-orange" alt="Skills">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="Swarm">
  <img src="https://img.shields.io/badge/Tools-21-0F766E" alt="Tools">
  <img src="https://img.shields.io/badge/Data_Sources-5-2563EB" alt="Data Sources">
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#-核心功能">核心功能</a> &nbsp;&middot;&nbsp;
  <a href="#-演示">演示</a> &nbsp;&middot;&nbsp;
  <a href="#-vibe-trading-是什么">产品介绍</a> &nbsp;&middot;&nbsp;
  <a href="#-快速开始">快速开始</a> &nbsp;&middot;&nbsp;
  <a href="#-cli-参考">CLI</a> &nbsp;&middot;&nbsp;
  <a href="#-api-服务">API</a> &nbsp;&middot;&nbsp;
  <a href="#-mcp-插件">MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-项目结构">项目结构</a> &nbsp;&middot;&nbsp;
  <a href="#-路线图">路线图</a> &nbsp;&middot;&nbsp;
  <a href="#贡献指南">贡献</a> &nbsp;&middot;&nbsp;
  <a href="#贡献者">贡献者</a>
</p>

<p align="center">
  <a href="#-快速开始"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 新闻

- **2026-04-13** 🌐 **跨市场复合回测**：新增 `CompositeEngine`，支持在同一次回测中混合不同市场的标的（如 A 股 + 加密货币），共享资金池，各市场规则（T+1、资金费率、掉期）按标的独立执行，信号按各自交易日历对齐。使用 `source: "auto"` 配合混合代码如 `["000001.SZ", "BTC-USDT"]` 即可。包含波动率加权策略技能和日历日年化计算。
- **2026-04-12** 🌍 **多平台指标导出**：`/pine` 命令现在一次性导出 **TradingView (Pine Script v6)**、**通达信/同花顺/东方财富 (TDX 公式)** 和 **MetaTrader 5 (MQL5)** 三个平台的指标代码 — 覆盖国际股票、中国 A 股和全球外汇/CFD 市场。一条命令，三大平台。
- **2026-04-11** 🛡️ **可靠性与开发体验**：`vibe-trading init` 交互式 .env 引导（[#19](https://github.com/HKUDS/Vibe-Trading/pull/19)），启动预检 LLM 与数据源连通性，主数据源返空时自动回退，回测引擎数据校验与错误隔离加固，Agent 与 Swarm 提示词注入当前日期时间。社区 PR [#21](https://github.com/HKUDS/Vibe-Trading/pull/21) 贡献多语言 README（zh/ja/ko）。
- **2026-04-10** 📦 **v0.1.4**：修复 Docker 构建（[#8](https://github.com/HKUDS/Vibe-Trading/issues/8)），新增 `web_search` MCP 工具（共 17 个），在依赖与 MCP 中加入 `akshare`/`ccxt`。支持 11 家 LLM 提供商（DeepSeek、Groq、Gemini、Ollama 等），全部调优参数可通过 `.env` 配置。加固 `ml-strategy` 技能。已发布至 PyPI 和 ClawHub。
- **2026-04-09** 📊 **回测 Wave 2 —— 多资产引擎**：新增 ChinaFutures（CFFEX/SHFE/DCE/ZCE，50+ 合约）、GlobalFutures（CME/ICE/Eurex，30+ 合约）、Forex（24 货币对，点差 + 掉期）、Options v2（美式行权、IV 微笑）。统计验证：蒙特卡洛置换检验、Bootstrap 夏普区间、Walk-Forward 分析。
- **2026-04-08** 🔧 **多市场回测** 支持分市场规则；**TradingView Pine Script v6 导出**。**数据源扩展**：5 源自动回退，`web_search` 工具，技能分 7 类。
- **2026-04-01** 🚀 **v0.1.0** —— 初始发布：ReAct 代理，64 技能，29 个 swarm 预设，跨市场回测，CLI + Web UI + MCP 服务器。

---

## 💡 Vibe-Trading 是什么？

Vibe-Trading 是一个由 AI 驱动的多代理金融工作台，将自然语言请求转化为可执行的交易策略、研究洞见和跨全球市场的投资组合分析。

### 核心能力：
• **Strategy Generation** —— 从你的想法自动生成交易代码<br>
• **Smart Data Access** —— 5 大数据源自动回退；所有市场零配置<br>
• **Performance Testing** —— 使用历史行情测试你的策略<br>
• **Multi-Platform Export** —— 一键导出到 TradingView、通达信/同花顺/东方财富 和 MT5<br>
• **Expert Teams** —— 部署专职 AI 代理处理复杂研究任务<br>
• **Live Updates** —— 全程实时查看分析过程

---

## ✨ 核心功能

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="Research"/><br>
      <h3>🔍 面向交易的深度研究</h3>
      <img src="https://img.shields.io/badge/69_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="Skills" /><br><br>
      <div align="left" style="font-size: 4px;">
        • 覆盖多市场的多领域分析<br>
        • 自动生成策略与信号<br>
        • 宏观经济研究与洞察<br>
        • 基于聊天的自然语言任务路由
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="Swarm"/><br>
      <h3>🐝 群体智能</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="Swarm" /><br><br>
      <div align="left">
        • 29 个开箱即用的交易团队预设<br>
        • 基于 DAG 的多代理编排<br>
        • 实时决策流式仪表盘<br>
        • 通过 YAML 自定义团队
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-backtest.png" height="150" alt="Backtest"/><br>
      <h3>📊 跨市场回测</h3>
      <img src="https://img.shields.io/badge/5_Data_Sources-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="Backtest" /><br><br>
      <div align="left">
        • A 股、港美股、加密、期货与外汇<br>
        • 7 个市场引擎 + 跨市场复合引擎（共享资金池）<br>
        • 统计验证：蒙特卡洛、Bootstrap 置信区间、Walk-Forward<br>
        • 15+ 绩效指标与 4 种优化器
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-quant.png" height="150" alt="Quant"/><br>
      <h3>🧮 量化分析工具箱</h3>
      <img src="https://img.shields.io/badge/Quant_Tools-C77DFF?style=for-the-badge&logo=wolfram&logoColor=white" alt="Quant" /><br><br>
      <div align="left">
        • 因子 IC/IR 分析与分位回测<br>
        • Black-Scholes 定价与全套 Greeks 计算<br>
        • 技术形态识别与检测<br>
        • 投资组合优化：MVO/风险平价/BL
      </div>
    </td>
  </tr>
</table>

## 7 大类别中的 69 个技能

- 📊 69 个金融专长技能，划分 7 大类
- 🌐 覆盖传统市场到加密与 DeFi
- 🔬 覆盖数据获取到量化研究的全链路能力

| Category | Skills | Examples |
|----------|--------|----------|
| Data Source | 6 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `ccxt` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 15 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 8 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader` |

## 29 个 Agent Swarm 团队预设

- 🏢 29 组可即用的代理团队
- ⚡ 预配置的金融工作流
- 🎯 投资、交易与风险管理场景预设

| Preset | Workflow |
|--------|----------|
| `investment_committee` | 多空辩论 → 风险复核 → PM 最终决策 |
| `global_equities_desk` | A 股 + 港美股 + 加密研究员 → 全球策略师 |
| `crypto_trading_desk` | 资金费/基差 + 清算 + 资金流 → 风险经理 |
| `earnings_research_desk` | 基本面 + 修正 + 期权 → 财报策略师 |
| `macro_rates_fx_desk` | 利率 + 外汇 + 商品 → 宏观 PM |
| `quant_strategy_desk` | 筛选 + 因子研究 → 回测 → 风险审计 |
| `technical_analysis_panel` | 经典 TA + 一目均衡 + 谐波 + 艾略特 + SMC → 共识 |
| `risk_committee` | 回撤 + 尾部风险 + Regime 评审 → 签核 |
| `global_allocation_committee` | A 股 + 加密 + 港美股 → 跨市场配置 |

<sub>另有 20+ 专项预设 —— 运行 vibe-trading --swarm-presets 查看全部。</sub>

### 🎬 演示

<div align="center">
<table>
<tr>
<td width="50%">

https://github.com/user-attachments/assets/4e4dcb80-7358-4b9a-92f0-1e29612e6e86

</td>
<td width="50%">

https://github.com/user-attachments/assets/3754a414-c3ee-464f-b1e8-78e1a74fbd30

</td>
</tr>
<tr>
<td colspan="2" align="center"><sub>☝️ 自然语言回测与多代理 swarm 辩论 —— Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 快速开始

### 一行安装（PyPI）

```bash
pip install vibe-trading-ai
```

> **包名与命令：** PyPI 包名是 `vibe-trading-ai`。安装后会获得三个命令：
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | 交互式 CLI / TUI |
> | `vibe-trading serve` | 启动 FastAPI Web 服务器 |
> | `vibe-trading-mcp` | 启动 MCP 服务器（Claude Desktop、OpenClaw、Cursor 等） |

```bash
vibe-trading init              # 交互式 .env 配置
vibe-trading                   # 启动 CLI
vibe-trading serve --port 8899 # 启动 Web UI
vibe-trading-mcp               # 启动 MCP 服务器（stdio）
```

### 或选择一条路径

| Path | Best for | Time |
|------|----------|------|
| **A. Docker** | 立即体验，零本地配置 | 2 min |
| **B. Local install** | 开发、完整 CLI 访问 | 5 min |
| **C. MCP plugin** | 接入你现有的代理 | 3 min |
| **D. ClawHub** | 一条命令，无需克隆 | 1 min |

### 前置条件

- 任一支持提供商的 **LLM API key**——或使用 **Ollama** 本地运行（无需 key）
- Path B 需 **Python 3.11+**
- Path A 需 **Docker**

> **支持的 LLM 提供商：** OpenRouter、OpenAI、DeepSeek、Gemini、Groq、DashScope/Qwen、智谱、Moonshot/Kimi、MiniMax、小米 MIMO、Z.ai、Ollama（本地）。参见 `.env.example` 配置。

> **提示：** 所有市场都可在无 API key 情况下运行，因自动回退。yfinance（港美股）、OKX（加密）、AKShare（A 股、美股、港股、期货、外汇）均免费。Tushare token 可选——A 股可回退到 AKShare 免费获取。

### Path A: Docker（零配置）

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# 编辑 agent/.env —— 取消注释你的 LLM 提供商并填写 API key
docker compose up --build
```

打开 `http://localhost:8899`。后端与前端同一容器。

### Path B: 本地安装

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# 激活
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # 编辑 —— 设置你的 LLM 提供商 API key
vibe-trading                       # 启动交互式 TUI
```

<details>
<summary><b>启动 Web UI（可选）</b></summary>

```bash
# 终端 1：API 服务器
vibe-trading serve --port 8899

# 终端 2：前端开发服务器
cd frontend && npm install && npm run dev
```

打开 `http://localhost:5899`。前端会代理到 `localhost:8899`。

**生产模式（单服务器）：**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI 同时提供 dist/ 静态文件
```

</details>

### Path C: MCP 插件

见下方 [MCP 插件](#-mcp-插件) 章节。

### Path D: ClawHub（一条命令）

```bash
npx clawhub@latest install vibe-trading --force
```

技能与 MCP 配置会下载到你代理的技能目录。详情见 [ClawHub 安装](#-mcp-插件)。

---

## 🧠 环境变量

复制 `agent/.env.example` 到 `agent/.env`，取消注释你需要的提供商块。每个提供商需 3-4 个变量：

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Yes | 提供商名称（`openrouter`、`deepseek`、`groq`、`z.ai`、`ollama` 等） |
| `<PROVIDER>_API_KEY` | Yes* | API key（`OPENROUTER_API_KEY`、`DEEPSEEK_API_KEY` 等） |
| `<PROVIDER>_BASE_URL` | Yes | API 端点 URL |
| `LANGCHAIN_MODEL_NAME` | Yes | 模型名（如 `deepseek/deepseek-v3.2`） |
| `TUSHARE_TOKEN` | No | A 股数据的 Tushare Pro token（可回退 AKShare） |
| `TIMEOUT_SECONDS` | No | LLM 调用超时，默认 120s |

<sub>* Ollama 不需要 API key。</sub>

**免费数据（无需 key）：** A 股经 AKShare，港美股经 yfinance，加密经 OKX，100+ 加密交易所经 CCXT。系统会为每个市场自动选择最佳可用数据源。

---

## 🖥 CLI 参考

```bash
vibe-trading               # 交互式 TUI
vibe-trading run -p "..."  # 单次运行
vibe-trading serve         # API 服务器
```

<details>
<summary><b>TUI 内斜杠命令</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | 显示全部命令 |
| `/skills` | 列出 69 个金融技能 |
| `/swarm` | 列出 29 个 swarm 团队预设 |
| `/swarm run <preset> [vars_json]` | 以流式输出运行一个 swarm 团队 |
| `/swarm list` | Swarm 运行历史 |
| `/swarm show <run_id>` | Swarm 运行详情 |
| `/swarm cancel <run_id>` | 取消运行中的 swarm |
| `/list` | 最近的运行 |
| `/show <run_id>` | 运行详情与指标 |
| `/code <run_id>` | 生成的策略代码 |
| `/pine <run_id>` | 导出指标代码（TradingView + TDX + MT5）|
| `/trace <run_id>` | 完整执行回放 |
| `/continue <run_id> <prompt>` | 带新指令继续运行 |
| `/sessions` | 列出聊天会话 |
| `/settings` | 显示运行时配置 |
| `/clear` | 清屏 |
| `/quit` | 退出 |
</details>

<details>
<summary><b>单次运行与参数</b></summary>

```bash
vibe-trading run -p "Backtest BTC-USDT MACD strategy, last 30 days"
vibe-trading run -p "Analyze AAPL momentum" --json
vibe-trading run -f strategy.txt
echo "Backtest 000001.SZ RSI" | vibe-trading run
```

```bash
vibe-trading -p "your prompt"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # 导出指标代码（TradingView + TDX + MT5）
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

</details>

---

## 🌐 API 服务

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | 列出运行 |
| `GET` | `/runs/{run_id}` | 运行详情 |
| `GET` | `/runs/{run_id}/pine` | 多平台指标导出 |
| `POST` | `/sessions` | 创建会话 |
| `POST` | `/sessions/{id}/messages` | 发送消息 |
| `GET` | `/sessions/{id}/events` | SSE 事件流 |
| `POST` | `/upload` | 上传 PDF/文件 |
| `GET` | `/swarm/presets` | 列出 swarm 预设 |
| `POST` | `/swarm/runs` | 启动 swarm 运行 |
| `GET` | `/swarm/runs/{id}/events` | Swarm SSE 流 |

交互式文档：`http://localhost:8899/docs`

---

## 🔌 MCP 插件

Vibe-Trading 为任意 MCP 兼容客户端提供 17 个 MCP 工具。以 stdio 子进程运行——无需服务器部署。**17 个工具中有 16 个无需任何 API key**（港美股/加密）。仅 `run_swarm` 需要 LLM key。

<details>
<summary><b>Claude Desktop</b></summary>

添加到 `claude_desktop_config.json`：

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

添加到 `~/.openclaw/config.yaml`：

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

</details>

<details>
<summary><b>Cursor / Windsurf / 其他 MCP 客户端</b></summary>

```bash
vibe-trading-mcp                  # stdio（默认）
vibe-trading-mcp --transport sse  # 供 Web 客户端的 SSE
```

</details>

**已暴露的 MCP 工具（17）：** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`。

<details>
<summary><b>ClawHub 一键安装</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> 需要 `--force`，因为该技能引用外部 API，会触发 VirusTotal 自动扫描。代码完全开源，可自行审阅。

这会将技能与 MCP 配置下载到你的代理技能目录。无需克隆。

浏览 ClawHub： [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — 自进化技能</b></summary>

全部 69 个金融技能已发布在 [open-space.cloud](https://open-space.cloud)，并通过 OpenSpace 的自进化引擎自动演进。

要在 OpenSpace 中使用，在代理配置中添加两个 MCP 服务器：

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

OpenSpace 会自动发现全部 69 个技能，支持自动修复、自动改进与社区共享。在任意连接 OpenSpace 的代理中通过 `search_skills("finance backtest")` 搜索 Vibe-Trading 技能。

</details>

---

## 📁 项目结构

<details>
<summary><b>展开查看</b></summary>

```
Vibe-Trading/
├── agent/                          # 后端（Python）
│   ├── cli.py                      # CLI 入口——交互式 TUI + 子命令
│   ├── api_server.py               # FastAPI 服务器——运行、会话、上传、swarm、SSE
│   ├── mcp_server.py               # MCP 服务器——为 OpenClaw / Claude Desktop 提供 17 个工具
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct 代理核心
│   │   │   ├── loop.py             #   主推理循环
│   │   │   ├── skills.py           #   技能加载器（69 个 SKILL.md，7 类）
│   │   │   ├── tools.py            #   工具编排
│   │   │   ├── context.py          #   系统提示构建器
│   │   │   ├── memory.py           #   运行记忆 / artifact 存储
│   │   │   └── trace.py            #   执行轨迹写入
│   │   │
│   │   ├── tools/                  # 21 个代理工具
│   │   │   ├── backtest_tool.py    #   运行回测
│   │   │   ├── factor_analysis_tool.py
│   │   │   ├── options_pricing_tool.py
│   │   │   ├── pattern_tool.py     #   图表形态检测
│   │   │   ├── doc_reader_tool.py  #   PDF 阅读（OCR 回退）
│   │   │   ├── web_reader_tool.py  #   网页读取（Jina）
│   │   │   ├── web_search_tool.py  #   DuckDuckGo 搜索
│   │   │   ├── swarm_tool.py       #   启动 swarm 团队
│   │   │   └── ...                 #   文件 I/O、bash、任务等
│   │   │
│   │   ├── skills/                 # 69 个金融技能（7 类，每个 SKILL.md）
│   │   ├── swarm/                  # Swarm DAG 执行引擎
│   │   ├── session/                # 多轮对话管理
│   │   └── providers/              # LLM 提供商抽象
│   │
│   ├── backtest/                   # 回测引擎
│   │   ├── engines/                #   7 个引擎 + 跨市场复合引擎 + options_portfolio
│   │   ├── loaders/                #   5 个数据源：tushare、okx、yfinance、akshare、ccxt
│   │   │   ├── base.py             #   DataLoader Protocol
│   │   │   └── registry.py         #   注册表 + 自动回退链
│   │   └── optimizers/             #   MVO、等波动、最大分散、风险平价
│   │
│   └── config/swarm/               # 29 个 swarm 预设 YAML 定义
│
├── frontend/                       # Web UI（React 19 + Vite + TypeScript）
│   └── src/
│       ├── pages/                  #   Home、Agent、RunDetail、Compare
│       ├── components/             #   chat、charts、layout
│       └── stores/                 #   Zustand 状态管理
│
├── Dockerfile                      # 多阶段构建
├── docker-compose.yml              # 一键部署
├── pyproject.toml                  # 包配置 + CLI 入口
└── LICENSE                         # MIT
```

</details>

---

## 🏛 生态

Vibe-Trading 属于 **[HKUDS](https://github.com/HKUDS)** 代理生态的一部分：

<table>
  <tr>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>代理 swarm 智能</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>超轻量个人 AI 助手</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>让所有软件都可被代理驱动</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>自进化 AI 代理技能</sub>
    </td>
  </tr>
</table>

---

## 🗺 路线图

> 我们分阶段发布。工作开始后会移至 [Issues](https://github.com/HKUDS/Vibe-Trading/issues)。

| Phase | Feature | Status |
|-------|---------|--------|
| **Analysis & Viz** | 期权波动率曲面与 Greeks 三维可视化 | Planned |
| | 跨资产相关性热力图（滚动窗口 + 聚类） | Planned |
| | CLI 回测输出中的基准对比 | Planned |
| | 回测指标新增 Calmar Ratio 与 Omega Ratio | Planned |
| **Skills & Presets** | 分红分析技能 | Planned |
| | ESG / 可持续投资 swarm 预设 | Planned |
| | 新兴市场研究台 swarm 预设 | Planned |
| **Portfolio & Optimization** | 高级组合优化器：杠杆、行业上限、换手约束 | Planned |
| **Future** | 新手教程：“5 分钟自然语言回测” | Planned |
| | 通过 WebSocket 的实时数据流 | Exploring |
| | 策略市场（分享与发现） | Exploring |

---

## 贡献指南

欢迎贡献！请参见 [CONTRIBUTING.md](CONTRIBUTING.md) 获取指南。

**Good first issues** 带有 [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 标签——挑一个开始吧。

想做更大的贡献？查看上方 [路线图](#-路线图)，开始前先开个 issue 讨论。

---

## 贡献者

感谢所有为 Vibe-Trading 做出贡献的人！

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## 免责声明

Vibe-Trading 仅用于研究、模拟与回测。它不是投资建议，也不会执行实盘交易。历史表现不代表未来结果。

## 许可证

MIT 许可证——参见 [LICENSE](LICENSE)

---

<p align="center">
  感谢关注 <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
