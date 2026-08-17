import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, ChevronsDown, ChevronsUp, GripVertical, Loader2, Minus, Plus, RefreshCw, Search, X } from "lucide-react";
import { Link } from "react-router";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api, type MarketIndexSnapshot, type MarketSymbolCandidate } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 15_000;

type WatchlistMarket = "a_share" | "us";
type WatchlistEntry = { symbol: string; name: string };
type Watchlists = Record<WatchlistMarket, WatchlistEntry[]>;

const EMPTY_WATCHLISTS: Watchlists = { a_share: [], us: [] };

function formatPrice(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatChange(value: number | null): string {
  if (value === null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function changeTone(value: number | null): string {
  if (value === null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-red-500" : "text-emerald-500";
}

function ChangeIcon({ value }: { value: number | null }) {
  if (value === null || value === 0) return <Minus className="h-3.5 w-3.5" aria-hidden="true" />;
  return value > 0
    ? <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
    : <ArrowDownRight className="h-3.5 w-3.5" aria-hidden="true" />;
}

function IndexCard({ item, unavailableLabel, action }: { item: MarketIndexSnapshot; unavailableLabel: string; action?: ReactNode }) {
  const tone = changeTone(item.change_pct);
  return (
    <article className="rounded-xl border border-border/60 bg-card p-4 shadow-sm transition-colors hover:border-border">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium text-foreground">{item.name}</h3>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{item.symbol}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full bg-muted/60 px-2 py-0.5 text-[10px] text-muted-foreground">
            {item.market === "a_share" ? "A股" : "美股"}
          </span>
          {action}
        </div>
      </div>
      <div className="mt-5 flex items-end justify-between gap-3">
        <span className="font-mono text-2xl font-semibold tracking-tight">
          {item.status === "ok" ? formatPrice(item.price) : unavailableLabel}
        </span>
        <span className={cn("inline-flex items-center gap-1 font-mono text-sm font-medium", tone)}>
          <ChangeIcon value={item.change_pct} />
          {formatChange(item.change_pct)}
        </span>
      </div>
    </article>
  );
}

export function Overview() {
  const { t, i18n } = useTranslation();
  const [aShareItems, setAShareItems] = useState<MarketIndexSnapshot[]>([]);
  const [usItems, setUSItems] = useState<MarketIndexSnapshot[]>([]);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [aShareLoading, setAShareLoading] = useState(true);
  const [usLoading, setUSLoading] = useState(true);
  const [aShareRefreshing, setAShareRefreshing] = useState(false);
  const [usRefreshing, setUSRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [watchlists, setWatchlists] = useState<Watchlists>(EMPTY_WATCHLISTS);
  const [watchlistsReady, setWatchlistsReady] = useState(false);
  const [watchlistsRemote, setWatchlistsRemote] = useState(false);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [watchQuotes, setWatchQuotes] = useState<Record<WatchlistMarket, MarketIndexSnapshot[]>>({ a_share: [], us: [] });
  const [watchLoading, setWatchLoading] = useState(false);
  const aShareController = useRef<AbortController | null>(null);
  const usController = useRef<AbortController | null>(null);
  const watchlistsRef = useRef<Watchlists>(EMPTY_WATCHLISTS);
  const watchlistMutationQueue = useRef<Promise<void>>(Promise.resolve());

  const loadWatchlists = useCallback(async () => {
    try {
      const remote = await api.getMarketWatchlists();
      watchlistsRef.current = remote;
      setWatchlists(remote);
      setWatchlistsRemote(true);
      setWatchlistsReady(true);
      setWatchlistError(null);
    } catch (err) {
      // The database is the only source of truth. Do not fall back to browser storage.
      watchlistsRef.current = EMPTY_WATCHLISTS;
      setWatchlists(EMPTY_WATCHLISTS);
      setWatchlistsReady(true);
      setWatchlistsRemote(false);
      setWatchlistError(err instanceof Error ? err.message : t("overview.loadFailed"));
    }
  }, [t]);

  const loadAShare = useCallback(async (initial = false) => {
    aShareController.current?.abort();
    const controller = new AbortController();
    aShareController.current = controller;
    if (initial) setAShareLoading(true);
    else setAShareRefreshing(true);
    setError(null);
    try {
      const response = await api.getMarketAShareOverview(controller.signal);
      if (controller.signal.aborted) return;
      setAShareItems(response.items);
      if (response.updated_at) setUpdatedAt(response.updated_at);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : t("overview.loadFailed"));
    } finally {
      if (!controller.signal.aborted) {
        setAShareLoading(false);
        setAShareRefreshing(false);
      }
    }
  }, [t]);

  const loadUS = useCallback(async (initial = false) => {
    usController.current?.abort();
    const controller = new AbortController();
    usController.current = controller;
    if (initial) setUSLoading(true);
    else setUSRefreshing(true);
    setError(null);
    try {
      const response = await api.getMarketUSOverview(controller.signal);
      if (controller.signal.aborted) return;
      setUSItems(response.items);
      if (response.updated_at) setUpdatedAt(response.updated_at);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : t("overview.loadFailed"));
    } finally {
      if (!controller.signal.aborted) {
        setUSLoading(false);
        setUSRefreshing(false);
      }
    }
  }, [t]);

  const loading = aShareLoading || usLoading;
  const refreshing = aShareRefreshing || usRefreshing;

  useEffect(() => {
    void loadAShare(true);
    const timer = window.setInterval(() => void loadAShare(false), POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      aShareController.current?.abort();
    };
  }, [loadAShare]);

  useEffect(() => {
    void loadUS(true);
    const timer = window.setInterval(() => void loadUS(false), POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      usController.current?.abort();
    };
  }, [loadUS]);

  useEffect(() => {
    void loadWatchlists();
  }, [loadWatchlists]);

  const enqueueWatchlistMutation = useCallback((update: (current: Watchlists) => Watchlists) => {
    if (!watchlistsRemote) {
      toast.error(watchlistError ?? t("overview.loadFailed"));
      return;
    }

    watchlistMutationQueue.current = watchlistMutationQueue.current
      .catch(() => undefined)
      .then(async () => {
        const current = watchlistsRef.current;
        const next = update(current);
        if (next === current) return;

        // Only update the UI after the database confirms the complete new list.
        const saved = await api.saveMarketWatchlists(next);
        watchlistsRef.current = saved;
        setWatchlists(saved);
        setWatchlistError(null);
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : t("overview.loadFailed");
        setWatchlistError(message);
        toast.error(message);
      });
  }, [t, watchlistError, watchlistsRemote]);

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;
    const loadWatchQuotes = async () => {
      controller?.abort();
      controller = new AbortController();
      setWatchLoading(true);
      try {
        const response = await api.getMarketWatchlistOverview(controller.signal);
        if (disposed || controller.signal.aborted) return;
        setWatchQuotes({ a_share: response.a_share, us: response.us });
      } catch {
        if (!disposed && !controller.signal.aborted) setWatchQuotes({ a_share: [], us: [] });
      } finally {
        if (!disposed && !controller.signal.aborted) setWatchLoading(false);
      }
    };

    void loadWatchQuotes();
    const timer = window.setInterval(() => void loadWatchQuotes(), POLL_INTERVAL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      controller?.abort();
    };
  }, [watchlists]);

  const addWatchlistEntry = useCallback((market: WatchlistMarket, candidate: MarketSymbolCandidate) => {
    enqueueWatchlistMutation((current) => current[market].some((entry) => entry.symbol === candidate.symbol)
      ? current
      : { ...current, [market]: [...current[market], { symbol: candidate.symbol, name: candidate.name }] });
  }, [enqueueWatchlistMutation]);

  const removeWatchlistEntry = useCallback((market: WatchlistMarket, symbol: string) => {
    enqueueWatchlistMutation((current) => ({
      ...current,
      [market]: current[market].filter((entry) => entry.symbol !== symbol),
    }));
  }, [enqueueWatchlistMutation]);

  const reorderWatchlistEntry = useCallback((market: WatchlistMarket, fromSymbol: string, toSymbol: string) => {
    enqueueWatchlistMutation((current) => {
      const entries = [...current[market]];
      const fromIndex = entries.findIndex((entry) => entry.symbol === fromSymbol);
      const toIndex = entries.findIndex((entry) => entry.symbol === toSymbol);
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return current;
      const [moved] = entries.splice(fromIndex, 1);
      entries.splice(toIndex, 0, moved);
      return { ...current, [market]: entries };
    });
  }, [enqueueWatchlistMutation]);

  const moveWatchlistEntry = useCallback((market: WatchlistMarket, symbol: string, edge: "top" | "bottom") => {
    enqueueWatchlistMutation((current) => {
      const entries = [...current[market]];
      const index = entries.findIndex((entry) => entry.symbol === symbol);
      if (index < 0 || (edge === "top" && index === 0) || (edge === "bottom" && index === entries.length - 1)) return current;
      const [moved] = entries.splice(index, 1);
      if (edge === "top") entries.unshift(moved);
      else entries.push(moved);
      return { ...current, [market]: entries };
    });
  }, [enqueueWatchlistMutation]);

  const refreshAll = useCallback(() => {
    void loadAShare(false);
    void loadUS(false);
    // The watchlist endpoint reads its own database-backed symbol list.
    // Changing the list also causes the effect above to request it again.
  }, [loadAShare, loadUS]);

  const grouped = useMemo(() => ({
    aShare: aShareItems,
    us: usItems,
  }), [aShareItems, usItems]);

  const updatedLabel = updatedAt
    ? new Intl.DateTimeFormat(i18n.language, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(updatedAt))
    : "—";

  return (
    <div className="min-h-full p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-7">
        <header className="flex flex-col gap-4 border-b border-border/60 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 text-xs font-medium text-primary">
              <Activity className="h-3.5 w-3.5" aria-hidden="true" />
              {t("overview.marketStatus")}
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("overview.title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("overview.subtitle")}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">
              {t("overview.updatedAt", { time: updatedLabel })}
            </span>
            <button
              type="button"
              onClick={refreshAll}
              disabled={refreshing || loading || watchLoading}
              className="inline-flex items-center gap-2 rounded-md border border-border/60 px-3 py-2 text-xs font-medium transition hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", (refreshing || watchLoading) && "animate-spin")} aria-hidden="true" />
              {t("overview.refresh")}
            </button>
          </div>
        </header>

        {error ? (
          <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
            {t("overview.loadFailed")}
          </div>
        ) : null}

        {loading && !aShareItems.length && !usItems.length ? (
          <div className="space-y-6" aria-label={t("overview.loading")}>
            {[1, 2].map((row) => (
              <section key={row} className="space-y-3">
                <div className="h-4 w-16 animate-pulse rounded bg-muted" />
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
                  {[1, 2, 3, 4, 5].slice(0, row === 1 ? 4 : 5).map((card) => (
                    <div key={card} className="h-32 animate-pulse rounded-xl border border-border/60 bg-card" />
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <>
            <MarketRow title={t("overview.aShare")} items={grouped.aShare} unavailableLabel={t("overview.unavailable")} />
            <MarketRow title={t("overview.us")} items={grouped.us} unavailableLabel={t("overview.unavailable")} />
            <section className="space-y-3 border-t border-border/60 pt-6">
              <h2 className="text-sm font-semibold tracking-wide text-foreground">{t("overview.watchlists")}</h2>
              {watchlistError ? (
                <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
                  {watchlistError}
                </div>
              ) : null}
              {watchlistsReady ? (
                <div className="grid gap-5 lg:grid-cols-2">
                  <WatchlistColumn
                    market="a_share"
                    title={t("overview.aShare")}
                    entries={watchlists.a_share}
                    quotes={watchQuotes.a_share}
                    loading={watchLoading}
                    unavailableLabel={t("overview.unavailable")}
                    addLabel={t("overview.addWatchlist")}
                    searchPlaceholder={t("overview.searchPlaceholder")}
                    emptyLabel={t("overview.emptyWatchlist")}
                    onAdd={addWatchlistEntry}
                    onRemove={removeWatchlistEntry}
                    onReorder={reorderWatchlistEntry}
                    onMoveEdge={moveWatchlistEntry}
                  />
                  <WatchlistColumn
                    market="us"
                    title={t("overview.us")}
                    entries={watchlists.us}
                    quotes={watchQuotes.us}
                    loading={watchLoading}
                    unavailableLabel={t("overview.unavailable")}
                    addLabel={t("overview.addWatchlist")}
                    searchPlaceholder={t("overview.searchPlaceholder")}
                    emptyLabel={t("overview.emptyWatchlist")}
                    onAdd={addWatchlistEntry}
                    onRemove={removeWatchlistEntry}
                    onReorder={reorderWatchlistEntry}
                    onMoveEdge={moveWatchlistEntry}
                  />
                </div>
              ) : (
                <div className="rounded-xl border border-border/60 bg-card/40 px-4 py-8 text-center text-sm text-muted-foreground">
                  {t("overview.loading")}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function WatchlistColumn({
  market,
  title,
  entries,
  quotes,
  loading,
  unavailableLabel,
  addLabel,
  searchPlaceholder,
  emptyLabel,
  onAdd,
  onRemove,
  onReorder,
  onMoveEdge,
}: {
  market: WatchlistMarket;
  title: string;
  entries: WatchlistEntry[];
  quotes: MarketIndexSnapshot[];
  loading: boolean;
  unavailableLabel: string;
  addLabel: string;
  searchPlaceholder: string;
  emptyLabel: string;
  onAdd: (market: WatchlistMarket, candidate: MarketSymbolCandidate) => void;
  onRemove: (market: WatchlistMarket, symbol: string) => void;
  onReorder: (market: WatchlistMarket, fromSymbol: string, toSymbol: string) => void;
  onMoveEdge: (market: WatchlistMarket, symbol: string, edge: "top" | "bottom") => void;
}) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<MarketSymbolCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [draggedSymbol, setDraggedSymbol] = useState<string | null>(null);

  const search = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    setSearching(true);
    try {
      const response = await api.searchMarketSymbols(trimmed, market);
      setCandidates(response.items);
    } catch {
      setCandidates([]);
    } finally {
      setSearching(false);
    }
  };

  const quoteBySymbol = new Map(quotes.map((quote) => [quote.symbol, quote]));
  const displayQuotes = entries.map((entry) => quoteBySymbol.get(entry.symbol) ?? {
    key: entry.symbol,
    name: entry.name,
    symbol: entry.symbol,
    market,
    price: null,
    change: null,
    change_pct: null,
    source: market === "a_share" ? "tencent" : "yfinance",
    status: "unavailable" as const,
  });

  return (
    <section className="rounded-xl border border-border/60 bg-card/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium">{title}</h3>
        <button
          type="button"
          onClick={() => { setAdding((value) => !value); setCandidates([]); }}
          className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1.5 text-xs font-medium transition hover:bg-muted/60"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {addLabel}
        </button>
      </div>

      {adding ? (
        <div className="mt-3 rounded-lg border border-border/60 bg-background p-3">
          <form className="flex gap-2" onSubmit={search}>
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={searchPlaceholder}
                className="w-full rounded-md border border-border/60 bg-background py-2 ps-8 pe-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                aria-label={searchPlaceholder}
              />
            </div>
            <button type="submit" disabled={searching || !query.trim()} className="rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50">
              {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t("overview.search")}
            </button>
            <button type="button" onClick={() => setAdding(false)} className="rounded-md p-2 text-muted-foreground hover:bg-muted" aria-label={t("overview.close")}>
              <X className="h-3.5 w-3.5" />
            </button>
          </form>
          {candidates.length ? (
            <div className="mt-2 divide-y divide-border/60 rounded-md border border-border/60">
              {candidates.map((candidate) => (
                <button
                  key={candidate.symbol}
                  type="button"
                  onClick={() => { onAdd(market, candidate); setAdding(false); setQuery(""); setCandidates([]); }}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2 text-start text-xs transition hover:bg-muted/60"
                >
                  <span className="min-w-0 truncate font-medium">{candidate.name}</span>
                  <span className="shrink-0 font-mono text-muted-foreground">{candidate.symbol}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {entries.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">{emptyLabel}</p>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {displayQuotes.map((quote, index) => (
            <div
              key={quote.key}
              draggable
              onDragStart={(event) => {
                setDraggedSymbol(quote.symbol);
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", quote.symbol);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const fromSymbol = event.dataTransfer.getData("text/plain") || draggedSymbol;
                if (fromSymbol) onReorder(market, fromSymbol, quote.symbol);
                setDraggedSymbol(null);
              }}
              onDragEnd={() => setDraggedSymbol(null)}
              className={cn("cursor-grab active:cursor-grabbing", draggedSymbol === quote.symbol && "opacity-50")}
            >
                  <IndexCard
                    item={quote}
                    unavailableLabel={unavailableLabel}
                    action={(
                      <div className="flex items-center gap-0.5">
                        <Link
                          to={`/stocks/${encodeURIComponent(quote.symbol)}`}
                          className="rounded px-1.5 py-1 text-[10px] font-medium text-primary transition hover:bg-primary/10"
                          aria-label={`${t("overview.details")} ${quote.name}`}
                        >
                          {t("overview.details")}
                        </Link>
                        <span className="rounded p-1 text-muted-foreground" title={t("overview.dragToSort")} aria-label={t("overview.dragToSort")}>
                      <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
                    </span>
                    <button
                      type="button"
                      disabled={index === 0}
                      onClick={() => onMoveEdge(market, quote.symbol, "top")}
                      className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
                      aria-label={`${t("overview.moveTop")} ${quote.name}`}
                      title={t("overview.moveTop")}
                    >
                      <ChevronsUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      disabled={index === entries.length - 1}
                      onClick={() => onMoveEdge(market, quote.symbol, "bottom")}
                      className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
                      aria-label={`${t("overview.moveBottom")} ${quote.name}`}
                      title={t("overview.moveBottom")}
                    >
                      <ChevronsDown className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemove(market, quote.symbol)}
                      className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-danger"
                      aria-label={`${t("overview.remove")} ${quote.name}`}
                      title={t("overview.remove")}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              />
            </div>
          ))}
        </div>
      )}
      {loading && entries.length > 0 ? <p className="mt-2 text-[11px] text-muted-foreground">{t("overview.refreshing")}</p> : null}
    </section>
  );
}

function MarketRow({ title, items, unavailableLabel }: { title: string; items: MarketIndexSnapshot[]; unavailableLabel: string }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold tracking-wide text-foreground">{title}</h2>
      <div className={cn(
        "grid gap-3 sm:grid-cols-2",
        items.length <= 4 ? "lg:grid-cols-4" : "lg:grid-cols-5",
      )}>
        {items.map((item) => <IndexCard key={item.key} item={item} unavailableLabel={unavailableLabel} />)}
      </div>
    </section>
  );
}
