import { Bot, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen } from "lucide-react";
import { useI18n } from "@/lib/i18n";

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

const CATEGORIES: Category[] = [
  {
    label: "多市场回测",
    icon: <TrendingUp className="h-4 w-4" />,
    color: "text-red-400 border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5",
    examples: [
      {
        title: "跨市场组合",
        desc: "A 股 + 加密货币 + 美股，使用风险平价优化器",
        prompt: "回测一个由 000001.SZ、BTC-USDT 和 AAPL 组成的风险平价组合，覆盖 2024 全年，并与等权基准比较。",
      },
      {
        title: "BTC 5 分钟 MACD 策略",
        desc: "基于分钟级 OKX 数据的加密回测",
        prompt: "回测 BTC-USDT 的 5 分钟 MACD 策略，fast=12 slow=26 signal=9，最近 30 天。",
      },
      {
        title: "美股科技最大分散化",
        desc: "基于 yfinance 的 FAANG+ 组合优化",
        prompt: "使用 max_diversification 组合优化器回测 AAPL、MSFT、GOOGL、AMZN、NVDA，覆盖 2024 全年。",
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
        desc: "基于 300 只股票的 IC 加权因子合成",
        prompt: "使用动量、反转、波动率和换手率构建多因子 Alpha 模型，覆盖沪深 300 成分股，并使用 IC 加权因子合成，回测 2023-2024 年。",
      },
      {
        title: "期权希腊值分析",
        desc: "使用 Black-Scholes 计算 Delta/Gamma/Theta/Vega",
        prompt: "使用 Black-Scholes 计算期权希腊值：现价=100，行权价=105，无风险利率=3%，波动率=25%，到期 90 天，分析 Delta/Gamma/Theta/Vega。",
      },
    ],
  },
  {
    label: "智能体团队",
    icon: <Users className="h-4 w-4" />,
    color: "text-violet-400 border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5",
    examples: [
      {
        title: "投资委员会评审",
        desc: "多智能体辩论：做多 vs 做空、风险审查、PM 决策",
        prompt: "[智能体团队模式] 使用 investment_committee 预设，评估在当前市场条件下 NVDA 应该做多还是做空。",
      },
      {
        title: "量化策略工作台",
        desc: "筛选 → 因子研究 → 回测 → 风控审计流水线",
        prompt: "[智能体团队模式] 使用 quant_strategy_desk 预设，在沪深 300 成分股中找出并回测最优动量策略。",
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
        desc: "上传 PDF 并询问财务细节",
        prompt: "总结上传的财报报告中的关键财务指标、风险和展望。",
      },
      {
        title: "网页研究：宏观展望",
        desc: "读取实时网页来源进行宏观分析",
        prompt: "阅读最新的美联储会议纪要，并总结对股票和加密市场的关键影响。",
      },
    ],
  },
  {
    label: "交易日志",
    icon: <NotebookPen className="h-4 w-4" />,
    color: "text-orange-400 border-orange-500/30 hover:border-orange-500/60 hover:bg-orange-500/5",
    examples: [
      {
        title: "分析券商导出文件",
        desc: "解析 同花顺 / 东财 / 富途 / 通用 CSV - 持有天数、胜率、盈亏比、小时分布",
        prompt: "分析我刚上传的交易日志，给出完整画像：持仓统计、胜率、最强标的和小时分布。",
      },
      {
        title: "诊断交易行为偏差",
        desc: "处置效应、过度交易、追涨、锚定 - 严重程度 + 数值证据",
        prompt: "对我的交易日志做 4 项行为诊断（处置效应、过度交易、追涨、锚定），并告诉我哪种偏差最伤害收益。",
      },
    ],
  },
  {
    label: "影子账户",
    icon: <UserCircle2 className="h-4 w-4" />,
    color: "text-emerald-400 border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5",
    examples: [
      {
        title: "用日志训练影子账户",
        desc: "从券商 CSV 提取策略规则并保存影子画像",
        prompt: "根据我刚上传的交易日志训练影子账户，展示提取出的规则并确认它们是否符合我的行为。",
      },
      {
        title: "我少赚了多少？",
        desc: "回测你的影子策略并对比实际收益差异",
        prompt: "对最近 90 天的美股市场运行影子回测，并拆解我的收益与影子账户的差异来自哪里（规则违规、过早离场、错过信号等）。",
      },
      {
        title: "生成影子报告",
        desc: "8 段式 HTML/PDF - 权益曲线、分市场 Sharpe、归因瀑布图",
        prompt: "渲染影子报告并把 URL 发给我——先给出我和影子账户的收益差异。",
      },
    ],
  },
];

const CAPABILITY_CHIPS = [
  "70 项金融技能",
  "29 个智能体预设",
  "32 个智能体工具",
  "3 个市场：A 股 · 加密货币 · 港美股",
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

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  const { t } = useI18n();

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
            与你的专业金融智能体团队一起进行 vibe trading
          </p>
          <p className="text-sm text-muted-foreground mt-2 max-w-md leading-relaxed mx-auto">
            {t.describeStrategy}
          </p>
        </div>
      </div>

      {/* Capability chips */}
      <div className="flex flex-wrap justify-center gap-2 max-w-lg">
        {CAPABILITY_CHIPS.map((chip) => (
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
          {CATEGORIES.map((cat) => (
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


