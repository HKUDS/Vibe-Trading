import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, RefreshCw } from "lucide-react";
import {
  shannon, parseHoldings, finite, percent, styleFactors,
  type ShannonDiagnosis, type ShannonSnapshot, type StyleFactor,
} from "@/lib/shannon";

function Bars({ rows }: {
  rows: { label: string; value: number; text: string; weight?: string; detail?: string }[];
}) {
  const { t } = useTranslation();
  if (!rows.length) return <p className="text-sm text-muted-foreground">{t("shannon.noData")}</p>;
  const max = Math.max(...rows.map(r => Math.abs(r.value)), .000001);
  const signed = rows.some(r => r.value < 0);
  return <table className="w-full table-fixed border-separate border-spacing-y-3 text-sm">
    <colgroup><col className="w-16 sm:w-20" /><col className="w-14 sm:w-16" /><col /><col className="w-16 sm:w-20" /></colgroup>
    <thead className="text-xs text-muted-foreground"><tr><th className="pr-2 text-left font-normal">{t("shannon.colStock")}</th><th className="pr-2 text-right font-normal">{t("shannon.colAllocation")}</th><th className="text-center font-normal">{t("shannon.colContribution")}</th><th className="whitespace-pre-line pl-2 text-right font-normal" aria-label={t("shannon.colShareLabel")}>{t("shannon.colShare")}</th></tr></thead>
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
  const { t } = useTranslation();
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
  const label = (key: StyleFactor) => t(`shannon.factors.${key}`);
  const failure = (e: unknown) => e instanceof Error ? e.message : t("shannon.serviceUnavailable");

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
  const style = styleFactors.map(key => ({ key, value: finite(exposures[key]) && (analysis?.meta?.factor_coverage?.[key]?.ratio ?? 1) >= 1 ? exposures[key] as number : null }));
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

  return <section className="space-y-6" aria-label={t("shannon.regionLabel")}>
    <header className="space-y-2"><h2 className="text-xl font-semibold">{t("shannon.title")}</h2><p className="text-sm text-muted-foreground">{t("shannon.intro")}</p></header>
    {configured === false ? <div className="rounded-xl border p-5 text-sm">{t("shannon.notConfigured")}</div> : <div className="grid gap-5 rounded-xl border bg-card p-5 md:grid-cols-[1fr_17rem]">
      <div><label htmlFor="shannon-holdings" className="text-sm font-medium">{t("shannon.holdingsLabel")}</label><textarea id="shannon-holdings" className="mt-2 min-h-36 w-full rounded-lg border bg-background p-3 font-mono text-sm" value={text} onChange={e => { invalidate(); setText(e.target.value); }} placeholder={"600519.SH 40%\n300750.SZ 30%\n600036.SH 30%"} />
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{t("shannon.holdingsHint")}</p>
        {text && !holdings && <p role="alert" className="mt-2 text-sm text-warning">{t("shannon.holdingsInvalid")}</p>}</div>
      <div className="flex flex-col items-start gap-3"><label htmlFor="shannon-date" className="text-sm font-medium">{t("shannon.dateLabel")}</label><input id="shannon-date" type="date" max={latest || undefined} value={date} onChange={e => { invalidate(); setDate(e.target.value); }} className="w-full rounded-lg border bg-background px-3 py-2 text-sm" />
        <p className="text-xs leading-relaxed text-muted-foreground">{date ? t("shannon.dateHint") : t("shannon.dateLatestHint")}{latest && <span className="block mt-1">{t("shannon.publishedThrough", { date: latest })}</span>}</p>
        {latest && date !== latest && <button className="text-xs underline underline-offset-4" onClick={() => { invalidate(); setDate(latest); }}>{t("shannon.useLatest")}</button>}
        <button onClick={diagnose} disabled={loading || !holdings || !configured} className="mt-auto inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50">{loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}{loading ? t("shannon.analyzing") : t("shannon.analyze")}</button>
      </div>
    </div>}
    {catalogError && <p role="alert" className="text-sm text-warning">{catalogError} <button onClick={() => void loadCatalog()} className="underline">{t("shannon.retry")}</button></p>}
    {error && <p role="alert" className="rounded-lg border border-danger/30 p-4 text-sm text-danger">{error}</p>}
    {analysis && <>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground" role="status"><span>{t("shannon.analysisDate", { date: effective })}</span><span>{t("shannon.included", { included, requested })}</span><span>{analysis.weight_assumption === "equal" ? t("shannon.equalWeight") : t("shannon.enteredWeights")}</span>{analysis.meta?.risk_as_of && <span>{t("shannon.riskDate", { date: analysis.meta.risk_as_of })}</span>}</div>
      {analysis.requested_date !== effective && <p role="status" className="rounded-lg border border-warning/40 p-3 text-sm">{t("shannon.dateFallback", { requested: analysis.requested_date, actual: effective })}</p>}
      {partial && <p role="alert" className="rounded-lg border border-warning/40 p-3 text-sm">{t("shannon.partial")} {t("shannon.coveredWeight", { weight: percent(coveredWeight) })} {(analysis.data.missing ?? []).map((m, i) => <span className="ml-1" key={i}>{typeof m === "string" ? m : typeof m === "object" && m && "ts_code" in m ? String(m.ts_code) : typeof m === "object" && m && "code" in m ? String(m.code) : ""}</span>)}</p>}
      {!!analysis.warnings?.length && <p role="status" className="text-sm text-warning">{t("shannon.sourceLimitations")}</p>}
      <section className="space-y-4 rounded-xl border p-4 sm:p-5" aria-label={t("shannon.styleTitle")}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{t("shannon.styleTitle")}</h3><span className="text-xs text-muted-foreground">{t("shannon.styleAxis")}</span></div>
        <div className="space-y-2">{style.map(row => <div key={row.key} className="grid grid-cols-[5.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-xs sm:text-sm" aria-label={`${label(row.key)}: ${finite(row.value) ? exposureText(row.value, 2) : "—"}`}>
          <span>{label(row.key)}</span><div className="relative h-5 rounded bg-muted/60" aria-hidden="true"><span className="absolute inset-y-0 left-1/2 w-px bg-muted-foreground/40" />{finite(row.value) && <span className={`absolute inset-y-1 rounded-sm ${row.value >= 0 ? "bg-rose-400" : "bg-emerald-500/70"}`} style={{ left: `${row.value >= 0 ? 50 : 50 - Math.abs(row.value) / styleMax * 50}%`, width: `${Math.abs(row.value) / styleMax * 50}%` }} />}</div><span className="text-right font-mono tabular-nums">{finite(row.value) ? exposureText(row.value, 2) : "—"}</span>
        </div>)}</div>
        <p className="text-xs leading-relaxed text-muted-foreground">{t("shannon.styleNote")}</p>
        <details className="border-t pt-3"><summary className="cursor-pointer text-sm font-medium">{t("shannon.viewStockStyles")}</summary>
          <div className="mt-4 space-y-3"><h4 className="text-sm font-medium">{t("shannon.heatmapTitle")}</h4><p className="text-xs leading-relaxed text-muted-foreground">{t("shannon.heatmapNote")}</p>
          <div className="max-h-[28rem] overflow-auto rounded-lg border"><table className="w-full min-w-[58rem] border-separate border-spacing-1 text-xs" aria-label={t("shannon.heatmapTitle")}>
            <thead><tr><th className="sticky left-0 z-10 min-w-36 bg-card p-3 text-left">{t("shannon.colStock")}</th>{style.map(row => <th key={row.key} className="whitespace-nowrap px-2 py-3 font-medium">{label(row.key)}</th>)}</tr></thead>
            <tbody>{analysis.data.holdings?.map(holding => <tr key={holding.ts_code}><th scope="row" className="sticky left-0 z-10 bg-card p-3 text-left font-normal"><span className="block">{holding.name || holding.ts_code}</span><span className="mt-1 block text-muted-foreground">{holding.ts_code}</span></th>{style.map(row => {
              const value = holding.exposures?.[row.key];
              const color = finite(value) && value !== 0 ? `rgba(${value > 0 ? "244, 63, 94" : "16, 145, 112"}, ${.08 + .52 * Math.min(Math.abs(value) / 2, 1)})` : undefined;
              return <td key={row.key} className="rounded bg-muted/30 px-2 py-4 text-center font-mono tabular-nums" style={{ backgroundColor: color }} title={finite(value) ? String(value) : t("shannon.missingData")}>{finite(value) ? exposureText(value, 1) : "—"}</td>;
            })}</tr>)}</tbody>
          </table></div>{!analysis.data.holdings?.some(holding => Object.values(holding.exposures ?? {}).some(finite)) && <p className="text-sm text-muted-foreground">{t("shannon.noStockStyle")}</p>}</div>
        </details>
      </section>
        <section className="space-y-4 rounded-xl border p-5"><h3 className="font-semibold">{t("shannon.riskTitle")}</h3>{mainContributor && <p className="text-sm">{t("shannon.mainContributor", { name: name(mainContributor[0]) })}</p>}<p className="text-xs text-muted-foreground">{t("shannon.riskNote")}</p><Bars rows={contributions.slice(0, 5).map(([code, value]) => {
          const holding = snapshot?.holdings.find(h => h.code === code);
          const weight = holding ? holding.weight ?? 1 / requested : undefined;
          const total = analysis.data.risk_attribution?.total_risk;
          const share = finite(total) && total > 0 ? value / total : null;
          return { label: name(code), weight: percent(weight), value, text: percent(share, true), detail: value < 0 ? t("shannon.diversifying") : value > 0 ? t("shannon.addingVolatility") : t("shannon.zeroContribution") };
        })} /><p className="text-xs text-muted-foreground">{t("shannon.riskFootnote")}</p></section>
    </>}
  </section>;
}
