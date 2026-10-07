// 中文文档。页面 id 与小节 id 必须与 content.en.js 一一对应、顺序一致——
// wiki/scripts/check_docs_parity.mjs 会在 CI 里检查。
// 文中的数量均按 content.js 所标版本从代码实测；发版前重新测量，不要手改数字。

export const DOCS_STRUCTURE = [
  {
    id: "getting-started",
    label: "入门",
    pages: [
      {
        id: "getting-started/vibe-trading-overview",
        title: "Vibe-Trading 简介",
        description: "Vibe-Trading 是什么、能做什么、守住哪些边界。",
        lead: "Vibe-Trading 是一个开源的金融研究智能体。你用自然语言提问，它去取行情数据、跑回测和分析工具，给出的每个数字都能追溯到这些数据。",
        sections: [
          {
            id: "what-it-is",
            title: "它是什么",
            body: `
              <p>Vibe-Trading 把一个智能体循环接到一整套金融工具上：行情加载器、策略生成、回测引擎、文档阅读、交割单分析、持久记忆，以及多智能体研究团队。</p>
              <p>同一个智能体有四个入口：</p>
              <ul>
                <li><strong>终端</strong>——<code>vibe-trading</code> 进入交互会话；<code>vibe-trading run -p "…"</code> 执行单条指令。</li>
                <li><strong>Web 界面</strong>——在浏览器里对话，查看历史运行、持仓、Alpha Zoo、定时研究和设置。</li>
                <li><strong>MCP 服务</strong>——<code>vibe-trading-mcp</code> 把同一套工具提供给 Claude Desktop、Cursor、OpenClaw 等 MCP 客户端。</li>
                <li><strong>IM 渠道</strong>——Telegram、Slack、Discord、飞书、钉钉、企业微信、邮件等共用同一套会话运行时。</li>
              </ul>
            `
          },
          {
            id: "capabilities",
            title: "0.1.16 包含什么",
            body: `
              <ul>
                <li><strong>28 个行情数据源</strong>，一次调用即可，每个市场各有一条回退链。多数市场不需要任何 API key。</li>
                <li><strong>11 个回测引擎</strong>：A 股、全球股票、印度、韩国、越南、加密货币、国内期货、海外期货、外汇，一个用于跨市场组合的复合引擎，以及一个期权组合引擎。</li>
                <li><strong>90 个金融技能</strong>，分 9 类；<strong>30 个多智能体团队预设</strong>，用于投委会式研究。</li>
                <li><strong>Alpha Zoo</strong>：462 个现成因子，一条命令即可在你的股票池上评测。</li>
                <li><strong>74 个 MCP 工具</strong>，供其他智能体调用。</li>
                <li><strong>18 个券商连接器</strong>，默认只读；另有只读的多券商持仓页。</li>
                <li><strong>数字核验</strong>：答案里的数字在展示给你之前，会先和本次会话取到的工具数据逐一核对。</li>
                <li>Web 界面支持九种语言。</li>
              </ul>
            `
          },
          {
            id: "where-to-start",
            title: "从哪里开始",
            body: `
              <ol>
                <li><a data-doc-link="getting-started/quick-start">快速开始</a>——安装并跑通第一个任务。</li>
                <li><a data-doc-link="getting-started/configuration">配置</a>——选模型服务商、填 key。</li>
                <li><a data-doc-link="core-concepts/research-workflow">研究流程</a>——从提问到答案之间发生了什么。</li>
                <li><a data-doc-link="getting-started/troubleshooting">故障排查</a>——运行失败或数字被删去时看这里。</li>
              </ol>
            `
          },
          {
            id: "research-only",
            title: "边界",
            body: `
              <p>Vibe-Trading 面向研究、模拟和回测。实盘交易需要你主动开启，默认只读：只通过你自己授权的券商执行，只在你设定上限的交易授权（mandate）之内运行，紧急停止（kill switch）可以立刻叫停。Vibe-Trading 不托管资金，不运营交易场所，也不构成投资建议。</p>
            `
          }
        ]
      },
      {
        id: "getting-started/quick-start",
        title: "快速开始",
        description: "从 PyPI 安装、配置模型、跑第一个研究任务。",
        lead: "三条命令就能在终端里用上智能体。Web 界面还要多一步，因为 PyPI 包里不含构建好的前端。",
        sections: [
          {
            id: "install",
            title: "安装",
            body: `
              <p>需要 Python 3.11 或更高版本，以及一个模型服务商的 API key（本地 Ollama 模型不需要 key）。</p>
              <pre><code>pip install vibe-trading-ai
vibe-trading init
vibe-trading</code></pre>
              <p><code>vibe-trading init</code> 会依次询问服务商、模型、key，以及可选的 Tushare token，写入 <code>~/.vibe-trading/.env</code>。之后 <code>vibe-trading</code> 打开交互终端，输入 <code>/help</code> 查看命令列表。</p>
            `
          },
          {
            id: "first-run",
            title: "第一次运行",
            body: `
              <p>在交互会话里直接提问，或者执行一条指令后退出：</p>
              <pre><code>vibe-trading run -p "回测 BTC-USDT 2024 年 20/50 均线策略，总结收益和回撤"</code></pre>
              <p>智能体会取 K 线、写策略、跑回测，再用回测指标作答。这次运行的代码、成交和指标都留在本地磁盘；<code>vibe-trading --list</code> 可以查看历史运行。</p>
            `
          },
          {
            id: "web-ui",
            title: "打开 Web 界面",
            body: `
              <p><strong>用 Docker</strong>——本机不需要装 Python 或 Node：</p>
              <pre><code>git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env   # 取消注释你的服务商，填入 key
docker compose up --build</code></pre>
              <p>然后打开 <code>http://127.0.0.1:8899</code>。记忆、会话、运行记录和连接器配置都存在 Docker 卷里，<code>git pull &amp;&amp; docker compose up --build</code> 之后仍然保留。</p>
              <p><strong>从源码运行</strong>——需要 Node.js 22.22 或更高版本：</p>
              <pre><code>git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
pip install -e .
vibe-trading setup                 # 安装依赖并构建前端
vibe-trading serve --port 8899</code></pre>
              <p>只用 <code>pip install</code> 安装时，<code>vibe-trading serve</code> 只启动 API，并提示 <code>No frontend build found</code>。这是正常的；要用浏览器界面，请走上面两种方式之一。</p>
            `
          },
          {
            id: "upgrade",
            title: "升级",
            body: `
              <pre><code>pip install -U vibe-trading-ai
vibe-trading --version</code></pre>
              <p><code>vibe-trading update</code> 会检查 PyPI 并替你安装最新版本。如果从 0.1.10 之前的版本升级后导入报错，请重建虚拟环境，或执行 <code>pip install --force-reinstall vibe-trading-ai</code>。</p>
            `
          },
          {
            id: "other-agents",
            title: "在其他智能体里使用",
            body: `
              <p>同一个包还会安装 <code>vibe-trading-mcp</code>，这是一个 stdio 模式的 MCP 服务。客户端配置见 <a data-doc-link="reference/mcp-server">MCP 服务</a>。</p>
            `
          }
        ]
      },
      {
        id: "getting-started/configuration",
        title: "配置",
        description: "配置从哪里读取、哪些变量要紧、长任务怎么调。",
        lead: "所有配置都通过环境变量完成。密钥只放在 .env 文件或系统钥匙串里，绝不写进对话或源码。",
        sections: [
          {
            id: "env",
            title: "配置从哪里读取",
            body: `
              <p>Vibe-Trading 按下面的顺序找第一个存在的文件，并且只读这一个：</p>
              <ol>
                <li><code>~/.vibe-trading/.env</code>——由 <code>vibe-trading init</code> 生成</li>
                <li>源码目录里的 <code>agent/.env</code></li>
                <li>当前目录下的 <code>.env</code></li>
              </ol>
              <p>在 shell 里 export 的变量永远优先于文件。Web 界面的设置页可以直接修改模型和数据源配置。</p>
            `
          },
          {
            id: "provider",
            title: "模型服务商",
            body: `
              <table>
                <thead><tr><th>变量</th><th>含义</th></tr></thead>
                <tbody>
                  <tr><td><code>LANGCHAIN_PROVIDER</code></td><td>服务商名称：<code>openrouter</code>、<code>deepseek</code>、<code>openai</code>、<code>anthropic</code>、<code>gemini</code>、<code>ollama</code>……（内置 25 个）</td></tr>
                  <tr><td><code>LANGCHAIN_MODEL_NAME</code></td><td>模型 id，例如 <code>deepseek-v4-pro</code></td></tr>
                  <tr><td><code>&lt;PROVIDER&gt;_API_KEY</code></td><td>API key，例如 <code>DEEPSEEK_API_KEY</code></td></tr>
                  <tr><td><code>&lt;PROVIDER&gt;_BASE_URL</code></td><td>API 地址</td></tr>
                  <tr><td><code>LANGCHAIN_REASONING_EFFORT</code></td><td>可选：<code>none</code>、<code>low</code>、<code>medium</code>、<code>high</code> 或 <code>max</code></td></tr>
                </tbody>
              </table>
              <pre><code>LANGCHAIN_PROVIDER=deepseek
LANGCHAIN_MODEL_NAME=deepseek-v4-pro
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1</code></pre>
              <ul>
                <li><strong>ChatGPT 账号登录（Codex）</strong>：设 <code>LANGCHAIN_PROVIDER=openai-codex</code>，再执行 <code>vibe-trading provider login openai-codex</code>。不使用 <code>OPENAI_API_KEY</code>；默认模型是 <code>gpt-6-sol</code>。</li>
                <li><strong>GitHub Copilot</strong>：<code>pip install "vibe-trading-ai[copilot]"</code>，再设 <code>LANGCHAIN_PROVIDER=copilot</code>；它使用你的 <code>gh</code> 或 Copilot CLI 登录凭据。</li>
                <li><strong>Ollama</strong>：不需要 key。</li>
              </ul>
            `
          },
          {
            id: "models",
            title: "怎么选模型",
            body: `
              <p>智能体做的每件事都通过工具调用完成，所以模型决定了它是真去用工具，还是凭记忆作答。长时间研究、多智能体团队和多步回测，请用工具调用能力强的模型。避开 <code>*-nano</code>、<code>*-flash-lite</code> 和小型蒸馏模型：它们的工具调用不可靠，答案读起来很流畅，实际上一条数据都没取。</p>
            `
          },
          {
            id: "keys",
            title: "行情数据 key（可选）",
            body: `
              <p>A 股、港股、美股、加拿大、英国、印度、韩国、加密货币和外汇都能免 key 使用。key 用来增加数据源或数据深度：</p>
              <ul>
                <li><code>TUSHARE_TOKEN</code>——更丰富的 A 股、基金和宏观数据。</li>
                <li><code>GILDATA_TOKEN</code>——恒生聚源商业 A 股数据。</li>
                <li>Finnhub、Alpha Vantage、Tiingo、FMP 的 key——额外的美股数据源。</li>
                <li>QVeris——付费数据市场，只在你明确要求时使用；用 <code>vibe-trading data mode</code> 切换。</li>
              </ul>
              <p>哪个数据源服务哪个市场，见 <a data-doc-link="tools/data-sources">数据源</a>。</p>
            `
          },
          {
            id: "long-runs",
            title: "长任务与超时",
            body: `
              <table>
                <thead><tr><th>变量</th><th>默认值</th><th>含义</th></tr></thead>
                <tbody>
                  <tr><td><code>VIBE_TRADING_CONTEXT_WINDOW</code></td><td>见右</td><td>你所用模型的上下文窗口（token 数）。不设时，依次取：本次运行中服务商报错给出的上限、内置模型目录、128K。</td></tr>
                  <tr><td><code>VIBE_TRADING_CONTEXT_MAX_TOKENS</code></td><td>200000</td><td>单次请求最多发送多少 token，与窗口大小无关，用来控制花费。</td></tr>
                  <tr><td><code>TIMEOUT_SECONDS</code></td><td>120</td><td>单次模型请求的超时。</td></tr>
                  <tr><td><code>VIBE_TRADING_TOOL_TIMEOUT_SECONDS</code></td><td>1800</td><td>只读工具或回测的硬超时；设为 0 表示不限。</td></tr>
                </tbody>
              </table>
              <p><code>TOKEN_THRESHOLD</code> 已在 0.1.16 移除。设置了也会被忽略并提示警告，请从 <code>.env</code> 里删掉。</p>
            `
          },
          {
            id: "deployment",
            title: "在本机以外访问",
            body: `
              <p>没有设置 <code>API_AUTH_KEY</code> 时，敏感接口只响应来自本机的请求。要从其他设备使用 Web 界面，请设置一个足够强的 <code>API_AUTH_KEY</code>，客户端请求带上 <code>Authorization: Bearer &lt;key&gt;</code>，并在 Web 界面的设置页填入同一个 key。<code>VIBE_TRADING_EXTRA_CORS_ORIGINS</code> 用于追加允许的浏览器来源。</p>
              <p>Shell 类工具只在本机交互终端里开启。API 和 MCP 服务默认关闭它们，除非设置 <code>VIBE_TRADING_ENABLE_SHELL_TOOLS=1</code>。</p>
            `
          },
          {
            id: "paths",
            title: "文件与目录",
            body: `
              <ul>
                <li><code>VIBE_TRADING_HOME</code>——运行记录、会话、记忆、连接器和审计账本的存放位置，默认 <code>~/.vibe-trading</code>。</li>
                <li><code>VIBE_TRADING_ALLOWED_FILE_ROOTS</code>——额外允许导入文档和交割单的目录，用逗号分隔。</li>
                <li><code>VIBE_TRADING_ALLOWED_RUN_ROOTS</code>——额外允许运行生成的策略代码的目录。</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "getting-started/troubleshooting",
        title: "故障排查",
        description: "常见报错是什么意思，该怎么处理。",
        lead: "大多数失败都会说明原因。本页把你可能看到的提示，对应到发生了什么、下一步怎么做。",
        sections: [
          {
            id: "version",
            title: "先确认版本",
            body: `
              <pre><code>vibe-trading --version
pip install -U vibe-trading-ai</code></pre>
              <p>下面好几个问题在 0.1.16 已经修复，先升级再往下查。</p>
            `
          },
          {
            id: "no-progress",
            title: "失败 · no_progress",
            body: `
              <p>如果连续八轮工具调用都没有拿到新的有效结果，智能体就会停下。这是防止原地打转的预算，不是程序崩溃。从 0.1.16 起，停止提示会列出每个没有产出的调用、原因和次数。常见原因：</p>
              <ul>
                <li><strong>数据源宕机或被限流。</strong>稍后重试，或在提问里指定别的数据源（"用 Yahoo"）。</li>
                <li><strong>模型反复猜文件路径。</strong>0.1.16 已修复：<code>read_file</code> 现在会说明可读的目录，并能列出目录内容。</li>
                <li><strong>长对比任务忘了已经取过的数据</strong>，又重新去取。0.1.16 已修复：上下文压缩按模型的真实上下文窗口计算。</li>
              </ul>
              <p>同一个失败的调用从第二次失败起会被拒绝执行。换个说法提问，或者开一次新的运行，就会重置。</p>
            `
          },
          {
            id: "zero-steps",
            title: "失败的运行显示 0 个步骤",
            body: `
              <p>0.1.16 之前，只有成功完成的运行才保存工具轨迹，所以失败或取消的运行在历史里显示"0 个步骤"。从 0.1.16 起，每次运行都会保留步骤。</p>
            `
          },
          {
            id: "omitted",
            title: "答案里出现（略※）",
            body: `
              <p>有数字无法和本次会话取到的数据对上，被从答案里删去了，※ 脚注会说明删了几处。先让智能体取数据或跑回测，再问一次。规则见 <a data-doc-link="core-concepts/checked-numbers">数字核验</a>。</p>
            `
          },
          {
            id: "context",
            title: "上下文长度报错",
            body: `
              <p>从 0.1.16 起，服务商返回上下文超长错误时，会先压缩再重试，并在本次运行余下的部分沿用报错里给出的上限。如果你用的模型不在内置目录里，请把 <code>VIBE_TRADING_CONTEXT_WINDOW</code> 设为它的真实窗口。<code>TOKEN_THRESHOLD</code> 这一行请删掉，它已不再生效。</p>
            `
          },
          {
            id: "us-ticker",
            title: "美股代码报错",
            body: `
              <p>美股代码要带 <code>.US</code> 后缀：写 <code>AAPL.US</code>，不要写 <code>AAPL</code>。报错会直接提示：<code>US equity symbols must include the .US suffix</code>。其他市场各有后缀，见 <a data-doc-link="tools/data-sources">数据源</a>。</p>
            `
          },
          {
            id: "web-ui",
            title: "No frontend build found",
            body: `
              <p>你是从 PyPI 安装的，PyPI 包只带 API，不带构建好的 Web 界面。请用 Docker，或在源码目录里执行 <code>vibe-trading setup</code>，步骤见 <a data-doc-link="getting-started/quick-start">快速开始</a>。</p>
            `
          },
          {
            id: "remote-403",
            title: "其他设备访问返回 403",
            body: `
              <p>没有设置 <code>API_AUTH_KEY</code> 时，敏感接口只响应本机请求。设置这个 key，并在另一台设备的设置页里填入它。</p>
            `
          },
          {
            id: "codex",
            title: "Codex 拒绝所选模型",
            body: `
              <p>用 ChatGPT 账号登录时，ChatGPT 账户无法使用 <code>gpt-5.4</code>。0.1.16 默认改为 <code>gpt-6-sol</code>；如果你的 <code>.env</code> 里写的是旧模型，请修改 <code>LANGCHAIN_MODEL_NAME</code>。</p>
            `
          },
          {
            id: "report",
            title: "反馈问题",
            body: `
              <p>在 <a href="https://github.com/HKUDS/Vibe-Trading/issues">GitHub</a> 提 issue，附上版本号、服务商和模型、以及停止提示。<code>vibe-trading --trace RUN_ID</code> 可以回放这次运行做了什么。不要贴 API key 或券商凭据。</p>
            `
          }
        ]
      }
    ]
  },
  {
    id: "core-concepts",
    label: "核心概念",
    pages: [
      {
        id: "core-concepts/research-workflow",
        title: "研究流程",
        description: "一次运行如何从你的问题走到带证据的答案。",
        lead: "每个请求都走同一条路：规划、取证、执行工具、核对结果，最后连同来源文件一起交付。",
        sections: [
          {
            id: "pipeline",
            title: "流程",
            body: `
              <ol>
                <li><strong>规划</strong>——选择技能、工具、数据源，必要时选一个多智能体团队预设。</li>
                <li><strong>取证</strong>——运行时去取 K 线、公告、文档、网页、交割单或本地文件。</li>
                <li><strong>执行</strong>——写策略代码，跑回测、因子分析、期权检查或生成报告。</li>
                <li><strong>验证</strong>——加上指标、基准对比、蒙特卡洛、自助法和滚动前推检验，以及运行卡上的警告。</li>
                <li><strong>核验</strong>——把答案草稿里的每个数字和本次会话的工具数据对照（见<a data-doc-link="core-concepts/checked-numbers">数字核验</a>）。</li>
                <li><strong>交付</strong>——返回答案和这次运行的产物。</li>
              </ol>
            `
          },
          {
            id: "progress",
            title: "进展预算",
            body: `
              <p>连续八轮工具调用都没有新的有效观测，运行就会停下，明确标记为失败。重复读到同样的结果、或者调用失败，都不算进展。完全相同的调用从第二次失败起被拒绝，所以限流或超时之后的一次重试仍会执行；参数变了的调用总会执行。另有一个按真实时间计的看门狗，负责停掉卡死的运行。</p>
            `
          },
          {
            id: "context",
            title: "长对话",
            body: `
              <p>对话超出模型的上下文窗口时，较早的内容分三层压缩：先清掉最早的工具结果，再折叠长文本，最后做摘要。三层分别在系统提示词和工具定义之外剩余空间的 80%、90%、100% 时启动，每次只清到这条线为止，所以最近的证据始终留在视野里。</p>
            `
          },
          {
            id: "artifacts",
            title: "运行记录与产物",
            body: `
              <p>每次回测都会在 <code>~/.vibe-trading/runs/</code> 下写一个运行目录：</p>
              <ul>
                <li><code>code/</code> 和 <code>config.json</code>——策略代码及其参数。</li>
                <li><code>run_card.json</code> 和 <code>run_card.md</code>——运行卡（run card）：跑了什么、用了哪些数据、有哪些警告。</li>
                <li><code>artifacts/metrics.csv</code>、<code>equity.csv</code>、<code>trades.csv</code>、<code>positions.csv</code>——结果。</li>
                <li><code>artifacts/validation.json</code>、<code>risk_xray.json</code>——验证结果和风险拆解。</li>
                <li><code>logs/</code>——引擎输出，运行超时也会保留。</li>
              </ul>
              <pre><code>vibe-trading --list
vibe-trading --show RUN_ID
vibe-trading --code RUN_ID
vibe-trading --pine RUN_ID     # 导出 TradingView Pine Script
vibe-trading --trace RUN_ID    # 回放智能体的每一步</code></pre>
            `
          },
          {
            id: "memory",
            title: "会话与记忆",
            body: `
              <ul>
                <li><strong>持久记忆</strong>存在 <code>~/.vibe-trading/memory/</code>，跨会话保留偏好和结论（<code>/memory</code>、<code>vibe-trading memory</code>）。</li>
                <li>用 <code>/search</code> 全文<strong>搜索</strong>所有历史会话；用 <code>/history</code> 恢复其中一个。</li>
                <li><strong>研究目标</strong>（<code>/goal</code>）跨多次运行保存一个较大的研究问题、它的证据和进度。</li>
                <li>可安全重启：被重启打断的运行会记录为"已中断"，并保留已经输出的文字。</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "core-concepts/checked-numbers",
        title: "数字核验",
        description: "答案里的数字如何与智能体取到的数据逐一核对。",
        lead: "答案送到你面前之前，其中每个数字都会和本次会话的工具结果核对。追溯不到来源的数字会退回修改，改完仍不通过就被删去。",
        sections: [
          {
            id: "how",
            title: "工作方式",
            body: `
              <p>模型要为每个数字声明它的来源：</p>
              <ul>
                <li><strong>observed（观测）</strong>——工具返回的值；</li>
                <li><strong>derived（推导）</strong>——由观测值计算而来，并写出公式；</li>
                <li><strong>proposed（建议）</strong>——目标价或假设，不是测量值；</li>
                <li><strong>cited（引用）</strong>——出自同一行里写明的来源；</li>
                <li><strong>count（计数）</strong>——某样东西的个数。</li>
              </ul>
              <p>核验按角色检查每个数字：观测值必须和某个工具结果一致，推导值必须能由它的操作数算出，引用值必须写明出处。这些声明在答案展示前会被移除。</p>
            `
          },
          {
            id: "scope",
            title: "哪些数字会被核验",
            body: `
              <p>小数、百分比、带货币符号的金额和表格单元格里的数字属于测量值，会被核验。日期、年份、代码、序号和句子里的普通整数不核验，但报价在 1,000 以上的品种，其整数价格仍会核验。四舍五入后的数字必须是工具值按所写位数正确舍入的结果，且与原值相差不超过 0.5%：30.2052% 可以写成 30.21% 或 30.2%，不能写成 30.20%；0.82467 可以写成 0.825，不能写成 0.82。</p>
            `
          },
          {
            id: "backtests",
            title: "回测报告",
            body: `
              <p>从 0.1.16 起，回测自己写下的内容可以作为这份回测报告的证据：运行卡、指标、风险透视、蒙特卡洛验证和调仓摘要里的每个值。逐 K 线的表格只认智能体实际读过的那些行。模型自己写的文件永远不算证据；一次回测的数值也不能支撑标注为另一次回测的数字。</p>
            `
          },
          {
            id: "what-you-see",
            title: "你会看到什么",
            body: `
              <ul>
                <li>核验进行中：<em>正在核对答案中的数字（第 N 轮）…</em></li>
                <li>不通过的数字会带着具体的修改意见退回，最多两轮。</li>
                <li>仍不通过的数字被替换成 <code>（略※）</code>，脚注说明删了几处，答案其余部分照常给出。</li>
                <li>只有这几种情况整段答案会被替换成简短的拒答：问的是价格却没取到任何价格；答案描述的品种和取到的不是同一个；删去不通过的数字后仍然不通过。</li>
              </ul>
            `
          },
          {
            id: "tips",
            title: "让数字顺利通过",
            body: `
              <ul>
                <li>让智能体先取数据，再报数字。</li>
                <li>对比多次回测时，让它标明每个数字来自哪次运行。</li>
                <li>你自己给出数字时，说明出处（"据 2025 年年报"）。</li>
                <li>折现率这类假设会标为建议值，而不是测量值。</li>
              </ul>
            `
          },
          {
            id: "limits",
            title: "局限",
            body: `
              <p>核验只能证明某个数字和本次会话的数据一致，不能证明数据本身正确，也不能证明分析站得住。句子里的普通整数、用文字写的单位（如"块""美元"），以及值没错但名称张冠李戴的情况，都拦不住。</p>
            `
          }
        ]
      },
      {
        id: "core-concepts/backtesting",
        title: "回测",
        description: "引擎、K 线周期、组合构建、验证与产物。",
        lead: "策略以代码形式编写，在按对应市场规则运行的引擎上回测，连同指标、成交和验证结果一起保存，方便日后复查。",
        sections: [
          {
            id: "engines",
            title: "引擎",
            body: `
              <table>
                <thead><tr><th>市场</th><th>建模的规则</th></tr></thead>
                <tbody>
                  <tr><td>A 股</td><td>T+1，散户不能做空，±10% / ±20% / ±5% 涨跌停，100 股一手</td></tr>
                  <tr><td>全球股票（美股、港股、加拿大、英国、指数）</td><td>各市场自己的交易规则和费用</td></tr>
                  <tr><td>印度（NSE / BSE）</td><td>日线交割（delivery）业务，熔断价格带，法定税费</td></tr>
                  <tr><td>韩国（KOSPI / KOSDAQ）</td><td>KRX 最小价位，±30% 价格带，只做多</td></tr>
                  <tr><td>越南（HOSE）</td><td>整数越南盾的最小价位和价格带</td></tr>
                  <tr><td>加密货币</td><td>永续合约：挂单/吃单费率，每 8 小时资金费，强平</td></tr>
                  <tr><td>国内期货</td><td>中金所、上期所、大商所、郑商所、上期能源、广期所：T+0、保证金、涨跌停</td></tr>
                  <tr><td>海外期货</td><td>CME、ICE、Eurex：保证金、合约乘数</td></tr>
                  <tr><td>外汇与贵金属</td><td>点差、杠杆、手数</td></tr>
                  <tr><td>复合</td><td>多个市场共用一个资金池</td></tr>
                  <tr><td>期权组合</td><td>带波动率微笑的 Black-Scholes，欧式与美式，多腿</td></tr>
                </tbody>
              </table>
              <p>阿根廷代码（<code>.BA</code>）有行情数据，但还没有回测引擎；对它们发起的回测会被拒绝，而不是套用别的市场规则去跑。</p>
            `
          },
          {
            id: "intervals",
            title: "K 线周期",
            body: `
              <p><code>1m</code>、<code>5m</code>、<code>15m</code>、<code>30m</code>、<code>1H</code>、<code>4H</code>、<code>1D</code>、<code>1W</code>、<code>1M</code>。周线和月线由日线合成。注意大小写：<code>1M</code> 是一个月，<code>1m</code> 是一分钟。分钟线取决于数据源能提供什么。</p>
            `
          },
          {
            id: "portfolio",
            title: "组合构建",
            body: `
              <p>内置优化器：等波动率、风险平价、均值-方差、最大分散化，以及考虑换手的调仓。</p>
            `
          },
          {
            id: "validation",
            title: "验证",
            body: `
              <p>一次运行可以加上基准对比、蒙特卡洛检验、夏普比率的自助法置信区间和滚动前推分析。当数据的 K 线间隔与声明的周期不符，或不同数据源的复权口径不一致时，运行卡会给出警告。这些是证据，不是保证。</p>
            `
          },
          {
            id: "example",
            title: "示例",
            body: `
              <pre><code>vibe-trading run -p "对比 600519.SH、000858.SZ、000001.SZ 在 2023-2025 年的风险平价与等权组合，按月调仓，并做蒙特卡洛检验"</code></pre>
            `
          }
        ]
      },
      {
        id: "core-concepts/swarm-teams",
        title: "多智能体团队",
        description: "投委会式研究用的专家智能体团队预设（Swarm）。",
        lead: "一个团队预设把一个问题交给一小组专家智能体：它们按依赖顺序工作，实时显示进度，最后写成一份报告。",
        sections: [
          {
            id: "presets",
            title: "预设",
            body: `
              <p>0.1.16 自带 30 个预设：</p>
              <p><code>investment_committee</code>、<code>quant_strategy_desk</code>、<code>risk_committee</code>、<code>crypto_trading_desk</code>、<code>crypto_research_lab</code>、<code>macro_rates_fx_desk</code>、<code>macro_strategy_forum</code>、<code>global_allocation_committee</code>、<code>global_equities_desk</code>、<code>equity_research_team</code>、<code>fundamental_research_team</code>、<code>earnings_research_desk</code>、<code>value_investing_committee</code>、<code>factor_research_committee</code>、<code>ml_quant_lab</code>、<code>statistical_arbitrage_desk</code>、<code>pairs_research_lab</code>、<code>derivatives_strategy_desk</code>、<code>convertible_bond_team</code>、<code>credit_research_team</code>、<code>commodity_research_team</code>、<code>etf_allocation_desk</code>、<code>fund_selection_panel</code>、<code>portfolio_review_board</code>、<code>sector_rotation_team</code>、<code>event_driven_task_force</code>、<code>geopolitical_war_room</code>、<code>sentiment_intelligence_team</code>、<code>social_alpha_team</code>、<code>technical_analysis_panel</code>。</p>
            `
          },
          {
            id: "run",
            title: "运行预设",
            body: `
              <pre><code>vibe-trading --swarm-presets
vibe-trading --swarm-inspect investment_committee
vibe-trading --swarm-run investment_committee '{"topic":"BTC 走势展望"}'</code></pre>
              <p>变量以一个 JSON 对象传入。交互终端里用 <code>/swarm</code>；Web 界面会实时显示每个成员的进度。</p>
            `
          },
          {
            id: "manage",
            title: "管理运行",
            body: `
              <pre><code>vibe-trading --swarm-list
vibe-trading --swarm-show RUN_ID
vibe-trading --swarm-cancel RUN_ID
vibe-trading --swarm-retry RUN_ID --swarm-resume   # 保留已完成的任务</code></pre>
            `
          },
          {
            id: "keys",
            title: "模型要求",
            body: `
              <p>每个成员都是一个完整的智能体，所以团队运行需要模型 key，花费相当于好几次单独运行。成员会自己去取行情数据；预设里列出的技能是强制约束，成员不能加载预设没有列出的技能。</p>
            `
          }
        ]
      }
    ]
  },
  {
    id: "tools",
    label: "工具",
    pages: [
      {
        id: "tools/data-sources",
        title: "数据源",
        description: "哪个数据源服务哪个市场、代码格式、如何指定数据源。",
        lead: "一次 get_market_data 调用可以用到 28 个数据源。source 设为 auto 时，每个代码按所属市场路由，沿该市场的回退链依次尝试，最不容易封禁你的数据源排在最前。",
        sections: [
          {
            id: "providers",
            title: "回退链",
            body: `
              <table>
                <thead><tr><th>市场</th><th>回退顺序</th></tr></thead>
                <tbody>
                  <tr><td>A 股</td><td>tencent、mootdx、eastmoney、baostock、akshare、tushare、gildata、local</td></tr>
                  <tr><td>美股</td><td>yahoo、stooq、sina、eastmoney、yfinance、tiingo、fmp、finnhub、alphavantage、longbridge、akshare、local</td></tr>
                  <tr><td>港股</td><td>tencent、eastmoney、yahoo、futu、akshare、yfinance、tushare、longbridge、local</td></tr>
                  <tr><td>印度</td><td>yahoo、yfinance、india_broker、local</td></tr>
                  <tr><td>韩国</td><td>pykrx、yahoo、yfinance、local</td></tr>
                  <tr><td>加拿大、英国、越南、阿根廷、指数</td><td>yahoo、yfinance、local</td></tr>
                  <tr><td>加密货币</td><td>okx、binance、ccxt、yfinance、local</td></tr>
                  <tr><td>国内期货</td><td>akshare、local</td></tr>
                  <tr><td>外汇与贵金属</td><td>mt5、akshare、yfinance、local</td></tr>
                  <tr><td>基金</td><td>tushare、akshare、local</td></tr>
                  <tr><td>宏观</td><td>akshare、tushare、local</td></tr>
                </tbody>
              </table>
              <p>有四个数据源只在你点名时使用：<code>qveris</code>（付费数据市场）、<code>tickerall</code>（托管的 MT5 行情）、<code>nobitex</code> / <code>wallex</code>（伊朗托曼计价交易对）。设置 <code>MARKET_DATA_ORDER_&lt;MARKET&gt;</code>（例如 <code>MARKET_DATA_ORDER_US_EQUITY</code>）可以调整某条链的顺序。</p>
            `
          },
          {
            id: "symbols",
            title: "代码格式",
            body: `
              <table>
                <thead><tr><th>市场</th><th>示例</th></tr></thead>
                <tbody>
                  <tr><td>A 股</td><td><code>600519.SH</code>、<code>000001.SZ</code></td></tr>
                  <tr><td>港股</td><td><code>0700.HK</code></td></tr>
                  <tr><td>美股</td><td><code>AAPL.US</code>、<code>SPY.US</code>——必须带后缀</td></tr>
                  <tr><td>加密货币</td><td><code>BTC-USDT</code>（大写，连字符）</td></tr>
                  <tr><td>韩国 / 印度 / 英国 / 加拿大</td><td><code>005930.KS</code>、<code>RELIANCE.NS</code>、<code>VOD.L</code>、<code>SHOP.TO</code></td></tr>
                  <tr><td>越南 / 阿根廷</td><td><code>VNM.VN</code>、<code>GGAL.BA</code></td></tr>
                  <tr><td>国内期货</td><td><code>RB0</code>（主力连续）、<code>IF2412</code></td></tr>
                  <tr><td>外汇与贵金属</td><td><code>EURUSD</code>、<code>XAUUSD</code></td></tr>
                  <tr><td>你自己的文件</td><td><code>local:</code> 前缀——CSV、Parquet 或 DuckDB</td></tr>
                </tbody>
              </table>
              <p>后缀只表示交易所，不表示币种。伦敦的报价必须声明 GBP 或 GBp；港股按股票代码所属区段的币种计价。</p>
            `
          },
          {
            id: "choosing",
            title: "指定数据源",
            body: `
              <p>直接用自然语言说（"用长桥取 QQQ.US 的历史数据"），或在回测配置里设置 <code>"source"</code>。明确写了 <code>local:</code> 的代码绝不会回退到网络数据源。</p>
            `
          },
          {
            id: "beyond-prices",
            title: "行情之外",
            body: `
              <p>22 个只读数据工具，覆盖资金流向、龙虎榜、北向资金、融资融券、大宗交易、股东户数、限售解禁、板块、研报、新闻、SEC 公告、财务报表、期权链、公司概况、条件选股、代码搜索、宏观序列、问财、13F 机构持仓、ETF 穿透、预测市场和学术论文。</p>
            `
          }
        ]
      },
      {
        id: "tools/shadow-account",
        title: "影子账户",
        description: "把交割单变成行为诊断，以及一个按规则执行的影子策略。",
        lead: "影子账户（Shadow Account）从你的真实交易出发，提炼出你实际在遵循的规则，再把你的交易和一个严格执行这些规则的策略做对比。",
        sections: [
          {
            id: "flow",
            title: "流程",
            body: `
              <ol>
                <li><strong>读取交割单</strong>——支持同花顺、东方财富、富途的导出文件，以及通用 CSV。</li>
                <li><strong>刻画交易行为</strong>——持仓天数、胜率、盈亏比、回撤，并检查处置效应、过度交易、追涨和锚定。</li>
                <li><strong>提炼规则</strong>——把反复出现的买卖点整理成明确的策略画像。</li>
                <li><strong>运行影子策略</strong>——回测这些规则，指出违规、过早离场和错过的信号。</li>
                <li><strong>生成报告</strong>——HTML 或 PDF 报告，可以留存，也可以之后继续完善。</li>
              </ol>
            `
          },
          {
            id: "example",
            title: "示例",
            body: `
              <pre><code>vibe-trading --upload trades_export.csv
vibe-trading run -p "分析我的交易行为，提炼我的影子策略，并和我的实际交易做对比"</code></pre>
              <p>在交互终端里，<code>/journal</code> 分析交割单，<code>/shadow</code> 训练或查看影子账户。</p>
            `
          }
        ]
      },
      {
        id: "tools/finance-skills",
        title: "金融技能",
        description: "智能体按任务需要加载的知识模块。",
        lead: "技能（skills）是写成 Markdown 的领域方法——怎样筛查 ST 风险、怎样做 DCF、某个数据源有什么脾气。智能体按任务需要加载相应技能，而不是每次都把全部塞进提示词。",
        sections: [
          {
            id: "library",
            title: "技能库",
            body: `
              <p>共 90 个技能，分 9 类：</p>
              <table>
                <thead><tr><th>类别</th><th>数量</th></tr></thead>
                <tbody>
                  <tr><td>分析</td><td>23</td></tr>
                  <tr><td>策略</td><td>19</td></tr>
                  <tr><td>数据源</td><td>10</td></tr>
                  <tr><td>工具</td><td>10</td></tr>
                  <tr><td>资产类别</td><td>9</td></tr>
                  <tr><td>资金流</td><td>8</td></tr>
                  <tr><td>加密货币</td><td>7</td></tr>
                  <tr><td>研究</td><td>3</td></tr>
                  <tr><td>风险分析</td><td>1</td></tr>
                </tbody>
              </table>
            `
          },
          {
            id: "using",
            title: "使用技能",
            body: `
              <pre><code>vibe-trading --skills     # 列出全部技能
/skill                    # 在交互终端里列出、加载或卸载</code></pre>
              <p>技能就是普通文件，你可以直接修改，也可以让智能体为你经常重复的流程写一个新技能。公式统一放在经过测试的金融数学库里，技能调用它，而不是各自带一份实现。</p>
            `
          },
          {
            id: "institutional",
            title: "机构研究命令",
            body: `
              <p><code>/comps</code> 可比公司分析，<code>/dcf</code> 带敏感性表的现金流折现估值，<code>/attrib</code> Brinson-Fachler 业绩归因，<code>/memo</code> 投资备忘录，<code>/earnings</code> 从营收到 EPS 的财报复盘，<code>/screen</code> 系统化选股。</p>
            `
          },
          {
            id: "examples",
            title: "示例",
            body: `
              <ul>
                <li>股息分析与高股息陷阱检查。</li>
                <li>A 股 ST 前风险筛查。</li>
                <li>投资人视角：把知名投资人的思考框架作为分析叠加层。</li>
                <li>导出 Pine Script、通达信和 MetaTrader 5 代码。</li>
                <li>因子研究、宏观分析、相关性状态和技术形态。</li>
              </ul>
            `
          }
        ]
      },
      {
        id: "tools/alpha-zoo",
        title: "Alpha Zoo",
        description: "462 个现成因子，可在你自己的股票池上评测。",
        lead: "Alpha Zoo 是已发表因子公式的注册表。一条命令就能在指定股票池和区间上给整组因子打分，并把每个因子归为有效、反向或失效。",
        sections: [
          {
            id: "zoos",
            title: "因子集",
            body: `
              <table>
                <thead><tr><th>因子集</th><th>数量</th></tr></thead>
                <tbody>
                  <tr><td><code>gtja191</code>——国泰君安 191</td><td>191</td></tr>
                  <tr><td><code>qlib158</code>——微软 Qlib Alpha158</td><td>154</td></tr>
                  <tr><td><code>alpha101</code>——Kakushadze 101 公式化因子</td><td>101</td></tr>
                  <tr><td><code>academic</code>——学术文献因子</td><td>12</td></tr>
                  <tr><td><code>fundamental</code>——时点正确的 SEC 基本面因子</td><td>4</td></tr>
                </tbody>
              </table>
            `
          },
          {
            id: "commands",
            title: "命令",
            body: `
              <pre><code>vibe-trading alpha list
vibe-trading alpha show gtja191_001
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
vibe-trading alpha compare
vibe-trading alpha export-manifest</code></pre>
              <p>股票池：<code>csi300</code>、<code>sp500</code>、<code>btc-usdt</code>。<code>--strict</code> 会加入同股票池的随机对照，配合 <code>--oos-split</code> 还会做样本外确认。Web 界面的 Alpha Zoo 页提供同样的评测和对比，本站的 <a href="/alpha-library/">Alpha Library</a> 可以浏览公式。</p>
            `
          },
          {
            id: "missing-data",
            title: "缺失数据",
            body: `
              <p>某根 K 线上只要因子的任一输入缺失，这根 K 线就不输出值，而不是用补 0 后的数据凭空造出信号。递归平滑类因子会跳过缺失的观测继续计算。</p>
            `
          }
        ]
      },
      {
        id: "tools/brokers-and-live-trading",
        title: "券商与实盘交易",
        description: "券商连接器、只读持仓，以及有边界的实盘交易。",
        lead: "券商连接默认只读。实盘下单只能通过你授权的券商、在你设定的交易授权范围内进行，并且有一个能叫停一切的紧急停止开关。",
        sections: [
          {
            id: "connectors",
            title: "连接器",
            body: `
              <p>18 个连接器，共 55 个配置档（profile）。每个配置档要么是模拟盘、要么是实盘，要么只读、要么可下单。</p>
              <table>
                <thead><tr><th>下单能力</th><th>券商</th></tr></thead>
                <tbody>
                  <tr><td>授权范围内实盘下单，也支持模拟盘</td><td>Alpaca、Binance、eToro、富途、MetaTrader 5、OKX、老虎</td></tr>
                  <tr><td>授权范围内实盘下单</td><td>Robinhood（Agentic Trading，经券商自己的 MCP）</td></tr>
                  <tr><td>仅模拟盘下单</td><td>Dhan、KIS、长桥、Shoonya、Upbit、Zerodha</td></tr>
                  <tr><td>只读</td><td>IBKR、Scalable Capital、Toss Securities、Trading 212</td></tr>
                </tbody>
              </table>
              <p>如果某家券商在运行时无法区分模拟账户和实盘账户，它最多只能做模拟盘和只读。</p>
            `
          },
          {
            id: "setup",
            title: "连接券商",
            body: `
              <pre><code>vibe-trading connector list
vibe-trading connector setup okx-live-sdk-readonly --connection-id main-okx --label "Main OKX"
vibe-trading connector check</code></pre>
              <p>终端会用隐藏输入的方式询问密钥，存进系统钥匙串，然后做一次只读检查。Web 界面：持仓 → 管理账户 → 连接中心。不要把券商密钥贴进对话。</p>
            `
          },
          {
            id: "portfolio",
            title: "持仓",
            body: `
              <p>只读的持仓页汇总你所选连接的持仓。每条持仓都标明来源；某个来源刷新失败时显示为错误并排除在合计之外，绝不拿旧快照顶替。终端里也有同样的视图：<code>vibe-trading portfolio show</code>、<code>refresh</code>、<code>sources</code>。</p>
            `
          },
          {
            id: "mandate",
            title: "实盘交易授权（mandate）",
            body: `
              <ol>
                <li>当你提出实盘交易时，智能体会给出二到四套授权方案，每套都被限制在你账户允许的范围之内。</li>
                <li>由你自己选定并提交，在 Web 界面的确认对话框或终端里完成。如果一个券商登录能访问多个账户，你还要选定授权绑定的账户。</li>
                <li>授权规定单笔上限、总敞口、杠杆、品种类型、每日交易次数、可交易范围和到期日。</li>
                <li>在授权范围内，智能体下单无需逐笔确认。任何会突破上限的订单都会被拒绝，并暂停等待你重新授权。</li>
              </ol>
            `
          },
          {
            id: "kill-switch",
            title: "紧急停止与审计",
            body: `
              <p>在终端输入 <code>/halt</code>（或 <code>/stop</code>），或在 Web 界面点停止，会立刻停下所有实盘活动；<code>/resume</code> 解除。每一次实盘操作都写入哈希链式审计账本，任何记录被改动或删除都能被发现。</p>
            `
          }
        ]
      }
    ]
  },
  {
    id: "reference",
    label: "参考",
    pages: [
      {
        id: "reference/cli",
        title: "命令行参考",
        description: "子命令、单次参数与交互式斜杠命令。",
        lead: "终端是跑可重复研究最快的方式。下面的内容都可以在 vibe-trading --help 里查到。",
        sections: [
          {
            id: "commands",
            title: "子命令",
            body: `
              <table>
                <thead><tr><th>命令</th><th>作用</th></tr></thead>
                <tbody>
                  <tr><td><code>run -p "…"</code></td><td>执行一条指令</td></tr>
                  <tr><td><code>chat</code></td><td>交互对话（等同于直接运行 <code>vibe-trading</code>）</td></tr>
                  <tr><td><code>init</code></td><td>交互式生成 <code>~/.vibe-trading/.env</code></td></tr>
                  <tr><td><code>serve --port 8899</code></td><td>启动 API 服务（前端已构建时同时提供 Web 界面）</td></tr>
                  <tr><td><code>setup</code></td><td>在源码目录里安装并构建 Web 界面</td></tr>
                  <tr><td><code>dev</code></td><td>同时启动后端和前端开发服务器</td></tr>
                  <tr><td><code>update</code></td><td>从 PyPI 安装最新版本</td></tr>
                  <tr><td><code>provider</code></td><td>服务商的 OAuth 登录，例如 Codex</td></tr>
                  <tr><td><code>data</code></td><td>数据路由模式：<code>status</code>、<code>mode</code>、<code>usage</code></td></tr>
                  <tr><td><code>list</code> / <code>show</code></td><td>列出运行 / 查看某次运行</td></tr>
                  <tr><td><code>memory</code></td><td>查看持久记忆</td></tr>
                  <tr><td><code>channels</code></td><td>IM 渠道：<code>status</code>、<code>start</code>、<code>stop</code>、<code>login</code>、<code>pairing</code></td></tr>
                  <tr><td><code>connector</code></td><td>券商连接器配置档与连接</td></tr>
                  <tr><td><code>portfolio</code></td><td>只读的多券商持仓</td></tr>
                  <tr><td><code>alpha</code></td><td>Alpha Zoo：<code>list</code>、<code>show</code>、<code>bench</code>、<code>compare</code>、<code>export-manifest</code></td></tr>
                  <tr><td><code>hypothesis</code></td><td>假设登记簿：<code>list</code>、<code>show</code>、<code>invalidate</code></td></tr>
                  <tr><td><code>playbook</code></td><td>定时研究模板</td></tr>
                  <tr><td><code>strategy-evidence</code></td><td>根据回测运行刷新策略证据</td></tr>
                </tbody>
              </table>
            `
          },
          {
            id: "flags",
            title: "单次参数",
            body: `
              <pre><code>vibe-trading -p "指令"              # 执行一条指令
vibe-trading -f prompt.txt          # 从文件读取指令
vibe-trading --json -p "指令"       # 机器可读的输出
vibe-trading --continue RUN_ID "追问"
vibe-trading --upload report.pdf
vibe-trading --list                 # 运行列表；另有 --show、--code、--pine、--trace RUN_ID
vibe-trading --sessions             # 会话列表；--session-chat SESSION_ID 继续某个会话
vibe-trading --skills
vibe-trading --max-iter 40 -p "指令"</code></pre>
            `
          },
          {
            id: "interactive",
            title: "交互式斜杠命令",
            body: `
              <table>
                <thead><tr><th>命令</th><th>作用</th></tr></thead>
                <tbody>
                  <tr><td><code>/help</code></td><td>快捷键与命令列表</td></tr>
                  <tr><td><code>/model</code></td><td>切换服务商和模型</td></tr>
                  <tr><td><code>/memory</code>、<code>/history</code>、<code>/search</code></td><td>记忆、历史会话、全文搜索</td></tr>
                  <tr><td><code>/goal</code></td><td>开始或查看研究目标</td></tr>
                  <tr><td><code>/swarm</code>、<code>/skill</code></td><td>团队预设、技能</td></tr>
                  <tr><td><code>/show</code>、<code>/pine</code>、<code>/export</code></td><td>查看运行、导出 Pine Script、导出会话</td></tr>
                  <tr><td><code>/journal</code>、<code>/shadow</code></td><td>交割单分析、影子账户</td></tr>
                  <tr><td><code>/comps</code>、<code>/dcf</code>、<code>/attrib</code>、<code>/memo</code>、<code>/earnings</code>、<code>/screen</code></td><td>机构研究</td></tr>
                  <tr><td><code>/playbook</code></td><td>定时研究模板</td></tr>
                  <tr><td><code>/connector</code>、<code>/data</code></td><td>券商配置档、数据路由</td></tr>
                  <tr><td><code>/halt</code>、<code>/resume</code></td><td>开启、解除紧急停止</td></tr>
                  <tr><td><code>/debug</code>、<code>/clear</code>、<code>/quit</code></td><td>token 与延迟面板、清空、退出</td></tr>
                </tbody>
              </table>
            `
          }
        ]
      },
      {
        id: "reference/mcp-server",
        title: "MCP 服务",
        description: "把 Vibe-Trading 的工具提供给 Claude Desktop、Cursor、OpenClaw 等 MCP 客户端。",
        lead: "vibe-trading-mcp 作为 MCP 客户端的 stdio 子进程运行，提供 74 个工具。研究类工具不需要模型 key；run_swarm 需要。",
        sections: [
          {
            id: "config",
            title: "客户端配置",
            body: `
              <pre><code>{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp",
      "env": { "VIBE_TRADING_ALLOWED_RUN_ROOTS": "/path/to/your/research" }
    }
  }
}</code></pre>
              <p>服务进程由客户端启动，你在 shell 里 export 的变量传不到它那里：key 和路径请写在 <code>env</code> 里。只有当你希望回测结果写进自己的目录时，才需要 <code>VIBE_TRADING_ALLOWED_RUN_ROOTS</code>。</p>
            `
          },
          {
            id: "tools",
            title: "工具范围",
            body: `
              <ul>
                <li><strong>研究</strong>：技能、研究目标、网页搜索、网址与文档阅读、文件读写。</li>
                <li><strong>行情</strong>：<code>get_market_data</code>，以及 22 个基本面与资金流工具。</li>
                <li><strong>分析</strong>：回测、因子分析、Alpha Zoo、期权、形态识别、技术指标、情绪、盘口深度、quantlib 函数、现金流业绩。</li>
                <li><strong>策略</strong>：列出、查询和刷新策略证据。</li>
                <li><strong>券商</strong>：<code>trading_connections</code>、<code>trading_check</code>、账户、持仓、订单、报价和历史——只读。</li>
                <li><strong>团队与运行</strong>：预设、<code>run_swarm</code>、状态、结果、重试。</li>
                <li><strong>影子账户</strong>：交割单分析、规则提炼、影子回测、报告。</li>
              </ul>
              <p>在所有 MCP 传输方式下，Shell 类工具默认关闭，除非传 <code>--enable-shell-tools</code> 或设置 <code>VIBE_TRADING_ENABLE_SHELL_TOOLS=1</code>。</p>
            `
          }
        ]
      },
      {
        id: "reference/web-ui-and-api",
        title: "Web 界面与 API",
        description: "浏览器界面、REST API、IM 渠道和定时研究。",
        lead: "vibe-trading serve 启动 FastAPI 服务，Web 界面、IM 渠道和定时任务都通过它运行。",
        sections: [
          {
            id: "pages",
            title: "Web 界面页面",
            body: `
              <ul>
                <li><strong>Agent</strong>——对话，实时显示工具步骤和团队面板；每条消息最多附五个文件。</li>
                <li><strong>报告</strong>与运行详情——历史运行、指标、图表和代码；<strong>对比</strong>页并排比较多次运行。</li>
                <li><strong>持仓</strong>——汇总各券商连接的只读持仓。</li>
                <li><strong>Alpha Zoo</strong>——浏览、评测和对比因子。</li>
                <li><strong>期权</strong>实验室与<strong>相关性</strong>状态。</li>
                <li><strong>定时</strong>——周期性研究任务。</li>
                <li><strong>设置</strong>——模型、数据源、IM 渠道和 API key。</li>
              </ul>
            `
          },
          {
            id: "auth",
            title: "访问与安全",
            body: `
              <p>在本机上无需任何配置即可使用。其他客户端访问时，请设置 <code>API_AUTH_KEY</code>，并在请求里带上 <code>Authorization: Bearer &lt;key&gt;</code>。交互式 API 文档 <code>/docs</code> 只在未设 key 的本机模式下开放；设了 key 后，带上请求头去取 <code>/openapi.json</code>。</p>
            `
          },
          {
            id: "channels",
            title: "IM 渠道",
            body: `
              <p>WebSocket、Telegram、Slack、Discord、Matrix、WhatsApp、Signal、QQ/NapCat、微信/企业微信、飞书/Lark、钉钉、Microsoft Teams、邮件和 Mochat 共用同一套会话。在设置 → IM 渠道里配置和启动，或使用 <code>vibe-trading channels status | start | stop</code>。不在渠道 <code>allow_from</code> 名单里的发送者会在私聊里收到一个配对码，在你用 <code>vibe-trading channels pairing approve</code> 批准之前，其消息都会被忽略。</p>
            `
          },
          {
            id: "scheduled",
            title: "定时研究",
            body: `
              <p>按固定间隔或 cron 表达式定时运行一条指令或一次回测。执行器默认关闭，启动服务时设置 <code>VIBE_TRADING_ENABLE_SCHEDULER=1</code> 才会开启。自带五个可直接定时的模板：盘前简报、财报季跟踪、组合体检、A 股资金流向和机构持仓变动。</p>
              <pre><code>vibe-trading playbook list
vibe-trading playbook show premarket-brief
vibe-trading playbook create premarket-brief</code></pre>
            `
          },
          {
            id: "endpoints",
            title: "主要接口",
            body: `
              <table>
                <thead><tr><th>接口</th><th>作用</th></tr></thead>
                <tbody>
                  <tr><td><code>POST /sessions</code>、<code>POST /sessions/{id}/messages</code></td><td>创建会话、发送消息</td></tr>
                  <tr><td><code>GET /sessions/{id}/events</code></td><td>SSE 事件流</td></tr>
                  <tr><td><code>POST /sessions/{id}/cancel</code></td><td>停止正在进行的运行</td></tr>
                  <tr><td><code>GET /runs</code>、<code>GET /runs/{run_id}</code></td><td>运行记录</td></tr>
                  <tr><td><code>POST /upload</code></td><td>上传文档、数据文件或图片</td></tr>
                  <tr><td><code>POST /swarm/runs</code></td><td>启动团队运行</td></tr>
                  <tr><td><code>POST /alpha/bench</code></td><td>启动 Alpha Zoo 评测</td></tr>
                  <tr><td><code>/scheduled-runs</code></td><td>定时任务与模板</td></tr>
                  <tr><td><code>POST /live/halt</code>、<code>POST /live/resume</code></td><td>紧急停止</td></tr>
                </tbody>
              </table>
            `
          }
        ]
      },
      {
        id: "reference/cloudflare-pages",
        title: "Cloudflare Pages",
        description: "本 wiki 如何构建、部署和编辑。",
        lead: "本 wiki 是静态站点，由 Cloudflare Pages 直接从仓库提供，没有构建步骤。",
        sections: [
          {
            id: "settings",
            title: "Pages 设置",
            body: `
              <ul>
                <li>项目根目录：<code>wiki</code></li>
                <li>构建命令：留空</li>
                <li>输出目录：<code>.</code></li>
                <li>自定义域名：<code>vibetrading.wiki</code></li>
              </ul>
              <p>推送到 <code>main</code> 且改动了 <code>wiki/</code> 或 <code>agent/src/factors/</code> 时自动部署；部署前会先生成因子库页面。</p>
            `
          },
          {
            id: "editing",
            title: "编辑文档",
            body: `
              <p>英文页面在 <code>wiki/docs/content.en.js</code>，中文页面在 <code>wiki/docs/content.zh.js</code>。两者的页面和小节必须一一对应、顺序一致。英文地址是 <code>/docs/latest/…</code>，中文地址是 <code>/docs/zh/…</code>。</p>
              <p>全站所有页面共用 <code>wiki/partials/</code> 里的同一套页头、页脚和 head 公共部分。其余页面的英文写在 HTML 里，中文在 <code>wiki/locales/zh.json</code>。默认英文，顶栏按钮切换整站语言并记住选择。CI 会运行：</p>
              <pre><code>node wiki/scripts/check_docs_parity.mjs
python3 wiki/scripts/sync_site_chrome.py --check
python3 wiki/scripts/check_i18n.py</code></pre>
            `
          },
          {
            id: "why-static",
            title: "为什么是静态站",
            body: `
              <p>文档、首页文案、跳转、主题、语言和搜索都能以静态文件实现，不需要 VPS、数据库或常驻服务；唯一的服务端代码是一个匿名的访问计数器。</p>
            `
          }
        ]
      }
    ]
  }
];
