import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type HistoryJob, type HistoryPlan, type HistorySpec, type HistoryStorage, type ScanJob, type GatewayCapabilities } from "@/lib/api";

const field = "rounded-md border bg-background px-3 py-2 text-sm min-w-0";
const button = "rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const mib = (bytes: number) => (bytes / 1024 ** 2).toFixed(1);

export function HistoryStorageSettings() {
  const { t } = useTranslation();
  const labels: Record<string, string> = {
    a_share: t("settings.sourcePriority.markets.a_share"),
    us_equity: t("settings.sourcePriority.markets.us_equity"),
    hk_equity: t("settings.sourcePriority.markets.hk_equity"),
    india_equity: t("settings.sourcePriority.markets.india_equity"),
    kr_equity: t("settings.sourcePriority.markets.kr_equity"),
    ca_equity: t("settings.sourcePriority.markets.ca_equity"),
    vietnam_equity: t("settings.sourcePriority.markets.vietnam_equity"),
    ar_equity: t("settings.sourcePriority.markets.ar_equity"),
    br_equity: t("settings.sourcePriority.markets.br_equity"),
    uk_equity: t("settings.sourcePriority.markets.uk_equity"),
    index: t("settings.sourcePriority.markets.index"),
    crypto: t("settings.sourcePriority.markets.crypto"),
    futures: t("settings.sourcePriority.markets.futures"),
    fund: t("settings.sourcePriority.markets.fund"),
    macro: t("settings.sourcePriority.markets.macro"),
    forex: t("settings.sourcePriority.markets.forex"),
  };
  const [capabilities, setCapabilities] = useState<GatewayCapabilities | null>(null);
  const [source, setSource] = useState("auto");
  const [connectionError, setConnectionError] = useState("");
  const [storage, setStorage] = useState<HistoryStorage | null>(null);
  const [scans, setScans] = useState<ScanJob[]>([]);
  const [jobs, setJobs] = useState<HistoryJob[]>([]);
  const [quota, setQuota] = useState(256);
  const [days, setDays] = useState(30);
  const [codes, setCodes] = useState("601398.SH, 600519.SH");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [interval, setIntervalValue] = useState("5m");
  const [plan, setPlan] = useState<{ result: HistoryPlan; spec: HistorySpec } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = async () => {
    const [nextStorage, nextJobs, nextScans] = await Promise.all([api.historyStorage(), api.historyJobs(), api.dataScans()]);
    setStorage(nextStorage);
    setJobs(nextJobs); setScans(nextScans);
  };
  useEffect(() => {
    let alive = true;
    let described = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async (initial = false) => {
      try {
        if (document.hidden && !initial) return;
        const [nextStorage, nextJobs, nextScans] = await Promise.all([api.historyStorage(), api.historyJobs(), api.dataScans()]);
        if (!alive) return;
        setStorage(nextStorage); setJobs(nextJobs); setScans(nextScans);
        setConnectionError("");
        if (!described) { const description = await api.dataCapabilities(); if (alive) { setCapabilities(description); described = true; } }
        if (initial) { setQuota(nextStorage.quota_bytes / 1024 ** 2); setDays(nextStorage.retention_days); }
      } catch (e) { if (alive) setConnectionError(String(e)); }
      finally { if (alive) timer = setTimeout(() => void poll(), 5000); }
    };
    void poll(true);
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const act = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await operation(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const states: Record<string, string> = {
    paused: t("history.paused"), waiting: t("history.queued"), queued: t("history.queued"), running: t("history.running"),
    complete: t("history.complete"), downloaded: t("history.downloaded"), failed: t("history.failed"),
    partial: t("history.scanPartial"), cancelled: t("history.scanCancelled"),
  };
  const change = (set: (value: string) => void, value: string) => { set(value); setPlan(null); };
  return <section className="rounded-xl border bg-card p-6 space-y-5" id="history-storage">
    <div><h2 className="text-lg font-medium">{t("history.title")}</h2><p className="mt-1 text-sm text-muted-foreground">{t("history.description")}</p></div>
    {connectionError && <p role="alert" className="text-sm text-destructive">{connectionError}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {storage && <div className="space-y-2">
      <p className="text-sm tabular-nums">{t("history.usage", { used: mib(storage.used_bytes), quota: mib(storage.quota_bytes), reserved: mib(storage.reserved_bytes) })}</p>
      <progress className="w-full h-2" max={storage.quota_bytes} value={storage.used_bytes + storage.reserved_bytes} aria-label={t("history.title")} />
    </div>}
    <div className="flex flex-wrap items-end gap-3">
      <label className="grid gap-1 text-sm">{t("history.quota")}<input className={field} type="number" min="4" max="10240" value={quota} onChange={e => setQuota(Number(e.target.value))} /></label>
      <label className="grid gap-1 text-sm">{t("history.retention")}<input className={field} type="number" min="1" max="365" value={days} onChange={e => setDays(Number(e.target.value))} /></label>
      <button className={button} disabled={busy} onClick={() => void act(() => api.saveHistoryStorage(quota * 1024 ** 2, days))}>{t("history.save")}</button>
      <button className={button} disabled={busy} onClick={() => void act(api.pruneHistory)}>{t("history.clean")}</button>
    </div>
    <p className="text-xs text-muted-foreground">{t("history.cleanup")}</p>
    <form className="border-t pt-5 space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
      const spec = { codes: codes.split(/[\s,]+/).filter(Boolean), start_date: start, end_date: end, interval, source };
      setPlan({ spec, result: await api.planHistory(spec) });
    }); }}>
      <p className="text-sm text-muted-foreground">{t("history.support")}</p>
      {capabilities && <details className="text-sm">
        <summary className="cursor-pointer">{t("history.routesAvailable", { sources: capabilities.history_datasets.sources.length, markets: capabilities.history_datasets.markets.length })}</summary>
        <p className="mt-2 text-muted-foreground">{capabilities.history_datasets.markets.map(market => labels[market] ?? market).join(" · ")}</p>
        <p className="mt-2 text-xs text-muted-foreground">{t("history.routeAvailability")}</p>
      </details>}
      <label className="grid gap-1 text-sm">{t("history.symbols")}<input required className={field} value={codes} onChange={e => change(setCodes, e.target.value)} /></label>
      <div className="flex flex-wrap gap-3 items-end">
        <label className="grid gap-1 text-sm">{t("history.start")}<input required type="date" className={field} value={start} onChange={e => change(setStart, e.target.value)} /></label>
        <label className="grid gap-1 text-sm">{t("history.end")}<input required type="date" className={field} value={end} onChange={e => change(setEnd, e.target.value)} /></label>
        <label className="grid gap-1 text-sm">{t("history.interval")}<select className={field} value={interval} onChange={e => change(setIntervalValue, e.target.value)}>{(capabilities?.history_datasets.intervals ?? ["1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"]).map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="grid gap-1 text-sm">{t("history.source")}<select className={field} value={source} onChange={e => change(setSource, e.target.value)}>
          <option value="auto">{t("history.autoSource")}</option>
          {capabilities?.history_datasets.sources.map(row => <option key={row.source} value={row.source}>{row.source}{row.requires_auth ? ` · ${t("history.credentialsRequired")}` : ""}</option>)}
        </select></label>
        <button className={button} disabled={busy}>{t("history.estimate")}</button>
      </div>
    </form>
    <div className="border-t pt-4 space-y-2">
      <p className="text-sm text-muted-foreground">{t("history.scanHint")}</p>
      <button className={button} disabled={busy || !start || !end || !codes.trim()} onClick={() => void act(() => api.createDataScan({ codes: codes.split(/[\s,]+/).filter(Boolean), start_date: start, end_date: end, interval: "1D" }))}>{t("history.scanStart")}</button>
      {scans.map(scan => <div key={scan.id} className="flex items-center gap-3 text-sm">
        <p className="flex-1 tabular-nums">{states[scan.state] ?? scan.state} · {t("history.scanProgress", { completed: scan.completed, total: scan.total, failed: scan.failed, retries: scan.retries })}</p>
        {["queued", "running"].includes(scan.state) && <button className={button} disabled={busy} onClick={() => void act(() => api.cancelDataScan(scan.id))}>{t("history.pause")}</button>}
      </div>)}
    </div>
    {plan && <div className="rounded-md bg-muted/50 p-4 space-y-2">
      <p className="text-sm">{t("history.plan", { chunks: plan.result.chunks, rows: plan.result.estimated_max_rows.toLocaleString(), size: mib(plan.result.estimated_uncompressed_bytes) })}</p>
      {Object.entries(plan.result.routes ?? {}).map(([symbol, route]) => <p key={symbol} className="text-xs break-words"><span className="font-mono">{symbol}</span> · {labels[route.market] ?? route.market}: {route.candidates.join(" → ")}</p>)}
      <p className="text-xs text-muted-foreground">{t("history.coverageHint")}</p>
      <button className={button} disabled={busy} onClick={() => void act(async () => { const job = await api.createHistory(plan.spec); await api.historyAction(job.id, "resume"); setPlan(null); })}>{t("history.download")}</button>
    </div>}
    <div className="divide-y">{jobs.map(job => <div key={job.id} className="py-3 flex flex-wrap items-center gap-3">
      <div className="min-w-0 flex-1 text-sm"><span className="font-mono">{job.spec?.codes.join(", ") ?? job.id.slice(0, 8)}</span> · {job.retry_at ? t("history.retrying", { seconds: Math.max(0, Math.ceil(job.retry_at - Date.now() / 1000)) }) : (states[job.state] ?? job.state)}{job.pinned ? ` · ${t("history.pinned")}` : ""}
        <p className="text-xs text-muted-foreground tabular-nums">{job.spec?.start_date} → {job.spec?.end_date} · {job.spec?.interval} · {job.completed_chunks} / {job.total_chunks}{job.sources?.length ? ` · ${job.sources.join(", ")}` : ""}</p>
        {job.state === "downloaded" && <p className="text-xs text-muted-foreground">{t("history.coverageHint")}</p>}
        {job.error && <p className="text-destructive break-words">{job.error}</p>}
      </div>
      <button className={button} disabled={busy} onClick={() => void act(() => api.historyAction(job.id, (job.retry_at || ["running", "queued", "waiting"].includes(job.state)) ? "cancel" : "resume"))}>{(job.retry_at || ["running", "queued", "waiting"].includes(job.state)) ? t("history.pause") : t("history.resume")}</button>
      <button className={button} disabled={busy} onClick={() => void act(() => api.pinHistory(job.id, !job.pinned))}>{job.pinned ? t("history.unpin") : t("history.pin")}</button>
      <button className={button} disabled={busy || ["running", "queued", "waiting"].includes(job.state)} onClick={() => void act(() => api.deleteHistory(job.id))}>{t("history.delete")}</button>
    </div>)}</div>
  </section>;
}
