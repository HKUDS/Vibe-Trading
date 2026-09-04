import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  Download,
  KeyRound,
  Loader2,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  WalletCards,
  WifiOff,
} from "lucide-react";
import { PortfolioSourceEditor } from "@/components/portfolio/PortfolioSourceEditor";
import { PortfolioCompatibilityBadge } from "@/components/portfolio/PortfolioCompatibilityBadge";
import {
  api,
  type PortfolioAccount,
  type PortfolioHistoryPoint,
  type PortfolioRefreshState,
  type PortfolioSettings,
  type PortfolioSnapshot,
  type PortfolioSourceCatalogItem,
} from "@/lib/api";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";
import i18n from "@/i18n";

const BROKER_COLORS: Record<string, string> = {
  IBKR: "#f05a47",
  LONGBRIDGE: "#4f6edb",
  BINANCE: "#f3ba2f",
};

const HOLDING_COLORS = [
  "#4f6edb", "#f3ba2f", "#45a67d", "#8b6fd6", "#ef8354",
  "#2d9cdb", "#d96c9d", "#7f8c8d", "#b5c83b", "#f05a47",
];

// Backend OAuth workers time out after 330 seconds. Keep a slightly longer
// client-side guard so a lost polling response can never spin forever.
const PORTFOLIO_RECONNECT_DEADLINE_MS = 360_000;

/**
 * Locale used by every Intl formatter on this page. The formatters live at
 * module scope (chart option builders need them outside React), so they read
 * the language off the i18n singleton rather than through a hook; components
 * that render them subscribe to `useTranslation()` and therefore re-render
 * whenever the language changes.
 */
function uiLocale(): string {
  return i18n.language || "en";
}

function money(value: number | null | undefined, currency: "USD" | "CNY" = "USD") {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(uiLocale(), {
    style: "currency",
    currency,
    maximumFractionDigits: currency === "USD" ? 2 : 0,
  }).format(value);
}

function quantity(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(uiLocale(), { maximumFractionDigits: 8 }).format(value);
}

function price(value: number | undefined | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(uiLocale(), {
    minimumFractionDigits: value >= 1 ? 2 : 4,
    maximumFractionDigits: value >= 100 ? 2 : value >= 1 ? 4 : 8,
  }).format(value);
}

function percentage(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(uiLocale(), {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}

/** ECharts reports slice shares as 0-100; `percentage` expects a 0-1 ratio. */
function slicePercentage(percent: number) {
  return percentage(percent / 100);
}

/** Compact USD tick label for the history axis, e.g. "$120K" / "1,2 Mio. $". */
function compactUsd(value: number) {
  return new Intl.NumberFormat(uiLocale(), {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function dateTime(value: string | undefined) {
  return value ? new Date(value).toLocaleString(uiLocale()) : "—";
}

function dayKey(value: string) {
  const date = new Date(value);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/**
 * Multi-account portfolio overview built from local read-only connections.
 *
 * An account the backend could not read arrives with `status === "error"` and
 * no totals; it contributes nothing to the headline figures and is rendered as
 * a failure card so the totals are never read as if those holdings counted.
 */
export function Portfolio() {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [history, setHistory] = useState<PortfolioHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [reconnectingSource, setReconnectingSource] = useState<string | null>(null);
  const [refreshState, setRefreshState] = useState<PortfolioRefreshState | null>(null);
  const [portfolioSettings, setPortfolioSettings] = useState<PortfolioSettings | null>(null);
  const [sourceCatalog, setSourceCatalog] = useState<PortfolioSourceCatalogItem[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [current, points, configuration] = await Promise.all([
        api.getPortfolio(),
        api.getPortfolioHistory(),
        api.getPortfolioSettings(),
      ]);
      setSnapshot(current.snapshot);
      setHistory(points.history ?? []);
      setPortfolioSettings(configuration.settings);
      setSourceCatalog(configuration.catalog);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("portfolio.page.errorLoad"));
    } finally {
      setLoading(false);
    }
  }

  async function refresh(settingsOverride?: PortfolioSettings) {
    const activeSettings = settingsOverride ?? portfolioSettings;
    const enabledSources = activeSettings?.sources.filter((source) => source.enabled) ?? [];
    if (!enabledSources.length) {
      setEditorOpen(true);
      return;
    }
    setRefreshing(true);
    setError(null);
    setRefreshState({
      running: true,
      current: null,
      sources: Object.fromEntries(enabledSources.map((source) => [source.connection_id, { status: "pending" as const }])),
    });
    const timer = window.setInterval(() => {
      void api.getPortfolioRefreshStatus()
        .then((result) => setRefreshState(normalizeRefreshState(result.refresh)))
        .catch(() => undefined);
    }, 500);
    try {
      const result = await api.refreshPortfolio();
      setSnapshot(result.snapshot);
      const points = await api.getPortfolioHistory();
      setHistory(points.history ?? []);
      const status = await api.getPortfolioRefreshStatus();
      setRefreshState(normalizeRefreshState(status.refresh));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("portfolio.page.errorRefresh"));
    } finally {
      window.clearInterval(timer);
      setRefreshing(false);
    }
  }

  async function reconnectSource(sourceId: string) {
    setReconnectingSource(sourceId);
    setError(null);
    try {
      await api.reconnectPortfolioSource(sourceId);
      const deadline = Date.now() + PORTFOLIO_RECONNECT_DEADLINE_MS;
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 1_000));
        if (Date.now() >= deadline) {
          throw new Error(t("portfolio.page.errorReconnectTimeout"));
        }
        const result = await api.getPortfolioReconnectStatus();
        if (result.reconnect.running) continue;
        if (result.reconnect.status !== "authorized") {
          throw new Error(result.reconnect.error ?? "Account reconnect failed");
        }
        break;
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("portfolio.page.errorReconnect"));
    } finally {
      setReconnectingSource(null);
    }
  }

  async function savePortfolioSettings(settings: PortfolioSettings) {
    setSavingSettings(true);
    setError(null);
    try {
      const result = await api.updatePortfolioSettings(settings);
      setPortfolioSettings(result.settings);
      setSourceCatalog(result.catalog);
      setEditorOpen(false);
      setSourceFilter("all");
      if (result.settings.sources.some((source) => source.enabled)) {
        await refresh(result.settings);
      } else {
        setSnapshot(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("portfolio.page.errorSaveSettings"));
    } finally {
      setSavingSettings(false);
    }
  }

  async function reloadConnections() {
    const configuration = await api.getPortfolioSettings();
    setPortfolioSettings(configuration.settings);
    setSourceCatalog(configuration.catalog);
  }

  async function download() {
    try {
      const blob = await api.downloadPortfolioCsv();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `portfolio-${new Date().toISOString().slice(0, 10)}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("portfolio.page.errorExport"));
    }
  }

  useEffect(() => { void load(); }, []);

  const positions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...(snapshot?.positions ?? [])]
      .filter((row) => sourceFilter === "all" || (row.source_id ?? row.broker) === sourceFilter)
      .filter((row) => !needle || [row.broker, row.symbol, row.name, row.asset_type, row.market]
        .join(" ").toLowerCase().includes(needle))
      .sort((a, b) => (b.market_value_usd ?? 0) - (a.market_value_usd ?? 0));
  }, [snapshot, query, sourceFilter]);

  const failedAccounts = useMemo(
    () => (snapshot?.accounts ?? []).filter((row) => row.status === "error"),
    [snapshot],
  );

  const brokerAllocation = useMemo(() => (snapshot?.accounts ?? [])
    .filter((row) => row.status !== "error" && (row.total_usd ?? 0) > 0)
    .map((row) => ({
      id: row.source_id ?? row.broker,
      name: row.label ?? row.broker.toUpperCase(),
      value: row.total_usd ?? 0,
      connector: row.broker,
    })), [snapshot]);

  const holdingAllocation = useMemo(() => {
    const rows = [...(snapshot?.combined_holdings ?? [])]
      .filter((row) => row.market_value_usd > 0)
      .sort((a, b) => b.market_value_usd - a.market_value_usd);
    const shown = rows.slice(0, 7).map((row) => ({ name: row.symbol, value: row.market_value_usd }));
    const other = rows.slice(7).reduce((sum, row) => sum + row.market_value_usd, 0);
    if (other > 0) shown.push({ name: t("portfolio.allocation.other"), value: other });
    const valuation = snapshot?.valuation;
    if ((valuation?.cash_usd ?? 0) > 0.01) shown.push({ name: t("portfolio.allocation.cash"), value: valuation?.cash_usd ?? 0 });
    if ((valuation?.unpriced_or_other_usd ?? 0) > 0.01) shown.push({ name: t("portfolio.allocation.unpriced"), value: valuation?.unpriced_or_other_usd ?? 0 });
    if (!valuation && snapshot) {
      const priced = rows.reduce((sum, row) => sum + row.market_value_usd, 0);
      const residual = Math.max(0, snapshot.totals.usd - priced);
      if (residual > 0.01) shown.push({ name: t("portfolio.allocation.cashUnpriced"), value: residual });
    }
    return shown;
  }, [snapshot, t]);

  const dailyChange = useMemo(() => {
    if (!snapshot || !history.length) return null;
    const sameDay = history.filter((row) => dayKey(row.created_at) === dayKey(snapshot.created_at));
    if (!sameDay.length) return null;
    return snapshot.totals.usd - Number(sameDay[0].total_usd);
  }, [snapshot, history]);

  const latestCompleteAt = history.length ? history[history.length - 1].created_at : undefined;
  const coverage = snapshot?.valuation?.identified_coverage ?? (() => {
    if (!snapshot?.totals.usd) return 0;
    return (snapshot.positions ?? []).reduce((sum, row) => sum + (row.priced ? row.market_value_usd : 0), 0) / snapshot.totals.usd;
  })();
  const displayCurrency = portfolioSettings?.display_currency ?? snapshot?.display_currency ?? "USD";
  const totalDisplay = displayCurrency === "CNY" ? snapshot?.totals.cny : snapshot?.totals.usd;

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-6">
        <header className="flex flex-col gap-4 border-b pb-6 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5 text-positive" />
              {t("portfolio.page.badge")}
            </div>
            <h1 className="text-3xl font-semibold tracking-tight">{t("portfolio.page.title")}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{t("portfolio.page.subtitle")}</p>
            {snapshot ? (
              <p className="mt-2 text-xs text-muted-foreground">
                {t(snapshot.fx.stale ? "portfolio.page.fxCached" : "portfolio.page.fxFresh", { rate: snapshot.fx.usd_cny.toFixed(4) })}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setEditorOpen(true)} className="inline-flex items-center gap-2 rounded-md border bg-card px-4 py-2 text-sm">
              <Settings2 className="h-4 w-4" />{t("portfolio.page.manageAccounts")}
            </button>
            <button onClick={() => void download()} disabled={!snapshot} className="inline-flex items-center gap-2 rounded-md border bg-card px-4 py-2 text-sm disabled:opacity-50">
              <Download className="h-4 w-4" />{t("portfolio.page.exportCsv")}
            </button>
            <button onClick={() => void refresh()} disabled={refreshing || reconnectingSource !== null} className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
              {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {refreshing ? t("portfolio.page.refreshing") : t("portfolio.page.refreshAll")}
            </button>
          </div>
        </header>

        {error ? <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 p-4 text-sm text-danger"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div> : null}
        {refreshing && refreshState ? <RefreshProgress state={refreshState} settings={portfolioSettings} /> : null}
        {loading ? <div className="flex h-56 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div> : null}

        {!loading && !snapshot ? (
          <section className="rounded-xl border border-dashed p-12 text-center">
            <WalletCards className="mx-auto h-8 w-8 text-muted-foreground" />
            <h2 className="mt-4 font-medium">{t("portfolio.page.emptyTitle")}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{t("portfolio.page.emptyBody")}</p>
            <button onClick={() => setEditorOpen(true)} className="mt-5 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"><Settings2 className="h-4 w-4" />{t("portfolio.page.emptyAction")}</button>
          </section>
        ) : null}

        {snapshot ? (
          <>
            <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Metric
                label={t("portfolio.metrics.total")}
                value={money(totalDisplay, displayCurrency)}
                note={displayCurrency === "USD" ? money(snapshot.totals.cny, "CNY") : money(snapshot.totals.usd)}
                warningNote={failedAccounts.length ? t("portfolio.metrics.excluded", { count: failedAccounts.length }) : undefined}
                icon={<WalletCards className="h-4 w-4" />}
              />
              <Metric
                label={t("portfolio.metrics.change")}
                value={dailyChange == null ? "—" : `${dailyChange >= 0 ? "+" : ""}${money(dailyChange)}`}
                note={t("portfolio.metrics.changeNote")}
                tone={dailyChange == null ? undefined : dailyChange >= 0 ? "positive" : "danger"}
                icon={<Clock3 className="h-4 w-4" />}
              />
              <Metric
                label={t("portfolio.metrics.coverage")}
                value={percentage(coverage)}
                note={t("portfolio.metrics.coverageNote", { priced: money(snapshot.valuation?.priced_usd), cash: money(snapshot.valuation?.cash_usd) })}
                icon={<Database className="h-4 w-4" />}
              />
              <Metric
                label={t("portfolio.metrics.lastComplete")}
                value={latestCompleteAt ? new Date(latestCompleteAt).toLocaleTimeString(uiLocale(), { hour: "2-digit", minute: "2-digit" }) : "—"}
                note={dateTime(latestCompleteAt)}
                tone={snapshot.complete ? "positive" : "warning"}
                icon={snapshot.complete ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
              />
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              <AllocationPie title={t("portfolio.allocation.byAccount")} data={brokerAllocation} centerLabel={money(totalDisplay, displayCurrency)} onSelect={(id) => setSourceFilter(id)} />
              <AllocationPie title={t("portfolio.allocation.byHolding")} data={holdingAllocation} centerLabel={t("portfolio.allocation.center")} />
            </section>

            {snapshot.warnings.length ? (
              <section className="rounded-lg border border-warning/30 bg-warning/5 p-4 text-sm">
                <div className="mb-2 font-medium text-warning">{t("portfolio.page.warningsTitle")}</div>
                <div className="space-y-1.5">{snapshot.warnings.map((warning) => <div key={warning} className="flex gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" /><span>{warning}</span></div>)}</div>
              </section>
            ) : null}

            <section>
              <div className="mb-3 flex items-end justify-between gap-3">
                <div><h2 className="font-semibold">{t("portfolio.accounts.title")}</h2><p className="mt-1 text-xs text-muted-foreground">{t("portfolio.accounts.hint")}</p></div>
                {sourceFilter !== "all" ? <button className="text-xs text-primary" onClick={() => setSourceFilter("all")}>{t("portfolio.accounts.clearFilter")}</button> : null}
              </div>
              <div className="grid gap-3 lg:grid-cols-3">
                {snapshot.accounts.map((account) => (
                  <AccountCard key={account.source_id ?? account.broker} account={account} active={sourceFilter === (account.source_id ?? account.broker)} displayCurrency={displayCurrency} onClick={() => { const id = account.source_id ?? account.broker; setSourceFilter((current) => current === id ? "all" : id); }} onReconnect={account.reconnect_required && account.source_id ? () => void reconnectSource(account.source_id!) : undefined} onRetry={!account.reconnect_required ? () => void refresh() : undefined} busy={refreshing || reconnectingSource === (account.source_id ?? account.broker)} actionsDisabled={refreshing || reconnectingSource !== null} />
                ))}
              </div>
            </section>

            <section className="overflow-hidden rounded-xl border bg-card">
              <div className="flex flex-col gap-3 border-b p-4 lg:flex-row lg:items-center lg:justify-between">
                <div><h2 className="font-semibold">{t("portfolio.holdings.title")}</h2><p className="mt-1 text-xs text-muted-foreground">{t("portfolio.holdings.count", { count: positions.length })}</p></div>
                <div className="relative w-full lg:w-72"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("portfolio.holdings.search")} aria-label={t("portfolio.holdings.search")} className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm" /></div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1050px] text-sm">
                  <thead className="bg-muted/40 text-left text-xs text-muted-foreground"><tr><Th>{t("portfolio.holdings.colBroker")}</Th><Th>{t("portfolio.holdings.colSymbol")}</Th><Th>{t("portfolio.holdings.colType")}</Th><Th>{t("portfolio.holdings.colQuantity")}</Th><Th>{t("portfolio.holdings.colCostPrice")}</Th><Th>{t("portfolio.holdings.colValue")}</Th><Th>{t("portfolio.holdings.colWeight")}</Th><Th>{t("portfolio.holdings.colPnl")}</Th><Th>{t("portfolio.holdings.colData")}</Th></tr></thead>
                  <tbody className="divide-y">
                    {positions.map((row) => {
                      const weight = snapshot.totals.usd > 0 ? row.market_value_usd / snapshot.totals.usd : 0;
                      return <tr key={`${row.source_id ?? row.broker}-${row.symbol}`} className="hover:bg-muted/20"><Td><div className="font-medium">{row.source_label ?? row.broker.toUpperCase()}</div><div className="mt-1 text-xs"><BrokerBadge broker={row.broker} /></div></Td><Td><div className="font-medium">{row.symbol}</div><div className="max-w-52 truncate text-xs text-muted-foreground">{row.name}</div></Td><Td><span className="capitalize text-muted-foreground">{row.asset_type}</span></Td><Td>{quantity(row.quantity)}</Td><Td><div>{price(row.cost_price)}</div><div className="text-xs text-muted-foreground">{price(row.market_price)}</div></Td><Td><div className="font-medium">{row.priced ? money(row.market_value_usd) : "—"}</div><div className="text-xs text-muted-foreground">{row.priced ? money(row.market_value_cny, "CNY") : t("portfolio.holdings.unpriced")}</div></Td><Td>{row.priced ? percentage(weight) : "—"}</Td><Td><span className={row.unrealized_pnl_usd == null ? "text-muted-foreground" : row.unrealized_pnl_usd >= 0 ? "text-positive" : "text-danger"}>{row.unrealized_pnl_usd == null ? "—" : money(row.unrealized_pnl_usd)}</span></Td><Td><DataBadge priced={row.priced} /></Td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            <HistoryChart history={history} />

            <section className="rounded-xl border bg-card p-5">
              <div className="mb-4 flex items-center gap-2"><KeyRound className="h-4 w-4 text-muted-foreground" /><h2 className="font-semibold">{t("portfolio.credentials.title")}</h2></div>
              <div className="grid gap-3 lg:grid-cols-3">{snapshot.accounts.map((account) => <CredentialCard key={account.source_id ?? account.broker} account={account} />)}</div>
            </section>
          </>
        ) : null}
      </div>
      <PortfolioSourceEditor open={editorOpen} settings={portfolioSettings} catalog={sourceCatalog} saving={savingSettings} onClose={() => setEditorOpen(false)} onSave={savePortfolioSettings} onConnectionsChanged={reloadConnections} />
    </div>
  );
}

/** Headline figure tile; `warningNote` is the amber caveat under the value. */
function Metric({ label, value, note, warningNote, icon, tone }: { label: string; value: string; note?: string; warningNote?: string; icon: ReactNode; tone?: "positive" | "danger" | "warning" }) {
  const toneClass = tone === "positive" ? "text-positive" : tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "";
  return <div className="rounded-xl border bg-card p-5">
    <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{label}</span>{icon}</div>
    <div className={`mt-3 text-2xl font-semibold tracking-tight ${toneClass}`}>{value}</div>
    {note ? <div className="mt-1 truncate text-xs text-muted-foreground" title={note}>{note}</div> : null}
    {warningNote ? <div className="mt-1 flex items-start gap-1.5 text-xs text-warning"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /><span>{warningNote}</span></div> : null}
  </div>;
}

/**
 * Coerce a refresh payload into the shape the progress panel renders.
 *
 * Older backends reported per-source progress under `brokers`, and a source
 * entry can arrive as null; both are normalized here so a malformed payload
 * cannot take the page down mid-refresh.
 */
function normalizeRefreshState(state: PortfolioRefreshState | null | undefined): PortfolioRefreshState {
  const candidate = state?.sources ?? state?.brokers;
  const sources = candidate && typeof candidate === "object" && !Array.isArray(candidate)
    ? Object.fromEntries(Object.entries(candidate).map(([sourceId, item]) => [
        sourceId,
        item && typeof item === "object" ? item : { status: "pending" as const },
      ]))
    : {};
  return {
    running: Boolean(state?.running),
    current: typeof state?.current === "string" ? state.current : null,
    sources,
    brokers: sources,
  };
}

function RefreshProgress({ state, settings }: { state: PortfolioRefreshState; settings: PortfolioSettings | null }) {
  const { t } = useTranslation();
  const labels = new Map(settings?.sources.map((source) => [source.connection_id, source.label]) ?? []);
  const entries = Object.entries(normalizeRefreshState(state).sources ?? {});
  const statusLabel = (status: string) => status === "refreshing"
    ? t("portfolio.status.reading")
    : status === "ok"
      ? t("portfolio.status.done")
      : status === "error"
        ? t("portfolio.status.failed")
        : t("portfolio.status.waiting");
  return <section className="rounded-lg border bg-card p-4">
    <div className="mb-3 flex items-center gap-2 text-sm font-medium"><Loader2 className="h-4 w-4 animate-spin text-primary" />{t("portfolio.status.title")}</div>
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{entries.map(([sourceId, item]) => {
      const status = item.status ?? "pending";
      return <div key={sourceId} className="flex items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-xs">
        <span className="truncate font-medium" title={labels.get(sourceId) ?? sourceId}>{labels.get(sourceId) ?? sourceId}</span>
        <span className={status === "ok" ? "text-positive" : status === "error" ? "text-danger" : "text-muted-foreground"}>{statusLabel(status)}</span>
      </div>;
    })}</div>
  </section>;
}

/**
 * One account tile. A source with `status === "error"` has no totals at all —
 * it renders the failure, the error text and the last successful read time
 * instead of a value, so nothing on the card suggests it is part of the total.
 */
function AccountCard({ account, active, displayCurrency, onClick, onReconnect, onRetry, busy, actionsDisabled }: { account: PortfolioAccount; active: boolean; displayCurrency: "USD" | "CNY"; onClick: () => void; onReconnect?: () => void; onRetry?: () => void; busy: boolean; actionsDisabled: boolean }) {
  const { t } = useTranslation();
  const failed = account.status === "error";
  return <div role="button" tabIndex={0} onClick={onClick} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onClick(); }} className={`cursor-pointer rounded-xl border bg-card p-5 transition ${active ? "border-primary ring-1 ring-primary/20" : "hover:border-primary/40"}`}>
    <div className="flex items-center justify-between gap-3">
      <div><div className="font-medium">{account.label ?? account.broker.toUpperCase()}</div><div className="mt-1 flex flex-wrap items-center gap-2 text-xs"><BrokerBadge broker={account.broker} /><PortfolioCompatibilityBadge compatibility={account.portfolio_compatibility} /></div></div>
      {failed ? <WifiOff className="h-4 w-4 text-danger" /> : <CheckCircle2 className="h-4 w-4 text-positive" />}
    </div>
    {failed ? (
      <>
        <p className="mt-4 text-sm text-danger">{t("portfolio.accounts.failed")}</p>
        <p className="mt-2 text-xs text-muted-foreground">{account.last_success_at ? t("portfolio.accounts.lastSuccess", { time: dateTime(account.last_success_at) }) : t("portfolio.accounts.noSuccess")}</p>
      </>
    ) : (
      <>
        <div className="mt-4 text-2xl font-semibold">{displayCurrency === "CNY" ? money(account.total_cny, "CNY") : money(account.total_usd)}</div>
        <div className="mt-1 text-xs text-muted-foreground">{displayCurrency === "CNY" ? money(account.total_usd) : money(account.total_cny, "CNY")} · {t("portfolio.accounts.positions", { count: account.position_count ?? 0 })}</div>
        <div className="mt-4 flex items-center justify-between border-t pt-3 text-xs"><span className="text-positive">{t("portfolio.accounts.fresh")}</span><span className="text-muted-foreground">{dateTime(account.last_success_at)}</span></div>
      </>
    )}
    {failed && account.error ? <p className="mt-3 line-clamp-2 text-xs text-muted-foreground" title={account.error}>{account.error}</p> : null}
    {failed && onReconnect ? <button onClick={(event) => { event.stopPropagation(); onReconnect(); }} disabled={actionsDisabled} className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs disabled:opacity-50">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{t("portfolio.accounts.reconnect")}</button> : null}
    {failed && onRetry ? <button onClick={(event) => { event.stopPropagation(); onRetry(); }} disabled={actionsDisabled} className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs disabled:opacity-50">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{t("portfolio.accounts.retryRead")}</button> : null}
  </div>;
}

function BrokerBadge({ broker }: { broker: string }) {
  const color = BROKER_COLORS[broker.toUpperCase()] ?? "#7c8493";
  return <span className="inline-flex items-center gap-2 font-medium uppercase"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />{broker}</span>;
}

function DataBadge({ priced }: { priced: boolean }) {
  const { t } = useTranslation();
  if (!priced) return <span className="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">{t("portfolio.holdings.unpriced")}</span>;
  return <span className="rounded-full bg-positive/10 px-2 py-1 text-xs text-positive">{t("portfolio.holdings.priced")}</span>;
}

function CredentialCard({ account }: { account: PortfolioAccount }) {
  const { t } = useTranslation();
  const auth = account.auth;
  const renewal = auth?.renewal === "automatic"
    ? t("portfolio.credentials.renewalAutomatic")
    : auth?.renewal === "session"
      ? t("portfolio.credentials.renewalSession")
      : t("portfolio.credentials.renewalProvider");
  return <div className="rounded-lg border p-4">
    <div className="flex items-center justify-between gap-3">
      <div><span className="font-medium">{account.label ?? account.broker.toUpperCase()}</span><div className="mt-1 text-xs text-muted-foreground">{account.broker.toUpperCase()}</div></div>
      <span className={`shrink-0 rounded-full px-2 py-1 text-xs ${auth?.readonly ? "bg-positive/10 text-positive" : "bg-warning/10 text-warning"}`}>{auth?.readonly ? t("portfolio.credentials.readOnlyProfile") : t("portfolio.credentials.writableProfile")}</span>
    </div>
    <div className="mt-3 text-sm">{auth?.method ?? "—"} · {renewal}</div>
    <p className="mt-1 text-xs text-muted-foreground">{auth?.detail ?? "—"}</p>
  </div>;
}

type AllocationDatum = { id?: string; name: string; value: number; connector?: string };

function AllocationPie({ title, data, centerLabel, onSelect }: { title: string; data: AllocationDatum[]; centerLabel: string; onSelect?: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const { i18n: instance } = useTranslation();
  const dark = useThemeDark();
  useEffect(() => {
    if (!ref.current || ref.current.clientWidth === 0) return;
    const theme = getChartTheme();
    const chart = echarts.init(ref.current);
    const brokerPalette = data.map((item) => BROKER_COLORS[(item.connector ?? item.name).toUpperCase()]).filter(Boolean);
    const palette = brokerPalette.length === data.length ? brokerPalette : HOLDING_COLORS;
    chart.setOption({
      backgroundColor: "transparent",
      color: palette,
      tooltip: {
        trigger: "item",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText },
        formatter: (params: { name: string; value: number; percent: number }) => `${params.name}<br/>${money(params.value)} · ${slicePercentage(params.percent)}`,
      },
      legend: { type: "scroll", bottom: 0, left: "center", textStyle: { color: theme.textColor }, pageTextStyle: { color: theme.textColor } },
      series: [{ type: "pie", radius: ["46%", "70%"], center: ["50%", "43%"], avoidLabelOverlap: true, padAngle: 2, itemStyle: { borderRadius: 5 }, label: { show: true, color: theme.textColor, formatter: (params: { name: string; percent: number }) => params.percent >= 2 ? `${params.name}\n${slicePercentage(params.percent)}` : "", fontSize: 12 }, labelLine: { length: 10, length2: 7, lineStyle: { color: theme.gridColor } }, labelLayout: { hideOverlap: true }, data }],
      graphic: [{ type: "text", left: "center", top: "39%", style: { text: centerLabel, textAlign: "center", fill: theme.textColor, fontSize: 12, fontWeight: 600 } }],
    });
    const resize = () => chart.resize();
    const select = (params: { dataIndex?: number }) => { const item = params.dataIndex == null ? undefined : data[params.dataIndex]; if (item && onSelect) onSelect(item.id ?? item.name); };
    chart.on("click", select);
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.off("click", select); chart.dispose(); };
  }, [data, centerLabel, onSelect, dark, instance.language]);
  return <div className="rounded-xl border bg-card p-5"><h2 className="font-semibold">{title}</h2><div ref={ref} className="h-80 w-full" /></div>;
}

function HistoryChart({ history }: { history: PortfolioHistoryPoint[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const { t, i18n: instance } = useTranslation();
  const dark = useThemeDark();
  useEffect(() => {
    if (!ref.current || ref.current.clientWidth === 0) return;
    const theme = getChartTheme();
    const chart = echarts.init(ref.current);
    const rows = history.slice(-180);
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 18, right: 18, top: 25, bottom: 28, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText },
        formatter: (items: Array<{ dataIndex: number; value: number }>) => { const item = items[0]; const row = rows[item.dataIndex]; return `${dateTime(row?.created_at)}<br/>${money(Number(item?.value))}`; },
      },
      xAxis: { type: "category", boundaryGap: false, data: rows.map((row) => new Date(row.created_at).toLocaleString(uiLocale(), { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })), axisLabel: { color: theme.textColor, hideOverlap: true }, axisLine: { lineStyle: { color: theme.gridColor } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: theme.textColor, formatter: compactUsd }, splitLine: { lineStyle: { color: theme.gridColor, opacity: 0.45 } } },
      series: [{ type: "line", data: rows.map((row) => Number(row.total_usd)), smooth: true, symbol: rows.length < 30 ? "circle" : "none", lineStyle: { width: 2, color: "#4f6edb" }, itemStyle: { color: "#4f6edb" }, areaStyle: { color: "rgba(79,110,219,0.10)" } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [history, dark, instance.language]);
  return <section className="rounded-xl border bg-card p-5">
    <div className="flex items-start justify-between gap-3">
      <div><h2 className="font-semibold">{t("portfolio.history.title")}</h2><p className="mt-1 text-xs text-muted-foreground">{t("portfolio.history.hint")}</p></div>
      <span className="rounded-full bg-positive/10 px-2 py-1 text-xs text-positive">{t("portfolio.history.count", { count: history.length })}</span>
    </div>
    {history.length ? <div ref={ref} className="mt-4 h-64 w-full" /> : <div className="flex h-44 items-center justify-center text-sm text-muted-foreground">{t("portfolio.history.empty")}</div>}
  </section>;
}

function Th({ children }: { children: ReactNode }) { return <th className="whitespace-nowrap px-4 py-3 font-medium">{children}</th>; }
function Td({ children }: { children: ReactNode }) { return <td className="px-4 py-3">{children}</td>; }
