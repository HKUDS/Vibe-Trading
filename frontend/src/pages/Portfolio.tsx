import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Plus, RefreshCw, RotateCcw, WalletCards } from "lucide-react";
import { Link } from "react-router";
import { api, type PortfolioAssetType, type PortfolioBrokerProfile, type PortfolioInstrumentCandidate, type PortfolioItem, type PortfolioSnapshotResponse, type PortfolioTransaction, type PortfolioTransactionType } from "@/lib/api";

const transactionTypes: Array<{ value: PortfolioTransactionType; label: string }> = [
  { value: "buy", label: "买入" },
  { value: "sell", label: "卖出" },
  { value: "fee", label: "费用" },
  { value: "dividend", label: "分红" },
  { value: "deposit", label: "入金" },
  { value: "withdrawal", label: "出金" },
  { value: "adjustment", label: "调整" },
];

function number(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString(undefined, { maximumFractionDigits: digits }) : "—";
}

function money(value: string | null | undefined, currency: string): string {
  if (value === null || value === undefined) return "—";
  return `${currency} ${number(value)}`;
}

function tone(value: string | null | undefined): string {
  if (!value) return "text-muted-foreground";
  // Chinese market convention: red means up/profit, green means down/loss.
  return Number(value) >= 0 ? "text-red-600" : "text-emerald-600";
}

export function Portfolio() {
  const [portfolios, setPortfolios] = useState<PortfolioItem[]>([]);
  const [brokerProfiles, setBrokerProfiles] = useState<PortfolioBrokerProfile[]>([]);
  const [selectedId, setSelectedId] = useState("all");
  const [snapshot, setSnapshot] = useState<PortfolioSnapshotResponse | null>(null);
  const [transactions, setTransactions] = useState<PortfolioTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [newPortfolio, setNewPortfolio] = useState("");
  const [brokerProfile, setBrokerProfile] = useState("");
  const [reconciliation, setReconciliation] = useState<{ items: Array<Record<string, string | null>>; observed_at?: string } | null>(null);
  const [instrumentQuery, setInstrumentQuery] = useState("");
  const [instrumentResults, setInstrumentResults] = useState<PortfolioInstrumentCandidate[]>([]);
  const [priceDrafts, setPriceDrafts] = useState<Record<string, string>>({});
  const [editingPriceKey, setEditingPriceKey] = useState<string | null>(null);
  const [form, setForm] = useState({ type: "buy" as PortfolioTransactionType, asset_type: "equity" as PortfolioAssetType, symbol: "", market: "a_share", quantity: "", price: "", amount: "", fee: "", tax: "", currency: "CNY", trade_at: new Date().toISOString().slice(0, 10), note: "" });

  const loadPortfolios = useCallback(async () => {
    const response = await api.listPortfolios();
    let items = response.items || [];
    if (items.length === 0) {
      const created = await api.createPortfolio({ name: "我的持仓", base_currency: "CNY" });
      items = [created];
    }
    setPortfolios(items);
    setSelectedId((current) => current === "all" || items.some((item) => item.id === current) ? current : items[0].id);
  }, []);

  const loadBrokerProfiles = useCallback(async () => {
    const response = await api.listPortfolioBrokerProfiles();
    const items = response.items || [];
    setBrokerProfiles(items);
    setBrokerProfile((current) => current && items.some((item) => item.id === current) ? current : "");
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadPortfolios(), loadBrokerProfiles()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法加载组合");
    }
  }, [loadBrokerProfiles, loadPortfolios]);

  useEffect(() => { void loadData(); }, [loadData]);

  const loadSelectedData = useCallback(async () => {
    if (!selectedId) return;
    setLoading(true);
    try {
      const [nextSnapshot, nextTransactions] = await Promise.all([
        api.getPortfolioSnapshot(selectedId),
        selectedId === "all" ? Promise.resolve({ items: [] as PortfolioTransaction[] }) : api.listPortfolioTransactions(selectedId),
      ]);
      setSnapshot(nextSnapshot);
      setTransactions(nextTransactions.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法加载持仓数据");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => { void loadSelectedData(); }, [loadSelectedData]);

  useEffect(() => {
    if (["fee", "dividend", "deposit", "withdrawal"].includes(form.type) || instrumentQuery.trim().length < 1) {
      setInstrumentResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const result = await api.searchPortfolioInstruments(instrumentQuery.trim(), controller.signal);
        setInstrumentResults(result.items || []);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) setInstrumentResults([]);
      }
    }, 250);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [form.type, instrumentQuery]);

  const currencyEntries = useMemo(() => Object.values(snapshot?.currencies || {}), [snapshot]);
  const primaryCurrency = currencyEntries[0]?.currency || "CNY";
  const submitTransaction = async (event: FormEvent) => {
    event.preventDefault();
    if (selectedId === "all") { setError("请先选择一个组合再记账"); return; }
    try {
      const payload: Record<string, unknown> = { ...form };
      for (const key of ["quantity", "price", "amount", "fee", "tax"]) if (!payload[key]) delete payload[key];
      if (["fee", "dividend", "deposit", "withdrawal"].includes(form.type)) {
        delete payload.symbol; delete payload.market; delete payload.quantity; delete payload.price;
      }
      await api.addPortfolioTransaction(selectedId, payload);
      setShowForm(false);
      setInstrumentQuery("");
      setInstrumentResults([]);
      setForm((current) => ({ ...current, symbol: "", quantity: "", price: "", amount: "", fee: "", tax: "", note: "" }));
      await loadSelectedData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "记账失败");
    }
  };

  const createPortfolio = async () => {
    const name = newPortfolio.trim();
    if (!name) return;
    try {
      const created = await api.createPortfolio({ name, base_currency: "CNY" });
      setPortfolios((items) => [...items, created]);
      setSelectedId(created.id);
      setNewPortfolio("");
    } catch (err) { setError(err instanceof Error ? err.message : "创建组合失败"); }
  };

  const refreshReconciliation = async () => {
    if (selectedId === "all" || !brokerProfile.trim()) return;
    try {
      const result = await api.refreshPortfolioReconciliation(selectedId, brokerProfile.trim());
      setReconciliation(result);
    } catch (err) { setError(err instanceof Error ? err.message : "对账失败"); }
  };

  const reconciliationRows = useMemo(() => {
    if (!reconciliation) return [];
    const rows = new Map<string, { symbol: string; market: "a_share" | "us"; currency: string; ledgerQuantity: number; brokerQuantity: number; avgCost: string }>();
    snapshot?.holdings.forEach((holding) => {
      if (holding.market !== "a_share" && holding.market !== "us") return;
      rows.set(`${holding.market}:${holding.symbol}`, { symbol: holding.symbol, market: holding.market, currency: holding.currency, ledgerQuantity: Number(holding.quantity), brokerQuantity: 0, avgCost: holding.avg_cost });
    });
    reconciliation.items.forEach((item) => {
      const symbol = String(item.symbol || "").toUpperCase();
      if (!symbol) return;
      const market = item.market === "a_share" ? "a_share" : "us";
      const key = `${market}:${symbol}`;
      const current = rows.get(key) || { symbol, market, currency: primaryCurrency, ledgerQuantity: 0, brokerQuantity: 0, avgCost: "0" };
      rows.set(key, { ...current, brokerQuantity: Number(item.quantity || 0), avgCost: String(item.avg_cost || current.avgCost || "0") });
    });
    return Array.from(rows.values()).map((row) => ({ ...row, delta: row.brokerQuantity - row.ledgerQuantity }));
  }, [primaryCurrency, reconciliation, snapshot]);

  const prepareAdjustment = (row: (typeof reconciliationRows)[number]) => {
    setForm((current) => ({ ...current, type: "adjustment", asset_type: "equity", symbol: row.symbol, market: row.market, currency: row.currency, quantity: String(row.delta), price: row.avgCost || "0", amount: "" }));
    setInstrumentQuery(row.symbol);
    setShowForm(true);
  };

  const chooseInstrument = (candidate: PortfolioInstrumentCandidate) => {
    setForm((current) => ({
      ...current,
      symbol: candidate.symbol,
      market: candidate.market,
      asset_type: candidate.asset_type,
      currency: candidate.market === "a_share" ? "CNY" : "USD",
    }));
    setInstrumentQuery(candidate.symbol);
    setInstrumentResults([]);
  };

  const marketLabel = (market: string) => ({ a_share: "A 股", us: "美股", commodity: "商品", other: "其他" }[market] || market);
  const assetLabel = (assetType: string) => ({ equity: "股票", etf: "ETF", commodity: "商品", future: "期货", bank_gold: "银行积存金", other: "其他" }[assetType] || assetType);
  const editablePortfolioId = selectedId !== "all" ? selectedId : portfolios.length === 1 ? portfolios[0].id : null;

  const saveManualPrice = async (holding: PortfolioSnapshotResponse["holdings"][number], draftValue?: string) => {
    if (!editablePortfolioId) {
      setError("请先选择具体组合，再编辑手动价格");
      return;
    }
    const key = `${holding.market}:${holding.symbol}:${holding.currency}`;
    const price = (draftValue ?? priceDrafts[key])?.trim();
    if (!price || !Number.isFinite(Number(price)) || Number(price) <= 0) {
      setError("请输入大于 0 的最新价格");
      return;
    }
    try {
      await api.savePortfolioPrice(editablePortfolioId, { symbol: holding.symbol, market: holding.market, currency: holding.currency, price });
      setPriceDrafts((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setEditingPriceKey(null);
      await loadSelectedData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存最新价格失败");
    }
  };

  const startManualPriceEdit = (holding: PortfolioSnapshotResponse["holdings"][number]) => {
    if (!editablePortfolioId) {
      setError("请先选择一个具体组合，再编辑手动价格");
      return;
    }
    if (holding.price_status === "ok" && holding.market !== "commodity" && holding.market !== "other") {
      setError("该标的已自动获取价格，无需手动填写");
      return;
    }
    const key = `${holding.market}:${holding.symbol}:${holding.currency}`;
    setPriceDrafts((current) => ({ ...current, [key]: holding.latest_price || "" }));
    setEditingPriceKey(key);
  };

  return (
    <main className="mx-auto w-full max-w-[1500px] space-y-6 p-4 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">Personal ledger</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">个人持仓</h1>
          <p className="mt-1 text-sm text-muted-foreground">流水驱动的持仓、现金与盈亏台账</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)} className="h-9 rounded-md border border-border bg-background px-3 text-sm">
            <option value="all">全部组合</option>
            {portfolios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <button type="button" onClick={() => setShowForm(true)} disabled={selectedId === "all"} className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"><Plus className="h-4 w-4" />记一笔</button>
          <button type="button" onClick={() => void loadSelectedData()} className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-muted"><RefreshCw className="h-4 w-4" />刷新</button>
        </div>
      </header>

      <section className="rounded-xl border border-border/70 bg-card/40 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <input value={newPortfolio} onChange={(event) => setNewPortfolio(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void createPortfolio(); }} placeholder="新组合名称" className="h-9 w-48 rounded-md border border-border bg-background px-3 text-sm" />
          <button type="button" onClick={() => void createPortfolio()} className="h-9 rounded-md border border-border px-3 text-sm hover:bg-muted">创建组合</button>
          <span className="text-xs text-muted-foreground">支持多个组合，跨币种只分组展示，不强行换算。</span>
        </div>
      </section>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {loading && !snapshot ? <div className="rounded-xl border border-border p-10 text-center text-sm text-muted-foreground">正在加载持仓…</div> : null}

      {snapshot && currencyEntries.map((summary) => (
        <section key={summary.currency} className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium"><WalletCards className="h-4 w-4" />{summary.currency} 组合摘要</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            {[ ["总资产", summary.total_assets], ["现金", summary.cash], ["持仓市值", summary.holdings_value], ["净投入", summary.net_contributed], ["当日盈亏", summary.daily_pnl], ["累计收益", summary.total_return] ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-border/70 bg-card p-4"><p className="text-xs text-muted-foreground">{label}</p><p className={`mt-2 text-lg font-semibold ${label.includes("盈亏") || label.includes("收益") ? tone(value) : ""}`}>{money(value, summary.currency)}</p></div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">已实现 {money(summary.realized_pnl, summary.currency)} · 未实现 {money(summary.unrealized_pnl, summary.currency)} · 分红 {money(summary.dividends, summary.currency)} · 收益率 {summary.return_pct ? `${number(summary.return_pct)}%` : "—"}</p>
        </section>
      ))}

      <section className="overflow-hidden rounded-xl border border-border/70 bg-card/40">
        <div className="border-b border-border/70 px-4 py-3"><h2 className="text-sm font-semibold">当前持仓</h2></div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr>{["标的", "市场", "数量", "平均成本", "最新价", "市值", "权重", "浮动盈亏"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-border/60">{snapshot?.holdings.map((holding) => { const priceKey = `${holding.market}:${holding.symbol}:${holding.currency}`; const manualMarket = holding.market === "commodity" || holding.market === "other"; const canEditPrice = Boolean(editablePortfolioId) && (manualMarket || holding.price_status !== "ok"); const isEditingPrice = editingPriceKey === priceKey; const showPriceInput = Boolean(editablePortfolioId) && (manualMarket || isEditingPrice); const isStock = holding.market === "a_share" || holding.market === "us"; return <tr key={priceKey} className="hover:bg-muted/20"><td className="px-4 py-3"><div className="font-medium">{isStock ? <Link to={`/stocks/${encodeURIComponent(holding.symbol)}`} className="hover:text-primary hover:underline">{holding.name}</Link> : holding.name}</div><div className="font-mono text-xs text-muted-foreground">{holding.symbol}</div></td><td className="px-4 py-3 text-muted-foreground">{marketLabel(holding.market)}</td><td className="px-4 py-3 font-mono">{number(holding.quantity, 4)}</td><td className="px-4 py-3 font-mono">{number(holding.avg_cost, 4)}</td><td className={`px-4 py-3 font-mono ${canEditPrice ? "cursor-text" : ""}`} onDoubleClick={() => { if (!manualMarket) startManualPriceEdit(holding); }}>{showPriceInput ? <input autoFocus={isEditingPrice} value={priceDrafts[priceKey] ?? holding.latest_price ?? ""} onChange={(event) => setPriceDrafts((current) => ({ ...current, [priceKey]: event.target.value }))} onBlur={() => void saveManualPrice(holding, priceDrafts[priceKey] ?? holding.latest_price ?? "")} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape" && !manualMarket) setEditingPriceKey(null); }} type="number" min="0" step="any" className="h-7 w-28 rounded border border-border bg-background px-1.5 text-xs" /> : <><div>{holding.latest_price ? number(holding.latest_price, 4) : "暂不可用"}</div>{holding.price_status === "ok" ? <div className="text-[10px] font-normal text-muted-foreground">自动行情</div> : canEditPrice ? <div className="text-[10px] font-normal text-muted-foreground">双击填写</div> : null}</>}</td><td className="px-4 py-3 font-mono">{holding.market_value ? money(holding.market_value, holding.currency) : "—"}</td><td className="px-4 py-3 font-mono">{number(holding.weight)}%</td><td className={`px-4 py-3 font-mono ${tone(holding.unrealized_pnl)}`}>{holding.unrealized_pnl ? `${money(holding.unrealized_pnl, holding.currency)} (${number(holding.unrealized_pnl_pct)}%)` : "—"}</td></tr>; })}</tbody>
          </table>
          {!snapshot?.holdings.length && <div className="p-10 text-center text-sm text-muted-foreground">还没有持仓，先记入一笔买入或入金。</div>}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="overflow-hidden rounded-xl border border-border/70 bg-card/40"><div className="border-b border-border/70 px-4 py-3"><h2 className="text-sm font-semibold">交易流水</h2></div><div className="max-h-[420px] overflow-auto"><table className="w-full min-w-[700px] text-left text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr>{["日期", "类型", "标的", "数量", "价格/金额", "币种", "操作"].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-border/60">{transactions.map((tx) => <tr key={tx.id}><td className="px-4 py-3 text-muted-foreground">{tx.trade_at.slice(0, 10)}</td><td className="px-4 py-3">{transactionTypes.find((item) => item.value === tx.type)?.label || tx.type}</td><td className="px-4 py-3 font-mono">{tx.symbol || "现金"}</td><td className="px-4 py-3 font-mono">{tx.quantity || "—"}</td><td className="px-4 py-3 font-mono">{tx.price || tx.amount || "—"}</td><td className="px-4 py-3">{tx.currency}</td><td className="px-4 py-3"><button type="button" disabled={Boolean(tx.reversed_transaction_id)} onClick={async () => { try { await api.reversePortfolioTransaction(selectedId, tx.id); await loadSelectedData(); } catch (err) { setError(err instanceof Error ? err.message : "冲销失败"); } }} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"><RotateCcw className="h-3 w-3" />冲销</button></td></tr>)}</tbody></table>{!transactions.length && <div className="p-10 text-center text-sm text-muted-foreground">暂无流水</div>}</div></div>
        <div className="rounded-xl border border-border/70 bg-card/40 p-4"><h2 className="text-sm font-semibold">券商只读对账</h2><p className="mt-2 text-xs leading-5 text-muted-foreground">选择已注册的券商 profile，只读取券商当前持仓并保存差异快照，不会自动修改台账。</p><div className="mt-4 flex gap-2"><select value={brokerProfile} onChange={(event) => { setBrokerProfile(event.target.value); setReconciliation(null); }} disabled={selectedId === "all" || brokerProfiles.length === 0} aria-label="券商 profile" className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-3 text-sm"><option value="">选择券商 profile</option>{brokerProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label} · {profile.environment === "paper" ? "模拟" : "实盘"}（{profile.id}）</option>)}</select><button type="button" onClick={() => void refreshReconciliation()} disabled={selectedId === "all" || !brokerProfile.trim()} className="h-9 rounded-md border border-border px-3 text-sm hover:bg-muted disabled:opacity-50">读取</button></div>{reconciliation && <div className="mt-4 space-y-2"><p className="text-xs text-muted-foreground">观察时间：{reconciliation.observed_at?.slice(0, 19).replace("T", " ")}</p>{reconciliationRows.map((row) => <div key={`${row.market}:${row.symbol}`} className="flex items-center justify-between gap-3 rounded-md border border-border/60 px-3 py-2 text-xs"><div><span className="font-mono">{row.symbol}</span><span className="ms-3 text-muted-foreground">台账 {number(row.ledgerQuantity, 4)} · 券商 {number(row.brokerQuantity, 4)}</span></div><button type="button" onClick={() => prepareAdjustment(row)} disabled={!row.delta} className="shrink-0 rounded border border-border px-2 py-1 hover:bg-muted disabled:opacity-40">{row.delta ? `调整 ${row.delta > 0 ? "+" : ""}${number(row.delta, 4)}` : "一致"}</button></div>)}</div>}</div>
      </section>

      {showForm && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"><form onSubmit={submitTransaction} className="w-full max-w-xl space-y-4 rounded-xl border border-border bg-background p-5 shadow-xl"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">记入一笔流水</h2><button type="button" onClick={() => setShowForm(false)} className="text-sm text-muted-foreground">取消</button></div><div className="grid gap-3 sm:grid-cols-2"><label className="text-xs text-muted-foreground">类型<select value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value as PortfolioTransactionType })} className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm">{transactionTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label className="text-xs text-muted-foreground">币种<input value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value.toUpperCase() })} className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" maxLength={3} /></label>{!["fee", "dividend", "deposit", "withdrawal"].includes(form.type) && <><label className="relative text-xs text-muted-foreground sm:col-span-2">搜索标的（代码、名称或简称）<input value={instrumentQuery} onChange={(event) => setInstrumentQuery(event.target.value)} placeholder="如 600519、贵州茅台、Moutai、黄金、沪金、积存金" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-3 text-sm" autoComplete="off" />{instrumentResults.length > 0 && <div className="absolute inset-x-0 top-full z-10 mt-1 max-h-56 overflow-auto rounded-md border border-border bg-background p-1 shadow-lg">{instrumentResults.map((candidate) => <button type="button" key={`${candidate.market}:${candidate.symbol}`} onClick={() => chooseInstrument(candidate)} className="flex w-full items-center justify-between gap-3 rounded px-2 py-2 text-left text-sm hover:bg-muted"><span><span className="font-medium">{candidate.name}</span><span className="ms-2 font-mono text-xs text-muted-foreground">{candidate.symbol}</span></span><span className="shrink-0 text-xs text-muted-foreground">{marketLabel(candidate.market)} · {assetLabel(candidate.asset_type)}</span></button>)}</div>}</label><label className="text-xs text-muted-foreground">代码<input required value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value.toUpperCase() })} placeholder="600519.SH / AAPL.US / XAUUSD" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 font-mono text-sm" /></label><label className="text-xs text-muted-foreground">市场<select value={form.market} onChange={(event) => setForm({ ...form, market: event.target.value })} className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm"><option value="a_share">A 股</option><option value="us">美股</option><option value="commodity">商品</option><option value="other">其他</option></select></label></>}{["buy", "sell", "adjustment"].includes(form.type) && <><label className="text-xs text-muted-foreground">数量<input required value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} type="number" step="any" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" /></label><label className="text-xs text-muted-foreground">价格<input required value={form.price} onChange={(event) => setForm({ ...form, price: event.target.value })} type="number" step="any" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" /></label></>}{["fee", "dividend", "deposit", "withdrawal"].includes(form.type) && <label className="text-xs text-muted-foreground">金额<input required value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} type="number" step="any" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" /></label>}<label className="text-xs text-muted-foreground">费用<input value={form.fee} onChange={(event) => setForm({ ...form, fee: event.target.value })} type="number" step="any" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" /></label><label className="text-xs text-muted-foreground">税费<input value={form.tax} onChange={(event) => setForm({ ...form, tax: event.target.value })} type="number" step="any" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" /></label><label className="text-xs text-muted-foreground sm:col-span-2">日期<input required value={form.trade_at} onChange={(event) => setForm({ ...form, trade_at: event.target.value })} type="date" className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm" /></label><label className="text-xs text-muted-foreground sm:col-span-2">备注<textarea value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} className="mt-1 min-h-16 w-full rounded-md border border-border bg-background p-2 text-sm" /></label></div><button type="submit" className="h-10 w-full rounded-md bg-primary text-sm text-primary-foreground">保存流水</button></form></div>}
    </main>
  );
}
