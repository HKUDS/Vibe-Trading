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

const INTRADAY_PERIODS = new Set<StockDetailPeriod>(["1m", "15m", "30m", "60m", "120m"]);
const INTRADAY_REFRESH_MS = 15_000;

function isStockMarketOpen(symbol: string): boolean {
  const market = /\.(SH|SZ|BJ)$/i.test(symbol) ? "a_share" : "us";
  const timeZone = market === "a_share" ? "Asia/Shanghai" : "America/New_York";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const value = (type: string) => parts.find((part) => part.type === type)?.value || "";
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(value("weekday"));
  if (weekday === 0 || weekday === 6) return false;
  const minutes = Number(value("hour")) * 60 + Number(value("minute"));
  return market === "a_share"
    ? (minutes >= 570 && minutes < 690) || (minutes >= 780 && minutes < 900)
    : minutes >= 570 && minutes < 960;
}

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
  const [error, setError] = useState<string | null>(null);
  const [baseReady, setBaseReady] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [industryLoading, setIndustryLoading] = useState(false);
  const [barsLoading, setBarsLoading] = useState(false);
  const [newsItems, setNewsItems] = useState<Array<Record<string, any>>>([]);
  const [newsPage, setNewsPage] = useState(1);
  const [newsHasMore, setNewsHasMore] = useState(false);
  const [newsLoading, setNewsLoading] = useState(false);
  const [reportItems, setReportItems] = useState<Array<Record<string, any>>>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [subChart, setSubChart] = useState<Sub>("vol");
  const [fundFlowRows, setFundFlowRows] = useState<StockFundFlowRow[]>([]);
  const routeToken = useRef(0);
  const profileRequestToken = useRef(0);
  const industryRequestToken = useRef(0);
  const barsRequestToken = useRef(0);
  const newsRequestToken = useRef(0);
  const reportsRequestToken = useRef(0);
  const fundFlowPeriod = period === "1m" ? "min" : "daily";

  const loadInfo = async (initial = false) => {
    if (!symbol) return;
    const route = routeToken.current;
    const request = ++profileRequestToken.current;
    setProfileLoading(true);
    try {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const response = await api.getStockInfo(symbol);
        if (route !== routeToken.current || request !== profileRequestToken.current) return;
        setDetail((current) => mergeDetail(current, response, symbol, current?.period || period));
        if (initial) setLoading(false);
        if (response.cache_status !== "refreshing") return;
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(1200, 150 * 2 ** attempt)));
      }
    } catch (err) {
      if (route === routeToken.current && initial) setError(err instanceof Error ? err.message : t("stockDetail.loadFailed"));
    } finally {
      if (route === routeToken.current && request === profileRequestToken.current) setProfileLoading(false);
    }
  };

  const loadIndustry = async () => {
    if (!symbol) return;
    const route = routeToken.current;
    const request = ++industryRequestToken.current;
    setIndustryLoading(true);
    try {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const response = await api.getStockIndustry(symbol);
        if (route !== routeToken.current || request !== industryRequestToken.current) return;
        setDetail((current) => mergeDetail(current, {
          ...response,
          profile: { industry: response.industry, boards: response.boards },
        }, symbol, current?.period || period));
        if (response.cache_status !== "refreshing") return;
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(1200, 150 * 2 ** attempt)));
      }
    } catch {
      // Keep the basic profile visible when the industry endpoint is unavailable.
    } finally {
      if (route === routeToken.current && request === industryRequestToken.current) setIndustryLoading(false);
    }
  };

  const loadBars = async (requestedPeriod: StockDetailPeriod, initial = false) => {
    if (!symbol) return;
    const route = routeToken.current;
    const request = ++barsRequestToken.current;
    setBarsLoading(true);
    const currentPeriod = detail?.symbol === symbol ? detail.period : null;
    setDetail((current) => mergeDetail(
      current?.symbol === symbol ? current : null,
      {
        symbol,
        market: /\.(SH|SZ|BJ)$/i.test(symbol) ? "a_share" : "us",
        period: requestedPeriod,
        ...(currentPeriod !== requestedPeriod ? { bars: [] } : {}),
      },
      symbol,
      requestedPeriod,
    ));

    try {
      // One user action maps to one bars request. If the backend is still
      // refreshing asynchronously, the next scheduled market-time refresh
      // will pick up the completed cache instead of polling this endpoint.
      const response = await api.getStockBars(symbol, requestedPeriod);
      if (route !== routeToken.current || request !== barsRequestToken.current) return;
      setDetail((current) => mergeDetail(current, response, symbol, requestedPeriod));
      if (initial) setLoading(false);
    } catch (err) {
      if (route === routeToken.current && initial) setError(err instanceof Error ? err.message : t("stockDetail.loadFailed"));
    } finally {
      if (route === routeToken.current && request === barsRequestToken.current) setBarsLoading(false);
    }
  };

  useEffect(() => {
    const route = ++routeToken.current;
    setPeriod("1m");
    setLoading(true);
    setBaseReady(false);
    setError(null);
    setDetail((current) => mergeDetail(
      current?.symbol === symbol ? current : null,
      {
        symbol,
        market: /\.(SH|SZ|BJ)$/i.test(symbol) ? "a_share" : "us",
        period: "1m",
        bars: [],
      },
      symbol,
      "1m",
    ));
    void (async () => {
      await loadInfo(true);
      await loadBars("1m", true);
      await loadIndustry();
      if (route === routeToken.current) setBaseReady(true);
    })();
    return () => {
      if (route === routeToken.current) routeToken.current += 1;
    };
    // The route symbol is the only input for this page's data request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  useEffect(() => {
    if (!symbol || !INTRADAY_PERIODS.has(period)) return;
    let active = true;
    let inFlight = false;
    const refreshIntraday = async () => {
      if (!active || inFlight || !isStockMarketOpen(symbol)) return;
      inFlight = true;
      try {
        await loadBars(period);
      } catch {
        // Keep the last persisted candle and quote visible on transient errors.
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => {
      void refreshIntraday();
    }, INTRADAY_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol, period]);

  const loadNews = async (seed: Array<Record<string, any>> = newsItems) => {
    if (!symbol) return;
    const route = routeToken.current;
    const request = ++newsRequestToken.current;
    setNewsLoading(true);
    try {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const page = await api.getStockNews(symbol, 1, 20);
        if (route !== routeToken.current || request !== newsRequestToken.current) return;
        setNewsItems(mergeNews(seed, page.items || []));
        setNewsPage(page.page);
        setNewsHasMore(page.has_more);
        if (page.cache_status !== "refreshing") return;
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(1200, 150 * 2 ** attempt)));
      }
    } catch {
      // Keep the detail page usable when the independent news endpoint is slow.
    } finally {
      if (route === routeToken.current && request === newsRequestToken.current) setNewsLoading(false);
    }
  };

  const loadReports = async () => {
    if (!symbol) return;
    const route = routeToken.current;
    const request = ++reportsRequestToken.current;
    setReportsLoading(true);
    try {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        const response = await api.getStockReports(symbol);
        if (route !== routeToken.current || request !== reportsRequestToken.current) return;
        setReportItems(response.reports || []);
        if (response.cache_status !== "refreshing") return;
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(1200, 150 * 2 ** attempt)));
      }
    } catch {
      // Keep the last persisted reports visible when the endpoint is slow.
    } finally {
      if (route === routeToken.current && request === reportsRequestToken.current) setReportsLoading(false);
    }
  };

  useEffect(() => {
    if (!detail || !baseReady) return;
    const initialNews = mergeNews([], detail.news || []);
    setNewsItems(initialNews);
    setNewsPage(detail.news_pagination?.page || 1);
    setNewsHasMore(detail.news_pagination?.has_more ?? (detail.news || []).length >= 20);
    void loadNews(initialNews);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, detail?.market, baseReady]);

  useEffect(() => {
    if (!detail || !baseReady) return;
    setReportItems(detail.reports || []);
    void loadReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, detail?.market, baseReady]);

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
  const reports = reportItems;
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
        </header>

        <section className="space-y-3" aria-labelledby="stock-profile-heading">
          <div className="flex items-center justify-between gap-3">
            <h2 id="stock-profile-heading" className="text-sm font-semibold tracking-wide">{t("stockDetail.profile")}</h2>
            <RefreshButton testId="refresh-profile" label={`${t("stockDetail.profile")} ${t("stockDetail.refresh")}`} loading={profileLoading} onClick={() => void loadInfo()} />
          </div>
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
            <div className="border-t border-border/60 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-muted-foreground">{t("stockDetail.boards")}</p>
                <RefreshButton testId="refresh-industry" label={`${t("stockDetail.boards")} ${t("stockDetail.refresh")}`} loading={industryLoading} onClick={() => void loadIndustry()} />
              </div>
              {boards.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {boards.map((board: Record<string, any>, index: number) => {
                    const label = String(board.board_name || board.name || "").trim();
                    if (!label) return null;
                    return <span key={`${String(board.board_code || label)}-${index}`} className="rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary">{label}</span>;
                  })}
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="space-y-3" aria-labelledby="stock-chart-heading">
          <div className="flex items-center justify-between gap-3">
            <h2 id="stock-chart-heading" className="text-sm font-semibold tracking-wide">{t("stockDetail.kline")}</h2>
            <RefreshButton testId="refresh-bars" label={`${t("stockDetail.kline")} ${t("stockDetail.refresh")}`} loading={barsLoading} onClick={() => void loadBars(period)} />
          </div>
          <div className="rounded-xl border border-border/60 bg-card p-3 sm:p-4">
            <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-border/60 pb-3">
              {STOCK_PERIODS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  aria-pressed={period === item.value}
                  disabled={barsLoading}
                  onClick={() => {
                    if (period === item.value) return;
                    setPeriod(item.value);
                    loadBars(item.value);
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
              {barsLoading && <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-muted-foreground" />}
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
          <FeedCard
            title={t("stockDetail.reports")}
            emptyLabel={t("stockDetail.noReports")}
            isEmpty={reports.length === 0}
            onRefresh={() => void loadReports()}
            refreshing={reportsLoading}
            refreshLabel={t("stockDetail.refresh")}
            refreshTestId="refresh-reports"
          >
            {reports.map((report, index) => <FeedItem key={`${String(report.iwencai_id || report.infoCode || report.title || index)}`} title={String(report.title || t("stockDetail.untitled"))} meta={[report.orgSName, formatDate(report.publishDate)].filter(Boolean).join(" · ")} href={report.url ? String(report.url) : report.infoCode ? `https://pdf.dfcfw.com/pdf/H3_${report.infoCode}_1.pdf` : undefined} />)}
          </FeedCard>
          <FeedCard
            title={t("stockDetail.news")}
            emptyLabel={t("stockDetail.noNews")}
            isEmpty={newsItems.length === 0 && !newsLoading}
            onRefresh={() => void loadNews()}
            refreshing={newsLoading}
            refreshLabel={t("stockDetail.refresh")}
            refreshTestId="refresh-news"
            onScroll={(event) => {
              const target = event.currentTarget;
              if (target.scrollHeight - target.scrollTop - target.clientHeight < 80) void loadMoreNews();
            }}
          >
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

function RefreshButton({ testId, label, loading, onClick }: { testId: string; label: string; loading: boolean; onClick: () => void }) {
  return <button type="button" data-testid={testId} aria-label={label} onClick={onClick} disabled={loading} className="rounded p-1 text-muted-foreground transition hover:bg-muted/60 hover:text-foreground disabled:opacity-50" title={label}><RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /></button>;
}

function FeedCard({ title, emptyLabel, isEmpty, children, onScroll, onRefresh, refreshing, refreshLabel, refreshTestId }: { title: string; emptyLabel: string; isEmpty: boolean; children: ReactNode; onScroll?: UIEventHandler<HTMLDivElement>; onRefresh?: () => void; refreshing?: boolean; refreshLabel?: string; refreshTestId?: string }) {
  return <div className="flex h-[520px] min-h-0 flex-col rounded-xl border border-border/60 bg-card p-4"><div className="flex shrink-0 items-center justify-between gap-3"><h2 className="text-sm font-semibold">{title}</h2>{onRefresh && <button type="button" data-testid={refreshTestId} aria-label={`${title} ${refreshLabel || "refresh"}`} onClick={onRefresh} disabled={refreshing} className="rounded p-1 text-muted-foreground transition hover:bg-muted/60 hover:text-foreground disabled:opacity-50" title={refreshLabel}><RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /></button>}</div><div className="mt-3 min-h-0 flex-1 overflow-y-auto divide-y divide-border/60" onScroll={onScroll}>{isEmpty ? <FeedEmpty label={emptyLabel} /> : children}</div></div>;
}

function FeedItem({ title, meta, snippet, href }: { title: string; meta: string; snippet?: string; href?: string }) {
  const content = <div className="min-w-0 flex-1"><p className="line-clamp-2 text-sm font-medium">{title}</p>{meta && <p className="mt-1 text-[11px] text-muted-foreground">{meta}</p>}{snippet && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{snippet}</p>}</div>;
  return <article className="py-3 first:pt-0 last:pb-0">{href ? <a href={href} target="_blank" rel="noreferrer" aria-label={`${title} - original`} className="group flex items-start justify-between gap-3 transition hover:text-primary">{content}<span className="mt-0.5 shrink-0 rounded p-1 text-muted-foreground transition group-hover:bg-primary/10 group-hover:text-primary"><ExternalLink className="h-3.5 w-3.5" /></span></a> : content}</article>;
}
