import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Eye, EyeOff, Link as LinkIcon, Loader2, RotateCcw, ArrowLeft, ArrowRight, CheckCircle2 } from "lucide-react";
import { Link } from "react-router";
import { CandlestickChart, ChanTheoryGuide, type Sub } from "@/components/charts/CandlestickChart";
import { api, type ChanTrainingAnalysisRun, type ChanTrainingCreateRequest, type ChanTrainingSession, type TradeMarker } from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULTS: ChanTrainingCreateRequest = {
  market: "a_share", period: "1d", initial_capital: "100000", window_size: 60,
  commission_enabled: false, commission_rate: "0.0003", stamp_enabled: false,
  stamp_rate: "0.0005", transfer_enabled: false, transfer_rate: "0.00001",
};

function number(value: string | number | null | undefined, digits = 2) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}

function maskSession(session: ChanTrainingSession): ChanTrainingSession {
  return {
    ...session,
    symbol: null,
    name: null,
    bars: session.bars?.map((bar, index) => ({ ...bar, time: `K${index + 1}` })),
    trades: session.trades?.map((trade) => ({ ...trade, trade_time: `K${trade.bar_index + 1}` })),
  };
}

function mergeStableSession(previous: ChanTrainingSession | null, next: ChanTrainingSession): ChanTrainingSession {
  if (!previous?.bars || !next.bars || previous.bars.length !== next.bars.length) return next;
  const unchanged = previous.bars.every((bar, index) => {
    const incoming = next.bars?.[index];
    return incoming
      && bar.time === incoming.time
      && bar.open === incoming.open
      && bar.high === incoming.high
      && bar.low === incoming.low
      && bar.close === incoming.close
      && bar.volume === incoming.volume
      && bar.amount === incoming.amount;
  });
  return unchanged ? { ...next, bars: previous.bars } : next;
}

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="space-y-1 text-xs text-muted-foreground"><span>{label}</span>{children}</label>;
}

function Input({ value, onChange, type = "text", disabled = false, step }: { value: string | number; onChange: (value: string) => void; type?: string; disabled?: boolean; step?: string }) {
  return <input value={value} type={type} step={step} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2.5 text-sm text-foreground outline-none focus:border-primary disabled:opacity-60" />;
}

export function ChanTraining() {
  const [form, setForm] = useState(DEFAULTS);
  const [session, setSession] = useState<ChanTrainingSession | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [sub, setSub] = useState<Sub>("vol");
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [action, setAction] = useState(false);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [poolCounts, setPoolCounts] = useState<Record<string, number>>({});
  const [analysisRun, setAnalysisRun] = useState<ChanTrainingAnalysisRun | null>(null);
  const [analysisSubmitting, setAnalysisSubmitting] = useState(false);
  const revealedSession = useRef<ChanTrainingSession | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.listChanTrainingSessions()
      .then(async (payload) => {
        const active = (payload.items || [])
          .filter((item) => item.status === "active")
          .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
        if (!active) return;
        const resumed = await api.getChanTrainingSession(active.id);
        if (!cancelled) {
          revealedSession.current = null;
          setSession(maskSession(resumed));
          setRevealed(false);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "无法恢复未结束的训练");
      })
      .finally(() => {
        if (!cancelled) setRestoring(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!session || session.status !== "finished") return;
    void api.getChanTrainingAnalysis(session.id).then(setAnalysisRun).catch(() => undefined);
  }, [session?.id, session?.status]);

  useEffect(() => {
    if (!session || session.status !== "finished" || !analysisRun || !["queued", "running"].includes(analysisRun.status)) return;
    const timer = window.setInterval(() => {
      void api.getChanTrainingAnalysis(session.id).then(setAnalysisRun).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [analysisRun, session]);

  useEffect(() => {
    let cancelled = false;
    void api.getChanTrainingInstrumentCounts()
      .then((result) => {
        if (!cancelled) setPoolCounts(result.counts || {});
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "无法读取本地标的池");
      });
    return () => { cancelled = true; };
  }, []);

  const syncInstruments = async (market: "a_share" | "us" | "all") => {
    setSyncing(true);
    setError("");
    try {
      await api.syncChanTrainingInstruments(market);
      const counts = await api.getChanTrainingInstrumentCounts();
      setPoolCounts(counts.counts || {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "标的同步失败，请稍后重试");
    } finally {
      setSyncing(false);
    }
  };

  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const capital = Number(form.initial_capital);
    if (!Number.isFinite(capital) || capital <= 0 || form.window_size < 2) {
      setError("初始资金必须大于0，窗口大小至少为2");
      return;
    }
    setLoading(true);
    try {
      const created = await api.createChanTrainingSession({ ...form, initial_capital: String(capital), window_size: Number(form.window_size) });
      revealedSession.current = null;
      setSession(maskSession(created));
      setRevealed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "行情获取失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const revealIdentity = async () => {
    if (!session) return;
    if (revealed) {
      setSession(maskSession(revealedSession.current || session));
      setRevealed(false);
      return;
    }
    setAction(true);
    try {
      const full = await api.getChanTrainingReview(session.id);
      revealedSession.current = full;
      setSession(full);
      setRevealed(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法揭示训练信息");
    } finally {
      setAction(false);
    }
  };

  const move = useCallback(async (delta: number) => {
    if (!session || action || !["active", "finished"].includes(session.status)) return;
    const bars = session.bars || [];
    const next = Math.max(session.window_size - 1, Math.min(session.current_cursor + delta, bars.length - 1));
    if (next === session.current_cursor) return;
    setAction(true);
    try {
      const updated = await api.saveChanTrainingState(session.id, next);
      const nextSession = revealed
        ? await api.getChanTrainingReview(session.id)
        : maskSession(updated);
      setSession((current) => mergeStableSession(current, nextSession));
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存训练进度失败");
    } finally {
      setAction(false);
    }
  }, [action, revealed, session]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT") return;
      if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") { event.preventDefault(); void move(1); }
      if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") { event.preventDefault(); void move(-1); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [move]);

  const trade = async (side: "buy" | "sell", ratio: string) => {
    if (!session || action || session.status !== "active") return;
    setAction(true);
    setError("");
    try {
      const updated = await api.executeChanTrainingTrade(session.id, side, ratio);
      const nextSession = revealed ? updated : maskSession(updated);
      setSession((current) => mergeStableSession(current, nextSession));
      if (revealed) revealedSession.current = updated;
    } catch (err) {
      setError(err instanceof Error ? err.message : "交易执行失败");
    } finally {
      setAction(false);
    }
  };

  const finish = async () => {
    if (!session || action) return;
    setAction(true);
    try {
      const updated = await api.finishChanTrainingSession(session.id);
      revealedSession.current = updated;
      setSession(updated);
      setRevealed(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "结束训练失败");
    } finally {
      setAction(false);
    }
  };

  const triggerAnalysis = async () => {
    if (!session || session.status !== "finished" || analysisSubmitting) return;
    setAnalysisSubmitting(true);
    setError("");
    try {
      setAnalysisRun(await api.createChanTrainingAnalysis(session.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 缠论分析提交失败");
    } finally {
      setAnalysisSubmitting(false);
    }
  };

  const bars = session?.bars || [];
  const startIndex = session ? Math.max(0, session.current_cursor - session.window_size + 1) : 0;
  const revealedBars = useMemo(() => session ? bars.slice(0, session.current_cursor + 1) : [], [bars, session?.current_cursor]);

  if (!session && restoring) {
    return <div className="flex min-h-full items-center justify-center text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />恢复未结束的训练</div>;
  }

  if (!session) {
    return <div className="min-h-full p-6 lg:p-8"><div className="mx-auto max-w-4xl space-y-6">
      <header><h1 className="text-2xl font-semibold tracking-tight">缠论训练</h1><p className="mt-1 text-sm text-muted-foreground">开始模拟前设置本局规则；点击开始后才获取股票和 K 线数据。</p></header>
      <form onSubmit={start} className="rounded-xl border border-border/70 bg-card p-5 shadow-sm">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="市场"><select value={form.market} onChange={(e) => setForm({ ...form, market: e.target.value as "a_share" | "us" })} className="h-9 w-full rounded-md border border-border bg-background px-2.5 text-sm"><option value="a_share">A股</option><option value="us">美股</option></select></FormField>
          <FormField label="周期"><select value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value as "1d" | "1w" })} className="h-9 w-full rounded-md border border-border bg-background px-2.5 text-sm"><option value="1d">日线</option><option value="1w">周线</option></select></FormField>
          <FormField label="初始资金"><Input value={form.initial_capital} type="number" step="any" onChange={(value) => setForm({ ...form, initial_capital: value })} /></FormField>
          <FormField label="可视窗口（根）"><Input value={form.window_size} type="number" onChange={(value) => setForm({ ...form, window_size: Number(value) })} /></FormField>
          <FormField label="佣金费率"><Input value={form.commission_rate} type="number" step="any" onChange={(value) => setForm({ ...form, commission_rate: value })} /></FormField>
          <FormField label="印花税率"><Input value={form.stamp_rate} type="number" step="any" onChange={(value) => setForm({ ...form, stamp_rate: value })} /></FormField>
          <FormField label="过户费率"><Input value={form.transfer_rate} type="number" step="any" onChange={(value) => setForm({ ...form, transfer_rate: value })} /></FormField>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {([["commission_enabled", "开启佣金"], ["stamp_enabled", "开启印花税"], ["transfer_enabled", "开启过户费"]] as const).map(([key, label]) => <label key={key} className="flex items-center gap-2 rounded-md border border-border/70 px-3 py-2 text-sm"><input type="checkbox" checked={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.checked })} />{label}</label>)}
        </div>
        <div className="mt-5 rounded-lg border border-dashed border-border/80 bg-muted/20 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><p className="text-sm font-medium">标的池</p><p className="text-xs text-muted-foreground">页面只读取数据库；点击同步时才请求第三方并更新股票基础信息，训练会话只从数据库标的池随机抽取。</p></div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void syncInstruments("a_share")} disabled={syncing} className="h-8 rounded-md border border-border px-3 text-xs hover:bg-muted disabled:opacity-50">同步 A 股</button>
              <button type="button" onClick={() => void syncInstruments("us")} disabled={syncing} className="h-8 rounded-md border border-border px-3 text-xs hover:bg-muted disabled:opacity-50">同步美股</button>
              <button type="button" onClick={() => void syncInstruments("all")} disabled={syncing} className="h-8 rounded-md bg-primary px-3 text-xs text-primary-foreground disabled:opacity-50">{syncing ? "同步中…" : "同步全部"}</button>
            </div>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">当前可用：A 股 {poolCounts.a_share ?? 0} 个，美股 {poolCounts.us ?? 0} 个</p>
        </div>
        {error && <p className="mt-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
        <div className="mt-5 flex flex-wrap items-center gap-3"><button type="submit" disabled={loading} className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground disabled:opacity-60">{loading && <Loader2 className="h-4 w-4 animate-spin" />}开始模拟</button><Link to="/chan-training/reviews" className="inline-flex h-10 items-center gap-2 rounded-md border border-border px-4 text-sm hover:bg-muted"><LinkIcon className="h-4 w-4" />查看复盘</Link></div>
      </form>
    </div></div>;
  }

  const visibleBars = revealedBars;
  const lastClose = Number(visibleBars[visibleBars.length - 1]?.close || 0);
  const cash = Number(session.cash);
  const position = Number(session.position);
  const assets = cash + position * lastClose;
  const pnl = assets - Number(session.initial_capital);
  const markers: TradeMarker[] = (session.trades || []).filter((trade) => trade.bar_index >= startIndex && trade.bar_index <= session.current_cursor).map((trade) => ({ time: revealedBars[trade.bar_index]?.time || `K${trade.bar_index + 1}`, price: Number(trade.price), side: trade.side === "buy" ? "BUY" : "SELL", qty: Number(trade.quantity), reason: `${trade.side === "buy" ? "买入" : "卖出"} ${trade.ratio}` }));
  const canLeft = session.current_cursor > session.window_size - 1;
  const canRight = session.current_cursor < bars.length - 1;
  const periodLabel = session.period === "1d" ? "日线" : "周线";

  return <div className="min-h-full p-6 lg:p-8"><div className="mx-auto max-w-7xl space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold tracking-tight">缠论训练 · {periodLabel}</h1><p className="mt-1 text-sm text-muted-foreground">{session.name || "股票名称未揭示"} {session.symbol ? `· ${session.symbol}` : "· 盲测中"}</p></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void revealIdentity()} disabled={action} className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-muted disabled:opacity-60">{revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}{revealed ? "隐藏身份/时间" : "显示身份/时间"}</button>{session.status === "finished" && <button type="button" onClick={() => void triggerAnalysis()} disabled={analysisSubmitting || ["queued", "running"].includes(analysisRun?.status || "")} className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:opacity-60">{analysisSubmitting ? "提交中…" : analysisRun?.status === "failed" ? "重新分析" : "AI 缠论分析"}</button>}<button type="button" onClick={finish} disabled={action || session.status !== "active"} className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-muted disabled:opacity-60"><CheckCircle2 className="h-4 w-4" />结束训练</button><button type="button" onClick={() => { setSession(null); setRevealed(false); revealedSession.current = null; setAnalysisRun(null); }} className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground"><RotateCcw className="h-4 w-4" />重新开始</button></div></header>
    {error && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
    {session.status === "finished" && analysisRun && <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm"><div><p className="font-medium">AI 缠论分析：{analysisRun.status === "queued" ? "排队中" : analysisRun.status === "running" ? "分析中" : analysisRun.status === "completed" ? "已完成" : "失败"}</p>{analysisRun.error && <p className="mt-1 text-xs text-danger">{analysisRun.error}</p>}</div><Link to={`/chan-training/reviews/${encodeURIComponent(session.id)}`} className="text-primary hover:underline">打开复盘报告</Link></section>}
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><Metric label="现金" value={number(cash)} suffix={session.currency} /><Metric label="持仓" value={number(position, 0)} suffix="股" /><Metric label="持仓市值" value={number(position * lastClose)} suffix={session.currency} /><Metric label="总资产" value={number(assets)} suffix={session.currency} /><Metric label="收益" value={`${pnl >= 0 ? "+" : ""}${number(pnl)} (${((pnl / Number(session.initial_capital)) * 100).toFixed(2)}%)`} tone={pnl >= 0 ? "text-red-500" : "text-emerald-500"} /></section>
    <ChanTheoryGuide />
    <section className="rounded-xl border border-border/70 bg-card p-3 sm:p-4"><div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3"><div className="flex items-center gap-2 text-xs text-muted-foreground"><span>窗口 {startIndex + 1}–{session.current_cursor + 1} / {bars.length}</span><span>·</span><span>快捷键 A/D 或 ←/→</span></div><div className="flex gap-1"><button type="button" onClick={() => void move(-1)} disabled={!canLeft || action} className="rounded border border-border p-1.5 disabled:opacity-40" title="上一根"><ArrowLeft className="h-4 w-4" /></button><button type="button" onClick={() => void move(1)} disabled={!canRight || action} className="rounded border border-border p-1.5 disabled:opacity-40" title="下一根"><ArrowRight className="h-4 w-4" /></button></div></div><CandlestickChart data={visibleBars} calculationData={bars} calculationOffset={startIndex} height={520} market={session.market} symbol={session.symbol || undefined} markers={markers} chanAnalysis={session.chan_analysis} showChan sub={sub} onSubChange={setSub} availableSubs={["vol", "amount", "macd", "rsi", "kdj", "boll", "expma"]} /></section>
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"><TradePanel session={session} action={action} onTrade={trade} /><TradeHistory trades={session.trades || []} currency={session.currency} /></section>
  </div></div>;
}

function Metric({ label, value, suffix, tone = "" }: { label: string; value: string; suffix?: string; tone?: string }) { return <div className="rounded-lg border border-border/60 bg-card px-4 py-3"><p className="text-[11px] text-muted-foreground">{label}</p><p className={cn("mt-1 font-mono text-lg font-semibold", tone)}>{value} <span className="text-xs font-normal text-muted-foreground">{suffix}</span></p></div>; }

function TradePanel({ session, action, onTrade }: { session: ChanTrainingSession; action: boolean; onTrade: (side: "buy" | "sell", ratio: string) => void }) {
  const buyRatios = ["1/2", "1/3", "1/4", "1"];
  const sellRatios = ["1/2", "1/3", "1/4"];
  const disabled = action || session.status !== "active";
  const buttonClass = "h-9 rounded-md text-sm disabled:opacity-40";
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4">
      <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">模拟交易</h2><span className="text-xs text-muted-foreground">收盘价成交</span></div>
      <div className="mt-4 space-y-2">
        <div className="grid grid-cols-4 gap-2">
          {buyRatios.map((ratio) => <button key={`buy-${ratio}`} type="button" onClick={() => onTrade("buy", ratio)} disabled={disabled} className={`${buttonClass} bg-red-500/10 text-red-600 hover:bg-red-500/20`}>{ratio === "1" ? "全仓买入" : `买入 ${ratio}`}</button>)}
        </div>
        <div className="grid grid-cols-4 gap-2">
          {sellRatios.map((ratio) => <button key={`sell-${ratio}`} type="button" onClick={() => onTrade("sell", ratio)} disabled={disabled} className={`${buttonClass} bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20`}>卖出 {ratio}</button>)}
          <button type="button" onClick={() => onTrade("sell", "clear")} disabled={disabled} className={`${buttonClass} border border-border hover:bg-muted`}>清仓</button>
        </div>
      </div>
      <p className="mt-4 text-xs text-muted-foreground">费用累计：{number(session.total_fees)} {session.currency}。佣金、印花税和过户费按本局开始前配置计算。</p>
    </div>
  );
}

function TradeHistory({ trades, currency }: { trades: ChanTrainingSession["trades"]; currency: string }) { return <div className="rounded-xl border border-border/70 bg-card p-4"><h2 className="text-sm font-semibold">成交记录</h2><div className="mt-3 max-h-64 overflow-auto"><table className="w-full text-left text-xs"><thead className="text-muted-foreground"><tr>{["序号", "方向", "位置", "价格", "数量", "费用"].map((label) => <th key={label} className="px-2 py-2 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{trades?.map((trade) => <tr key={trade.id}><td className="px-2 py-2">{trade.sequence}</td><td className={cn("px-2 py-2", trade.side === "buy" ? "text-red-500" : "text-emerald-500")}>{trade.side === "buy" ? "买入" : "卖出"}</td><td className="px-2 py-2">{trade.trade_time}</td><td className="px-2 py-2 font-mono">{number(trade.price)}</td><td className="px-2 py-2 font-mono">{number(trade.quantity, 0)}</td><td className="px-2 py-2 font-mono">{number(trade.total_fees)} {currency}</td></tr>)}</tbody></table>{!trades?.length && <p className="py-8 text-center text-sm text-muted-foreground">暂无成交</p>}</div></div>; }
