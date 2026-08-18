import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Loader2 } from "lucide-react";
import { CandlestickChart, ChanTheoryGuide, type Sub } from "@/components/charts/CandlestickChart";
import { api, type ChanTrainingSession, type TradeMarker } from "@/lib/api";
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

  useEffect(() => {
    if (!sessionId) return;
    api.getChanTrainingReview(sessionId).then((payload) => {
      setSession(payload);
      setCursor(payload.current_cursor);
    }).finally(() => setLoading(false));
  }, [sessionId]);

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
  const windowDescription = trades.length
    ? `首笔交易前 20 根至末笔交易后 10 根；实际显示第 ${reviewWindow.start + 1}-${reviewWindow.end} 根`
    : "本局没有成交记录，显示完整行情";

  return <div className="min-h-full p-6 lg:p-8"><div className="mx-auto max-w-7xl space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><Link to="/chan-training/reviews" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />返回复盘列表</Link><h1 className="text-2xl font-semibold tracking-tight">{session.name} · {session.symbol}</h1><p className="mt-1 text-sm text-muted-foreground">{session.market === "a_share" ? "A股" : "美股"} · {session.period === "1d" ? "日线" : "周线"} · {session.status === "finished" ? "已完成" : "进行中"}</p></div><div className="rounded-lg border border-border/70 bg-card px-4 py-3 text-right text-sm"><p className="text-xs text-muted-foreground">最终收益</p><p className={cn("mt-1 font-mono font-semibold", pnl >= 0 ? "text-red-500" : "text-emerald-500")}>{pnl >= 0 ? "+" : ""}{number(pnl)} {session.currency}</p><p className="text-xs text-muted-foreground">{((pnl / Number(session.initial_capital)) * 100).toFixed(2)}%</p></div></header>
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><Metric label="初始资金" value={session.initial_capital} suffix={session.currency} /><Metric label="现金" value={session.cash} suffix={session.currency} /><Metric label="持仓" value={session.position} suffix="股" /><Metric label="累计费用" value={session.total_fees} suffix={session.currency} /><Metric label="交易次数" value={String(trades.length)} /></section>
    <ChanTheoryGuide />
    <section className="rounded-xl border border-border/70 bg-card p-3 sm:p-4"><div className="mb-3 flex items-center justify-between gap-3 border-b border-border/60 pb-3 text-xs text-muted-foreground"><span>复盘窗口：{windowDescription}（完整日线/周线数据已加载）</span><span>当前第 {reviewCursor + 1} / {bars.length} 根</span></div><CandlestickChart data={bars} calculationData={bars} initialStartIndex={reviewWindow.start} initialEndIndex={reviewWindow.end - 1} height={560} market={session.market} symbol={session.symbol || undefined} markers={markers} chanAnalysis={session.chan_analysis} showChan sub={sub} onSubChange={setSub} availableSubs={["vol", "amount", "macd", "rsi", "kdj", "boll", "expma"]} /></section>
    <section className="rounded-xl border border-border/70 bg-card p-4"><h2 className="text-sm font-semibold">交易明细</h2><div className="mt-3 overflow-auto"><table className="w-full min-w-[950px] text-left text-xs"><thead className="bg-muted/40 text-muted-foreground"><tr>{["序号", "时间", "方向", "收盘价", "数量", "成交金额", "佣金", "印花税", "过户费", "费用合计", "交易后总资产"].map((label) => <th key={label} className="px-3 py-2 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{trades.map((trade) => <tr key={trade.id} onClick={() => setCursor(trade.bar_index)} className="cursor-pointer hover:bg-muted/30"><td className="px-3 py-2">{trade.sequence}</td><td className="px-3 py-2">{trade.trade_time}</td><td className={cn("px-3 py-2", trade.side === "buy" ? "text-red-500" : "text-emerald-500")}>{trade.side === "buy" ? "买入" : "卖出"}</td><td className="px-3 py-2 font-mono">{number(trade.price)}</td><td className="px-3 py-2 font-mono">{number(trade.quantity, 0)}</td><td className="px-3 py-2 font-mono">{number(trade.gross_amount)}</td><td className="px-3 py-2 font-mono">{number(trade.commission)}</td><td className="px-3 py-2 font-mono">{number(trade.stamp_tax)}</td><td className="px-3 py-2 font-mono">{number(trade.transfer_fee)}</td><td className="px-3 py-2 font-mono">{number(trade.total_fees)}</td><td className="px-3 py-2 font-mono">{number(trade.total_assets_after)}</td></tr>)}</tbody></table>{!trades.length && <p className="py-8 text-center text-sm text-muted-foreground">暂无成交记录</p>}</div></section>
  </div></div>;
}

function Metric({ label, value, suffix }: { label: string; value: string; suffix?: string }) { return <div className="rounded-lg border border-border/60 bg-card px-4 py-3"><p className="text-[11px] text-muted-foreground">{label}</p><p className="mt-1 font-mono text-lg font-semibold">{number(value)} <span className="text-xs font-normal text-muted-foreground">{suffix}</span></p></div>; }
