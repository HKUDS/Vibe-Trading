import { Bot, TrendingUp, Bitcoin, Globe, Sparkles, Users, UserCircle2, NotebookPen } from "lucide-react";
import { useI18n, type Language } from "@/lib/i18n";

interface Example {
  title: string;
  desc: string;
  prompt: string;
}

interface Category {
  label: string;
  icon: React.ReactNode;
  color: string;
  examples: Example[];
}

const EN_CATEGORIES: Category[] = [
  {
    label: "Multi-Market Backtest",
    icon: <TrendingUp className="h-4 w-4" />,
    color: "text-red-400 border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5",
    examples: [
      {
        title: "Cross-Market Portfolio",
        desc: "A-shares + crypto + US equities with risk-parity optimizer",
        prompt: "Backtest a risk-parity portfolio of 000001.SZ, BTC-USDT, and AAPL for full-year 2024, compare against equal-weight baseline",
      },
      {
        title: "BTC 5-Min MACD Strategy",
        desc: "Minute-level crypto backtest with real-time OKX data",
        prompt: "Backtest BTC-USDT 5-minute MACD strategy, fast=12 slow=26 signal=9, last 30 days",
      },
      {
        title: "US Tech Max Diversification",
        desc: "Portfolio optimizer across FAANG+ via yfinance",
        prompt: "Backtest AAPL, MSFT, GOOGL, AMZN, NVDA with max_diversification portfolio optimizer, full-year 2024",
      },
    ],
  },
  {
    label: "Research & Analysis",
    icon: <Sparkles className="h-4 w-4" />,
    color: "text-amber-400 border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5",
    examples: [
      {
        title: "Multi-Factor Alpha Model",
        desc: "IC-weighted factor synthesis across 300 stocks",
        prompt: "Build a multi-factor alpha model using momentum, reversal, volatility, and turnover on CSI 300 constituents with IC-weighted factor synthesis, backtest 2023-2024",
      },
      {
        title: "Options Greeks Analysis",
        desc: "Black-Scholes pricing with Delta/Gamma/Theta/Vega",
        prompt: "Calculate option Greeks using Black-Scholes: spot=100, strike=105, risk-free rate=3%, vol=25%, expiry=90 days, analyze Delta/Gamma/Theta/Vega",
      },
    ],
  },
  {
    label: "Swarm Teams",
    icon: <Users className="h-4 w-4" />,
    color: "text-violet-400 border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5",
    examples: [
      {
        title: "Investment Committee Review",
        desc: "Multi-agent debate: long vs short, risk review, PM decision",
        prompt: "[Swarm Team Mode] Use the investment_committee preset to evaluate whether to go long or short on NVDA given current market conditions",
      },
      {
        title: "Quant Strategy Desk",
        desc: "Screening → factor research → backtest → risk audit pipeline",
        prompt: "[Swarm Team Mode] Use the quant_strategy_desk preset to find and backtest the best momentum strategy on CSI 300 constituents",
      },
    ],
  },
  {
    label: "Document & Web Research",
    icon: <Globe className="h-4 w-4" />,
    color: "text-blue-400 border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5",
    examples: [
      {
        title: "Analyze an Earnings Report PDF",
        desc: "Upload a PDF and ask questions about the financials",
        prompt: "Summarize the key financial metrics, risks, and outlook from the uploaded earnings report",
      },
      {
        title: "Web Research: Macro Outlook",
        desc: "Read live web sources for macro analysis",
        prompt: "Read the latest Fed meeting minutes and summarize the key takeaways for equity and crypto markets",
      },
    ],
  },
  {
    label: "Trade Journal",
    icon: <NotebookPen className="h-4 w-4" />,
    color: "text-orange-400 border-orange-500/30 hover:border-orange-500/60 hover:bg-orange-500/5",
    examples: [
      {
        title: "Analyze My Broker Export",
        desc: "Parse 同花顺/东财/富途/generic CSV — holding days, win rate, PnL ratio, hourly distribution",
        prompt: "Analyze the trade journal I just uploaded — full profile with holding stats, win rate, top symbols, and hourly distribution",
      },
      {
        title: "Diagnose My Behavior Biases",
        desc: "Disposition effect, overtrading, chasing momentum, anchoring — severity + numeric evidence",
        prompt: "Run the 4 behavior diagnostics on my trade journal (disposition, overtrading, chasing, anchoring) and tell me which bias hurts my PnL most",
      },
    ],
  },
  {
    label: "Shadow Account",
    icon: <UserCircle2 className="h-4 w-4" />,
    color: "text-emerald-400 border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5",
    examples: [
      {
        title: "Train My Shadow from Journal",
        desc: "Extract your strategy rules from a broker CSV and persist a Shadow profile",
        prompt: "Train my shadow account from the trading journal I just uploaded — show the extracted rules and confirm they look like my behavior",
      },
      {
        title: "How Much Am I Leaving on the Table?",
        desc: "Backtest your shadow strategy and attribute delta vs. your actual PnL",
        prompt: "Run a shadow backtest for the last 90 days on the US market and break down where my PnL diverged from the shadow (rule violations, early exits, missed signals)",
      },
      {
        title: "Generate Shadow Report",
        desc: "8-section HTML/PDF — equity curve, per-market Sharpe, attribution waterfall",
        prompt: "Render the shadow report and give me the URL — lead with the you-vs-shadow delta",
      },
    ],
  },
];

const ZH_CATEGORIES: Category[] = [
  {
    label: "跨市场回测",
    icon: <TrendingUp className="h-4 w-4" />,
    color: "text-red-400 border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5",
    examples: [
      {
        title: "跨市场组合",
        desc: "A 股 + 加密货币 + 美股，使用风险平价优化器",
        prompt: "回测 000001.SZ、BTC-USDT 和 AAPL 的风险平价组合，时间为 2024 全年，并与等权基准对比",
      },
      {
        title: "BTC 5 分钟 MACD 策略",
        desc: "使用 OKX 实时数据做分钟级加密货币回测",
        prompt: "回测 BTC-USDT 5 分钟 MACD 策略，fast=12 slow=26 signal=9，最近 30 天",
      },
      {
        title: "美股科技股最大分散化",
        desc: "通过 yfinance 对 FAANG+ 做组合优化",
        prompt: "回测 AAPL、MSFT、GOOGL、AMZN、NVDA，使用 max_diversification 组合优化器，时间为 2024 全年",
      },
    ],
  },
  {
    label: "研究与分析",
    icon: <Sparkles className="h-4 w-4" />,
    color: "text-amber-400 border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5",
    examples: [
      {
        title: "多因子 Alpha 模型",
        desc: "在 300 只股票上做 IC 加权因子合成",
        prompt: "基于沪深 300 成分股，使用动量、反转、波动率和换手率构建多因子 alpha 模型，采用 IC 加权因子合成，回测 2023-2024",
      },
      {
        title: "期权 Greeks 分析",
        desc: "Black-Scholes 定价，计算 Delta/Gamma/Theta/Vega",
        prompt: "使用 Black-Scholes 计算期权 Greeks：现价=100，行权价=105，无风险利率=3%，波动率=25%，到期=90 天，并分析 Delta/Gamma/Theta/Vega",
      },
    ],
  },
  {
    label: "代理团队",
    icon: <Users className="h-4 w-4" />,
    color: "text-violet-400 border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5",
    examples: [
      {
        title: "投资委员会评审",
        desc: "多代理辩论：多头 vs 空头、风险复核、PM 决策",
        prompt: "[Swarm Team Mode] 使用 investment_committee 预设，结合当前市场环境评估 NVDA 应该做多还是做空",
      },
      {
        title: "量化策略台",
        desc: "筛选 → 因子研究 → 回测 → 风险审计流水线",
        prompt: "[Swarm Team Mode] 使用 quant_strategy_desk 预设，在沪深 300 成分股中寻找并回测最佳动量策略",
      },
    ],
  },
  {
    label: "文档与网页研究",
    icon: <Globe className="h-4 w-4" />,
    color: "text-blue-400 border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5",
    examples: [
      {
        title: "分析财报 PDF",
        desc: "上传 PDF 后询问其中的财务数据",
        prompt: "总结我上传的财报中的关键财务指标、风险和展望",
      },
      {
        title: "网页研究：宏观展望",
        desc: "读取实时网页来源做宏观分析",
        prompt: "读取最新的美联储会议纪要，并总结其对股票和加密市场的关键影响",
      },
    ],
  },
  {
    label: "交易日志",
    icon: <NotebookPen className="h-4 w-4" />,
    color: "text-orange-400 border-orange-500/30 hover:border-orange-500/60 hover:bg-orange-500/5",
    examples: [
      {
        title: "分析券商导出记录",
        desc: "解析同花顺/东财/富途/通用 CSV，统计持仓天数、胜率、盈亏比和小时分布",
        prompt: "分析我刚上传的交易日志，给出完整画像：持仓统计、胜率、主要标的和小时分布",
      },
      {
        title: "诊断交易行为偏差",
        desc: "处置效应、过度交易、追涨杀跌、锚定偏差，给出严重程度和数字证据",
        prompt: "对我的交易日志运行 4 项行为诊断（处置效应、过度交易、追涨杀跌、锚定），告诉我哪个偏差最伤害 PnL",
      },
    ],
  },
  {
    label: "影子账户",
    icon: <UserCircle2 className="h-4 w-4" />,
    color: "text-emerald-400 border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5",
    examples: [
      {
        title: "从交易日志训练影子账户",
        desc: "从券商 CSV 中提取你的策略规则，并保存为 Shadow profile",
        prompt: "从我刚上传的交易日志训练影子账户，展示提取出的规则，并确认这些规则是否像我的真实行为",
      },
      {
        title: "我错过了多少收益？",
        desc: "回测你的影子策略，并归因它与真实 PnL 的差异",
        prompt: "对最近 90 天的美股市场运行影子回测，拆解我的 PnL 与影子账户差异来自哪里（规则违反、过早离场、漏掉信号）",
      },
      {
        title: "生成影子账户报告",
        desc: "8 节 HTML/PDF：权益曲线、分市场 Sharpe、归因瀑布图",
        prompt: "生成影子账户报告并给我 URL，优先展示我和影子账户的差异",
      },
    ],
  },
];

const CATEGORIES_BY_LANGUAGE: Record<Language, Category[]> = {
  en: EN_CATEGORIES,
  "zh-CN": ZH_CATEGORIES,
};

const EN_CAPABILITY_CHIPS = [
  "70 Finance Skills",
  "29 Swarm Presets",
  "32 Agent Tools",
  "3 Markets: A-Share · Crypto · HK/US",
  "Minute to Daily Timeframes",
  "4 Portfolio Optimizers",
  "15+ Risk Metrics",
  "Options & Derivatives",
  "PDF & Web Research",
  "Factor Analysis & ML",
  "Trade Journal Analyzer",
  "Shadow Account Backtest",
  "Persistent Memory",
  "Session Search",
];

const ZH_CAPABILITY_CHIPS = [
  "70 个金融技能",
  "29 个代理团队预设",
  "32 个代理工具",
  "3 类市场：A 股 · 加密 · 港美股",
  "分钟到日线周期",
  "4 种组合优化器",
  "15+ 风险指标",
  "期权与衍生品",
  "PDF 与网页研究",
  "因子分析与机器学习",
  "交易日志分析器",
  "影子账户回测",
  "持久记忆",
  "会话搜索",
];

const CAPABILITY_CHIPS_BY_LANGUAGE: Record<Language, string[]> = {
  en: EN_CAPABILITY_CHIPS,
  "zh-CN": ZH_CAPABILITY_CHIPS,
};

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  const { t, language } = useI18n();
  const categories = CATEGORIES_BY_LANGUAGE[language];
  const capabilityChips = CAPABILITY_CHIPS_BY_LANGUAGE[language];

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-8 text-center">
      {/* Header */}
      <div className="space-y-3">
        <div className="h-16 w-16 mx-auto rounded-2xl bg-gradient-to-br from-primary/80 to-info/80 flex items-center justify-center shadow-lg">
          <Bot className="h-8 w-8 text-white" />
        </div>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Vibe-Trading</h2>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto leading-relaxed">
            {t.welcomeTagline}
          </p>
          <p className="text-sm text-muted-foreground mt-2 max-w-md leading-relaxed mx-auto">
            {t.describeStrategy}
          </p>
        </div>
      </div>

      {/* Capability chips */}
      <div className="flex flex-wrap justify-center gap-2 max-w-lg">
        {capabilityChips.map((chip) => (
          <span
            key={chip}
            className="px-2.5 py-1 text-xs rounded-full border border-border/60 text-muted-foreground bg-muted/30"
          >
            {chip}
          </span>
        ))}
      </div>

      {/* Example categories grid */}
      <div className="w-full max-w-2xl text-left space-y-4">
        <p className="text-xs text-muted-foreground px-1">{t.examples}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {categories.map((cat) => (
            <div key={cat.label} className="space-y-2">
              <div className={`flex items-center gap-1.5 text-xs font-medium px-1 ${cat.color.split(" ").filter(c => c.startsWith("text-")).join(" ")}`}>
                {cat.icon}
                <span>{cat.label}</span>
              </div>
              <div className="space-y-1.5">
                {cat.examples.map((ex) => (
                  <button
                    key={ex.title}
                    onClick={() => onExample(ex.prompt)}
                    className={`block w-full text-left px-3 py-2.5 rounded-xl border transition-colors ${cat.color}`}
                  >
                    <span className="text-sm font-medium text-foreground leading-snug">
                      {ex.title}
                    </span>
                    <span className="block text-xs text-muted-foreground mt-0.5 leading-snug">
                      {ex.desc}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


