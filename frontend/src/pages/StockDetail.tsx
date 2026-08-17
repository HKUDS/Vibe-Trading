import { type ReactNode, type UIEventHandler, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ExternalLink, Loader2, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { useNavigate, useParams } from "react-router";
import { useTranslation } from "react-i18next";
import { CandlestickChart, type Sub } from "@/components/charts/CandlestickChart";
import { api, type StockDetailPeriod, type StockDetailResponse, type StockFundFlowRow } from "@/lib/api";
import { cn } from "@/lib/utils";

function numberValue(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function hasMetricValue(value: unknown): boolean {
  const numeric = numberValue(value);
  if (numeric !== null) return numeric !== 0;
  return typeof value === "string" && value.trim().length > 0 && value.trim() !== "—" && value.trim() !== "-";
}

function formatNumber(value: unknown, digits = 2): string {
  const parsed = numberValue(value);
  return parsed === null ? "—" : parsed.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function formatDate(value: unknown): string {
  const text = String(value || "");
  return text.length >= 10 ? text.slice(0, 10) : text || "—";
}

function formatPercent(value: unknown): string {
  const parsed = numberValue(value);
  return parsed === null ? "—" : `${parsed.toFixed(2)}%`;
}

function formatShares(value: unknown): string {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  if (Math.abs(parsed) >= 100_000_000) return `${(parsed / 100_000_000).toFixed(2)}亿`;
  if (Math.abs(parsed) >= 10_000) return `${(parsed / 10_000).toFixed(2)}万`;
  return formatNumber(parsed, 0);
}

function formatMoney(value: unknown): string {
  const parsed = numberValue(value);
  if (parsed === null) return "—";
  if (Math.abs(parsed) >= 100_000_000) return `${(parsed / 100_000_000).toFixed(2)}亿`;
  if (Math.abs(parsed) >= 10_000) return `${(parsed / 10_000).toFixed(2)}万`;
  return formatNumber(parsed);
}

function formatWithUnit(value: unknown, unit: string, formatter: (input: unknown) => string = formatNumber): string {
  return numberValue(value) === null ? "—" : `${formatter(value)}${unit}`;
}

function FeedEmpty({ label }: { label: string }) {
  return <p className="py-8 text-center text-sm text-muted-foreground">{label}</p>;
}

function Growth({ value }: { value: unknown }) {
  const parsed = numberValue(value);
  if (parsed === null) return null;
  return <span className={cn("ml-1 text-[11px]", parsed >= 0 ? "text-red-500" : "text-emerald-500")}>{parsed >= 0 ? "同比+" : "同比"}{parsed.toFixed(2)}%</span>;
}

function newsSortValue(item: Record<string, any>): string {
  return String(item.time || item.published || "");
}

function mergeNews(current: Array<Record<string, any>>, incoming: Array<Record<string, any>>): Array<Record<string, any>> {
  const seen = new Set<string>();
  return [...current, ...incoming]
    .filter((item, index, all) => {
      const key = String(item.url || `${item.title || ""}|${newsSortValue(item)}` || index);
      if (seen.has(key)) return false;
      seen.add(key);
      return all.findIndex((candidate) => String(candidate.url || `${candidate.title || ""}|${newsSortValue(candidate)}`) === key) === index;
    })
    .sort((left, right) => newsSortValue(right).localeCompare(newsSortValue(left)));
}

function mergeDetail(
  current: StockDetailResponse | null,
  patch: Partial<StockDetailResponse>,
  symbol: string,
  period: StockDetailPeriod,
): StockDetailResponse {
  return {
    symbol: patch.symbol || current?.symbol || symbol,
    market: patch.market || current?.market || "a_share",
    period: patch.period || current?.period || period,
    profile: { ...(current?.profile || {}), ...(patch.profile || {}) },
    financials: { ...(current?.financials || {}), ...(patch.financials || {}) },
    bars: patch.bars ?? current?.bars ?? [],
    reports: patch.reports ?? current?.reports ?? [],
    news: patch.news ?? current?.news ?? [],
    news_pagination: patch.news_pagination || current?.news_pagination,
    errors: { ...(current?.errors || {}), ...(patch.errors || {}) },
    updated_at: patch.updated_at || current?.updated_at || new Date().toISOString(),
  };
}

const STOCK_PERIODS: Array<{ value: StockDetailPeriod; label: string }> = [
  { value: "1m", label: "分时" },
  { value: "1d", label: "日线" },
  { value: "1w", label: "周线" },
  { value: "1mo", label: "月线" },
  { value: "15m", label: "15分" },
  { value: "30m", label: "30分" },
  { value: "60m", label: "60分" },
  { value: "120m", label: "120分" },
];

export function StockDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { symbol: encodedSymbol } = useParams<{ symbol: string }>();
  const symbol = useMemo(() => {
    try {
      return decodeURIComponent(encodedSymbol || "");
    } catch {
      return encodedSymbol || "";
    }
  }, [encodedSymbol]);
  const [detail, setDetail] = useState<StockDetailResponse | null>(null);
  const [period, setPeriod] = useState<StockDetailPeriod>("1m");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newsItems, setNewsItems] = useState<Array<Record<string, any>>>([]);
  const [newsPage, setNewsPage] = useState(1);
  const [newsHasMore, setNewsHasMore] = useState(false);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsReloadKey, setNewsReloadKey] = useState(0);
  const [subChart, setSubChart] = useState<Sub>("vol");
  const [fundFlowRows, setFundFlowRows] = useState<StockFundFlowRow[]>([]);
  const loadToken = useRef(0);
  const fundFlowPeriod = period === "1m" ? "min" : "daily";

  const load = (initial = false, requestedPeriod: StockDetailPeriod = period) => {
    if (!symbol) return;
    const token = ++loadToken.current;
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError(null);
    setNewsReloadKey((value) => value + 1);
    const currentPeriod = detail?.symbol === symbol ? detail.period : null;
    setDetail((current) => mergeDetail(
      current?.symbol === symbol ? current : null,
      {
        symbol,
        market: /\.(SH|SZ|BJ)$/i.test(symbol) ? "a_share" : "us",
        period: requestedPeriod,
        // Do not draw a previous period's bars while the new cache request is pending.
        ...(currentPeriod !== requestedPeriod ? { bars: [] } : {}),
      },
      symbol,
      requestedPeriod,
    ));
    const tasks = [
      () => api.getStockInfo(symbol),
      () => api.getStockBars(symbol, requestedPeriod),
      () => api.getStockReports(symbol),
      () => api.getStockIndustry(symbol),
    ];
    let succeeded = false;
    const applyChunk = (chunk: any) => {
      if (token !== loadToken.current) return;
      succeeded = true;
      setDetail((current) => mergeDetail(current, {
        ...chunk,
        profile: chunk.industry !== undefined || chunk.boards !== undefined
          ? { industry: chunk.industry, boards: chunk.boards }
          : chunk.profile,
      }, symbol, requestedPeriod));
      setLoading(false);
      setRefreshing(false);
    };
    const pollSection = async (request: () => Promise<any>) => {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const chunk = await request();
        if (token !== loadToken.current) return;
        applyChunk(chunk);
        if (chunk.cache_status !== "refreshing") return;
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(1200, 150 * 2 ** attempt)));
      }
    };
    tasks.forEach((request) => {
      void pollSection(request).catch((err) => {
        if (token === loadToken.current && !succeeded) setError(err instanceof Error ? err.message : t("stockDetail.loadFailed"));
      });
    });
  };

  useEffect(() => {
    setPeriod("1m");
    load(true, "1m");
    // The route symbol is the only input for this page's data request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  useEffect(() => {
    if (!detail) return;
    const initialNews = mergeNews([], detail.news || []);
    setNewsItems(initialNews);
    setNewsPage(detail.news_pagination?.page || 1);
    setNewsHasMore(detail.news_pagination?.has_more ?? (detail.news || []).length >= 20);
    let active = true;
    setNewsLoading(true);
    void (async () => {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const page = await api.getStockNews(detail.symbol, 1, 20);
        if (!active) return;
        setNewsItems(mergeNews(initialNews, page.items || []));
        setNewsPage(page.page);
        setNewsHasMore(page.has_more);
        if (page.cache_status !== "refreshing") return;
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(1200, 150 * 2 ** attempt)));
      }
    })()
      .catch(() => {
        // Keep the detail page usable when the independent news endpoint is slow.
      })
      .finally(() => {
        if (active) setNewsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [detail?.symbol, detail?.market, newsReloadKey]);

  useEffect(() => {
    if (!detail || detail.market !== "a_share" || subChart !== "fundflow") {
      setFundFlowRows([]);
      return;
    }
    let active = true;
    void api.getStockFundFlow(detail.symbol, fundFlowPeriod, 30)
      .then(async (payload) => {
        if (!active) return;
        let result = payload.data?.[detail.symbol] || Object.values(payload.data || {})[0];
        if ((!result?.rows || result.rows.length === 0) && fundFlowPeriod === "min") {
          try {
            const dailyPayload = await api.getStockFundFlow(detail.symbol, "daily", 30);
            result = dailyPayload.data?.[detail.symbol] || Object.values(dailyPayload.data || {})[0];
          } catch {
            // Keep the empty state when both granularities are unavailable.
          }
        }
        if (active) setFundFlowRows(result?.rows || []);
      })
      .catch(() => {
        if (active) setFundFlowRows([]);
      });
    return () => {
      active = false;
    };
  }, [detail?.symbol, detail?.market, fundFlowPeriod, subChart]);

  useEffect(() => {
    if (detail?.market !== "a_share" && subChart === "fundflow") setSubChart("vol");
  }, [detail?.market, subChart]);

  const loadMoreNews = async () => {
    if (!symbol || !detail || newsLoading || !newsHasMore) return;
    setNewsLoading(true);
    try {
      const nextPage = await api.getStockNews(symbol, newsPage + 1, 20);
      setNewsItems((current) => mergeNews(current, nextPage.items || []));
      setNewsPage(nextPage.page);
      setNewsHasMore(nextPage.has_more);
    } catch {
      // Keep the first page visible when a later page is temporarily unavailable.
    } finally {
      setNewsLoading(false);
    }
  };

  if (loading) {
    return <div className="flex min-h-full items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t("stockDetail.loading")}</div>;
  }

  if (!detail || error) {
    return (
      <div className="min-h-full p-6 lg:p-8">
        <div className="mx-auto max-w-7xl">
          <button type="button" onClick={() => navigate(-1)} className="mb-6 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />{t("stockDetail.back")}</button>
          <div className="rounded-xl border border-danger/30 bg-danger/5 p-6 text-sm text-danger">{error || t("stockDetail.loadFailed")}</div>
        </div>
      </div>
    );
  }

  const profile = detail.profile || {};
  const financials = detail.financials || profile.financials || {};
  const price = numberValue(profile.price);
  const changePct = numberValue(profile.change_pct);
  const positive = (changePct || 0) >= 0;
  const name = String(profile.name || detail.symbol);
  const marketLabel = detail.market === "a_share" ? t("stockDetail.aShare") : t("stockDetail.us");
  const reports = detail.reports || [];
  const boards = Array.isArray(profile.boards) ? profile.boards : [];
  const news = newsItems;
  const metricCells = [
    { key: "peDynamic", label: t("stockDetail.peDynamic"), raw: profile.pe_ttm, value: formatNumber(profile.pe_ttm) },
    { key: "eps", label: t("stockDetail.eps"), raw: financials.eps, value: formatWithUnit(financials.eps, "元") },
    { key: "capitalReserve", label: t("stockDetail.capitalReserve"), raw: financials.capital_reserve_ps, value: formatWithUnit(financials.capital_reserve_ps, "元") },
    { key: "category", label: t("stockDetail.category"), raw: profile.category, value: profile.category },
    { key: "peStatic", label: t("stockDetail.peStatic"), raw: profile.pe_static, value: formatNumber(profile.pe_static) },
    { key: "revenue", label: t("stockDetail.revenue"), raw: financials.revenue, value: <>{formatWithUnit(financials.revenue, "元", formatMoney)} <Growth value={financials.revenue_yoy} /></> },
    { key: "retainedProfit", label: t("stockDetail.retainedProfit"), raw: financials.retained_profit_ps, value: formatWithUnit(financials.retained_profit_ps, "元") },
    { key: "totalShares", label: t("stockDetail.totalShares"), raw: profile.total_shares, value: formatWithUnit(profile.total_shares, "股", formatShares) },
    { key: "pb", label: t("stockDetail.pb"), raw: profile.pb, value: formatNumber(profile.pb) },
    { key: "netProfit", label: t("stockDetail.netProfit"), raw: financials.net_profit, value: <>{formatWithUnit(financials.net_profit, "元", formatMoney)} <Growth value={financials.net_profit_yoy} /></> },
    { key: "operatingCashflow", label: t("stockDetail.operatingCashflow"), raw: financials.operating_cashflow_ps, value: formatWithUnit(financials.operating_cashflow_ps, "元") },
    { key: "marketCap", label: t("stockDetail.marketCap"), raw: profile.mcap, value: formatWithUnit(profile.mcap, "元", formatMoney) },
    { key: "bookValue", label: t("stockDetail.bookValue"), raw: financials.bvps, value: formatWithUnit(financials.bvps, "元") },
    { key: "grossMargin", label: t("stockDetail.grossMargin"), raw: financials.gross_margin, value: formatPercent(financials.gross_margin) },
    { key: "roe", label: t("stockDetail.roe"), raw: financials.roe, value: formatPercent(financials.roe) },
    { key: "floatShares", label: t("stockDetail.floatShares"), raw: profile.float_shares, value: formatWithUnit(profile.float_shares, "股", formatShares) },
    { key: "industry", label: t("stockDetail.industry"), raw: profile.industry, value: profile.industry },
    { key: "updatedDate", label: t("stockDetail.updatedDate"), raw: financials.period || detail.updated_at, value: formatDate(financials.period || detail.updated_at) },
  ].filter((cell) => hasMetricValue(cell.raw));

  return (
    <div className="min-h-full p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 border-b border-border/60 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <button type="button" onClick={() => navigate(-1)} className="mb-3 inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />{t("stockDetail.back")}</button>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">{name}</h1>
              <span className="rounded-full bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">{detail.symbol}</span>
              <span className="rounded-full bg-primary/10 px-2 py-1 text-xs text-primary">{marketLabel}</span>
            </div>
          </div>
          <button type="button" onClick={() => void load(false)} disabled={refreshing} className="inline-flex items-center gap-2 self-start rounded-md border border-border/60 px-3 py-2 text-xs font-medium transition hover:bg-muted/60 disabled:opacity-50 sm:self-auto"><RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />{t("stockDetail.refresh")}</button>
        </header>

        <section className="space-y-3" aria-labelledby="stock-profile-heading">
          <h2 id="stock-profile-heading" className="text-sm font-semibold tracking-wide">{t("stockDetail.profile")}</h2>
          <div className="overflow-hidden rounded-xl border border-border/60 bg-card">
            <div className="grid gap-4 border-b border-border/60 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div>
                <p className="text-xs text-muted-foreground">{t("stockDetail.latestPrice")}</p>
                <p className="mt-1 font-mono text-2xl font-semibold">{formatNumber(price)}</p>
              </div>
              <p className={cn("inline-flex items-center gap-1 font-mono text-sm", positive ? "text-red-500" : "text-emerald-500")}>
                {positive ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                {changePct === null ? "—" : `${positive ? "+" : ""}${changePct.toFixed(2)}%`}
              </p>
            </div>
            <div className="grid sm:grid-cols-2 xl:grid-cols-4">
              {metricCells.map((cell) => <MetricCell key={cell.key} label={cell.label} value={cell.value} />)}
            </div>
            {boards.length > 0 && (
              <div className="border-t border-border/60 px-4 py-3">
                <p className="text-[11px] text-muted-foreground">{t("stockDetail.boards")}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {boards.map((board: Record<string, any>, index: number) => {
                    const label = String(board.board_name || board.name || "").trim();
                    if (!label) return null;
                    return <span key={`${String(board.board_code || label)}-${index}`} className="rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary">{label}</span>;
                  })}
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="space-y-3" aria-labelledby="stock-chart-heading">
          <h2 id="stock-chart-heading" className="text-sm font-semibold tracking-wide">{t("stockDetail.kline")}</h2>
          <div className="rounded-xl border border-border/60 bg-card p-3 sm:p-4">
            <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-border/60 pb-3">
              {STOCK_PERIODS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  aria-pressed={period === item.value}
                  disabled={refreshing}
                  onClick={() => {
                    if (period === item.value) return;
                    setPeriod(item.value);
                    void load(false, item.value);
                  }}
                  className={cn(
                    "rounded border px-2.5 py-1 text-xs transition-colors disabled:cursor-wait disabled:opacity-60",
                    period === item.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border/60 text-muted-foreground hover:border-primary/50 hover:text-foreground",
                  )}
                >
                  {item.label}
                </button>
              ))}
              {refreshing && <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-muted-foreground" />}
            </div>
            <CandlestickChart
              data={detail.bars}
              height={520}
              intraday={period === "1m"}
              previousClose={numberValue(profile.last_close)}
              market={detail.market}
              symbol={detail.symbol}
              fundFlowRows={fundFlowRows}
              sub={subChart}
              onSubChange={setSubChart}
              availableSubs={detail.market === "a_share" ? undefined : (["vol", "amount", "macd", "macdfs", "rsi", "kdj", "boll", "expma"] as Sub[])}
            />
          </div>
        </section>

        <section className="grid gap-5 lg:grid-cols-2" aria-label={t("stockDetail.researchAndNews")}>
          <FeedCard title={t("stockDetail.reports")} emptyLabel={t("stockDetail.noReports")} isEmpty={reports.length === 0}>
            {reports.map((report, index) => <FeedItem key={`${String(report.iwencai_id || report.infoCode || report.title || index)}`} title={String(report.title || t("stockDetail.untitled"))} meta={[report.orgSName, formatDate(report.publishDate)].filter(Boolean).join(" · ")} href={report.url ? String(report.url) : report.infoCode ? `https://pdf.dfcfw.com/pdf/H3_${report.infoCode}_1.pdf` : undefined} />)}
          </FeedCard>
          <FeedCard title={t("stockDetail.news")} emptyLabel={t("stockDetail.noNews")} isEmpty={newsItems.length === 0 && !newsLoading} onScroll={(event) => {
              const target = event.currentTarget;
              if (target.scrollHeight - target.scrollTop - target.clientHeight < 80) void loadMoreNews();
            }}>
            {news.map((item, index) => <FeedItem key={`${String(item.url || item.title || index)}`} title={String(item.title || t("stockDetail.untitled"))} meta={[item.source, formatDate(item.time || item.published)].filter(Boolean).join(" · ")} snippet={String(item.content || item.snippet || "")} href={item.url ? String(item.url) : undefined} />)}
              {newsLoading && <p className="py-3 text-center text-xs text-muted-foreground"><Loader2 className="mr-1 inline h-3 w-3 animate-spin" />{t("stockDetail.newsLoading")}</p>}
          </FeedCard>
        </section>
      </div>
    </div>
  );
}

function MetricCell({ label, value }: { label: string; value: ReactNode }) {
  return <div className="min-w-0 border-b border-r border-border/60 px-3 py-2.5 last:border-b-0 sm:px-4"><p className="truncate text-[11px] text-muted-foreground">{label}</p><p className="mt-1 truncate font-mono text-sm font-semibold">{value}</p></div>;
}

function FeedCard({ title, emptyLabel, isEmpty, children, onScroll }: { title: string; emptyLabel: string; isEmpty: boolean; children: ReactNode; onScroll?: UIEventHandler<HTMLDivElement> }) {
  return <div className="flex h-[520px] min-h-0 flex-col rounded-xl border border-border/60 bg-card p-4"><h2 className="shrink-0 text-sm font-semibold">{title}</h2><div className="mt-3 min-h-0 flex-1 overflow-y-auto divide-y divide-border/60" onScroll={onScroll}>{isEmpty ? <FeedEmpty label={emptyLabel} /> : children}</div></div>;
}

function FeedItem({ title, meta, snippet, href }: { title: string; meta: string; snippet?: string; href?: string }) {
  const content = <div className="min-w-0 flex-1"><p className="line-clamp-2 text-sm font-medium">{title}</p>{meta && <p className="mt-1 text-[11px] text-muted-foreground">{meta}</p>}{snippet && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{snippet}</p>}</div>;
  return <article className="py-3 first:pt-0 last:pb-0">{href ? <a href={href} target="_blank" rel="noreferrer" aria-label={`${title} - original`} className="group flex items-start justify-between gap-3 transition hover:text-primary">{content}<span className="mt-0.5 shrink-0 rounded p-1 text-muted-foreground transition group-hover:bg-primary/10 group-hover:text-primary"><ExternalLink className="h-3.5 w-3.5" /></span></a> : content}</article>;
}
