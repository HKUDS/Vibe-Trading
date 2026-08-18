import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowRight, BookOpen, Loader2, Trash2 } from "lucide-react";
import { api, type ChanTrainingSession } from "@/lib/api";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";

function money(value: string, currency: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${currency}` : "-";
}

export function ChanTrainingReviews() {
  const [items, setItems] = useState<ChanTrainingSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ChanTrainingSession | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await api.listChanTrainingSessions();
      setItems(payload.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载复盘记录失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const remove = async () => {
    if (!pendingDelete) return;
    const item = pendingDelete;
    setPendingDelete(null);
    setDeletingId(item.id);
    setError("");
    try {
      await api.deleteChanTrainingSession(item.id);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除复盘记录失败");
    } finally {
      setDeletingId(null);
    }
  };

  return <div className="min-h-full p-6 lg:p-8"><div className="mx-auto max-w-5xl space-y-6">
    <header className="flex items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold tracking-tight">缠论训练复盘</h1><p className="mt-1 text-sm text-muted-foreground">查看每次模拟的行情、交易、费用和收益过程。</p></div><Link to="/chan-training" className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground">开始新训练</Link></header>
    {error && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
    {loading ? <div className="flex justify-center py-16 text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div> : items.length ? <div className="overflow-hidden rounded-xl border border-border/70 bg-card"><table className="w-full text-left text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr>{["时间", "标的", "市场/周期", "状态", "现金", "操作"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{items.map((item) => <tr key={item.id} className="hover:bg-muted/20"><td className="px-4 py-3 text-muted-foreground">{new Date(item.created_at).toLocaleString("zh-CN")}</td><td className="px-4 py-3"><div className="font-medium">{item.name || item.symbol}</div><div className="font-mono text-xs text-muted-foreground">{item.symbol}</div></td><td className="px-4 py-3">{item.market === "a_share" ? "A股" : "美股"} · {item.period === "1d" ? "日线" : "周线"}</td><td className="px-4 py-3">{item.status === "finished" ? "已完成" : "进行中"}</td><td className="px-4 py-3 font-mono">{money(item.cash, item.currency)}</td><td className="px-4 py-3"><div className="flex flex-wrap items-center gap-3"><Link to={`/chan-training/reviews/${encodeURIComponent(item.id)}`} className="inline-flex items-center gap-1 text-primary hover:underline"><BookOpen className="h-3.5 w-3.5" />打开复盘<ArrowRight className="h-3.5 w-3.5" /></Link>{item.status === "active" && <Link to="/chan-training" className="text-amber-600 hover:underline">继续训练</Link>}<button type="button" onClick={() => setPendingDelete(item)} disabled={deletingId === item.id} className="inline-flex items-center gap-1 text-danger hover:underline disabled:opacity-50"><Trash2 className="h-3.5 w-3.5" />{deletingId === item.id ? "删除中" : "删除"}</button></div></td></tr>)}</tbody></table></div> : <div className="rounded-xl border border-dashed border-border p-16 text-center text-sm text-muted-foreground">暂无训练记录</div>}
    <ConfirmDialog
      open={pendingDelete !== null}
      title={`删除${pendingDelete?.status === "active" ? "未结束的训练" : "复盘记录"}？`}
      description="删除后将无法恢复本次训练的行情、交易和复盘数据。"
      confirmLabel="确认删除"
      cancelLabel="取消"
      tone="destructive"
      onConfirm={() => void remove()}
      onCancel={() => setPendingDelete(null)}
    />
  </div></div>;
}
