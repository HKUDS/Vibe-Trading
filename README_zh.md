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
  <img src="https://img.shields.io/badge/Skills-72-orange" alt="Skills">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="Swarm">
  <img src="https://img.shields.io/badge/Tools-27-0F766E" alt="Tools">
  <img src="https://img.shields.io/badge/Data_Sources-6-2563EB" alt="Data Sources">
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

- **2026-04-28** 🚀 **v0.1.6 发布**（`pip install -U vibe-trading-ai`）：修复 `pip install` / `uv tool install` 安装后 `vibe-trading --swarm-presets` 返回空的问题（[#55](https://github.com/HKUDS/Vibe-Trading/issues/55)）—— 预设 YAML 现已打包进 `src.swarm` 包内，配套 6 个回归测试。同时 AKShare 加载器正确路由 ETF（`510300.SH`）和外汇（`USDCNH`）到对应端点，并加固注册表回退链。汇总自 v0.1.5 以来全部更新：基准对比面板、`/upload` 流式上传 + 大小限制、富途数据源（港股/A 股）、vnpy 导出技能、安全加固、前端懒加载（688KB → 262KB）。
- **2026-04-27** 📊 **基准对比面板 + 上传安全**：回测输出新增基准对比面板（标的 / 基准收益 / 超额收益 / 信息比率），通过 yfinance 解析 SPY、沪深 300 等基准（[#48](https://github.com/HKUDS/Vibe-Trading/issues/48)）。同时 `/upload` 端点改为 1MB 分块流式落盘，超过 `MAX_UPLOAD_SIZE` 立即中断并清理半截文件，让 50MB 上限在恶意/超大请求下真正生效（[#53](https://github.com/HKUDS/Vibe-Trading/pull/53)）—— 配套 4 个回归测试。
- **2026-04-22** 🛡️ **加固 + 新接入**：`safe_path` 强制路径包含校验 + 交割单/影子账户工具沙箱化，新增 `MANIFEST.in` 让 sdist 打包 `.env.example` / 测试 / Docker 文件，前端按路由懒加载把首屏包从 688KB 压到 262KB。同时新增富途港股/A 股数据加载器（[#47](https://github.com/HKUDS/Vibe-Trading/pull/47)）和 vnpy CtaTemplate 导出技能（[#46](https://github.com/HKUDS/Vibe-Trading/pull/46)）。

<details>
<summary>更早的新闻</summary>

- **2026-04-21** 🛡️ **工作区与文档**：相对路径 `run_dir` 归一化到当前 run 目录（[#43](https://github.com/HKUDS/Vibe-Trading/pull/43)）。README 加入使用示例（[#45](https://github.com/HKUDS/Vibe-Trading/pull/45)）。
- **2026-04-20** 🔌 **推理模型与 Swarm 修复**：`reasoning_content` 在所有 `ChatOpenAI` 序列化路径上保留 —— Kimi / DeepSeek / Qwen thinking 端到端可用（[#39](https://github.com/HKUDS/Vibe-Trading/issues/39)）。Swarm 切流式调用 + 干净的 Ctrl+C 退出（[#42](https://github.com/HKUDS/Vibe-Trading/issues/42)）。
- **2026-04-19** 📦 **v0.1.5**：发布至 PyPI 与 ClawHub。`python-multipart` CVE 版本下限升级，5 个新 MCP 工具接入（`analyze_trade_journal` + 4 个影子账户工具），修复 `pattern_recognition` → `pattern` 工具注册名不一致，Docker 依赖对齐，SKILL 清单同步（22 MCP 工具 / 71 技能）。
- **2026-04-18** 👥 **影子账户 Shadow Account**：从券商交割单提取你自己的策略规则 → 跨市场回测这个"影子" → 8 节 HTML/PDF 报告精确告诉你每一块钱是怎么错过的（规则违反、过早止盈、漏掉信号、反向操作）。4 个新工具、1 个新技能、共 32 工具。Trade Journal / Shadow Account 例句已进 Web UI 欢迎屏。
- **2026-04-17** 📊 **交割单分析器 + 通用文件阅读器**：上传券商交割单（同花顺/东财/富途/通用 CSV）→ 自动生成交易画像（持仓天数、胜率、盈亏比、最大回撤）+ 4 项行为偏差诊断（处置效应、过度交易、追涨杀跌、锚定效应）。`read_document` 现统一分发 PDF、Word、Excel、PowerPoint、图片（OCR）及 40+ 文本格式，一个调用走全部类型。
- **2026-04-16** 🧠 **Agent Harness**：跨会话持久记忆、FTS5 会话搜索、自进化技能（完整 CRUD）、5 层上下文压缩、读写工具批处理。27 工具，107 新测试。
- **2026-04-15** 🤖 **Z.ai + MiniMax**：新增 Z.ai 提供商（[#35](https://github.com/HKUDS/Vibe-Trading/pull/35)），修复 MiniMax temperature 及模型更新（[#33](https://github.com/HKUDS/Vibe-Trading/pull/33)）。共 13 家提供商。
- **2026-04-14** 🔧 **MCP 稳定性**：修复回测工具在 stdio 传输中的 `Connection closed` 错误（[#32](https://github.com/HKUDS/Vibe-Trading/pull/32)）。
- **2026-04-13** 🌐 **跨市场复合回测**：新增 `CompositeEngine`，混合不同市场标的（如 A 股 + 加密货币）共享资金池回测，各市场规则按标的独立执行。同时修复 swarm 模板变量回退和前端超时问题。
- **2026-04-12** 🌍 **多平台指标导出**：`/pine` 一次性导出 TradingView (Pine Script v6)、通达信/同花顺/东方财富 (TDX)、MetaTrader 5 (MQL5) 三大平台。
- **2026-04-11** 🛡️ **可靠性与 DX**：`vibe-trading init` .env 引导（[#19](https://github.com/HKUDS/Vibe-Trading/pull/19)），启动预检、数据源自动回退、回测引擎加固。多语言 README（[#21](https://github.com/HKUDS/Vibe-Trading/pull/21)）。
- **2026-04-10** 📦 **v0.1.4**：Docker 修复（[#8](https://github.com/HKUDS/Vibe-Trading/issues/8)），`web_search` MCP 工具，12 家 LLM 提供商，`akshare`/`ccxt` 依赖。已发布至 PyPI 和 ClawHub。
- **2026-04-09** 📊 **回测 Wave 2**：新增 ChinaFutures、GlobalFutures、Forex、Options v2 引擎。蒙特卡洛、Bootstrap CI、Walk-Forward 统计验证。
- **2026-04-08** 🔧 **多市场回测**：分市场规则，Pine Script v6 导出，5 数据源自动回退。

</details>

---

## 💡 Vibe-Trading 是什么？

Vibe-Trading 是一个由 AI 驱动的多代理金融工作台，将自然语言请求转化为可执行的交易策略、研究洞见和跨全球市场的投资组合分析。

### 核心能力：
• **自然语言 → 策略** —— 描述想法，代理自动编写、测试、导出交易代码<br>
• **5 大数据源，零配置** —— A 股、港美股、加密、期货、外汇自动回退<br>
• **29 支专家团队** —— 预构建的多代理 swarm 工作流，覆盖投资、交易与风控<br>
• **跨会话记忆** —— 记住偏好与洞察；自动创建、进化可复用技能<br>
• **7 大回测引擎** —— 跨市场复合测试 + 统计验证 + 4 种优化器<br>
• **多平台导出** —— 一键到 TradingView、TDX（通达信/同花顺）和 MetaTrader 5

---

## ✨ 核心功能

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="Research"/><br>
      <h3>🔍 面向交易的深度研究</h3>
      <img src="https://img.shields.io/badge/72_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="Skills" /><br><br>
      <div align="left" style="font-size: 4px;">
        • 72 个专长技能 + 跨会话持久记忆<br>
        • 自进化：代理从经验中创建并优化工作流<br>
        • 5 层上下文压缩——长对话不丢失信息<br>
        • 覆盖全金融领域的自然语言任务路由
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="Swarm"/><br>
      <h3>🐝 群体智能</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="Swarm" /><br><br>
      <div align="left">
        • 29 个开箱即用的交易团队预设<br>
        • 基于 DAG 的多代理编排<br>
        • 实时流式仪表盘，显示代理运行状态<br>
        • FTS5 跨会话搜索全部历史对话
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

## 7 大类别中的 72 个技能

- 📊 72 个金融专长技能，划分 7 大类
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

### 🎯 推荐模型

Vibe-Trading 是重度依赖工具调用的 agent — skills、回测、记忆、swarm 全部通过 tool call 完成。模型选择直接决定 agent 是**真的在用工具**，还是从训练数据里编答案。

| 等级 | 示例 | 适用场景 |
|------|------|---------|
| **最佳** | `anthropic/claude-opus-4.7`、`anthropic/claude-sonnet-4.6`、`openai/gpt-5.4`、`google/gemini-3.1-pro-preview` | 复杂 swarm（3+ agent）、长研究会话、论文级分析 |
| **性价比**（默认） | `deepseek/deepseek-v3.2`、`x-ai/grok-4.20`、`z-ai/glm-5.1`、`moonshotai/kimi-k2.5`、`qwen/qwen3-max-thinking` | 日常使用 — tool-calling 稳定，成本约 1/10 |
| **不建议用于 agent** | `*-nano`、`*-flash-lite`、`*-coder-next`、小参数 / 蒸馏版 | tool-calling 不可靠 — agent 会"凭记忆回答"而不加载 skill 或跑回测 |

默认 `agent/.env.example` 使用 `deepseek/deepseek-v3.2` — 性价比档里最便宜的选项。

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
| `/skills` | 列出 72 个金融技能 |
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

Vibe-Trading 为任意 MCP 兼容客户端提供 22 个 MCP 工具。以 stdio 子进程运行——无需服务器部署。**22 个工具中有 21 个无需任何 API key**（港美股/加密）。仅 `run_swarm` 需要 LLM key。

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

**已暴露的 MCP 工具（22）：** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`。

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

全部 72 个金融技能已发布在 [open-space.cloud](https://open-space.cloud)，并通过 OpenSpace 的自进化引擎自动演进。

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

OpenSpace 会自动发现全部 72 个技能，支持自动修复、自动改进与社区共享。在任意连接 OpenSpace 的代理中通过 `search_skills("finance backtest")` 搜索 Vibe-Trading 技能。

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
│   ├── mcp_server.py               # MCP 服务器——为 OpenClaw / Claude Desktop 提供 22 个工具
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct 代理核心
│   │   │   ├── loop.py             #   5 层压缩 + 读写工具批处理
│   │   │   ├── context.py          #   系统提示 + 持久记忆自动召回
│   │   │   ├── skills.py           #   技能加载器（69 内置 + 用户 CRUD 创建）
│   │   │   ├── tools.py            #   工具基类 + 注册表
│   │   │   ├── memory.py           #   单次运行轻量工作区状态
│   │   │   ├── frontmatter.py      #   共享 YAML frontmatter 解析器
│   │   │   └── trace.py            #   执行轨迹写入
│   │   │
│   │   ├── memory/                 # 跨会话持久记忆
│   │   │   └── persistent.py       #   基于文件的记忆（~/.vibe-trading/memory/）
│   │   │
│   │   ├── tools/                  # 27 个自动发现的代理工具
│   │   │   ├── backtest_tool.py    #   运行回测
│   │   │   ├── remember_tool.py    #   跨会话记忆（保存/召回/遗忘）
│   │   │   ├── skill_writer_tool.py #  技能 CRUD（保存/修补/删除/文件）
│   │   │   ├── session_search_tool.py # FTS5 跨会话搜索
│   │   │   ├── swarm_tool.py       #   启动 swarm 团队
│   │   │   ├── web_search_tool.py  #   DuckDuckGo 搜索
│   │   │   └── ...                 #   bash、文件 I/O、因子分析、期权等
│   │   │
│   │   ├── skills/                 # 72 个金融技能（7 类，每个 SKILL.md）
│   │   ├── swarm/                  # Swarm DAG 执行引擎
│   │   │   └── presets/            #   29 个 swarm 预设 YAML 定义
│   │   ├── session/                # 多轮对话 + FTS5 会话搜索
│   │   └── providers/              # LLM 提供商抽象
│   │
│   └── backtest/                   # 回测引擎
│       ├── engines/                #   7 个引擎 + 跨市场复合引擎 + options_portfolio
│       ├── loaders/                #   6 个数据源：tushare、okx、yfinance、akshare、ccxt、futu
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   注册表 + 自动回退链
│       └── optimizers/             #   MVO、等波动、最大分散、风险平价
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
| **Agent Harness** | 跨会话持久记忆（保存 / 召回 / 遗忘） | **Done** |
| | 自进化技能——代理自主创建、修补和删除工作流 | **Done** |
| | FTS5 跨会话搜索全部历史对话 | **Done** |
| | 5 层上下文压缩（微压缩 → 折叠 → 自动 → 手动 → 迭代） | **Done** |
| | 读写工具批处理——只读工具并行执行 | **Done** |
| **Next Up** | 自主研究循环——代理通宵迭代假设 | In Progress |
| | IM 集成（Slack / Telegram / 微信） | Planned |
| **Analysis & Viz** | 期权波动率曲面与 Greeks 三维可视化 | Planned |
| | 跨资产相关性热力图（滚动窗口 + 聚类） | Planned |
| | CLI 回测输出中的基准对比 | Planned |
| **Skills & Presets** | 分红分析技能 | Planned |
| | ESG / 可持续投资 swarm 预设 | Planned |
| **Portfolio & Optimization** | 高级组合优化器：杠杆、行业上限、换手约束 | Planned |
| **Future** | 策略市场（分享与发现） | Exploring |
| | 通过 WebSocket 的实时数据流 | Exploring |

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

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

---

<p align="center">
  感谢关注 <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
