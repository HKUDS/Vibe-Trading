import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Language = "en" | "zh-CN";

const enMessages = {
  home: "Home", agent: "Agent", runs: "Runs", settings: "Settings",
  startResearch: "Start Research", describeStrategy: "Describe a trading strategy to get started.",
  prompt: "e.g. Create a dual MA crossover strategy for 000001.SZ, backtest 2024",
  send: "Send", loading: "Loading...", noRuns: "No runs yet. Go to Agent to create one.",
  runHistory: "Run History", status: "Status", elapsed: "Elapsed",
  chart: "Chart", trades: "Trades", code: "Code", trace: "Trace",
  noData: "No data available", noTrades: "No trades recorded.", noCode: "No code files.",
  noTrace: "No trace data.", priceAndTrades: "Price & Trades", equityAndDrawdown: "Equity & Drawdown",
  examples: "Try an example:", bye: "Goodbye",
  heroTitle: "AI-Powered Quant Strategy Research",
  heroDesc: "Describe a trading strategy in natural language. The agent generates code, runs backtests, and optimizes — all in real time.",
  feat1: "AI Agent", feat1d: "Natural language strategy generation with ReAct reasoning",
  feat2: "Built-in Backtest", feat2d: "3 data sources: A-shares, US/HK, Crypto",
  feat3: "Real-time Streaming", feat3d: "Watch the agent think, call tools, and iterate",
  feat4: "Strategy Replay", feat4d: "Trade journal analyzer + Shadow Account — extract your rules, backtest them, attribute PnL delta",
  score: "Score", passed: "Passed", failed: "Failed", findings: "Findings", recommendations: "Recommendations",
  darkMode: "Dark", lightMode: "Light", language: "Language",
  sessions: "Sessions", newChat: "New Chat", deleteConfirm: "Delete?",
  noSessions: "No sessions yet",
  viewDetails: "View Details",
  fullReport: "Full Report →",
  strategyComparison: "Strategy Comparison",
  baseline: "Baseline", compareTo: "Compare", delta: "Delta", metric: "Metric",
  selectRun: "-- Select --",
  selectTwoRuns: "Select two runs to compare their metrics.",
  online: "Online", offline: "Offline",
  checking: "Checking…", checkConnection: "Check Connection",
  appearance: "Appearance",
  connection: "Connection",
  endpoints: "Endpoints",
  review: "Review",
  noReview: "No review data available.",
  welcomeTagline: "vibe trading with your professional financial agent team",
  colTime: "Time", colCode: "Code", colSide: "Side",
  colPrice: "Price", colQty: "Qty", colReason: "Reason",
  equityDrawdown: "Equity & Drawdown",
  noPriceData: "No price data", noEquityData: "No equity data",
  filterLogs: "Filter logs...",
  confirmDelete: "Confirm", cancelDelete: "Cancel",
  reconnectingN: "Connection lost, reconnecting (attempt {n})…",
  disconnected: "Connection lost",
  sessionCreated: "Session started",
  sendFailed: "Failed to send message, please retry.",
  reconnecting: "Connection lost, reconnecting…",
  connected: "Connection restored",
  toolLoadSkill: "Load strategy knowledge",
  toolWriteFile: "Generate code",
  toolEditFile: "Edit code",
  toolReadFile: "Read file",
  toolRunBacktest: "Run backtest",
  toolBash: "Run command",
  toolReadUrl: "Read webpage",
  toolReadDocument: "Read document",
  toolCompact: "Compact context",
  toolCreateTask: "Create task",
  toolUpdateTask: "Update task",
  toolSpawnSubagent: "Spawn sub-agent",
  toolProcessing: "Processing",
  toolRunning: "Running",
  thinkingRunning: "Running {tool}...",
  thinkingDone: "Done · {count} steps",
  metricTotalReturn: "Total Return",
  metricAnnualReturn: "Annual",
  metricSharpe: "Sharpe",
  metricMaxDrawdown: "Max DD",
  metricWinRate: "Win Rate",
  metricTradeCount: "Trades",
  metricFinalValue: "Final Value",
  metricCalmar: "Calmar",
  metricSortino: "Sortino",
  metricProfitLossRatio: "P/L Ratio",
  metricMaxConsecutiveLoss: "Max Consec. Loss",
  metricAvgHoldingDays: "Avg Hold Days",
  metricBenchmarkReturn: "Benchmark",
  metricExcessReturn: "Excess Return",
  metricIR: "IR",
  validation: "Validation",
  overlayMA: "Moving Avg",
  overlayChannel: "Channel",
  overlayIndicators: "Indicators",
  overlayClearAll: "Bare K (clear all)",
  rename: "Rename",
  goBack: "Go back",
  noChartData: "No chart data available",
  noChartDataHint: "The backtest engine may not have generated price data. Check the artifacts/ directory.",
  executionFailed: "Execution failed",
  executionTimeout: "Execution timed out, automatically stopped",
  cancelSent: "Cancel request sent",
  cancelFailed: "Cancel failed",
  exportChat: "Export chat",
  stopGeneration: "Stop generation",
  newMessages: "New messages",
  moreOptions: "More options",
  uploadPdf: "Upload PDF document",
  agentSwarm: "Agent Swarm",
  uploading: "Uploading...",
  executablesBlocked: "Executables and archives are not allowed",
  fileSizeExceeded: "File size exceeds 50 MB limit",
  uploaded: "Uploaded: {name}",
  uploadFailed: "Upload failed: {error}",
  unknownError: "Unknown error",
  runNotFound: "Run not found",
  switchLanguage: "Switch language",
  languageEnglish: "English",
  languageChinese: "中文",
  collapseSidebar: "Collapse",
  expandSidebar: "Expand",
  step: "Step",
  stepN: "Step {n}",
  exportTitle: "# Chat Export",
  exportTime: "Export time",
  exportUser: "## User",
  exportAssistant: "## Assistant",
  exportError: "## Error",
  exportToolCall: "> Tool call",
  exportRunComplete: "> Backtest complete",
  downloadTradesCsv: "Download Trades CSV",
  downloadMetricsCsv: "Download Metrics CSV",
  example1: "Dual MA crossover on 000001.SZ (5/20 day), backtest 2024",
  example2: "Build a dual MA crossover strategy for 000001.SZ, backtest 2024",
  example3: "Bollinger band mean-reversion on 600519.SH, backtest last 3 years",
} as const;

type EnglishMessages = typeof enMessages;
export type MessageKey = keyof EnglishMessages;
export type Messages = Record<MessageKey, string>;

const zhMessages: Messages = {
  home: "首页", agent: "代理", runs: "运行记录", settings: "设置",
  startResearch: "开始研究", describeStrategy: "描述一个交易策略即可开始。",
  prompt: "例如：为 000001.SZ 创建双均线交叉策略，并回测 2024 年",
  send: "发送", loading: "加载中...", noRuns: "还没有运行记录。前往代理页面创建一个。",
  runHistory: "运行历史", status: "状态", elapsed: "耗时",
  chart: "图表", trades: "交易", code: "代码", trace: "追踪",
  noData: "暂无数据", noTrades: "暂无交易记录。", noCode: "暂无代码文件。",
  noTrace: "暂无追踪数据。", priceAndTrades: "价格与交易", equityAndDrawdown: "权益与回撤",
  examples: "试试这些示例：", bye: "再见",
  heroTitle: "AI 驱动的量化策略研究",
  heroDesc: "用自然语言描述交易策略。代理会生成代码、运行回测并实时优化。",
  feat1: "AI 代理", feat1d: "通过 ReAct 推理把自然语言转成策略",
  feat2: "内置回测", feat2d: "覆盖 A 股、港美股、加密货币三类数据源",
  feat3: "实时流式输出", feat3d: "实时查看代理思考、调用工具和迭代过程",
  feat4: "策略复盘", feat4d: "交易日志分析 + 影子账户，提取规则、回测并归因盈亏差异",
  score: "评分", passed: "通过", failed: "失败", findings: "发现", recommendations: "建议",
  darkMode: "深色", lightMode: "浅色", language: "语言",
  sessions: "会话", newChat: "新建会话", deleteConfirm: "删除？",
  noSessions: "还没有会话",
  viewDetails: "查看详情",
  fullReport: "完整报告 →",
  strategyComparison: "策略对比",
  baseline: "基准", compareTo: "对比", delta: "差异", metric: "指标",
  selectRun: "-- 请选择 --",
  selectTwoRuns: "选择两个运行记录以对比指标。",
  online: "在线", offline: "离线",
  checking: "检查中…", checkConnection: "检查连接",
  appearance: "外观",
  connection: "连接",
  endpoints: "端点",
  review: "审查",
  noReview: "暂无审查数据。",
  welcomeTagline: "与你的专业金融代理团队一起 vibe trading",
  colTime: "时间", colCode: "代码", colSide: "方向",
  colPrice: "价格", colQty: "数量", colReason: "原因",
  equityDrawdown: "权益与回撤",
  noPriceData: "暂无价格数据", noEquityData: "暂无权益数据",
  filterLogs: "筛选日志...",
  confirmDelete: "确认", cancelDelete: "取消",
  reconnectingN: "连接中断，正在重连（第 {n} 次）…",
  disconnected: "连接中断",
  sessionCreated: "会话已开始",
  sendFailed: "发送失败，请重试。",
  reconnecting: "连接中断，正在重连…",
  connected: "连接已恢复",
  toolLoadSkill: "加载策略知识",
  toolWriteFile: "生成代码",
  toolEditFile: "编辑代码",
  toolReadFile: "读取文件",
  toolRunBacktest: "运行回测",
  toolBash: "运行命令",
  toolReadUrl: "读取网页",
  toolReadDocument: "读取文档",
  toolCompact: "压缩上下文",
  toolCreateTask: "创建任务",
  toolUpdateTask: "更新任务",
  toolSpawnSubagent: "启动子代理",
  toolProcessing: "处理中",
  toolRunning: "运行中",
  thinkingRunning: "正在运行 {tool}...",
  thinkingDone: "完成 · {count} 步",
  metricTotalReturn: "总收益",
  metricAnnualReturn: "年化收益",
  metricSharpe: "夏普",
  metricMaxDrawdown: "最大回撤",
  metricWinRate: "胜率",
  metricTradeCount: "交易数",
  metricFinalValue: "最终价值",
  metricCalmar: "卡玛",
  metricSortino: "索提诺",
  metricProfitLossRatio: "盈亏比",
  metricMaxConsecutiveLoss: "最大连亏",
  metricAvgHoldingDays: "平均持仓天数",
  metricBenchmarkReturn: "基准收益",
  metricExcessReturn: "超额收益",
  metricIR: "信息比率",
  validation: "验证",
  overlayMA: "均线",
  overlayChannel: "通道",
  overlayIndicators: "指标",
  overlayClearAll: "裸 K（清空）",
  rename: "重命名",
  goBack: "返回",
  noChartData: "暂无图表数据",
  noChartDataHint: "回测引擎可能没有生成价格数据。请检查 artifacts/ 目录。",
  executionFailed: "执行失败",
  executionTimeout: "执行超时，已自动停止",
  cancelSent: "已发送取消请求",
  cancelFailed: "取消失败",
  exportChat: "导出聊天",
  stopGeneration: "停止生成",
  newMessages: "新消息",
  moreOptions: "更多选项",
  uploadPdf: "上传 PDF 文档",
  agentSwarm: "代理团队",
  uploading: "上传中...",
  executablesBlocked: "不允许上传可执行文件和压缩包",
  fileSizeExceeded: "文件大小超过 50 MB 限制",
  uploaded: "已上传：{name}",
  uploadFailed: "上传失败：{error}",
  unknownError: "未知错误",
  runNotFound: "未找到运行记录",
  switchLanguage: "切换语言",
  languageEnglish: "English",
  languageChinese: "中文",
  collapseSidebar: "收起侧栏",
  expandSidebar: "展开侧栏",
  step: "步骤",
  stepN: "第 {n} 步",
  exportTitle: "# 聊天导出",
  exportTime: "导出时间",
  exportUser: "## 用户",
  exportAssistant: "## 助手",
  exportError: "## 错误",
  exportToolCall: "> 工具调用",
  exportRunComplete: "> 回测完成",
  downloadTradesCsv: "下载交易 CSV",
  downloadMetricsCsv: "下载指标 CSV",
  example1: "000001.SZ 双均线交叉（5/20 日），回测 2024 年",
  example2: "为 000001.SZ 构建双均线交叉策略，回测 2024 年",
  example3: "600519.SH 布林带均值回归，回测最近 3 年",
};

const messagesByLanguage: Record<Language, Messages> = {
  en: enMessages,
  "zh-CN": zhMessages,
};

const STORAGE_KEY = "vibe-trading-language";

function getInitialLanguage(): Language {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "en" || saved === "zh-CN") return saved;
  return navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

interface I18nValue {
  language: Language;
  setLanguage: (language: Language) => void;
  toggleLanguage: () => void;
  t: Messages;
}

const I18nCtx = createContext<I18nValue>({
  language: "zh-CN",
  setLanguage: () => {},
  toggleLanguage: () => {},
  t: zhMessages,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(getInitialLanguage);

  const setLanguage = (next: Language) => {
    setLanguageState(next);
    localStorage.setItem(STORAGE_KEY, next);
  };

  const toggleLanguage = () => {
    setLanguage(language === "zh-CN" ? "en" : "zh-CN");
  };

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<I18nValue>(() => ({
    language,
    setLanguage,
    toggleLanguage,
    t: messagesByLanguage[language],
  }), [language]);

  return (
    <I18nCtx.Provider value={value}>
      {children}
    </I18nCtx.Provider>
  );
}

export function useI18n() { return useContext(I18nCtx); }
