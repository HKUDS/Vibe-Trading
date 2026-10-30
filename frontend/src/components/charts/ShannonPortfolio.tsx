import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, RefreshCw } from "lucide-react";
import {
  shannon, parseHoldings, finite, percent, styleLabels,
  type ShannonDiagnosis, type ShannonSnapshot,
} from "@/lib/shannon";

function Bars({ rows, zh }: {
  rows: { label: string; value: number; text: string; weight?: string; detail?: string }[];
  zh: boolean;
}) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">{zh ? "本次没有可用数据，不以零代替。" : "No data available; missing values are not zero."}</p>;
  const max = Math.max(...rows.map(r => Math.abs(r.value)), .000001);
  const signed = rows.some(r => r.value < 0);
  return <table className="w-full table-fixed border-separate border-spacing-y-3 text-sm">
    <colgroup><col className="w-16 sm:w-20" /><col className="w-14 sm:w-16" /><col /><col className="w-16 sm:w-20" /></colgroup>
    <thead className="text-xs text-muted-foreground"><tr><th className="pr-2 text-left font-normal">{zh ? "股票" : "Stock"}</th><th className="pr-2 text-right font-normal">{zh ? "仓位" : "Allocation"}</th><th className="text-center font-normal">{zh ? "波动贡献" : "Contribution"}</th><th className="pl-2 text-right font-normal" aria-label={zh ? "组合波动贡献占比" : "Portfolio volatility contribution share"}>{zh ? <>组合波动<br />贡献占比</> : "Portfolio volatility share"}</th></tr></thead>
    <tbody>{rows.map((r, i) => <tr key={`${r.label}-${i}`}>
      <td className="break-words pr-2 align-middle text-xs sm:text-sm">{r.label}</td>
      <td className="pr-2 text-right align-middle text-xs tabular-nums whitespace-nowrap">{r.weight ?? "—"}</td>
      <td className="align-middle"><div className="relative h-5 rounded bg-muted/60" aria-hidden="true">
        <span className={`absolute inset-y-0 ${signed ? "left-1/2" : "left-0"} w-px bg-muted-foreground/40`} />
        <span className={`absolute inset-y-1 rounded-sm ${r.value >= 0 ? "bg-rose-500/70" : "bg-teal-500/75"}`} style={{ left: `${signed ? r.value < 0 ? 50 - Math.abs(r.value) / max * 50 : 50 : 0}%`, width: `${Math.abs(r.value) / max * (signed ? 50 : 100)}%` }} />
      </div></td>
      <td className="break-words pl-2 text-right align-middle text-xs tabular-nums"><span className="block">{r.text}</span>{r.detail && <span className="mt-0.5 block text-muted-foreground">{r.detail}</span>}</td>
    </tr>)}</tbody>
  </table>;
}

export function ShannonPortfolio() {
  const { i18n } = useTranslation(); const zh = i18n.language.startsWith("zh");
  const tr = (cn: string, en: string) => zh ? cn : en;
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [latest, setLatest] = useState(""); const [catalogError, setCatalogError] = useState("");
  const [text, setText] = useState(""); const [date, setDate] = useState("");
  const [analysis, setAnalysis] = useState<ShannonDiagnosis | null>(null);
  const [snapshot, setSnapshot] = useState<ShannonSnapshot | null>(null);
  const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const generation = useRef(0); const controller = useRef<AbortController | null>(null);
  const holdings = parseHoldings(text);
  const effective = analysis?.meta?.actual_factor_date ?? "";
  const name = (code: string) => analysis?.data.holdings?.find(h => h.ts_code === code)?.name || code;
  const label = (key: string) => styleLabels[key]?.[zh ? 0 : 1] ?? key;
  const failure = (e: unknown) => e instanceof Error ? e.message : tr("服务暂不可用，请重试。", "Service unavailable. Please retry.");

  async function loadCatalog(signal?: AbortSignal) {
    setCatalogError("");
    try {
      const state = await shannon.status(signal); if (signal?.aborted) return; setConfigured(state.configured);
      if (state.configured) {
        const result = await shannon.catalog(signal); if (signal?.aborted) return;
        const published = result.data?.universes?.find(u => u.id === "all" && u.ready)?.current_as_of ?? "";
        setLatest(published); setDate(current => current || published);
      }
    } catch (e) { if (!signal?.aborted) setCatalogError(failure(e)); }
  }
  useEffect(() => { const abort = new AbortController(); void loadCatalog(abort.signal); return () => abort.abort(); }, []);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  function invalidate() {
    generation.current++; controller.current?.abort(); setLoading(false); setError("");
    setAnalysis(null); setSnapshot(null);
  }
  async function diagnose() {
    if (!holdings) return;
    invalidate(); const id = generation.current; const abort = new AbortController(); controller.current = abort;
    setLoading(true);
    try {
      const result = await shannon.diagnosis({ holdings, ...(date ? { date } : {}) }, abort.signal);
      if (id !== generation.current) return;
      const body = { holdings, date: result.meta?.actual_factor_date };
      setAnalysis(result); setSnapshot(body);

    } catch (e) { if (!abort.signal.aborted && id === generation.current) setError(failure(e)); }
    finally { if (id === generation.current) setLoading(false); }
  }
  const exposures = analysis?.data.exposures?.portfolio ?? {};
  const style = Object.keys(styleLabels).map(key => ({ key, value: finite(exposures[key]) && (analysis?.meta?.factor_coverage?.[key]?.ratio ?? 1) >= 1 ? exposures[key] as number : null }));
  const styleMax = Math.max(1, ...style.map(row => Math.abs(row.value ?? 0)));
  const exposureText = (value: number, decimals: number) => {
    const rounded = Number(value.toFixed(decimals));
    return `${rounded > 0 ? "+" : ""}${rounded.toFixed(decimals)}`;
  };
  const contributions = Object.entries(analysis?.data.risk_attribution?.top_stock_contributions ?? {}).filter((r): r is [string, number] => finite(r[1])).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const mainContributor = contributions.find(([, value]) => value > 0);
  const included = analysis?.meta?.included_holding_count ?? analysis?.data.holdings?.length ?? 0;
  const requested = snapshot?.holdings.length ?? 0;
  const partial = included < requested || !!analysis?.data.missing?.length;
  const includedCodes = new Set(analysis?.data.holdings?.map(h => h.ts_code));
  const coveredWeight = (snapshot?.holdings ?? []).filter(h => includedCodes.has(h.code)).reduce((sum, h) => sum + (h.weight ?? 1 / requested), 0);

  return <section className="space-y-6" aria-label={tr("香农持仓诊断", "Shannon portfolio diagnosis")}>
    <header className="space-y-2"><h2 className="text-xl font-semibold">{tr("持仓风格与风险", "Portfolio style and risk")}</h2><p className="text-sm text-muted-foreground">{tr("查看组合的风格倾向、个股特征，以及组合波动集中在哪些持仓。", "Explore portfolio style, individual stock characteristics and the holdings that contribute to portfolio volatility.")}</p></header>
    {configured === false ? <div className="rounded-xl border p-5 text-sm">{tr("配置聚源 Token 后可使用持仓诊断，原有相关性分析仍可正常使用。", "Configure a Gildata token to use diagnosis. The existing correlation analysis remains available.")}</div> : <div className="grid gap-5 rounded-xl border bg-card p-5 md:grid-cols-[1fr_17rem]">
      <div><label htmlFor="shannon-holdings" className="text-sm font-medium">{tr("你的A股持仓", "Your A-share holdings")}</label><textarea id="shannon-holdings" className="mt-2 min-h-36 w-full rounded-lg border bg-background p-3 font-mono text-sm" value={text} onChange={e => { invalidate(); setText(e.target.value); }} placeholder={"600519.SH 40%\n300750.SZ 30%\n600036.SH 30%"} />
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{tr("每行一只，填写代码和权重。权重全部留空时按等权估算；自定义权重须全部填写且合计100%。仅支持A股股票，不自动剔除现金或其他资产。", "One stock per line: code and weight. Omit all weights for equal allocation, or enter all weights totaling 100%. A-share stocks only; cash and other assets are not silently excluded.")}</p>
        {text && !holdings && <p role="alert" className="mt-2 text-sm text-warning">{tr("请检查代码、重复股票和权重；按上方格式填写。", "Check symbols, duplicates and weights using the format above.")}</p>}</div>
      <div className="flex flex-col items-start gap-3"><label htmlFor="shannon-date" className="text-sm font-medium">{tr("分析截至日期（可选）", "As-of date (optional)")}</label><input id="shannon-date" type="date" max={latest || undefined} value={date} onChange={e => { invalidate(); setDate(e.target.value); }} className="w-full rounded-lg border bg-background px-3 py-2 text-sm" />
        <p className="text-xs leading-relaxed text-muted-foreground">{date ? tr("用这一天的数据分析当前输入的持仓，不代表你当时实际持有。", "Analyze the entered holdings at this date, not your historical account holdings.") : tr("留空使用最新可用数据", "Leave blank for the latest available data")}{latest && <span className="block mt-1">{tr("数据更新至", "Published through")} {latest}</span>}</p>
        {latest && date !== latest && <button className="text-xs underline underline-offset-4" onClick={() => { invalidate(); setDate(latest); }}>{tr("使用最新数据", "Use latest data")}</button>}
        <button onClick={diagnose} disabled={loading || !holdings || !configured} className="mt-auto inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50">{loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}{loading ? tr("正在分析持仓…", "Analyzing…") : tr("诊断持仓", "Analyze holdings")}</button>
      </div>
    </div>}
    {catalogError && <p role="alert" className="text-sm text-warning">{catalogError} <button onClick={() => void loadCatalog()} className="underline">{tr("重新检查", "Retry")}</button></p>}
    {error && <p role="alert" className="rounded-lg border border-danger/30 p-4 text-sm text-danger">{error}</p>}
    {analysis && <>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground" role="status"><span>{tr("实际分析日", "Actual analysis date")} {effective}</span><span>{tr("已纳入", "Included")} {included}/{requested} {tr("只股票", "stocks")}</span><span>{analysis.weight_assumption === "equal" ? tr("等权估算", "Equal-weight assumption") : tr("按输入权重分析", "Using entered weights")}</span>{analysis.meta?.risk_as_of && <span>{tr("风险估计日", "Risk estimate date")} {analysis.meta.risk_as_of}</span>}</div>
      {analysis.requested_date !== effective && <p role="status" className="rounded-lg border border-warning/40 p-3 text-sm">{tr("请求日期", "Requested date")} {analysis.requested_date}；{tr("实际使用可用数据日", "Actual available date")} {effective}。</p>}
      {partial && <p role="alert" className="rounded-lg border border-warning/40 p-3 text-sm">{tr("部分股票未被纳入。下方模型结果只代表已覆盖部分，不能当作完整组合画像。", "Some stocks were excluded. Model results describe only the covered portion, not the entire portfolio.")} {tr("已覆盖输入权重", "Covered entered allocation")} {percent(coveredWeight)}。 {(analysis.data.missing ?? []).map((m, i) => <span className="ml-1" key={i}>{typeof m === "string" ? m : typeof m === "object" && m && "ts_code" in m ? String(m.ts_code) : typeof m === "object" && m && "code" in m ? String(m.code) : ""}</span>)}</p>}
      {!!analysis.warnings?.length && <p role="status" className="text-sm text-warning">{tr("数据源提示本次分析存在限制，结果仅供参考。", "The source reported limitations; interpret these estimates with caution.")}</p>}
      <section className="space-y-4 rounded-xl border p-4 sm:p-5" aria-label={tr("组合风格暴露", "Portfolio style exposure")}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{tr("组合风格暴露", "Portfolio style exposure")}</h3><span className="text-xs text-muted-foreground">{tr("偏低 ← 模型参照0 → 偏高", "Lower ← Model reference 0 → Higher")}</span></div>
        <div className="space-y-2">{style.map(row => <div key={row.key} className="grid grid-cols-[5.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-xs sm:text-sm" aria-label={`${label(row.key)}: ${finite(row.value) ? exposureText(row.value, 2) : "—"}`}>
          <span>{label(row.key)}</span><div className="relative h-5 rounded bg-muted/60" aria-hidden="true"><span className="absolute inset-y-0 left-1/2 w-px bg-muted-foreground/40" />{finite(row.value) && <span className={`absolute inset-y-1 rounded-sm ${row.value >= 0 ? "bg-rose-400" : "bg-emerald-500/70"}`} style={{ left: `${row.value >= 0 ? 50 : 50 - Math.abs(row.value) / styleMax * 50}%`, width: `${Math.abs(row.value) / styleMax * 50}%` }} />}</div><span className="text-right font-mono tabular-nums">{finite(row.value) ? exposureText(row.value, 2) : "—"}</span>
        </div>)}</div>
        <p className="text-xs leading-relaxed text-muted-foreground">{tr("红色偏高、绿色偏低，距离中线越远倾向越明显。数值为标准化特征，不是仓位或涨跌预测；市场贝塔也不是原始回归β。缺失或覆盖不足显示为—。", "Red means higher, green lower; distance from zero shows the tilt. Values are standardized traits, not allocations or forecasts; market beta is standardized, not raw regression beta. Missing or incomplete coverage is shown as —.")}</p>
        <details className="border-t pt-3"><summary className="cursor-pointer text-sm font-medium">{tr("查看个股风格", "View stock styles")}</summary>
          <div className="mt-4 space-y-3"><h4 className="text-sm font-medium">{tr("个股风格暴露热力图", "Stock style exposure heatmap")}</h4><p className="text-xs leading-relaxed text-muted-foreground">{tr("每行一只股票，每列一个因子，顺序与上图一致。红色偏高、绿色偏低；颜色在±2处饱和，数值不截断。它展示个股特点，不是该股风险贡献的分解。", "Rows are stocks; columns follow the factor order above. Red is higher and green lower; colors saturate at ±2 without clipping values. These are stock characteristics, not a breakdown of the stock's risk contribution.")}</p>
          <div className="max-h-[28rem] overflow-auto rounded-lg border"><table className="w-full min-w-[58rem] border-separate border-spacing-1 text-xs" aria-label={tr("个股风格暴露热力图", "Stock style exposure heatmap")}>
            <thead><tr><th className="sticky left-0 z-10 min-w-36 bg-card p-3 text-left">{tr("股票", "Stock")}</th>{style.map(row => <th key={row.key} className="whitespace-nowrap px-2 py-3 font-medium">{label(row.key)}</th>)}</tr></thead>
            <tbody>{analysis.data.holdings?.map(holding => <tr key={holding.ts_code}><th scope="row" className="sticky left-0 z-10 bg-card p-3 text-left font-normal"><span className="block">{holding.name || holding.ts_code}</span><span className="mt-1 block text-muted-foreground">{holding.ts_code}</span></th>{style.map(row => {
              const value = holding.exposures?.[row.key];
              const color = finite(value) && value !== 0 ? `rgba(${value > 0 ? "244, 63, 94" : "16, 145, 112"}, ${.08 + .52 * Math.min(Math.abs(value) / 2, 1)})` : undefined;
              return <td key={row.key} className="rounded bg-muted/30 px-2 py-4 text-center font-mono tabular-nums" style={{ backgroundColor: color }} title={finite(value) ? String(value) : tr("数据缺失", "Missing data")}>{finite(value) ? exposureText(value, 1) : "—"}</td>;
            })}</tr>)}</tbody>
          </table></div>{!analysis.data.holdings?.some(holding => Object.values(holding.exposures ?? {}).some(finite)) && <p className="text-sm text-muted-foreground">{tr("本次没有可用的个股风格数据。", "No stock style data is available.")}</p>}</div>
        </details>
      </section>
        <section className="space-y-4 rounded-xl border p-5"><h3 className="font-semibold">{tr("风险归因：谁在影响组合波动", "Risk attribution: volatility sources")}</h3>{mainContributor && <p className="text-sm">{tr(`${name(mainContributor[0])}在已返回股票中对组合波动的估计贡献最大。`, `${name(mainContributor[0])} has the largest estimated volatility contribution among returned stocks.`)}</p>}<p className="text-xs text-muted-foreground">{tr("用于定位组合波动集中在哪里，优先复核相关仓位。仓位是资金占比；组合波动贡献占比＝个股波动贡献÷组合总波动。条形按本图最大贡献缩放。", "Locate where portfolio volatility is concentrated and review the relevant allocations. Allocation is the capital weight; volatility share is stock volatility contribution divided by total portfolio volatility. Bars scale to the largest contribution shown.")}</p><Bars zh={zh} rows={contributions.slice(0, 5).map(([code, value]) => {
          const holding = snapshot?.holdings.find(h => h.code === code);
          const weight = holding ? holding.weight ?? 1 / requested : undefined;
          const total = analysis.data.risk_attribution?.total_risk;
          const share = finite(total) && total > 0 ? value / total : null;
          return { label: name(code), weight: percent(weight), value, text: percent(share, true), detail: value < 0 ? tr("分散波动", "Diversifying") : value > 0 ? tr("推高波动", "Adding volatility") : tr("贡献为零", "Zero contribution") };
        })} /><p className="text-xs text-muted-foreground">{tr("展示贡献最大的前5只股票。占比不是亏损概率，也不等于减仓后的风险降幅；可为负或超过100%，前5项不一定合计100%。负贡献表示分散作用。个股自身风险采用统一波动率假设。", "Shows the five largest contributions by magnitude. Shares are not loss probabilities or predicted risk reductions from selling; they can be negative or exceed 100%, and the top five may not sum to 100%. Negative contributions diversify volatility. Stock-specific risk uses a common volatility assumption.")}</p></section>
    </>}
  </section>;
}
