<p align="center">
  <a href="README.md">English</a> | <b>中文</b> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading：你的个人交易智能体</h1>

<p align="center">
  <b>一条命令，让你的智能体具备完整交易研究能力</b>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25527" alt="HKUDS%2FVibe-Trading | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/6TdQnT5xcF"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://vibetrading.wiki/">官网</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">文档</a> &nbsp;&middot;&nbsp;
  <a href="#-news">News</a> &nbsp;&middot;&nbsp;
  <a href="#-key-features">Features</a> &nbsp;&middot;&nbsp;
  <a href="#-shadow-account">Shadow Account</a> &nbsp;&middot;&nbsp;
  <a href="#-demo">Demo</a> &nbsp;&middot;&nbsp;
  <a href="#-quick-start">Quick Start</a> &nbsp;&middot;&nbsp;
  <a href="#-examples">Examples</a> &nbsp;&middot;&nbsp;
  <a href="#-api-server">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-roadmap">Roadmap</a> &nbsp;&middot;&nbsp;
  <a href="#-contributing">Contributing</a>
</p>

<p align="center">
  <a href="#-quick-start"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 News

- **2026-06-19** 🌍 **全球数据层 — 8 个新数据源 + 18 个只读数据工具**：行情数据 loader 从 10 个增至 18 个——四个免费直连源（**东方财富**、**新浪**、**Stooq**、直连 HTTP 的 **Yahoo** 客户端）加四个可选 key 的美股源（**Finnhub**、**Alpha Vantage**、**Tiingo**、**FMP**），fallback 链按"被封 IP 风险"重新排序。在此之上是 **18 个新只读数据工具**，把能力从 OHLCV 拓展到基本面与资金面——资金流、龙虎榜、北向（陆股通）资金、融资融券、大宗交易、股东户数、限售解禁、板块归属、券商研报、新闻、SEC 文件（EDGAR + XBRL）、财务报表、期权链、机构持仓、全市场筛选、代码搜索——覆盖 A股 / 美股 / 港股，全部经 MCP 暴露。统一的 `data-routing` 路由索引与按源的 `eastmoney` / `sec-edgar` skill 将其文档化，并通过真实端到端的 LLM 路由 + 数据冒烟验证。
- **2026-06-18** 🔬 **Research Autopilot 第一阶段 + 本地 Data Bridge 加载器，外加一则 Discord 安全提示**：两个新 agent 工具把**假设登记（Hypothesis Registry）→ 研究目标（Research Goal）→ 回测**这条链路打通——`run_research_autopilot` 把一个 `hypothesis_id` 变成一个研究目标（论点即目标、面向回测的验收标准、下一步提示），`generate_backtest_config` 则根据假设的标的池与数据源自动写出回测 `config.json`，让 agent 可以从想法 → `signal_engine.py` → 实跑一气呵成（现在 **50 个工具**）（[#260](https://github.com/HKUDS/Vibe-Trading/pull/260)，感谢 @Robin1987China）。新的 **`local` 数据加载器**直接从你自己的 **CSV / Parquet / DuckDB** 文件读取 OHLCV：在 `~/.vibe-trading/data-bridge/config.yaml` 里把 symbol 映射到文件，并给 symbol 加 `local:` 前缀即可路由到本地数据，照常支持 fallback 链（[#252](https://github.com/HKUDS/Vibe-Trading/pull/252)，感谢 @Robin1987China）。一个快速跟进修掉了二者各自带来的运行期缺陷——Autopilot 从未收到宿主 `session_id`（每次调用都报错），`generate_backtest_config` 写到了 `safe_run_dir` 拒绝的 run 根目录，本地加载器在 tz-naive 时间戳比较时静默清空了 tz-aware 输入（[#266](https://github.com/HKUDS/Vibe-Trading/pull/266)）。DeepSeek 的 `DSML` 包裹式工具调用现在能正确解析（[#261](https://github.com/HKUDS/Vibe-Trading/issues/261)），Robinhood OAuth 握手获得了更长的初始化超时，MCP `initTimeout` 配置项也已写进文档（[#263](https://github.com/HKUDS/Vibe-Trading/pull/263)），并落地了一波标识符收敛加固：持久记忆类型校验（[#257](https://github.com/HKUDS/Vibe-Trading/pull/257)）、MCP swarm run-id 收敛（[#258](https://github.com/HKUDS/Vibe-Trading/pull/258)）、以及在 relay、preview 与 commit 网关之间一致强制的严格 `mp_[0-9a-f]{32}` mandate proposal-id 格式（[#256](https://github.com/HKUDS/Vibe-Trading/pull/256)、[#264](https://github.com/HKUDS/Vibe-Trading/pull/264)）。⚠️ **安全提示**：旧的社区邀请链接现在指向一个我们已无法控制的服务器，里面跑着假冒 Collab.Land 的钱包"验证"钓鱼骗局——它已从所有 README 和 issue 模板中移除，**唯一**官方 Discord 现在是 HKUDS 社区服务器（[discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF)）。Vibe-Trading 绝不会要求你"验证"或连接加密钱包。
- **2026-06-17** 🧩 **安装兼容 + Opus/Kimi provider 修复**：基础 `pip install vibe-trading-ai` 不再拉取可选的 `pyharmonics` / `ta` 依赖链；谐波形态识别现在放到 `vibe-trading-ai[harmonic]` extra 后面，同时保留内置 fallback 检测器（[#250](https://github.com/HKUDS/Vibe-Trading/pull/250)，关闭 [#249](https://github.com/HKUDS/Vibe-Trading/issues/249)）。Agent loop 也不再发送 Opus 4.8+ 会拒绝的 assistant-prefill handoff 消息，Kimi/Moonshot 可通过 `MOONSHOT_USER_AGENT` 覆盖客户端 `User-Agent`（[#248](https://github.com/HKUDS/Vibe-Trading/pull/248)，关闭 [#246](https://github.com/HKUDS/Vibe-Trading/issues/246) 和 [#204](https://github.com/HKUDS/Vibe-Trading/issues/204)）；后续测试已直接覆盖 background-result 与 auto-compact 两条 handoff 路径（[#251](https://github.com/HKUDS/Vibe-Trading/pull/251)）。
<details>
<summary>更早的更新</summary>

- **2026-06-16** 🛡️ **安全/API 加固 + GLM/Zhipu alias**：Settings 写入在配置认证时必须鉴权（[#245](https://github.com/HKUDS/Vibe-Trading/pull/245)）；API session 中 shell-capable 工具必须显式设置 `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` 才会暴露（[#243](https://github.com/HKUDS/Vibe-Trading/pull/243)）；配置 API key 后 local shutdown 也要求鉴权（[#241](https://github.com/HKUDS/Vibe-Trading/pull/241)）；看似 loopback 但不可信的 Host 会被拒绝，而不再被当成本地请求（[#242](https://github.com/HKUDS/Vibe-Trading/pull/242)）。运行边角也继续打磨：Web chat 会同步已完成尝试（[#236](https://github.com/HKUDS/Vibe-Trading/pull/236)），run card 对非有限指标写出 strict JSON（[#238](https://github.com/HKUDS/Vibe-Trading/pull/238)），畸形 `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S` 会安全回退（[#240](https://github.com/HKUDS/Vibe-Trading/pull/240)），ddgs retry fallback 已有回归覆盖（[#239](https://github.com/HKUDS/Vibe-Trading/pull/239)）。GLM/Zhipu 现在是一等 provider alias，并支持按模型名推断（[#247](https://github.com/HKUDS/Vibe-Trading/pull/247)，关闭 [#237](https://github.com/HKUDS/Vibe-Trading/issues/237)）。

- **2026-06-15** 🧭 **Web 搜索韧性 + Web UI 运行连续性修复**：`web_search` 不再因单个引擎被限流而失败——现在按序查询多个免费、免 key 的引擎（DuckDuckGo、Google、Bing、Brave、Mojeek、Yahoo），带重试/退避，把"无结果"当作空答案而非错误，所有引擎都被限流时返回可操作的提示而不是一个干巴巴的 ❌（可用 `VIBE_TRADING_SEARCH_BACKENDS` 覆盖引擎列表）（[#232](https://github.com/HKUDS/Vibe-Trading/pull/232)，关闭 [#231](https://github.com/HKUDS/Vibe-Trading/issues/231)，感谢 @Ethan-sun01）。Web UI 方面，运行过程中切换页面不再卡死——聊天页返回时会重新订阅实时流并回放期间错过的进度（[#234](https://github.com/HKUDS/Vibe-Trading/pull/234)）——停止按钮现在会在流式中和工具之间即时生效，而不只是在迭代边界（[#235](https://github.com/HKUDS/Vibe-Trading/pull/235)），两个症状一起关闭了 [#229](https://github.com/HKUDS/Vibe-Trading/issues/229)（感谢 @kalkinj）。baostock loader 也开始接受原生的 `sh.601398` / `sz.000001` 代码格式，与 tushare 风格的 `601398.SH` 并存（[#230](https://github.com/HKUDS/Vibe-Trading/pull/230)，感谢 @bhlt）。

- **2026-06-14** 📊 **按运行记录 token 用量 + Run Detail 图表按需加载**：每次 agent 运行现在都会把 provider 上报的 token 用量持久化为运行级的 `llm_usage.json`——provider/模型、累计总量、逐迭代计数——并附加到 `/runs/{id}` 上，这样一次运行结束、实时流消失后，它的 token 成本依然可审计（仅 provider 上报值；不抓 prompt/内容，不估算价格）（[#223](https://github.com/HKUDS/Vibe-Trading/pull/223)，感谢 @LemonCANDY42）。Run Detail 页面也不再一上来就加载每个标的的 K 线：默认 `/runs/{id}` 响应保持不变，但 UI 现在先渲染运行摘要，再通过可选的 `?chart_payload=summary` / `?chart_symbol=` 模式按需加载每个标的的图表，带有逐标的的加载状态和一个"全部加载 + 进度"控件（[#225](https://github.com/HKUDS/Vibe-Trading/pull/225)，感谢 @LemonCANDY42）。两个 loader 修复收尾：yfinance 的排他 `end` 边界不再漏掉请求范围内的最后一个交易日——下载调用现在传 `end + 1 天`，而缓存键仍保留原始范围（[#226](https://github.com/HKUDS/Vibe-Trading/pull/226)，感谢 @gyx09212214-prog）；畸形的 `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` 值现在会告警并回退到默认值，而不是在 import 时抛错、阻塞启动（[#227](https://github.com/HKUDS/Vibe-Trading/pull/227)，感谢 @gyx09212214-prog）。
- **2026-06-13** ↩️ **从 CLI 按 ID 恢复历史会话**：交互式 CLI 现在会在退出时打印 session-id，并附上可直接复制的 `vibe-trading resume <session-id>` 提示——找某次运行对应的 trace 不再需要靠时间戳去猜 `agent/sessions/` 下哪个目录最新。新增的 `vibe-trading resume <session-id>` 子命令会重新打开那个确切的会话，并把最近几轮对话回放进 loop；ID 不存在时会立即报错退出，而不是静默开一个空会话（[#218](https://github.com/HKUDS/Vibe-Trading/pull/218)，感谢 @zwrong）。
- **2026-06-12** 🩺 **Provider 可靠性大修——DeepSeek 卡死、Kimi 接入、流式存活**：一批 provider 报告——DeepSeek 运行卡在"智能体工作中…"（[#208](https://github.com/HKUDS/Vibe-Trading/issues/208)，感谢 @XYWOX）、`reached max iterations` 掩盖了模型空响应（[#203](https://github.com/HKUDS/Vibe-Trading/issues/203)，感谢 @mojianliang）、卡住后 UI 无法恢复（[#195](https://github.com/HKUDS/Vibe-Trading/issues/195)，感谢 @mafia23）、Kimi 拒绝客户端（[#204](https://github.com/HKUDS/Vibe-Trading/issues/204)，感谢 @liao497）——指向同一个根因：所有 OpenAI 兼容 provider 共用一个 shim，把 DeepSeek/Kimi/Gemini 的协议怪癖全局套用，还静默吞掉流式失败。现在 provider 专属行为收进显式的**能力层（capability layer）**——reasoning 捕获/回放、Gemini thought signature、Kimi `User-Agent`、OpenRouter reasoning body 各自只作用于自己的 provider，不再互相污染。纯 reasoning 流式会显示实时 **"Reasoning…"** 指示而不是一片死寂；流式失败会抛出带上下文的 `provider_stream_error`，瞬态中断自动重试一次（确定性 4xx 立即失败），不再静默降级为慢速非流式调用；模型空响应被如实诊断为 `empty_model_response` 而非"max iterations"；SSE 心跳不再破坏重连回放；卡死的只读工具会超时退出而不是永远躲在心跳后面。新增 **`vibe-trading provider doctor`**，一条命令打印脱敏的 provider/模型/包/代理快照，快速定位环境侧假卡死。DeepSeek 用户可通过 `pip install "vibe-trading-ai[deepseek]"` 启用官方原生 adapter；kimi-k2.x 的 `temperature=1` 要求自动适配——Kimi 链路已对真实 API 完成端到端验证（`kimi-k2.6` 工具调用 + 严格多轮 reasoning 回放）。

- **2026-06-11** 🐝 **Swarm worker 全面接入 loader 层行情数据**：一次 NVDA 投资委员会运行暴露出一串缺口——worker 自己手写 yfinance 脚本、轻信了一根残缺的最新 K 线（有成交量但 OHLC 为空）、`NaN` 泄漏进非严格 JSON，丢失上下文的续跑 prompt 还被路由到错误的 preset（[#198](https://github.com/HKUDS/Vibe-Trading/issues/198)，感谢 @BillDin 出色的诊断和两个修复 PR）。现在 swarm worker 拥有本地 `get_market_data` 工具，与 MCP 共用同一套归一化 loader 注册表——严格 JSON、非有限浮点序列化为 `null`——并接入**所有行情类 preset**（13 个 preset、21 个 worker），prompt 政策引导 OHLCV 工作优先走工具（[#199](https://github.com/HKUDS/Vibe-Trading/pull/199)）；`run_swarm` 支持显式 `preset_name`，含糊的续跑片段会被直接拒绝，而不是静默回落到 `equity_research_team`（[#200](https://github.com/HKUDS/Vibe-Trading/pull/200)）。Grounding 也更聪明：swarm prompt 里裸写的美股代码（如 `NVDA`）会自动提升为 `NVDA.US`（带停用词防误判），worker 从一开始就拿到权威的预取价格。该工具同时进入主 agent 注册表——现在共 **48 个工具**。另外：**Docker 数据现在可以跨更新存活**——持久记忆、会话搜索索引、自建 skills、shadow account 和 broker 配置都放进了命名数据卷，`docker compose up --build` 不会再清空它们（[#197](https://github.com/HKUDS/Vibe-Trading/issues/197)，感谢 @FlyerJ）。
- **2026-06-10** 🐳 **Docker 开箱即可访问宿主机 Ollama**：容器内的 `localhost` 指向容器自身，默认的 `OLLAMA_BASE_URL=http://localhost:11434` 让所有 Docker + Ollama 组合的 LLM 预检直接失败。`docker-compose.yml` 现在默认指向 `http://host.docker.internal:11434`（导出 `OLLAMA_BASE_URL` 可覆盖），并加入 `host-gateway` 的 `extra_hosts` 映射，在 Linux 上与 Docker Desktop 一样开箱即用（[#196](https://github.com/HKUDS/Vibe-Trading/pull/196)，感谢 @ShahNewazKhan）。
- **2026-06-09** 🔑 **从另一台机器打开 Web UI 时的报错更清晰**：从非 loopback 客户端（另一台机器、虚拟机宿主机、局域网里的手机）访问聊天且未设 `API_AUTH_KEY` 时，所有敏感接口——发消息、列会话、live 状态——都会返回 `403`，但聊天界面只笼统显示 “Failed to send message, please retry.”。现在发送路径会直接给出真实原因——*“Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use.”*——README 的 Web UI 配置说明也讲清了 localhost 与局域网的区别以及三种解法（在同一台机器上用 `localhost` 访问；设置 `API_AUTH_KEY` 并在 Settings 里填一次；或为 Docker Desktop 宿主网关设 `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1`）（[#191](https://github.com/HKUDS/Vibe-Trading/issues/191)，感谢 @mafia23）。
- **2026-06-08** 🔧 **Gemini 3.x 多轮工具调用修复**：补全了 Gemini 3.x 思考模型的修复。6/05 的回传（[#176](https://github.com/HKUDS/Vibe-Trading/pull/176)）只覆盖了内存中的历史，而真正的 agent loop 会把历史以 OpenAI 格式的 dict 回放，LangChain 在构建请求前丢掉了每个工具调用的 `thought_signature`——导致多轮工具调用仍以 `missing thought_signature` 报 400。现在它会在 `invoke` 与 `stream` 共用的唯一入口 `_convert_input` 处重新挂回（并行调用——N 个里只有第一个带签名——也已涵盖）（[#184](https://github.com/HKUDS/Vibe-Trading/pull/184)，感谢 @ngoanpv）。
- **2026-06-07** 🐝 **聊天时间线中的实时 swarm 状态**：当 agent 启动多智能体 swarm（投资委员会、量化台、风险委员会……）时，聊天界面现在会内联渲染一张**状态卡**，实时流式展示每个 worker 的状态——等待 / 运行 / 完成 / 失败 / 阻塞 / 重试——与独立 swarm 仪表盘一致的逐 agent 可见性。运行时事件被桥接进会话 SSE 流，且不改动现有的 `/swarm/runs` API；重连或回放历史时，已结束的卡片会从最终的 `run_swarm` 结果复原（[#188](https://github.com/HKUDS/Vibe-Trading/pull/188)，感谢 @BillDin）。preset 路由也更精准：显式指定的 preset（如 `investment_committee`，带不带下划线均可）现在优先于关键词打分，而裸 `IV` 衍生品关键词也不再误匹配 “g**iv**en” 之类普通单词（[#189](https://github.com/HKUDS/Vibe-Trading/pull/189)，感谢 @BillDin）。
- **2026-06-06** ⚖️ **Alpha 对比 —— CLI / Web UI / REST / agent 四端齐全**：新增 `alpha compare`，把你手选的一组 Alpha Zoo 因子放在同一 universe 和区间上两两对比，按 IC 均值/标准差、IR、IC>0 比例或样本数排名，并标出每个因子与榜首的差距。不同于整库 bench，它**只评估你点名的因子**（新增 `run_bench(only=…)` 子集过滤），所以对比 3 个因子不会再把整库 191 个全跑一遍。四端共用同一套核心：`vibe-trading alpha compare <id1> <id2> … --sort ir`（CLI）、Alpha Zoo Web UI 的 **Compare 视图**（在目录里勾选因子 → 一键对比 + 流式排名表）、`POST /alpha/compare` + SSE（REST），以及只读的 `alpha_compare` agent 工具（工具数达 **47**）。
- **2026-06-05** 🇮🇳 **Dhan + Shoonya connector（印度）——10 家券商**：connector-first 交易层新增 **Dhan** 与 **Shoonya** 两个印度券商（NSE/BSE 股票 + F&O），券商总数达到十家。两者均为**模拟盘 + 只读**——与长桥一样，其 API 不暴露运行时的模拟/正式判别标识，因此 `place_order` / `cancel_order` 在第一行就硬拒任何非模拟配置（通用规则：无结构性模拟/正式守卫的券商一律封顶模拟盘 + 只读）（[#181](https://github.com/HKUDS/Vibe-Trading/pull/181)，收尾 [#174](https://github.com/HKUDS/Vibe-Trading/issues/174)）。本轮还修复了 **Gemini 2.5 / 3.x 思考模型**：每个工具调用的 `thoughtSignature` 现在能在 OpenAI 兼容路径上完整回传，多轮 function calling 不再因 `INVALID_ARGUMENT` 失败（[#176](https://github.com/HKUDS/Vibe-Trading/pull/176)，关闭 [#170](https://github.com/HKUDS/Vibe-Trading/issues/170)，感谢 @mvanhorn 与 @jliu6789）。全部 **452 个 Alpha Zoo 因子**补上了中文 docstring（中文名称/说明/用途）（[#180](https://github.com/HKUDS/Vibe-Trading/pull/180)，感谢 @LeeCQiang）；**前端测试套件（197 个 vitest 用例）**加上后端鉴权 / 路径穿越 / CORS 安全测试也进了 CI（[#175](https://github.com/HKUDS/Vibe-Trading/pull/175)，感谢 @sambazhu）。
- **2026-06-04** 🗃️ **全部 7 个数据源的可选本地缓存**：新增 `VIBE_TRADING_DATA_CACHE` 开关，让每个回测 loader——tushare、okx、ccxt、akshare、mootdx、yfinance、futu——把已结算的历史 bar 缓存到 `~/.vibe-trading/cache`（用户主目录，绝不写入仓库），让重复以及长周期 / 跨市场回测跳过网络、避开数据源限流。默认关闭。批量与连接型 loader（yfinance、futu）在缓存全部命中时完全跳过批量下载 / FutuOpenD 连接；结算守卫绝不缓存截止到当天的区间（最后一根 bar 还在形成中）；缓存帧与实时拉取的结果逐字节一致（[#177](https://github.com/HKUDS/Vibe-Trading/pull/177)，感谢 @mvanhorn）。同时还落地了一份面向 AI / 自动化辅助 PR 的贡献者指南，梳理了安全的本地检查项与高风险的 broker/MCP/凭证操作面（[#173](https://github.com/HKUDS/Vibe-Trading/pull/173)）。
- **2026-06-03** 🧹 **社区 triage + trace 关联**：工具调用的 trace 条目现在带上原始 `call_id`，回放 run trace 时可以把 `tool_result` 对回它的 `tool_call`——入参预览仍保持截断，避免 trace 文件膨胀（[#168](https://github.com/HKUDS/Vibe-Trading/pull/168)，感谢 @zwrong）。源码注释不再指向外部贡献者找不到的内部文档路径（[#166](https://github.com/HKUDS/Vibe-Trading/issues/166)，感谢 @jaleelpersonal）。另外澄清了安装时的 `langchain-community` 依赖解析告警只是残留旧包的无害提示、并非安装失败（[#167](https://github.com/HKUDS/Vibe-Trading/issues/167)），并把 Gemini 2.5/3.0 函数调用的 `thoughtSignature` 往返梳理成一条带完整修复方案的 `help wanted` 任务（[#170](https://github.com/HKUDS/Vibe-Trading/issues/170)，感谢 @jliu6789）。
- **2026-06-02** 🔌 **六个新券商 connector（老虎 / 长桥 / Alpaca / OKX / 币安 / 富途）**：connector-first 交易层在 IBKR（本地）和 Robinhood（MCP）之外，新增一条直连 SDK 传输。每个 connector 都暴露只读的账户 / 持仓 / 订单 / 行情 / 历史，外加模拟账户下单——把你的策略放到这些券商的模拟盘上跑。其中五个（老虎、Alpaca、OKX、币安、富途）还支持在用户提交的 mandate（标的/单量/敞口/杠杆/每日笔数）约束下的有界下单，沿用与 Robinhood 同一套安全模型：用户提交的 mandate、文件级即时 kill switch、fail-closed 的下单前门禁，以及完整审计账本。长桥仅支持模拟盘 + 只读（其 API 不暴露运行时的模拟/正式判别标识）。每一处模拟/正式的区分都是按券商落实的结构性守卫——账户 id 格式、host 隔离、demo 标志或 trade environment。新增 `trading_place_order` / `trading_cancel_order` 工具；mandate universe 也补上了港股和 A 股资产类别。实验性 / 风险自负。
- **2026-06-01** 🚀 **v0.1.9 发布**（`pip install -U vibe-trading-ai`）：汇总 0.1.8 以来的全部更新。Connector-first 券商 profile（IBKR 本地只读 TWS / IB Gateway + Robinhood Agentic Trading，受 OAuth、已提交 mandate、order guard、审计账本和即时 halt 约束）。Research Goal 运行时贯通 CLI / REST / MCP / Web。一轮 swarm 升级——实时 reconcile + MCP keepalive、operator 配置的 worker MCP 工具、严格 alpha-bench 随机控制，以及新增 `retry_run` 重跑失败/过期 run（现 **36 个 MCP 工具**）。`agent/cli/` 包重构 + 刷新的终端 UI、`mootdx` 免 token A 股 loader，以及 backtest / agent loop / session 的健壮性增强。`--version` 现在始终与已安装版本一致，修复 0.1.8 漂移（[#156](https://github.com/HKUDS/Vibe-Trading/issues/156)）。
- **2026-05-31** 🔌 **Connector-first 券商架构（IBKR + Robinhood）**：交易接入现在从可选择的 connector profile 开始，不再拆成分散的券商入口和 live 入口。`vibe-trading connector list/use/check/account/positions/orders/quote/history` 与 MCP `trading_*` 工具共享同一个选中的 profile；paper/live 只是该 connector 下的属性。IBKR 可立即通过本地只读 TWS / IB Gateway profile 使用；官方 IBKR 远程 MCP 先作为 OAuth `mcp.read` 探测种子，等待稳定 read 工具名后再映射。Robinhood Agentic Trading 仍是有界 live MCP connector，必须经过 OAuth、已提交 mandate、order guard、审计账本和即时 halt。
- **2026-05-30** 🧰 **健壮性专项 — backtest、agent loop、session**：LLM 生成的 signal engine 现在会在实例化前先过接口预检，提前抓出循环 self-import、缺失 `generate()`、`__init__` 参数没有默认值、返回类型错误等常见问题，并给出可操作的 JSON 报错而非原始 traceback（[#149](https://github.com/HKUDS/Vibe-Trading/pull/149)）；后续一并把源码级 AST 校验的报错也走同一套干净的 JSON 信封。agent loop 不再把 50 次迭代全烧光后留下一个没有任何输出的 `failed` 状态——它复用 swarm worker 已验证的做法：在迭代预算 80% 处注入 wrap-up nudge，并在最后一次迭代丢掉 tool 定义以强制产出文本答案（[#148](https://github.com/HKUDS/Vibe-Trading/pull/148)），且只在中途触发，绝不挤掉 research-goal 上下文。session 消息写入现在每次 append 后 `flush + fsync`，让昂贵的 AI 回复能在写到一半崩溃时存活；读取端则跳过损坏的 JSONL 行（记录前 200 字符以便人工恢复），而不是让整个 `/messages` 端点 500（[#147](https://github.com/HKUDS/Vibe-Trading/pull/147)）。Web 输入框也修了 IME 回车处理，让中日韩输入法的确认上屏回车不再误触发提交（[#146](https://github.com/HKUDS/Vibe-Trading/pull/146)）。
- **2026-05-29** 🔐 **支持 Robinhood Agentic Trading（可选开启、有界自主）**：新增对 Robinhood Agentic Trading 的支持（远程 MCP，OAuth）。默认关闭且只读；仅在用户提交的 mandate（标的/单量/敞口/杠杆/每日笔数）内自主交易，配文件级即时 kill switch、抢占式平仓、mandate 自动过期、完整审计账本，以及一个持久自主 runner。无托管、无场所——券商持有资金并执行，我们只中继意图。实验性 / 风险自负。
- **2026-05-28** 🧪 **Swarm 安全 + 严格 alpha 门 + worker 端 MCP**：Swarm DAG 在上游任务失败时阻断下游任务（[#145](https://github.com/HKUDS/Vibe-Trading/pull/145)）。新增 `run_bench_strict()` 在 IC 门之上加入同 universe 随机控制 + 训练/测试 OOS 切分，识别只是跟随市场 beta 的伪因子（[#143](https://github.com/HKUDS/Vibe-Trading/pull/143)，感谢 @Soli22de）。Swarm worker 现在可以调用 operator 配置的外部 MCP server，信任边界由专项测试固定（[#142](https://github.com/HKUDS/Vibe-Trading/pull/142)，感谢 @shadowinlife）。
- **2026-05-27** 📊 **mootdx A 股数据源 + 输出排版**：新增 `mootdx` loader，走原生通达信 TCP 协议拉 A 股 OHLCV（无需 token，无 IP 速率限制，日线 + 分钟线 25 页 walk-back 分页），在 fallback chain 中位于 tushare 和 akshare 之间（[#107](https://github.com/HKUDS/Vibe-Trading/issues/107)）。CCXT loader 现在会读取 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，使 Binance/OKX 公开数据可在受限网络下拉取（[#126](https://github.com/HKUDS/Vibe-Trading/pull/126)，感谢 @ruok808）。最终回答的渲染也去掉了 CLI 和 Web 上丑陋的全宽 `---` 分隔符：系统提示鼓励 agent 用 markdown 表格和 `##` 标题，CLI 渲染端兜底 strip 孤立 HR，前端 chat 气泡隐藏任何漏过去的 `<hr>`（[#139](https://github.com/HKUDS/Vibe-Trading/issues/139)，感谢 @sdwxm188）。
- **2026-05-26** ✅ **Research Goal 生命周期闭环**：Goal 模式现在像真正的任务运行器：Web UI 创建 goal 会创建或绑定 session，并立刻发出 kickoff turn；active goal 可在 Web/API/CLI/MCP 中继续、编辑、取消和完成；agent loop 会按当前 goal snapshot（criteria、evidence、claims、open items）推进，而不是只按最初 prompt。criteria 已 covered 但 goal 仍 active 时，会进入 audit/status 更新，不再静默停住，并用 backend、CLI、MCP 与 frontend events 回归覆盖固定。

- **2026-05-25** 🧼 **更干净的 Chat UI + composer 工作流**：Web UI 现在把注意力留给下一步输入：upload、swarm 和 research-goal 模式都收进 composer 的 `+` 菜单，不再用漂浮面板打断聊天。当前上下文会以紧凑 chip 附在输入框上方，goal 详情只在点击 chip 时原地展开。UI 也移除了旧的自定义 i18n 层，改用直接英文文案；Full Report card 只在真正有报告价值的 run 出现；本地 dev 启动与状态报告也加固，方便稳定做浏览器 smoke test。
- **2026-05-24** 🎯 **Research Goal runtime**：新增 session 级 Research Goal 层，贯通 backend、CLI、API/MCP、SSE 和 Web UI。Goal 会持久化 claim、acceptance criteria、evidence row、budget 与 completion policy；agent tools 可以创建 goal 并追加 evidence；`/goal` 成为 CLI 入口；REST/MCP 暴露 goal snapshot 和 evidence 写入；SSE 保持 chat client 状态新鲜。后续审计修复锁紧 verified evidence，阻断 agent tool 写入 live-trading 风险层，串起 CLI 创建的 goal 与后续 turn，删除 session 时清理 goal ledger，接上 replay-all，并修复前端跨 session snapshot race。
- **2026-05-23** 🖥️ **交互式 CLI 刷新**：终端入口现在使用更大的 Vibe-Trading banner、更清晰的 prompt 分隔线、上一轮摘要、运行后耗时，以及 Claude Code 风格的活动轨来展示实时 agent 工作。工具调用、网页/数据抓取、shell 风格动作、Markdown 回答和管道表格都会以更易读的 transcript 渲染；pipe 或非 TTY 运行仍保留适合自动化的纯文本输出。生成的 CLI 截图现在作为本地 artifact 处理，不再提交进 docs，让仓库更轻。
- **2026-05-22** 🧭 **Swarm 恢复 + MCP keepalive**：Swarm 状态现在每次读取都会从实时 task 文件 reconcile，API/MCP/SSE/list 视图可以自动恢复 crash 或过期 run，不再永久停在 `running` 快照。`run_swarm` 在 MCP polling 期间持续发送 progress heartbeat，首帧固定为 `swarm_started run_id=<id>`，方便 transport 掉线后的客户端找回句柄；worker 的 LLM streaming、grounding fetch、tool execution 也都包上了 heartbeat。stale-run reaper 按每个 run 的阈值判断，并从 task 状态推导终态；`SwarmTool` wait budget 用尽后不再取消仍在跑的 team，MCP 客户端也可以调用 `reap_stale_runs()` 显式清理。今天的 DX pass 还同步刷新 provider 默认模型，并把 CI syntax check 对齐到新的 `agent/cli/` 包。22 条新回归覆盖 hydrate、终态恢复、stale 回收、keepalive cadence、env 容错和 heartbeat wiring；完整 swarm/MCP 套件 169 passed、4 skipped。
- **2026-05-21** 🧱 **CLI 包重构**：`agent/cli.py`（3216 行）拆成 `agent/cli/` 包 —— 交互入口、slash 路由、Rich 组件，加 `_legacy.py` shim 保留所有子命令并 re-export 所有公共符号，`cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` 不变。新增 FastAPI middleware：浏览器直开 `/runs/{id}` 或 `/correlation` 时返回 SPA shell；Vite dev proxy 同步收窄到相同 regex。版本号通过 `cli/_version.py` 单一来源（`--version` 与 banner 不再 drift），`python -m cli` 通过 `__main__.py` 恢复，chat-gate 收窄使 `chat --help` / `chat extra` 正确走 legacy argparse 而不被新 REPL 吞掉。
- **2026-05-20** 🔬 **Hypothesis Registry CLI**：补齐了 5-16 上线但只有后端的 Hypothesis Registry 的 CLI 侧。`vibe-trading hypothesis list` 输出 Rich 表格或 JSON（支持 `--status` 过滤、`--limit`）；`show <id>` 渲染详情面板，包含已 link 的 run card；`invalidate <id> --note "..."` 把 status 翻成 `rejected`，省略 `--note` 时保留原有 invalidation notes。沿用 `VIBE_TRADING_HYPOTHESES_PATH` 环境变量，并新增按调用覆盖的 `--path`。22 个新单测覆盖 wiring、JSON 输出、状态过滤、limit、缺 id 报错、备注持久化。
- **2026-05-19** ✨ **工具实时反馈 + 优雅取消**：长时间运行的工具（回测、大 PDF、swarm worker）不再看起来卡死。每个工具调用现在会发出 3 秒一次的心跳，以及结构化的阶段进度 —— `run_backtest` 输出阶段标记（`validate` / `simulate` / `finalize`），`read_document` 在 PDF 上按页打点 / Excel 上按工作表打点，`read_url` 标记 `fetch` / `parse`。CLI 的 Rich Live 面板渲染 Unicode 转轮、ASCII 进度条、ETA，按工具名最多堆叠 3 个并行工具；前端 chat 新增 `ToolProgressIndicator`，rAF 合并刷新、ARIA `role="status"` + 隐藏的原生 `<progress>` 供屏幕阅读器使用，已知总数时切换为 determinate 的 `ProgressRing` SVG。CLI 中第一次 `Ctrl+C` 现在会调 `agent.cancel()` 优雅退出（当前步骤跑完、trace 干净关闭）；2 秒内第二次 `Ctrl+C` 强制退出。顺手抽出可复用基础件：`ProgressBar.tsx` 和 `lib/tools.ts`（共享工具名 i18n 映射）。
- **2026-05-18** 🧹 **清理一次 + 3 个潜伏 bug 修复**：`CompositeEngine` 不再把无交易所后缀的中国期货代码（如 `RB2410`）错误路由到 `GlobalFuturesEngine` —— `_is_china_futures` 移到共享的 `_market_hooks` 模块，产品代码表做了大小写归一并加入非中国交易所守卫，新增 9 条回归用例。session FTS5 索引现在会持久化时间戳，跨 session 搜索可按日期排序；同一改动也修复了 re-upsert 路径每次都用 wall-clock 覆盖 `started_at` 的副作用 bug。前端 Vite dev proxy 补上漏配的 `/alpha`，AlphaZoo 页在 `npm run dev` 下不再 404。`tests/test_e2e_harness_v2.py`（真 LLM 的 e2e 套件）现在用 `VIBE_TRADING_RUN_LIVE_E2E=1` 做环境门控，CI 不再因为有无 LLM key 而静默切状态。Ruff 为 factor zoo 添加 `per-file-ignores`（3783 → 0 F401 噪音），前端 tsconfig 打开 `noUnusedLocals` / `noUnusedParameters` 做回归护栏，并删掉了 76 个 `gtja191` alpha 文件里没用上的 `vw = vwap(...)` 残留。净 **-918 行**。
- **2026-05-17** 🧬 **Alpha Zoo v1（0.1.8）**：内置 452 个量化 alpha，覆盖 4 个 zoo —— `qlib158`（Microsoft Qlib 的 Alpha158 特征，Apache-2.0 出处声明）、`alpha101`（Kakushadze 的 "101 Formulaic Alphas"，从 arXiv:1601.00991 论文公式重写）、`gtja191`（国君证券 2014 短周期交易型因子研报）、`academic`（Fama-French 5 因子 + Carhart 动量的价格代理实现）。一行 CLI 就能在自己的 universe 上跑横评：`vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`。配套设施包括 AST 纯函数门禁、lookahead 防护测试、`pytest-socket` 网络隔离、每个 zoo 一份 LICENSE.md、社区贡献用的 DCO 签名流程；Alpha Library 自动渲染上线 [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/)；Research Lab 同步发布 [《191 个 GTJA alpha 哪些在 2026 还能用》](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html)。
- **2026-05-16** 🧪 **研究主干更新**：新增后端 Hypothesis Registry，提供 `create_hypothesis`、`update_hypothesis`、`link_backtest`、`search_hypotheses`；外部内容读取工具现在会附加 warning-only 的 `security_warnings`；Shadow Account 扫描也从旧的日历 phase stub 升级为确定性的 OHLCV 特征评估。
- **2026-05-15** 🪪 Run 详情页现在会在 metrics 和 artifacts 旁边渲染 Trust Layer 的 run card，把 2026-05-12 已落地的 `run_card.json` 工作补齐到 UI 一侧。`PersistentMemory.add()` 也根据 #108/#109/#110 的 triage，在长度限制、空 / 纯空白 name、以及 C0/C1 控制字节三条路径上做了加固（[#112](https://github.com/HKUDS/Vibe-Trading/pull/112)，感谢 @Teerapat-Vatpitak）。
- **2026-05-14** 🌐 公开 Wiki 已上线 [vibetrading.wiki](https://vibetrading.wiki/)，包含 docs、tutorials、Research Lab 和 Alpha Library，并通过 Cloudflare Pages 部署。持久记忆也可以通过 CLI 使用 `vibe-trading memory list/show/search/forget` 检查（[#102](https://github.com/HKUDS/Vibe-Trading/pull/102)，感谢 @Teerapat-Vatpitak）；记忆 tokenizer/slug 现在支持泰语、阿拉伯语、希伯来语和西里尔文字（[#104](https://github.com/HKUDS/Vibe-Trading/pull/104)）。
- **2026-05-13** 🧭 Swarm 运行现在会用已获取的市场数据为 worker 提供依据，并生成更清晰的持久化报告（[#93](https://github.com/HKUDS/Vibe-Trading/pull/93)，[#84](https://github.com/HKUDS/Vibe-Trading/pull/84)）。
- **2026-05-12** 🧾 回测现在会随 artifacts 一起输出 `run_card.json` 和 `run_card.md`，便于复现实验研究。
- **2026-05-11** 🧭 **记忆 slug、swarm 统计与 CLI 预检**：持久记忆在生成文件 slug 时会保留 CJK 字符，避免中文/日文/韩文笔记发生静默文件名冲突（[#95](https://github.com/HKUDS/Vibe-Trading/pull/95)，感谢 @voidborne-d）。Swarm 运行总量现在优先采用 provider 返回的 token 用量，并保留原有估算作为 fallback（[#94](https://github.com/HKUDS/Vibe-Trading/pull/94)，感谢 @Teerapat-Vatpitak）。CLI 运行界面也新增了启动预检，用于发现常见环境问题（[#96](https://github.com/HKUDS/Vibe-Trading/pull/96)，感谢 @ykykj）。
- **2026-05-10** 🧱 **回归护栏与运行元数据**：记忆召回现在将下划线视为 token 边界，因此 `mcp_wiring_test` 这类 snake_case 记忆可以匹配 "mcp wiring" 等自然语言查询（[#87](https://github.com/HKUDS/Vibe-Trading/pull/87)，感谢 @hp083625）。MCP server 增加了覆盖 initialize → `tools/list` → `tools/call` 的 subprocess smoke test，以防止首次调用死锁路径回归（[#86](https://github.com/HKUDS/Vibe-Trading/pull/86)）。同时还完成了多项低风险加固：Windows 路径敏感测试、API best-effort 异常处理、backtest `run_dir` allowed-root 校验，以及 SwarmRun provider/model 元数据（[#88](https://github.com/HKUDS/Vibe-Trading/pull/88)，[#90](https://github.com/HKUDS/Vibe-Trading/pull/90)，[#91](https://github.com/HKUDS/Vibe-Trading/pull/91)，[#92](https://github.com/HKUDS/Vibe-Trading/pull/92)，感谢 @Teerapat-Vatpitak）。
- **2026-05-09** 🛡️ **API 路径加固与 MCP server 稳定性**：API run/session 路由现在会在查询前校验 path ID，拒绝包含换行等异常字符的参数，并将该行为纳入 auth/security 回归测试（[#80](https://github.com/HKUDS/Vibe-Trading/pull/80)，感谢 @SJoon99）。MCP server 现在会在主线程预热工具注册表再处理 `tools/call`，避免懒加载工具发现中的首次调用死锁（[#85](https://github.com/HKUDS/Vibe-Trading/pull/85)，感谢 @Teerapat-Vatpitak）。Vite dev proxy 也会为非默认后端目标遵循 `VITE_API_URL`（[#82](https://github.com/HKUDS/Vibe-Trading/pull/82)，感谢 @voidborne-d）。
- **2026-05-08** 🧾 **筛选器支持 Tushare 财报字段**：A 股日线回测现在可以通过 `fundamental_fields` 请求 PIT-safe 财务报表字段，使信号引擎能够在公告/披露日之后筛选 `income_total_revenue`、`income_n_income`、`balancesheet_total_hldr_eqy_exc_min_int`、`fina_indicator_roe` 等带表名前缀的字段（[#76](https://github.com/HKUDS/Vibe-Trading/pull/76)，感谢 @mrbob-git）。后续加固让显式财报字段请求在 Tushare enrich 无法运行时快速失败，而不是静默回退到原始价格 bar（[#77](https://github.com/HKUDS/Vibe-Trading/pull/77)）。
- **2026-05-07** 📈 **Tushare fundamentals 与社区 triage**：新增面向基本面研究工作流的 point-in-time `TushareFundamentalProvider` contract，并为项目 `TUSHARE_TOKEN` 环境路径加入回归覆盖（[#74](https://github.com/HKUDS/Vibe-Trading/pull/74)）。社区 triage 也明确了：Vibe-Trading 目前会将快速迭代聚焦在单一 UI 语言；在已内置 DuckDuckGo 支持的 `web_search` 时避免添加冗余搜索依赖；非官方托管部署不应被视为 API key 或数据源 token 的可信存放位置。
- **2026-05-06** 🚀 **v0.1.7 发布**（[Release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7)，`pip install -U vibe-trading-ai`）：安全边界加固已发布到 PyPI 和 ClawHub，覆盖更安全的 API/read/upload/file/URL/generated-code/shell-tool/Docker 默认行为，同时保持 localhost CLI/Web UI 工作流低摩擦。本周期还包含 Web UI Settings、相关性热力图、OpenAI Codex OAuth、A 股 pre-ST 筛选、交互式 CLI UX、swarm preset 检查、股息分析、开发工作流打磨，以及经审计的前端构建依赖下限。感谢 0.1.7 贡献者，也感谢 lemi9090 (S2W) 的协同安全验证。
- **2026-05-05** 🛡️ **安全边界后续加固**：完成围绕显式 CORS origins、Settings 凭据指示、Web URL 读取和 Shadow Account 代码生成的剩余安全边界加固，并为每条路径加入回归测试。普通 localhost CLI/Web UI 工作流保持不变；远程部署应继续使用 `API_AUTH_KEY` 和显式可信 origins。
- **2026-05-04** 🖥️ **交互式 CLI UX 与 CI 清理**：交互模式现在拥有实时底部状态栏，可显示 provider/model、session 时长、最近一次运行延迟和累计工具调用统计；并通过 `prompt_toolkit` 支持 prompt 历史导航和方向键光标编辑（[#69](https://github.com/HKUDS/Vibe-Trading/pull/69)）。当 `prompt_toolkit` 或 TTY 不可用时，CLI 仍会回退到 Rich prompts。CI 路径期望也已与加固后的 file-import sandbox 和跨平台 `/tmp` 解析对齐，使 main 恢复绿色（[`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)）。
- **2026-05-03** 🛡️ **安全加固补丁**：收紧非本地部署的默认 API 认证，保护敏感 run/session/swarm 读取，限制上传与本地文件读取边界，按入口限制 shell-capable 工具，导入前校验生成策略加载，并让 Docker 镜像默认以非 root 用户和 localhost-only 端口发布运行。本地 CLI 和 localhost Web UI 工作流仍保持低摩擦；远程 API/Web 部署应设置 `API_AUTH_KEY`。
- **2026-05-02** 🧭 **股息分析与更清晰路线图**：新增 `dividend-analysis` skill，用于收入型股票、派息可持续性、股息增长、股东收益、除息机制和收益率陷阱检查，并由 bundled-skill 回归测试固定。公开路线图现在聚焦即将开展的工作：Research Autopilot、Data Bridge、Options Lab、Portfolio Studio、Alpha Zoo、Research Delivery、Trust Layer 和 Community sharing。
- **2026-05-01** 🔥 **相关性热力图、OpenAI Codex OAuth 与 A 股 pre-ST 筛选**：新的相关性 dashboard/API 会计算滚动收益相关性，并为组合与标的分析渲染 ECharts 热力图（[#64](https://github.com/HKUDS/Vibe-Trading/pull/64)）。OpenAI Codex provider 现在通过 `vibe-trading provider login openai-codex` 使用 ChatGPT OAuth，并加入 Settings 元数据和 adapter 回归测试（[#65](https://github.com/HKUDS/Vibe-Trading/pull/65)）。新增并加固 `ashare-pre-st-filter` skill，用于 A 股 ST/*ST 风险筛查，包括 Sina 处罚相关性过滤，避免证券账户提及错误抬高 E2 计数（[#63](https://github.com/HKUDS/Vibe-Trading/pull/63)）。
- **2026-04-30** ⚙️ **Web UI Settings 与 validation CLI 加固**：新增 Settings 页面，用于配置 LLM provider/model、base URL、reasoning effort 和数据源凭据，由本地/认证保护的 settings API 与数据驱动的 provider metadata 支撑（[#57](https://github.com/HKUDS/Vibe-Trading/pull/57)）。同时加固 `python -m backtest.validation <run_dir>`，让缺失、空白、格式错误、不存在和非目录输入在 validation 开始前以清晰的面向操作者的信息失败（[#60](https://github.com/HKUDS/Vibe-Trading/pull/60)）。
- **2026-04-28** 🚀 **v0.1.6 发布**（`pip install -U vibe-trading-ai`）：修复 `pip install` / `uv tool install` 后 `vibe-trading --swarm-presets` 返回空的问题（[#55](https://github.com/HKUDS/Vibe-Trading/issues/55)）—— preset YAML 现在打包在 `src.swarm` 包内，并由 6 个回归测试固定。同时 AKShare loader 会将 ETF（`510300.SH`）和外汇（`USDCNH`）正确路由到对应 endpoint，并强化 registry fallback。汇总 v0.1.5 以来的所有内容：benchmark comparison panel、`/upload` streaming + size limits、Futu loader（港股 + A 股）、vnpy export skill、安全加固、前端懒加载（688KB → 262KB）。
- **2026-04-27** 📊 **Benchmark panel 与上传安全**：回测输出现在包含 benchmark comparison panel（ticker / benchmark return / excess return / information ratio），并通过 yfinance 支持 SPY、沪深 300 等解析（[#48](https://github.com/HKUDS/Vibe-Trading/issues/48)）。此外 `/upload` 会以 1 MB chunk 流式读取请求体，并在超过 `MAX_UPLOAD_SIZE` 时中止，在超大/畸形客户端场景下限制内存使用（[#53](https://github.com/HKUDS/Vibe-Trading/pull/53)）——由 4 个回归用例固定。
- **2026-04-22** 🛡️ **加固与新集成**：`safe_path` + journal/shadow tool sandbox 强制路径 containment，`MANIFEST.in` 在 sdist 中包含 `.env.example` / tests / Docker files，route-level lazy loading 将前端初始 bundle 从 688KB 降到 262KB。另有面向港股与 A 股 equities 的 Futu data loader（[#47](https://github.com/HKUDS/Vibe-Trading/pull/47)）和 vnpy CtaTemplate export skill（[#46](https://github.com/HKUDS/Vibe-Trading/pull/46)）。
- **2026-04-21** 🛡️ **Workspace 与文档**：相对 `run_dir` 会规范化到 active run dir（[#43](https://github.com/HKUDS/Vibe-Trading/pull/43)）。README 使用示例（[#45](https://github.com/HKUDS/Vibe-Trading/pull/45)）。
- **2026-04-20** 🔌 **Reasoning 与 Swarm**：所有 `ChatOpenAI` 路径都会保留 `reasoning_content`，Kimi / DeepSeek / Qwen thinking 全链路可用（[#39](https://github.com/HKUDS/Vibe-Trading/issues/39)）。Swarm streaming 与干净的 Ctrl+C（[#42](https://github.com/HKUDS/Vibe-Trading/issues/42)）。
- **2026-04-19** 📦 **v0.1.5**：发布到 PyPI 与 ClawHub。`python-multipart` CVE 下限升级，接入 5 个新 MCP tools（`analyze_trade_journal` + 4 个 shadow-account tools），修复 `pattern_recognition` → `pattern` registry，Docker 依赖对齐，SKILL manifest 同步（22 MCP tools / 71 skills）。
- **2026-04-18** 👥 **Shadow Account**：从券商流水中提取你的策略规则 → 跨市场回测 shadow → 生成 8 节 HTML/PDF 报告，明确展示你错过了多少机会（规则违背、过早离场、错过信号、反事实交易）。新增 4 个工具、1 个 skill，总计 32 tools。Trade Journal + Shadow Account 示例现在已在 Web UI 欢迎页中提供。
- **2026-04-17** 📊 **Trade Journal Analyzer 与 Universal File Reader**：上传券商导出（同花顺/东财/富途/generic CSV）→ 自动生成交易画像（持仓天数、胜率、盈亏比、回撤）+ 4 类行为偏差诊断（处置效应、过度交易、追涨、锚定）。`read_document` 现在以统一调用分发 PDF、Word、Excel、PowerPoint、图片（OCR）和 40+ 文本格式。
- **2026-04-16** 🧠 **Agent Harness**：跨 session 持久记忆、FTS5 session search、自进化 skills（完整 CRUD）、5 层上下文压缩、read/write tool batching。27 tools，107 个新增测试。
- **2026-04-15** 🤖 **Z.ai 与 MiniMax**：Z.ai provider（[#35](https://github.com/HKUDS/Vibe-Trading/pull/35)），MiniMax temperature 修复与模型更新（[#33](https://github.com/HKUDS/Vibe-Trading/pull/33)）。13 个 providers。
- **2026-04-14** 🔧 **MCP 稳定性**：修复 stdio transport 下 backtest tool 的 `Connection closed` 错误（[#32](https://github.com/HKUDS/Vibe-Trading/pull/32)）。
- **2026-04-13** 🌐 **跨市场组合回测**：新的 `CompositeEngine` 可用共享资金池和分市场规则回测混合市场组合（例如 A 股 + crypto）。同时修复 swarm template variable fallback 和前端 timeout。
- **2026-04-12** 🌍 **多平台导出**：`/pine` 可一条命令将策略导出到 TradingView（Pine Script v6）、TDX（通达信/同花顺/东方财富）和 MetaTrader 5（MQL5）。
- **2026-04-11** 🛡️ **可靠性与 DX**：`vibe-trading init` .env bootstrap（[#19](https://github.com/HKUDS/Vibe-Trading/pull/19)）、预检、运行时数据源 fallback、加固的回测引擎。多语言 README（[#21](https://github.com/HKUDS/Vibe-Trading/pull/21)）。
- **2026-04-10** 📦 **v0.1.4**：Docker 修复（[#8](https://github.com/HKUDS/Vibe-Trading/issues/8)）、`web_search` MCP tool、12 个 LLM providers、`akshare`/`ccxt` 依赖。发布到 PyPI 与 ClawHub。
- **2026-04-09** 📊 **Backtest Wave 2**：ChinaFutures、GlobalFutures、Forex、Options v2 engines。Monte Carlo、Bootstrap CI、Walk-Forward validation。
- **2026-04-08** 🔧 **多市场回测**，支持分市场规则、Pine Script v6 导出、5 个数据源自动 fallback。

</details>

---

## ✨ Key Features

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="Self-improving trading agent"/><br>
      <h3>🔍 自我改进的交易智能体</h3>
      <div align="left">
        • 自然语言市场研究<br>
        • 策略草稿与文件/网页分析<br>
        • 由记忆驱动的研究工作流
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="Multi-agent trading teams"/><br>
      <h3>🐝 多智能体交易团队</h3>
      <div align="left">
        • 投资、量化、加密与风控团队<br>
        • 流式进度与持久化报告<br>
        • Worker 基于已获取的市场数据展开分析
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="Cross-market data and backtesting"/><br>
      <h3>📊 跨市场数据与回测</h3>
      <div align="left">
        • A 股、港股、美股、加密、期货与外汇<br>
        • 数据 fallback 与组合回测<br>
        • PIT 数据、验证与 run cards
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • 券商交易日志行为诊断<br>
        • 基于规则的 Shadow Account 对比<br>
        • 可导出的审计报告与策略代码
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 What Is Vibe-Trading?

Vibe-Trading 是一个开源研究工作台，用于把金融问题转化为可运行的分析。它将自然语言提示连接到市场数据加载器、策略生成、回测引擎、报告、导出和持久研究记忆。

它面向研究、模拟和回测——并且在你选择时，可通过你自己授权的券商（如 Robinhood Agentic Trading）进行自主交易。它不托管任何资金，绝不超出你设定的限额交易，且你可随时一键停止。

---

## ✨ What You Can Do

| 任务 | 输出 |
|------|------|
| **提出交易问题** | 结合工具、数据、文档和可复用 session 上下文的市场研究。 |
| **回测策略想法** | 策略代码、指标、benchmark 上下文、验证 artifacts 和 run cards。 |
| **复盘自己的交易** | 券商日志解析、行为诊断、规则提取和 Shadow Account 对比。 |
| **改进重复研究** | 持久记忆和可编辑 skills 将有用流程变成可复用工作流。 |
| **运行分析师团队** | 面向投资、量化、加密、宏观和风控工作流的多智能体研究评审。 |
| **交付可用成果** | 报告、TradingView Pine Script、TDX、MetaTrader 5、MCP tools，以及可延续的研究 sessions。 |
| **跑预置 alpha zoo 横评** | 452 个 alpha 因子（Qlib 158 + Kakushadze 101 + GTJA 191 + FF5 + Carhart），一行 CLI 在你选的 universe 上算 IC + IR + alive/reversed/dead 分类 |

---

## ⚡ Quick Example

```bash
pip install vibe-trading-ai

# 自然语言研究
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# 一行 CLI 跑预置 alpha zoo 横评
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 👥 Shadow Account

Shadow Account 从你自己的交易记录出发，而不是从通用策略模板出发。

上传券商导出，让智能体总结你的交易行为，然后将真实交易路径与基于规则的 shadow strategy 进行对比。

| 步骤 | 智能体输出 |
|------|------------|
| **1. 读取交易日志** | 解析来自同花顺、东方财富、富途和 generic CSV 格式的券商导出。 |
| **2. 生成行为画像** | 持仓天数、胜率、盈亏比、回撤、处置效应、过度交易、追涨和锚定检查。 |
| **3. 提取你的规则** | 将反复出现的入场/出场行为转化为明确策略画像，而不是空泛总结。 |
| **4. 运行 shadow** | 回测提取出的规则，并高亮规则违背、过早离场、错过信号和替代交易路径。 |
| **5. 交付报告** | 生成可检查、可归档或在后续 session 中继续精修的 HTML/PDF 报告。 |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 🧪 Research Workflow

多数运行都会遵循同一条证据路径：路由请求、加载正确的市场上下文、执行工具、验证输出，并保持 artifacts 可检查。

| 层 | 发生什么 |
|----|----------|
| **Plan** | 选择相关金融 skills、tools、数据源，以及在有帮助时选择 swarm preset。 |
| **Ground** | 通过可用 loader 拉取 A 股、港股/美股、加密、期货、外汇、文档或网页上下文。 |
| **Execute** | 生成可测试的策略代码，运行工具，并使用匹配的回测引擎或分析工作流。 |
| **Validate** | 在适用时加入指标、benchmark comparison、Monte Carlo、Bootstrap、Walk-Forward、run cards 和 warnings。 |
| **Deliver** | 返回报告、artifacts、tool traces，以及面向 TradingView、TDX、MetaTrader 5、MCP clients 或后续 sessions 的导出。 |

---

## 📡 数据源与智能 Fallback

一次 `get_market_data` 调用，**18 个行情数据源**。设 `source: "auto"`——loader 按符号自动选源，再沿按 **被封 IP 风险** 排序的同市场链向下走（永不封的公开源在前，限速 / 需 key 的在后）。零配置，无单点故障。

| Source | Markets | Auth | Role |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share | none | never IP-banned (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / US / HK | none | OHLCV + deep fundamentals & flow tools (throttled) |
| `baostock` · `akshare` | A (+ US/HK/futures/macro/fx) | none | free fallbacks |
| `tushare` | A / futures / fund / macro | token | richest A-share |
| `yahoo` · `sina` · `stooq` | US (/HK) | none | direct chart/quotes/options · K-line to 1984 · EOD CSV |
| `yfinance` | US / HK | none | wrapper |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | US | key | optional providers |
| `okx` · `ccxt` | crypto | none | OKX + 100+ exchanges |
| `futu` | HK / A | OpenD | optional local FutuOpenD |
| `local` | any | none | your own CSV / Parquet / DuckDB via `local:` prefix |

**Fallback 链（按被封 IP 风险排序）：**

- **A股** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **美股** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `akshare` · `local`
- **港股** → `eastmoney` · `yahoo` · `futu` · `yfinance` · `akshare` · `local`
- **加密** → `okx` · `ccxt` · `yfinance` · `local` &nbsp;·&nbsp; *(期货 / 基金 / 宏观 / 外汇 → `tushare`/`akshare` → `local`)*

除 OHLCV 外，**18 个只读数据工具**深入基本面与资金面——资金流、龙虎榜、北向、两融、大宗交易、股东户数、解禁、板块、研报、新闻、SEC 文件、财务报表、期权链、机构持仓、全市场筛选、代码搜索、宏观——全部经 MCP 暴露。显式 `local:` 源永不静默 fallback 到网络源。

---

## 🔩 Detailed Capabilities

为保持主 README 易读，详细清单折叠在下方。需要检查可用构件时可展开查看。

<details>
<summary><b>Finance Skill Library</b> <sub>8 个类别中的 77 个 skills</sub></summary>

- 📊 77 个专业金融 skills，分布在 8 个类别中
- 🌐 覆盖传统市场、加密与 DeFi
- 🔬 从数据源到量化研究的完整能力链路

| 类别 | Skills | 示例 |
|------|--------|------|
| Data Source | 9 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 17 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 11 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `alpha-zoo` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>自定义数据源</b> <sub>注册你自己的历史 OHLCV loader</sub></summary>

需要一个我们没有内置 loader 的市场或数据商？自己加一个历史 K 线 loader，用
`source="<name>"` 选用即可。以下步骤会改动包源码，请从 clone 运行（`pip install -e .`）。

1. **编写 loader** —— 新建 `agent/backtest/loaders/<name>_loader.py`，写一个满足
   `DataLoaderProtocol` 的类（duck-typed，无需基类），并打上 `@register`：

   ```python
   import pandas as pd
   from backtest.loaders.registry import register

   @register
   class DataLoader:
       name = "mysource"            # the value you pass as source=
       markets = {"us_equity"}      # a_share/us_equity/hk_equity/crypto/futures/fund/macro/forex
       requires_auth = False

       def is_available(self) -> bool:
           return True              # token present? network reachable?

       def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
           # return {symbol: DataFrame indexed by trade_date,
           #         columns: open, high, low, close, volume}
           ...
   ```

2. **注册模块** 让 `@register` 生效 —— 把 `"backtest.loaders.<name>_loader"` 加进
   `agent/backtest/loaders/registry.py` 的 `_loader_modules`。
3. **放行名称** 通过配置校验 —— 把 `"mysource"` 加进 `agent/backtest/runner.py`
   的 `_VALID_SOURCES`。
4. *（可选）* 把它放进 `registry.py` 中某个市场的 `FALLBACK_CHAINS`，让
   `source="auto"` 也能命中它。
5. **使用** —— 在回测配置里写 `source="mysource"`，或经 CLI / agent 调用。

> **实时 ticks / 盘口深度不在 loader 范围内** —— loader 层只负责 point-in-time
> 历史 K 线。实时行情走 broker connector：加密用 `okx` / `binance` / `ccxt`，
> 股票用 `futu` / `tiger`。

</details>

<details>
<summary><b>Preset Trading Teams</b> <sub>29 个 swarm presets</sub></summary>

- 🏢 29 个开箱即用的智能体团队
- ⚡ 预配置金融工作流
- 🎯 投资、交易与风险管理 presets

| Preset | 工作流 |
|--------|--------|
| `investment_committee` | 多空辩论 → 风险审查 → PM 最终决策 |
| `global_equities_desk` | A 股 + 港/美股 + 加密研究员 → 全球策略师 |
| `crypto_trading_desk` | Funding/basis + liquidation + flow → 风险经理 |
| `earnings_research_desk` | 基本面 + 预期修正 + options → 财报策略师 |
| `macro_rates_fx_desk` | 利率 + 外汇 + 商品 → 宏观 PM |
| `quant_strategy_desk` | 筛选 + 因子研究 → 回测 → 风险审计 |
| `technical_analysis_panel` | 经典 TA + Ichimoku + harmonic + Elliott + SMC → 共识 |
| `risk_committee` | 回撤 + 尾部风险 + regime review → 审批 |
| `global_allocation_committee` | A 股 + 加密 + 港/美股 → 跨市场配置 |

<sub>另有 20+ 专业 presets，可运行 vibe-trading --swarm-presets 查看全部。

</sub>

</details>

<details>
<summary><b>Alpha Zoo</b> <sub>452 个预置 alpha，覆盖 4 个 zoo</sub></summary>

- 🧬 452 个横截面 alpha，算子层即禁用 lookahead
- 📈 一条 CLI 命令完成 IC + IR + alive/reversed/dead 分类
- 🔬 AST 纯函数门禁 + 300 行 lookahead 哨兵测试 + `pytest-socket` 网络阻断
- 📦 Qlib 部分附 Apache-2 出处声明；每个 zoo 一份 `LICENSE.md`，声明公式属于数学内容
- 🤝 社区 PR 走 Developer Certificate of Origin (DCO) 签名流程

| Zoo | 数量 | 来源 | 许可 |
|-----|------|------|------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158`（Apache-2.0，锁定 commit） | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991 | 公式属于数学内容 |
| **gtja191** | 191 | 国君证券 (2014)《191 个短周期交易型 alpha 因子》研报 | 公式属于数学内容 |
| **academic** | 6 | Fama-French 5 因子 + Carhart 动量（基于价格的代理实现） | 公开学术文献 |

运行 `vibe-trading alpha list` 浏览全部因子，`vibe-trading alpha show <id>` 查看公式与源码，`vibe-trading alpha bench --zoo X --universe Y --period Z` 给一整个 zoo 打分。

</details>

## 🎬 Demo

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
<td colspan="2" align="center"><sub>☝️ 自然语言回测与多智能体 swarm 辩论 — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 Quick Start

### 一行安装（PyPI）

```bash
pip install vibe-trading-ai
```

然后运行第一个研究任务：

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **包名与命令：** PyPI 包名是 `vibe-trading-ai`。安装后会获得三个命令：
>
> | 命令 | 用途 |
> |------|------|
> | `vibe-trading` | 交互式 CLI / TUI |
> | `vibe-trading serve` | 启动 FastAPI web server |
> | `vibe-trading-mcp` | 启动 MCP server（用于 Claude Desktop、OpenClaw、Cursor 等） |

```bash
vibe-trading init              # interactive .env setup
vibe-trading                   # launch CLI
vibe-trading serve --port 8899 # launch web UI
vibe-trading-mcp               # start MCP server (stdio)
```

### 或选择一种路径

| 路径 | 最适合 | 时间 |
|------|--------|------|
| **A. Docker** | 立即试用，零本地配置 | 2 min |
| **B. Local install** | 开发，完整 CLI 访问 | 5 min |
| **C. MCP plugin** | 接入你现有的智能体 | 3 min |
| **D. ClawHub** | 一条命令，无需 clone | 1 min |

### 前置条件

- 任意受支持 provider 的 **LLM API key**，或使用 **Ollama** 本地运行（无需 key）
- 路径 B 需要 **Python 3.11+**
- 路径 A 需要 **Docker**
- OpenAI Codex 也可通过 ChatGPT OAuth 使用：设置 `LANGCHAIN_PROVIDER=openai-codex`，然后运行 `vibe-trading provider login openai-codex`。它不使用 `OPENAI_API_KEY`。

> **支持的 LLM providers：** OpenRouter、OpenAI、DeepSeek、Gemini、Groq、DashScope/Qwen、Zhipu、Moonshot/Kimi、MiniMax、Xiaomi MIMO、Z.ai、Ollama（本地）。配置见 `.env.example`。

> **提示：** 由于自动 fallback，所有市场都可以在没有任何 API key 的情况下工作。yfinance（港/美股）、OKX（加密）、mootdx（A 股，TCP 直连不封 IP）和 AKShare（A 股、美股、港股、期货、外汇）都是免费的。Tushare token 是可选项 —— mootdx 是首选的免 token A 股 fallback，AKShare 作为覆盖更广的兜底。

### Path A: Docker（零配置）

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

打开 `http://localhost:8899`。后端 + 前端在同一个容器中运行。

Docker 默认将后端发布在 `127.0.0.1:8899`，并以非 root 容器用户运行应用。如果你有意将 API 暴露到本机之外，请设置强 `API_AUTH_KEY`，并让客户端发送 `Authorization: Bearer <key>`。

### Path B: Local install

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

<details>
<summary><b>启动 Web UI（可选）</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev
```

打开 `http://localhost:5899`。前端会将 API 调用代理到 `localhost:8899`。

**生产模式（单 server）：**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

> [!NOTE]
> `vibe-trading serve` 绑定 `0.0.0.0`，但默认只信任 loopback：在**同一台机器**上打开 UI（`http://localhost:8899`）零配置即可用。若你从**另一台机器、虚拟机宿主机或局域网内的手机**访问，敏感接口会返回 `403`，聊天会提示 “Remote API access requires an API key”——请在 `agent/.env` 里设置一个强 `API_AUTH_KEY`，重启，并在 **Settings** 中输入同一个 key。（Docker Desktop 宿主网关场景：设 `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` 并保持默认的 `127.0.0.1` 端口绑定。）

</details>

### Path C: MCP plugin

见下方 [MCP Plugin](#-mcp-plugin) 章节。

### Path D: ClawHub（一条命令）

```bash
npx clawhub@latest install vibe-trading --force
```

skill + MCP config 会下载到你的智能体 skills 目录。详情见 [ClawHub install](#-mcp-plugin)。

---

## 🧠 Environment Variables

将 `agent/.env.example` 复制为 `agent/.env`，并取消注释你想使用的 provider block。每个 provider 需要 3-4 个变量：

| 变量 | 必需 | 说明 |
|------|:----:|------|
| `LANGCHAIN_PROVIDER` | Yes | Provider 名称（`openrouter`, `deepseek`, `groq`, `ollama` 等） |
| `<PROVIDER>_API_KEY` | Yes* | API key（`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` 等） |
| `<PROVIDER>_BASE_URL` | Yes | API endpoint URL |
| `LANGCHAIN_MODEL_NAME` | Yes | 模型名称（例如 `deepseek-v4-pro`） |
| `TUSHARE_TOKEN` | No | A 股数据的 Tushare Pro token（会 fallback 到 AKShare） |
| `TIMEOUT_SECONDS` | No | LLM 调用超时，默认 120s |
| `API_AUTH_KEY` | 网络部署推荐 | API 可被非本地客户端访问时要求的 Bearer token |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | No | 在远程 API/MCP-SSE 风格部署中显式启用 shell-capable tools |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | No | 文档和券商日志导入额外允许的逗号分隔 roots |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | No | 生成代码 run directories 额外允许的逗号分隔 roots |

<sub>* Ollama 不需要 API key。OpenAI Codex 使用 ChatGPT OAuth，并通过 `oauth-cli-kit` 存储 token，不写入 `agent/.env`。</sub>

**免费数据（无需 key）：** A 股通过 AKShare，港/美股通过 yfinance，加密通过 OKX，100+ 加密交易所通过 CCXT。系统会为每个市场自动选择最佳可用数据源。

### 🎯 Recommended Models

Vibe-Trading 是高度依赖工具的智能体：skills、backtests、memory 和 swarms 都会通过工具调用流转。模型选择会直接决定智能体是实际使用工具，还是从训练数据中编造答案。

| 档位 | 示例 | 使用场景 |
|------|------|----------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | 复杂 swarms（3+ agents）、长研究 sessions、论文级分析 |
| **Sweet spot**（默认） | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | 日常主力，约 1/10 成本下具备可靠工具调用 |
| **避免用于 agent** | `*-nano`, `*-flash-lite`, `*-coder-next`, 小型 / 蒸馏变体 | 工具调用不可靠，智能体会看起来像是在“凭记忆回答”，而不是加载 skills 或运行回测 |

默认 `agent/.env.example` 使用 DeepSeek 官方 API + `deepseek-v4-pro`；OpenRouter 用户可以使用 `deepseek/deepseek-v4-pro`。

---

## 🖥 CLI Reference

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # 浏览 452 个预置 alpha；支持 show / bench / compare / export-manifest 子命令
```

<details>
<summary><b>TUI 内 slash commands</b></summary>

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有命令 |
| `/skills` | 列出全部 77 个 finance skills |
| `/swarm` | 列出 29 个 swarm team presets |
| `/swarm run <preset> [vars_json]` | 运行一个 swarm team，并实时流式展示 |
| `/swarm list` | Swarm 运行历史 |
| `/swarm show <run_id>` | Swarm 运行详情 |
| `/swarm cancel <run_id>` | 取消运行中的 swarm |
| `/list` | 最近 runs |
| `/show <run_id>` | Run 详情 + 指标 |
| `/code <run_id>` | 生成的策略代码 |
| `/pine <run_id>` | 导出指标（TradingView + TDX + MT5） |
| `/trace <run_id>` | 完整执行回放 |
| `/continue <run_id> <prompt>` | 用新指令继续一个 run |
| `/sessions` | 列出 chat sessions |
| `/settings` | 显示运行时配置 |
| `/clear` | 清屏 |
| `/quit` | 退出 |

</details>

<details>
<summary><b>Single run 与 flags</b></summary>

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
vibe-trading --pine <run_id>           # Export indicators (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
vibe-trading alpha list --zoo gtja191 --limit 10
vibe-trading alpha show gtja191_171
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

</details>

---

## 💡 Examples

### Strategy & Backtesting

```bash
# Moving average crossover on US equities
vibe-trading run -p "Backtest a 20/50-day moving average crossover on AAPL for the past year, show Sharpe ratio and max drawdown"

# RSI mean-reversion on crypto
vibe-trading run -p "Test RSI(14) mean-reversion on BTC-USDT: buy below 30, sell above 70, last 6 months"

# Multi-factor strategy on A-shares
vibe-trading run -p "Backtest a momentum + value + quality multi-factor strategy on CSI 300 constituents over 2 years"

# After backtesting, export to TradingView / TDX / MetaTrader 5
vibe-trading --pine <run_id>
```

**一行命令横评预置 alpha zoo**：
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**浏览目录** + 查看单个 alpha：
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**用 zoo 因子组合多因子信号**（Python）：
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

### Market Research

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Swarm Workflows

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"topic": "Is TSLA a buy at current levels?"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'
```

### Cross-Session Memory

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### Upload & Analyze Documents

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

## 🌐 API Server

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | 说明 |
|--------|----------|------|
| `GET` | `/runs` | 列出 runs |
| `GET` | `/runs/{run_id}` | Run 详情 |
| `GET` | `/runs/{run_id}/pine` | 多平台指标导出 |
| `POST` | `/sessions` | 创建 session |
| `POST` | `/sessions/{id}/messages` | 发送消息 |
| `GET` | `/sessions/{id}/events` | SSE event stream |
| `POST` | `/upload` | 上传 PDF/file |
| `GET` | `/swarm/presets` | 列出 swarm presets |
| `POST` | `/swarm/runs` | 启动 swarm run |
| `GET` | `/swarm/runs/{id}/events` | Swarm SSE stream |
| `GET` | `/alpha/list` | 按 zoo/theme/universe 过滤列出 alpha |
| `GET` | `/alpha/{alpha_id}` | Alpha 元数据 + 源代码 |
| `POST` | `/alpha/bench` | 启动一个 bench job（返回 `job_id`） |
| `GET` | `/alpha/bench/{job_id}/stream` | SSE 进度流 |
| `GET` | `/settings/llm` | 读取 Web UI LLM settings |
| `PUT` | `/settings/llm` | 更新本地 LLM settings |
| `GET` | `/settings/data-sources` | 读取本地数据源 settings |
| `PUT` | `/settings/data-sources` | 更新本地数据源 settings |

交互式文档：`http://localhost:8899/docs`

### Security defaults

对于 localhost 开发，`vibe-trading serve` 会保持浏览器工作流简单。对任何非本地客户端，敏感 API endpoints 都要求 `API_AUTH_KEY`；JSON/upload 请求请使用 `Authorization: Bearer <key>`。浏览器 EventSource streams 会在你于 Settings 中输入同一个 key 后由 Web UI 处理。

Shell-capable tools 可用于本地 CLI 与可信 localhost 工作流，但不会暴露给远程 API sessions，除非你显式设置 `VIBE_TRADING_ENABLE_SHELL_TOOLS=1`。文档和日志读取器默认限制在 upload/import roots 内；请将文件放在 `agent/uploads`、`agent/runs`、`./uploads`、`./data`、`~/.vibe-trading/uploads` 或 `~/.vibe-trading/imports` 下，或通过 `VIBE_TRADING_ALLOWED_FILE_ROOTS` 添加专用目录。

### Web UI Settings

Web UI Settings 页面允许本地用户更新 LLM provider/model、base URL、generation parameters、reasoning effort，以及 Tushare token 等可选市场数据凭据。Settings 会持久化到 `agent/.env`；provider defaults 从 `agent/src/providers/llm_providers.json` 加载。

Settings 读取无副作用：`GET /settings/llm` 和 `GET /settings/data-sources` 永远不会创建 `agent/.env`，并且只返回项目相对路径。Settings 读写可能暴露凭据状态或更新凭据/运行时环境，因此在配置了 `API_AUTH_KEY` 时会要求认证。如果 dev mode 下未设置 `API_AUTH_KEY`，settings 访问只接受 loopback clients。

---

## 🔌 MCP Plugin

Vibe-Trading 为任何 MCP-compatible client 暴露 36 个 MCP tools。它作为 stdio subprocess 运行，无需 server setup。核心 research tools 对港股/美股/加密零 API key 可用；trading connector tools 使用当前选择的 connector profile；只有 `run_swarm` 需要 LLM key。

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
<summary><b>Cursor / Windsurf / other MCP clients</b></summary>

```bash
vibe-trading-mcp                  # stdio (default)
vibe-trading-mcp --transport sse  # SSE for web clients
```

</details>

**暴露的 MCP tools（36）：** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`.

<details>
<summary><b>从 ClawHub 安装（一条命令）</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> 由于该 skill 引用了外部 API，会触发 VirusTotal 自动扫描，因此需要 `--force`。代码完全开源，可自行检查。

这会将 skill + MCP config 下载到你的智能体 skills 目录。无需 clone。

在 ClawHub 浏览：[clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — 自进化 skills</b></summary>

全部 77 个 finance skills 都发布在 [open-space.cloud](https://open-space.cloud)，并通过 OpenSpace 的自进化引擎自主演进。

要配合 OpenSpace 使用，请将两个 MCP servers 都加入你的 agent config：

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

OpenSpace 会自动发现全部 77 个 skills，启用 auto-fix、auto-improve 和社区分享。在任意已连接 OpenSpace 的智能体中，可通过 `search_skills("finance backtest")` 搜索 Vibe-Trading skills。

</details>

---

## 📁 Project Structure

<details>
<summary><b>点击展开</b></summary>

```
Vibe-Trading/
├── agent/                          # 后端（Python）
│   ├── cli/                        # CLI 包 —— 交互式 TUI + 子命令
│   ├── api_server.py               # FastAPI server —— runs、sessions、upload、swarm、SSE
│   ├── mcp_server.py               # MCP server —— 54 个工具，面向 OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent 内核
│   │   │   ├── loop.py             #   5 层上下文压缩 + 读/写工具批处理
│   │   │   ├── context.py          #   system prompt + 持久记忆自动召回
│   │   │   ├── skills.py           #   skill loader（77 个内置 + 通过 CRUD 创建的用户 skill）
│   │   │   ├── tools.py            #   tool 基类 + 注册表
│   │   │   ├── memory.py           #   每个 run 的轻量 workspace 状态
│   │   │   ├── frontmatter.py      #   共享的 YAML frontmatter 解析器
│   │   │   └── trace.py            #   执行 trace 写入器
│   │   │
│   │   ├── memory/                 # 跨 session 持久记忆
│   │   │   └── persistent.py       #   基于文件的记忆（~/.vibe-trading/memory/）
│   │   │
│   │   ├── tools/                  # 31 个自动发现的 agent 工具
│   │   │   ├── backtest_tool.py    #   运行回测
│   │   │   ├── remember_tool.py    #   跨 session 记忆（save/recall/forget）
│   │   │   ├── skill_writer_tool.py #  skill CRUD（save/patch/delete/file）
│   │   │   ├── session_search_tool.py # FTS5 跨 session 搜索
│   │   │   ├── swarm_tool.py       #   启动 swarm team
│   │   │   ├── web_search_tool.py  #   DuckDuckGo 网络搜索
│   │   │   └── ...                 #   bash、文件 I/O、因子分析、期权、alpha 浏览 + 横评等
│   │   │
│   │   ├── factors/                # Alpha Zoo —— 4 个 zoo 共 452 个 alpha
│   │   │   ├── base.py             #   19 个算子（rank/scale/ts_*/delta/decay_linear/safe_div/vwap）
│   │   │   ├── registry.py         #   纯 AST 元数据加载 + 惰性计算 + sanity 校验
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead 分类
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (6)
│   │   │
│   │   ├── api/                    # FastAPI 路由模块
│   │   │   └── alpha_routes.py     #   /alpha/list、/alpha/{id}、/alpha/bench、SSE 流
│   │   │
│   │   ├── skills/                 # 8 个类别共 77 个 finance skills（每个一份 SKILL.md）
│   │   ├── swarm/                  # Swarm DAG 执行引擎
│   │   │   └── presets/            #   29 个 swarm preset YAML 定义
│   │   ├── session/                # 多轮对话 + FTS5 session 搜索
│   │   └── providers/              # LLM provider 抽象层
│   │
│   └── backtest/                   # 回测引擎
│       ├── engines/                #   7 个引擎 + 跨市场 composite 引擎 + options_portfolio
│       ├── loaders/                #   18 个数据源：tushare、okx、yfinance、akshare、baostock、tencent、mootdx、ccxt、futu、local、eastmoney、sina、stooq、yahoo、finnhub、alphavantage、tiingo、fmp
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + 自动 fallback 链路
│       └── optimizers/             #   MVO、equal vol、max div、risk parity
│
├── frontend/                       # Web UI（React 19 + Vite + TypeScript）
│   └── src/
│       ├── pages/                  #   Home、Agent、AlphaZoo、RunDetail、Compare、Correlation、Settings
│       ├── components/             #   chat、charts、layout
│       └── stores/                 #   Zustand 状态管理
│
├── Dockerfile                      # 多阶段构建
├── docker-compose.yml              # 一条命令部署
├── pyproject.toml                  # 包配置 + CLI entrypoint
├── tools/                          # 仓库级 CI 辅助脚本
│   └── ci_grep_gates.sh            # 拦截 yaml.load / 商标 / 个股数据泄露
└── LICENSE                         # MIT
```

</details>

---

## 🏛 Ecosystem

Vibe-Trading 是 **[HKUDS](https://github.com/HKUDS)** 智能体生态的一部分：

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>Ultra-Lightweight Personal AI Assistant</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/AI-Trader"><b>AI-Trader</b></a><br>
      <sub>Agent-Native Signal &amp; Copy Trading Platform</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>Making All Software Agent-Native</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>Self-Evolving AI Agent Skills</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Agent Swarm Intelligence</sub>
    </td>
  </tr>
</table>

---

## 🗺 Roadmap

> 我们按阶段交付。工作开始时，条目会移动到 [Issues](https://github.com/HKUDS/Vibe-Trading/issues)。

| 阶段 | 功能 | 状态 |
|------|------|------|
| **Trust Layer** | 可复现 run cards 已输出并展示在 Run Detail；v1 会补充 tool traces 与 citations | v0 已发布 |
| **Hypothesis Registry** | 持久化研究假设：lifecycle status、data sources、skills、run-card links 与 invalidation notes | Backend MVP 已发布 |
| **Research Autopilot** | 手动触发优先的研究循环：hypothesis → deterministic backtest → evidence report | 下一步 |
| **Data Bridge** | 自带数据：本地 CSV/Parquet/SQL connectors 与 schema mapping | Planned |
| **Options Lab** | Vol surface、Greeks dashboard、payoff/scenario explorer | Planned |
| **Portfolio Studio** | Risk x-ray、constraints、turnover-aware optimizer、rebalance notes | Planned |
| **Alpha Zoo** | 452 个预置 alpha 因子（Qlib 158 + Kakushadze 101 + GTJA 191 + FF5 + Carhart），一行 CLI 跑横评，agent 集成，Web UI 浏览 | **已发布 0.1.8** |
| **Research Delivery** | 定时 briefs 到 Slack / Telegram / email-style channels | Planned |
| **Community** | 可分享的 skills、presets 和 strategy cards | Exploring |

---

## Contributing

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

**Good first issues** 使用 [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 标记，可选择一个开始。

想贡献更大的内容？请查看上方 [Roadmap](#-roadmap)，并在开始前先开 issue 讨论。

---

## Contributors

感谢所有为 Vibe-Trading 做出贡献的人！

近期 v0.1.9 周期贡献者与致谢：

- @toanalien — session JSONL 崩溃加固 (#147)、迭代预算用尽时优雅退出 (#148)、LLM 生成 signal engine 的预检校验 (#149)、跨浏览器 Full Report 链接 (#150)
- @ai7eam-dev — 跨市场相关性时间戳对齐 (#158),以及会话运行状态指示器 + swarm 重试 (#159 → #160)
- @shadowinlife — 通过 SSE/HTTP 的远程 MCP server (#125),以及 swarm worker 中 operator 配置的外部 MCP 工具 (#142)
- @DoubleSky123 — 可配置 SSE idle timeout (#157)
- @ArthurXi — Web composer 的 IME 回车提交处理 (#146)
- @omcdecor-cyber — 上游任务失败时阻断下游的 swarm DAG (#145)
- @Soli22de — 带强制随机对照的严格 alpha-bench (#143)
- @ruok808 — CCXT loader 的 proxy 环境变量支持 (#126)
- @faizack — 远程 Ollama base URL 规范化 (#129)
- @fightZy — agent 会话历史加载修复 (#136)
- @lcwSeven — alpha list 接口接受短 universe 名 (#137)
- @Teerapat-Vatpitak — 解析后的 .env 来源日志 (#124)
- @warren618 / Haozhe Wu — connector-first 券商 profile、Robinhood Agentic Trading 通道、Research Goal 运行时、swarm reconcile + retry_run、agent/cli 重构、mootdx loader、发布集成

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## Disclaimer

Vibe-Trading 是研究与交易软件。它不是投资建议，不托管任何资金，也不运营执行场所。仅通过你自己明确授权的券商通道（如 Robinhood Agentic Trading）进行交易，且只在你设定的限额内、你可随时停止。该券商交易能力为实验性，未经我们对接真实券商账户验证——风险自负。历史表现不代表未来结果。

## License

MIT License — see [LICENSE](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

<p align="center">
  ⭐ 如果 <b>Vibe-Trading</b> 对你的研究有帮助，点个 Star 让更多人看到它。
</p>

---

<p align="center">
  感谢访问 <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
