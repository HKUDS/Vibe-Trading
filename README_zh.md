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
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
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

- **2026-05-29** 🔐 **支持 Robinhood Agentic Trading（可选开启、有界自主）**：新增对 Robinhood Agentic Trading 的支持（远程 MCP，OAuth）。默认关闭且只读；仅在用户提交的 mandate（标的/单量/敞口/杠杆/每日笔数）内自主交易，配文件级即时 kill switch、抢占式平仓、mandate 自动过期、完整审计账本，以及一个持久自主 runner。无托管、无场所——券商持有资金并执行，我们只中继意图。实验性 / 风险自负。
- **2026-05-28** 🧪 **Swarm 安全 + 严格 alpha 门 + worker 端 MCP**：Swarm DAG 在上游任务失败时阻断下游任务（[#145](https://github.com/HKUDS/Vibe-Trading/pull/145)）。新增 `run_bench_strict()` 在 IC 门之上加入同 universe 随机控制 + 训练/测试 OOS 切分，识别只是跟随市场 beta 的伪因子（[#143](https://github.com/HKUDS/Vibe-Trading/pull/143)，感谢 @Soli22de）。Swarm worker 现在可以调用 operator 配置的外部 MCP server，信任边界由专项测试固定（[#142](https://github.com/HKUDS/Vibe-Trading/pull/142)，感谢 @shadowinlife）。
- **2026-05-27** 📊 **mootdx A 股数据源 + 输出排版**：新增 `mootdx` loader，走原生通达信 TCP 协议拉 A 股 OHLCV（无需 token，无 IP 速率限制，日线 + 分钟线 25 页 walk-back 分页），在 fallback chain 中位于 tushare 和 akshare 之间（[#107](https://github.com/HKUDS/Vibe-Trading/issues/107)）。CCXT loader 现在会读取 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，使 Binance/OKX 公开数据可在受限网络下拉取（[#126](https://github.com/HKUDS/Vibe-Trading/pull/126)，感谢 @ruok808）。最终回答的渲染也去掉了 CLI 和 Web 上丑陋的全宽 `---` 分隔符：系统提示鼓励 agent 用 markdown 表格和 `##` 标题，CLI 渲染端兜底 strip 孤立 HR，前端 chat 气泡隐藏任何漏过去的 `<hr>`（[#139](https://github.com/HKUDS/Vibe-Trading/issues/139)，感谢 @sdwxm188）。
<details>
<summary>更早的更新</summary>

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

## 🔩 Detailed Capabilities

为保持主 README 易读，详细清单折叠在下方。需要检查可用构件时可展开查看。

<details>
<summary><b>Finance Skill Library</b> <sub>8 个类别中的 77 个 skills</sub></summary>

- 📊 77 个专业金融 skills，分布在 8 个类别中
- 🌐 覆盖传统市场、加密与 DeFi
- 🔬 从数据源到量化研究的完整能力链路

| 类别 | Skills | 示例 |
|------|--------|------|
| Data Source | 7 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 17 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 11 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `alpha-zoo` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

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

Vibe-Trading 为任何 MCP-compatible client 暴露 22 个 MCP tools。它作为 stdio subprocess 运行，无需 server setup。**22 个工具中有 21 个零 API key 可用**（港/美股/加密）。只有 `run_swarm` 需要 LLM key。

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

**暴露的 MCP tools（22）：** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

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
│   ├── mcp_server.py               # MCP server —— 22 个工具，面向 OpenClaw / Claude Desktop
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
│       ├── loaders/                #   7 个数据源：tushare、okx、yfinance、akshare、mootdx、ccxt、futu
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

近期 v0.1.8 周期贡献者与致谢：

- @GTC2080 / TaoMu — Web UI Settings 和 provider/data-source configuration APIs (#57)
- @BigNounce90 — backtest `run_dir` 输入的 validation CLI 加固 (#60)
- @shadowinlife — A 股 pre-ST filter skill (#63)
- @MB-Ndhlovu — correlation heatmap dashboard 和 review fixes (#64, #66)
- @ykykj — OpenAI Codex OAuth provider option (#65)
- @RuifengFu — 交互式 CLI live status bar 和 prompt editing (#69)
- @SiMinus — swarm preset inspection command (#73)
- @warren618 / Haozhe Wu — 安全加固、release integration、文档、Docker、packaging 和本地开发工作流
- lemi9090 (S2W) — 协同安全研究、验证和披露支持

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
