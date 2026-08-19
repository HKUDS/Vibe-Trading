import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Loader2 } from "lucide-react";
import { CandlestickChart, ChanTheoryGuide, type Sub } from "@/components/charts/CandlestickChart";
import { MarkdownContent } from "@/components/chat/MessageBubble";
import { api, type ChanTrainingAnalysisRun, type ChanTrainingSession, type TradeMarker } from "@/lib/api";
import { cn } from "@/lib/utils";

function number(value: string | number | null | undefined, digits = 2) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "-";
}

export function ChanTrainingReview() {
  const { sessionId } = useParams();
  const [session, setSession] = useState<ChanTrainingSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [sub, setSub] = useState<Sub>("vol");
  const [cursor, setCursor] = useState<number | null>(null);
  const [analysisRun, setAnalysisRun] = useState<ChanTrainingAnalysisRun | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisSubmitting, setAnalysisSubmitting] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    api.getChanTrainingReview(sessionId).then((payload) => {
      setSession(payload);
      setCursor(payload.current_cursor);
    }).finally(() => setLoading(false));
    void api.getChanTrainingAnalysis(sessionId).then(setAnalysisRun).catch(() => undefined);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !analysisRun || !["queued", "running"].includes(analysisRun.status)) return;
    const timer = window.setInterval(() => {
      void api.getChanTrainingAnalysis(sessionId).then(setAnalysisRun).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [analysisRun, sessionId]);

  const triggerAnalysis = async () => {
    if (!sessionId) return;
    setAnalysisSubmitting(true);
    setAnalysisError(null);
    try {
      setAnalysisRun(await api.createChanTrainingAnalysis(sessionId));
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "生成分析失败");
    } finally {
      setAnalysisSubmitting(false);
    }
  };

  const bars = session?.bars || [];
  const trades = session?.trades || [];
  const reviewCursor = cursor ?? session?.current_cursor ?? 0;
  const reviewWindow = useMemo(() => {
    if (!trades.length || !bars.length) return { start: 0, end: bars.length };
    const firstTrade = Math.min(...trades.map((trade) => trade.bar_index));
    const lastTrade = Math.max(...trades.map((trade) => trade.bar_index));
    return { start: Math.max(0, firstTrade - 20), end: Math.min(bars.length, lastTrade + 11) };
  }, [bars, trades]);
  const markers: TradeMarker[] = useMemo(() => trades.map((trade) => ({
    time: bars[trade.bar_index]?.time || trade.trade_time,
    price: Number(trade.price),
    side: trade.side === "buy" ? "BUY" : "SELL",
    qty: Number(trade.quantity),
    reason: `${trade.side === "buy" ? "买入" : "卖出"} ${trade.ratio}`,
  })), [bars, trades]);

  if (loading) return <div className="flex min-h-full items-center justify-center text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载复盘</div>;
  if (!session) return <div className="p-8 text-sm text-danger">复盘不存在</div>;

  const lastClose = Number(bars[reviewCursor]?.close || 0);
  const assets = Number(session.cash) + Number(session.position) * lastClose;
  const pnl = assets - Number(session.initial_capital);
  const windowDescription = trades.length ? `首笔交易前 20 根至末笔交易后 10 根；实际显示第 ${reviewWindow.start + 1}-${reviewWindow.end} 根` : "本局没有成交记录，显示完整行情";

  return <div className="min-h-full p-6 lg:p-8"><div className="mx-auto max-w-7xl space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><Link to="/chan-training/reviews" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />返回复盘列表</Link><h1 className="text-2xl font-semibold tracking-tight">{session.name} · {session.symbol}</h1><p className="mt-1 text-sm text-muted-foreground">{session.market === "a_share" ? "A股" : "美股"} · {session.period === "1d" ? "日线" : "周线"} · {session.status === "finished" ? "已完成" : "进行中"}</p></div><div className="flex items-center gap-3"><button type="button" onClick={triggerAnalysis} disabled={analysisSubmitting || ["queued", "running"].includes(analysisRun?.status || "")} className="rounded-lg bg-primary px-4 py-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60">{analysisSubmitting ? "提交中…" : analysisRun?.status === "failed" ? "重新生成缠论分析" : "生成缠论分析"}</button><div className="flex items-center gap-2 whitespace-nowrap rounded-lg border border-border/70 bg-card px-4 py-3 text-sm"><span className="text-xs text-muted-foreground">最终收益</span><span className={cn("font-mono font-semibold", pnl >= 0 ? "text-red-500" : "text-emerald-500")}>{pnl >= 0 ? "+" : ""}{number(pnl)} {session.currency}</span><span className="text-xs text-muted-foreground">{((pnl / Number(session.initial_capital)) * 100).toFixed(2)}%</span></div></div></header>
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><Metric label="初始资金" value={session.initial_capital} suffix={session.currency} /><Metric label="现金" value={session.cash} suffix={session.currency} /><Metric label="持仓" value={session.position} suffix="股" /><Metric label="累计费用" value={session.total_fees} suffix={session.currency} /><Metric label="交易次数" value={String(trades.length)} /></section>
    <ChanTheoryGuide />
    <AnalysisCard run={analysisRun} error={analysisError} />
    <section className="rounded-xl border border-border/70 bg-card p-3 sm:p-4"><div className="mb-3 flex items-center justify-between gap-3 border-b border-border/60 pb-3 text-xs text-muted-foreground"><span>复盘窗口：{windowDescription}（完整日线/周线数据已加载）</span><span>当前第 {reviewCursor + 1} / {bars.length} 根</span></div><CandlestickChart data={bars} calculationData={bars} initialStartIndex={reviewWindow.start} initialEndIndex={reviewWindow.end - 1} height={560} market={session.market} symbol={session.symbol || undefined} markers={markers} chanAnalysis={session.chan_analysis} showChan sub={sub} onSubChange={setSub} availableSubs={["vol", "amount", "macd", "rsi", "kdj", "boll", "expma"]} /></section>
    <TradeDetails trades={trades} onSelect={setCursor} />
  </div></div>;
}

function AnalysisCard({ run, error }: { run: ChanTrainingAnalysisRun | null; error: string | null }) {
  const [expanded, setExpanded] = useState(true);
  if (error) return <section className="mb-3 rounded-xl border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-600">{error}</section>;
  if (!run || run.status === "not_started") return null;
  const report = run.report;
  const summary = report?.structure_summary || {};
  const window = run.window || {};
  const status = run.status === "queued" ? "排队中" : run.status === "running" ? "分析中" : run.status === "completed" ? "已完成" : "失败";
  return <aside className="mb-3 rounded-xl border border-border/70 bg-card p-3 text-xs">
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)} className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 text-left">
      <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><h3 className="text-sm font-semibold">缠论 Agent 分析</h3><span className="leading-5 text-muted-foreground">状态：{status} · 数据版本 {run.analysis_version || "-"}</span></span>
      <span className="text-muted-foreground">{expanded ? "收起" : "展开"}</span>
    </button>
    {expanded && <div className="mt-3 space-y-4">
      {run.status !== "completed" || !report ? <div>{run.status === "failed" ? <p className="text-red-600">{run.error || "分析失败，请重新触发。"}</p> : <p className="text-muted-foreground">正在基于不可变行情快照计算，页面会自动更新。</p>}</div> : <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{Object.entries(summary).map(([key, value]) => <div key={key} className="rounded-lg bg-muted/40 px-3 py-2"><span className="text-muted-foreground">{key}</span><strong className="ml-2 font-mono">{value}</strong></div>)}</div>
        <div className="rounded-lg border border-border/60 p-3"><p className="font-medium">交易表现与置信度</p><p className="mt-1 text-muted-foreground">交易 {String(report.performance?.trade_count ?? 0)} 笔；顺应结构 {String(report.performance?.aligned_trade_count ?? 0)} 笔；置信度 {report.confidence || "-"}</p></div>
        <TradeAnalysisTable trades={report.trades || []} />
        <div className="grid gap-3 md:grid-cols-2"><ReportList title="执行正确项" items={report.execution_correct} /><ReportList title="违反缠论规则项" items={report.rule_violations} /><ReportList title="时机、持仓和退出" items={report.timing_and_exit} /><ReportList title="后续复盘规则" items={report.follow_up_rules} /></div>
        <div className="rounded-lg bg-muted/30 p-3 text-muted-foreground"><p>分析窗口：{String(window.start || "-")} 至 {String(window.end || "-")}；实际数据：{String(window.available_start || "-")} 至 {String(window.available_end || "-")}；来源：训练会话不可变行情快照。</p>{report.agent_report && <div className="mt-3 border-t border-border/50 pt-3 text-foreground"><MarkdownContent content={report.agent_report} /></div>}</div>
      </>}
    </div>}
  </aside>;
}

function TradeAnalysisTable({ trades }: { trades: Array<Record<string, any>> }) { return <div><p className="mb-2 text-sm font-medium">逐笔缠论对照</p><div className="overflow-auto"><table className="w-full min-w-[720px] text-left"><thead className="bg-muted/40 text-muted-foreground"><tr>{["序号", "方向", "时间", "最近结构", "信号", "趋势顺应", "中枢附近"].map((label) => <th key={label} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{trades.map((trade) => <tr key={String(trade.sequence)}><td className="px-3 py-2">{String(trade.sequence)}</td><td className="px-3 py-2">{trade.side === "buy" ? "买入" : "卖出"}</td><td className="px-3 py-2">{String(trade.trade_time || "-")}</td><td className="px-3 py-2">{String(trade.nearest_structure?.direction || "未匹配")}</td><td className="px-3 py-2">{String(trade.matched_signal?.label || "未识别")}</td><td className="px-3 py-2">{trade.trend_aligned ? "是" : "否"}</td><td className="px-3 py-2">{trade.near_center ? "是" : "否"}</td></tr>)}</tbody></table>{!trades.length && <p className="py-4 text-center text-muted-foreground">暂无交易记录</p>}</div></div>; }

function TradeDetails({ trades, onSelect }: { trades: ChanTrainingSession["trades"]; onSelect: (index: number) => void }) { return <section className="rounded-xl border border-border/70 bg-card p-4"><h2 className="text-sm font-semibold">交易明细</h2><div className="mt-3 overflow-auto"><table className="w-full min-w-[950px] text-left text-xs"><thead className="bg-muted/40 text-muted-foreground"><tr>{["序号", "时间", "方向", "收盘价", "数量", "成交金额", "佣金", "印花税", "过户费", "费用合计", "交易后总资产"].map((label) => <th key={label} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{(trades || []).map((trade) => <tr key={trade.id} onClick={() => onSelect(trade.bar_index)} className="cursor-pointer hover:bg-muted/30"><td className="px-3 py-2">{trade.sequence}</td><td className="px-3 py-2">{trade.trade_time}</td><td className={cn("px-3 py-2", trade.side === "buy" ? "text-red-500" : "text-emerald-500")}>{trade.side === "buy" ? "买入" : "卖出"}</td><td className="px-3 py-2 font-mono">{number(trade.price)}</td><td className="px-3 py-2 font-mono">{number(trade.quantity, 0)}</td><td className="px-3 py-2 font-mono">{number(trade.gross_amount)}</td><td className="px-3 py-2 font-mono">{number(trade.commission)}</td><td className="px-3 py-2 font-mono">{number(trade.stamp_tax)}</td><td className="px-3 py-2 font-mono">{number(trade.transfer_fee)}</td><td className="px-3 py-2 font-mono">{number(trade.total_fees)}</td><td className="px-3 py-2 font-mono">{number(trade.total_assets_after)}</td></tr>)}</tbody></table>{!trades?.length && <p className="py-8 text-center text-sm text-muted-foreground">暂无成交记录</p>}</div></section>; }

function Metric({ label, value, suffix }: { label: string; value: string; suffix?: string }) { return <div className="rounded-lg border border-border/60 bg-card px-4 py-3"><p className="text-[11px] text-muted-foreground">{label}</p><p className="mt-1 font-mono text-lg font-semibold">{number(value)} <span className="text-xs font-normal text-muted-foreground">{suffix}</span></p></div>; }
function ReportList({ title, items }: { title: string; items?: string[] }) { return <div className="rounded-lg border border-border/60 p-3"><p className="text-xs font-medium">{title}</p>{items?.length ? <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="mt-2 text-xs text-muted-foreground">暂无可确认项</p>}</div>; }
