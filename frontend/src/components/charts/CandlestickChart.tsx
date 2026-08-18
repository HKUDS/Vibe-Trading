import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import i18n from "@/i18n";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";
import type { PriceBar, TradeMarker, IndicatorPoint, StockFundFlowRow, ChanTrainingAnalysis } from "@/lib/api";
import { calcMA, calcBOLL, calcMACD, calcMACDFS, calcRSI, calcKDJ, calcEMA, calcIntradayAverage } from "@/lib/indicators";
import { getChartTheme } from "@/lib/chart-theme";
import { abbreviateNum } from "@/lib/formatters";
import { echarts, CHART_GROUP, connectCharts } from "@/lib/echarts";
import { escapeHtml } from "@/lib/escapeHtml";
import { useThemeDark } from "@/lib/theme-store";

export type Sub = "fundflow" | "vol" | "amount" | "macd" | "macdfs" | "rsi" | "kdj" | "boll" | "expma";
type Range = "1M" | "3M" | "6M" | "1Y" | "ALL";
type Overlay = "ma5" | "ma10" | "ma20" | "ma60" | "ema12" | "ema26" | "boll";

export function getSubChartAxisBounds(sub: Sub) {
  return sub === "rsi" ? { min: 0, max: 100 } : { min: null, max: null };
}

const SUB_OPTIONS: Array<readonly [Sub, string]> = [
  ["fundflow", "资金流"],
  ["vol", "成交量"],
  ["amount", "成交额"],
  ["macd", "MACD"],
  ["macdfs", "MACDFS"],
  ["rsi", "RSI"],
  ["kdj", "KDJ"],
  ["boll", "BOLL"],
  ["expma", "EXPMA"],
];

const OVERLAY_OPTIONS: { id: Overlay; label: string; group: string }[] = [
  { id: "ma5", label: "MA5", group: "MA" },
  { id: "ma10", label: "MA10", group: "MA" },
  { id: "ma20", label: "MA20", group: "MA" },
  { id: "ma60", label: "MA60", group: "MA" },
  { id: "ema12", label: "EMA12", group: "MA" },
  { id: "ema26", label: "EMA26", group: "MA" },
  { id: "boll", label: "BOLL", group: "Channel" },
];

const RANGE_BARS: Record<Range, number> = { "1M": 22, "3M": 63, "6M": 126, "1Y": 252, ALL: Infinity };
const OVERLAY_COLORS = ["#f59e0b", "#8b5cf6", "#3b82f6", "#ec4899", "#10b981", "#f97316", "#6366f1"];
const CHART_GRID_LEFT = 56;
const CHART_GRID_RIGHT = 16;

export function getChartGridLayout(intraday: boolean) {
  void intraday;
  return [
    { left: CHART_GRID_LEFT, right: CHART_GRID_RIGHT, top: 36, height: "55%", containLabel: false },
    { left: CHART_GRID_LEFT, right: CHART_GRID_RIGHT, top: "66%", height: "22%", containLabel: false },
  ];
}

export function resetChartDataZoom(
  chart: { dispatchAction: (action: { type: "dataZoom"; dataZoomIndex: number; startValue: number; endValue: number }) => void },
  dataLength: number,
) {
  const endValue = Math.max(0, dataLength - 1);
  for (const dataZoomIndex of [0, 1]) {
    chart.dispatchAction({ type: "dataZoom", dataZoomIndex, startValue: 0, endValue });
  }
}

export type ChartDataZoomRange = { start: number; end: number };

export function getInitialChartDataZoomRange(dataLength: number, range: "1M" | "3M" | "6M" | "1Y" | "ALL"): ChartDataZoomRange {
  const maxIndex = Math.max(0, dataLength - 1);
  const maxBars = RANGE_BARS[range];
  const start = maxBars >= dataLength ? 0 : Math.max(0, dataLength - maxBars);
  return { start, end: maxIndex };
}

/** Move the visible range by one small, cursor-anchored wheel step. */
export function buildChartDataZoomStep(
  range: ChartDataZoomRange,
  dataLength: number,
  deltaY: number,
  anchorIndex?: number,
): ChartDataZoomRange {
  const maxIndex = Math.max(0, dataLength - 1);
  if (maxIndex <= 1) return { start: 0, end: maxIndex };

  const start = Math.max(0, Math.min(maxIndex, Math.round(range.start)));
  const end = Math.max(start, Math.min(maxIndex, Math.round(range.end)));
  const currentSpan = Math.max(1, end - start);
  const fullSpan = maxIndex;
  const minSpan = Math.min(5, fullSpan);
  const zoomIn = deltaY < 0;
  const step = Math.max(1, Math.ceil(currentSpan * 0.12));
  const targetSpan = zoomIn
    ? Math.max(minSpan, currentSpan - step)
    : Math.min(fullSpan, currentSpan + step);
  const safeAnchor = Math.max(start, Math.min(end, Math.round(anchorIndex ?? (start + end) / 2)));
  const anchorRatio = currentSpan > 0 ? (safeAnchor - start) / currentSpan : 0.5;

  let nextStart = Math.round(safeAnchor - anchorRatio * targetSpan);
  let nextEnd = nextStart + targetSpan;
  if (nextStart < 0) {
    nextEnd -= nextStart;
    nextStart = 0;
  }
  if (nextEnd > maxIndex) {
    nextStart -= nextEnd - maxIndex;
    nextEnd = maxIndex;
  }
  return {
    start: Math.max(0, nextStart),
    end: Math.min(maxIndex, nextEnd),
  };
}

function readChartDataZoomRange(
  chart: { getOption: () => unknown },
  dataLength: number,
): ChartDataZoomRange {
  const maxIndex = Math.max(0, dataLength - 1);
  const option = chart.getOption() as {
    dataZoom?: Array<{ start?: number; end?: number; startValue?: number; endValue?: number }>;
  };
  const current = option.dataZoom?.[0] ?? {};
  const rawStartValue = Number(current.startValue);
  const rawEndValue = Number(current.endValue);
  const rawStartPercent = Number(current.start);
  const rawEndPercent = Number(current.end);
  const start = Number.isFinite(rawStartValue)
    ? rawStartValue
    : Number.isFinite(rawStartPercent)
      ? (rawStartPercent / 100) * maxIndex
      : 0;
  const end = Number.isFinite(rawEndValue)
    ? rawEndValue
    : Number.isFinite(rawEndPercent)
      ? (rawEndPercent / 100) * maxIndex
      : maxIndex;
  return {
    start: Math.round(Math.max(0, Math.min(maxIndex, start))),
    end: Math.round(Math.max(0, Math.min(maxIndex, end))),
  };
}

export function getStablePriceAxisBounds(highs: number[], lows: number[]) {
  const values = [...highs, ...lows].map(Number).filter((value) => Number.isFinite(value));
  if (values.length === 0) return {};
  const low = Math.min(...values);
  const high = Math.max(...values);
  const padding = Math.max((high - low) * 0.05, Math.abs(high || low) * 0.001, 0.01);
  return { min: low - padding, max: high + padding };
}

export function getPriceAxisBoundsForRange(data: Pick<PriceBar, "high" | "low">[], start: number, end: number) {
  const first = Math.max(0, Math.min(data.length - 1, Math.round(start)));
  const last = Math.max(first, Math.min(data.length - 1, Math.round(end)));
  const visible = data.slice(first, last + 1);
  return getStablePriceAxisBounds(
    visible.map((bar) => bar.high),
    visible.map((bar) => bar.low),
  );
}

export function formatPriceAxisLabel(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : String(value);
}

export type ChartDragMode = "pan" | "zoom";

export function getChartDragMode(event: Pick<MouseEvent, "button" | "ctrlKey">): ChartDragMode | null {
  if (event.button !== 0) return null;
  return event.ctrlKey ? "zoom" : "pan";
}

export function canStartChartDrag(event: Pick<MouseEvent, "button" | "ctrlKey">) {
  return getChartDragMode(event) !== null;
}

export function buildChartPanRange(range: ChartDataZoomRange, dataLength: number, deltaIndex: number): ChartDataZoomRange {
  const maxIndex = Math.max(0, dataLength - 1);
  const span = Math.max(0, Math.round(range.end) - Math.round(range.start));
  let start = Math.round(range.start) + Math.round(deltaIndex);
  let end = start + span;
  if (start < 0) {
    end -= start;
    start = 0;
  }
  if (end > maxIndex) {
    start -= end - maxIndex;
    end = maxIndex;
  }
  return {
    start: Math.max(0, start),
    end: Math.max(0, Math.min(maxIndex, end)),
  };
}

export function getChartPanDelta(startX: number, currentX: number, pixelsPerIndex: number) {
  if (!Number.isFinite(startX) || !Number.isFinite(currentX) || !Number.isFinite(pixelsPerIndex) || pixelsPerIndex <= 0) return 0;
  return Math.round((startX - currentX) / pixelsPerIndex);
}

export function getChanFractalMarkerStyle(kind: "top" | "bottom", upColor: string, downColor: string) {
  const isTop = kind === "top";
  return {
    symbolRotate: isTop ? 180 : 0,
    symbolOffset: [0, isTop ? -13 : 13] as [number, number],
    color: isTop ? upColor : downColor,
  };
}

export function getChanAnalysisRenderKey(analysis: ChanTrainingAnalysis | null | undefined) {
  if (!analysis) return "none";
  const encode = (items: unknown[]) => JSON.stringify(items);
  return JSON.stringify({
    fractals: encode(analysis.fractals.map((item) => [item.kind, item.bar_index, item.confirmed_index, item.price])),
    strokes: encode(analysis.strokes.map((item) => [item.start_index, item.end_index, item.start_price, item.end_price, item.direction, item.confirmed_index])),
    segments: encode(analysis.segments.map((item) => [item.start_index, item.end_index, item.start_price, item.end_price, item.direction, item.confirmed_index])),
    centers: encode(analysis.centers.map((item) => [item.start_index, item.end_index, item.low, item.high, item.confirmed_index])),
    signals: encode(analysis.signals.map((item) => [item.label, item.side, item.bar_index, item.price, item.confirmed_index])),
  });
}

export function ChanTheoryGuide() {
  const [expanded, setExpanded] = useState(false);
  const items = [
    { symbol: "▼", className: "text-red-500", title: "顶分型", description: "局部高点结构，图中用向下的三角标识。" },
    { symbol: "▲", className: "text-emerald-500", title: "底分型", description: "局部低点结构，图中用向上的三角标识。" },
    { symbol: "╱", className: "text-sky-500", title: "笔", description: "蓝色细虚线，连接相邻有效顶、底分型。" },
    { symbol: "━", className: "text-amber-500", title: "线段", description: "橙色粗实线，由多笔组成的更高一级结构。" },
    { symbol: "▰", className: "text-sky-500", title: "中枢 / 区间", description: "蓝色半透明区域，表示多段走势的重叠价格区间。" },
    { symbol: "B/S", className: "text-primary", title: "交易标记", description: "B表示买入，S表示卖出，均按当前K线收盘价成交。" },
  ];
  return (
    <aside className="mb-3 rounded-xl border border-border/70 bg-card p-3 text-xs">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 text-left"
      >
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="text-sm font-semibold">缠论图例说明</h3>
          <span className="leading-5 text-muted-foreground">图中颜色和符号对应的缠论结构</span>
        </span>
        <span className="text-muted-foreground">{expanded ? "收起" : "展开"}</span>
      </button>
      {expanded && <>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {items.map((item) => (
          <div key={item.title} className="flex items-start gap-3">
            <span className={cn("flex h-6 min-w-8 items-center justify-center rounded border border-border/60 bg-muted/20 font-mono text-base font-semibold", item.className)}>{item.symbol}</span>
            <div className="min-w-0">
              <p className="font-medium">{item.title}</p>
              <p className="mt-0.5 leading-5 text-muted-foreground">{item.description}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-border/60 pt-2 leading-5 text-muted-foreground">
        训练模式只展示当前已揭示的 K 线和结构，不使用未来数据。
      </div>
      </>}
    </aside>
  );
}

export function buildChartDataUpdate(
  chartDates: string[],
  series: Array<{ name: string; data: unknown; [key: string]: unknown }>,
) {
  return {
    xAxis: [{ data: chartDates }, { data: chartDates }],
    series: series.map(({ name, data }) => ({ name, data })),
  };
}

type DisposableChart = {
  dispose: () => void;
  isDisposed?: () => boolean;
};

/** ECharts v6 can throw while disposing an unrendered dataZoom view. */
export function disposeChartSafely(chart: DisposableChart | null | undefined) {
  if (!chart || chart.isDisposed?.()) return;
  try {
    chart.dispose();
  } catch {
    // Teardown must not turn a route change into an application error.
  }
}

interface Props {
  data: PriceBar[];
  calculationData?: PriceBar[];
  calculationOffset?: number;
  initialStartIndex?: number;
  initialEndIndex?: number;
  viewportStartIndex?: number;
  viewportEndIndex?: number;
  markers?: TradeMarker[];
  indicators?: Record<string, IndicatorPoint[]>;
  height?: number;
  intraday?: boolean;
  previousClose?: number | null;
  market?: "a_share" | "us";
  symbol?: string;
  fundFlowRows?: StockFundFlowRow[];
  sub?: Sub;
  onSubChange?: (sub: Sub) => void;
  availableSubs?: Sub[];
  chanAnalysis?: ChanTrainingAnalysis | null;
  showChan?: boolean;
}

interface IntradayAxisData {
  categories: string[];
  categoryKeys: string[];
  dataKeys: string[];
  prices: Array<number | null>;
  averages: Array<number | null>;
  guideIndexes: number[];
  labelIndexes: number[];
}

function shanghaiMinute(value: unknown): number | null {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
}

function formatShanghaiMinute(value: number): string {
  const date = new Date(value);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

function clockLabel(value: number): string {
  return formatShanghaiMinute(value).slice(11, 16);
}

function intradayDataKey(value: unknown, market: "a_share" | "us"): string | null {
  const timestamp = shanghaiMinute(value);
  if (timestamp === null) return null;
  const formatted = formatShanghaiMinute(timestamp);
  if (market === "a_share") {
    const time = formatted.slice(11, 16);
    return time === "11:30" || time === "13:00" ? "break" : time;
  }
  return formatted;
}

function mapIntradayValues(values: Array<number | null>, axis: IntradayAxisData): Array<number | null> {
  const byKey = new Map<string, number | null>();
  axis.dataKeys.forEach((key, index) => {
    const value = values[index];
    if (value !== null && value !== undefined) byKey.set(key, value);
  });
  return axis.categoryKeys.map((key) => byKey.get(key) ?? null);
}

function mapIntradayObjects<T>(values: T[], axis: IntradayAxisData): Array<T | null> {
  const byKey = new Map<string, T>();
  axis.dataKeys.forEach((key, index) => {
    const value = values[index];
    if (value !== undefined) byKey.set(key, value);
  });
  return axis.categoryKeys.map((key) => byKey.get(key) ?? null);
}

interface FundFlowSeries {
  main: Array<number | null>;
  superLarge: Array<number | null>;
  large: Array<number | null>;
  medium: Array<number | null>;
  small: Array<number | null>;
  histogram: Array<number | null>;
}

function fundFlowKey(value: unknown, market: "a_share" | "us", intraday: boolean): string | null {
  if (!intraday) return String(value || "").slice(0, 10) || null;
  return intradayDataKey(value, market) ?? (String(value || "").slice(0, 16) || null);
}

function hasIntradayTime(value: unknown): boolean {
  return /(?:[T ]|^)\d{1,2}:\d{2}/.test(String(value || ""));
}

export function buildFundFlowSeries(
  rows: StockFundFlowRow[],
  chartDates: string[],
  chartKeys: string[],
  market: "a_share" | "us",
  intraday: boolean,
): FundFlowSeries {
  const byKey = new Map<string, { main: number; superLarge: number; large: number; medium: number; small: number; histogram: number }>();
  let main = 0;
  let superLarge = 0;
  let large = 0;
  let medium = 0;
  let small = 0;
  const finiteOrZero = (value: number | null | undefined) =>
    typeof value === "number" && Number.isFinite(value) ? value : 0;
  const sortedRows = [...rows]
    .filter((row) => !intraday || hasIntradayTime(row.timestamp) || rows.every((candidate) => !hasIntradayTime(candidate.timestamp)))
    .sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
  sortedRows.forEach((row) => {
    const key = fundFlowKey(row.timestamp, market, intraday);
    if (!key) return;
    main += finiteOrZero(row.main);
    superLarge += finiteOrZero(row.super_large);
    large += finiteOrZero(row.large);
    medium += finiteOrZero(row.medium);
    small += finiteOrZero(row.small);
    byKey.set(key, { main, superLarge, large, medium, small, histogram: finiteOrZero(row.main) });
  });
  const keys = chartDates.map((date, index) => chartKeys[index] ?? fundFlowKey(date, market, intraday) ?? date);
  const latest = sortedRows.length > 0 ? byKey.get(fundFlowKey(sortedRows[sortedRows.length - 1].timestamp, market, intraday) || "") : undefined;
  if (intraday && latest && sortedRows.every((row) => !hasIntradayTime(row.timestamp))) {
    return {
      main: keys.map(() => latest.main),
      superLarge: keys.map(() => latest.superLarge),
      large: keys.map(() => latest.large),
      medium: keys.map(() => latest.medium),
      small: keys.map(() => latest.small),
      histogram: keys.map((_, index) => index === keys.length - 1 ? latest.histogram : null),
    };
  }
  const values = keys.map((key) => byKey.get(key));
  return {
    main: values.map((value) => value?.main ?? null),
    superLarge: values.map((value) => value?.superLarge ?? null),
    large: values.map((value) => value?.large ?? null),
    medium: values.map((value) => value?.medium ?? null),
    small: values.map((value) => value?.small ?? null),
    histogram: values.map((value) => value?.histogram ?? null),
  };
}

function aShareLimitRate(symbol?: string): number {
  const code = String(symbol || "").replace(/\D/g, "").slice(-6);
  if (String(symbol || "").toUpperCase().endsWith(".BJ") || /^(4|8|92)/.test(code)) return 0.3;
  if (/^(30|68)/.test(code)) return 0.2;
  return 0.1;
}

function dailyLimitColor(data: PriceBar[], index: number, market: "a_share" | "us", symbol: string | undefined): string | undefined {
  if (market !== "a_share" || index === 0) return undefined;
  const previousClose = Number(data[index - 1]?.close);
  const close = Number(data[index]?.close);
  if (!Number.isFinite(previousClose) || previousClose <= 0 || !Number.isFinite(close)) return undefined;
  const rate = aShareLimitRate(symbol);
  const tick = 0.01;
  const upper = Math.round(previousClose * (1 + rate) / tick) * tick;
  const lower = Math.round(previousClose * (1 - rate) / tick) * tick;
  if (Math.abs(close - upper) <= tick / 2) return "#f59e0b";
  if (Math.abs(close - lower) <= tick / 2) return "#8b5cf6";
  return undefined;
}

function buildIntradayAxis(data: PriceBar[], market: "a_share" | "us"): IntradayAxisData {
  const categories: string[] = [];
  const categoryKeys: string[] = [];
  const addCategory = (label: string, key = label) => {
    categories.push(label);
    categoryKeys.push(key);
  };

  if (market === "a_share") {
    const morningStart = Date.UTC(2026, 0, 1, 9, 30);
    for (let offset = 0; offset < 120; offset += 1) {
      const label = clockLabel(morningStart + offset * 60_000);
      addCategory(label);
    }
    addCategory("11:30/13:00", "break");
    const afternoonStart = Date.UTC(2026, 0, 1, 13, 0);
    for (let offset = 1; offset <= 120; offset += 1) {
      const label = clockLabel(afternoonStart + offset * 60_000);
      addCategory(label);
    }
  } else {
    const firstTimestamp = data.map((bar) => shanghaiMinute(bar.time)).find((value): value is number => value !== null);
    if (firstTimestamp === undefined) {
      return { categories: data.map((bar) => bar.time), categoryKeys: data.map((bar) => bar.time), dataKeys: data.map((bar) => bar.time), prices: data.map((bar) => bar.close), averages: calcIntradayAverage(data), guideIndexes: [], labelIndexes: [] };
    }
    for (let offset = 0; offset <= 390; offset += 1) {
      const timestamp = firstTimestamp + offset * 60_000;
      addCategory(clockLabel(timestamp), formatShanghaiMinute(timestamp));
    }
  }

  const average = calcIntradayAverage(data);
  const priceByKey = new Map<string, number>();
  const averageByKey = new Map<string, number>();
  const dataKeys: string[] = [];
  data.forEach((bar, index) => {
    const key = intradayDataKey(bar.time, market);
    dataKeys.push(key ?? `__missing_${index}`);
    if (key === null) return;
    const close = Number(bar.close);
    if (Number.isFinite(close)) priceByKey.set(key, close);
    const averageValue = average[index];
    if (averageValue !== null && Number.isFinite(averageValue)) averageByKey.set(key, averageValue);
  });

  const guideIndexes = market === "a_share" ? [60, 120, 180] : [60, 120, 180, 240, 300, 360];
  const labelIndexes = market === "a_share" ? [0, 60, 120, 180, 240] : [0, 60, 120, 180, 240, 300, 360, 390];
  return {
    categories,
    categoryKeys,
    dataKeys,
    prices: categoryKeys.map((key) => priceByKey.get(key) ?? null),
    averages: categoryKeys.map((key) => averageByKey.get(key) ?? null),
    guideIndexes,
    labelIndexes,
  };
}

export function CandlestickChart({ data, calculationData, calculationOffset = 0, initialStartIndex, initialEndIndex, viewportStartIndex, viewportEndIndex, markers, indicators, height = 500, intraday = false, previousClose, market = "a_share", symbol, fundFlowRows = [], sub: controlledSub, onSubChange, availableSubs, chanAnalysis, showChan = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const zoomSelectionRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const chartLayoutKeyRef = useRef<string | null>(null);
  const initialZoomKeyRef = useRef<string | null>(null);
  const activeSubSeriesIdsRef = useRef<string[]>([]);
  const previousSubRef = useRef<Sub | null>(null);
  const zoomDragRef = useRef<{
    startX: number;
    startY: number;
    currentX: number;
    currentY: number;
    mode: ChartDragMode;
    baseRange: ChartDataZoomRange;
    pixelsPerIndex: number;
  } | null>(null);
  const [internalSub, setInternalSub] = useState<Sub>("vol");
  const [range, setRange] = useState<Range>("1M");
  const [overlays, setOverlays] = useState<Set<Overlay>>(new Set(["ma5", "ma20"]));
  const [showMenu, setShowMenu] = useState(false);
  const dark = useThemeDark();
  const sub = controlledSub ?? internalSub;
  const subOptions = availableSubs ? SUB_OPTIONS.filter(([id]) => availableSubs.includes(id)) : SUB_OPTIONS;
  const hasImplicitViewport = useMemo(() => {
    if (intraday || !calculationData || (calculationOffset <= 0 && data.length >= calculationData.length) || data.length <= calculationOffset || data.length > calculationData.length) return false;
    return data.every((bar, index) => bar.time === calculationData[index]?.time);
  }, [calculationData, calculationOffset, data, intraday]);
  const effectiveCalculationOffset = hasImplicitViewport ? 0 : calculationOffset;
  const effectiveViewportStartIndex = viewportStartIndex ?? (hasImplicitViewport ? calculationOffset : undefined);
  const effectiveViewportEndIndex = viewportEndIndex ?? (hasImplicitViewport ? data.length - 1 : undefined);

  const selectSub = useCallback((next: Sub) => {
    setInternalSub(next);
    onSubChange?.(next);
  }, [onSubChange]);

  const toggleOverlay = useCallback((id: Overlay) => {
    setOverlays(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Memoize base data arrays — only recompute when raw data changes
  const baseData = useMemo(() => {
    const dates = data.map(d => d.time);
    const closes = data.map(d => d.close);
    const highs = data.map(d => d.high);
    const lows = data.map(d => d.low);
    const opens = data.map(d => d.open);
    const candle = data.map(d => [d.open, d.close, d.low, d.high]);
    return { dates, closes, highs, lows, opens, candle };
  }, [data]);

  // Memoize indicator calculations — only recompute when data changes (not on overlay toggle)
  const indicatorCache = useMemo(() => {
    const source = calculationData ?? data;
    const closes = source.map((item) => item.close);
    const highs = source.map((item) => item.high);
    const lows = source.map((item) => item.low);
    const slice = <T,>(values: T[]) => values.slice(effectiveCalculationOffset, effectiveCalculationOffset + data.length);
    return {
      ma5: slice(calcMA(closes, 5)),
      ma10: slice(calcMA(closes, 10)),
      ma20: slice(calcMA(closes, 20)),
      ma60: slice(calcMA(closes, 60)),
      ema12: slice(calcEMA(closes, 12)),
      ema26: slice(calcEMA(closes, 26)),
      boll: { upper: slice(calcBOLL(closes, 20, 2).upper), mid: slice(calcBOLL(closes, 20, 2).mid), lower: slice(calcBOLL(closes, 20, 2).lower) },
      macd: { dif: slice(calcMACD(closes).dif), signal: slice(calcMACD(closes).signal), histogram: slice(calcMACD(closes).histogram) },
      macdfs: { dif: slice(calcMACDFS(closes).dif), signal: slice(calcMACDFS(closes).signal), histogram: slice(calcMACDFS(closes).histogram) },
      rsi: slice(calcRSI(closes)),
      kdj: { k: slice(calcKDJ(highs, lows, closes).k), d: slice(calcKDJ(highs, lows, closes).d), j: slice(calcKDJ(highs, lows, closes).j) },
    };
  }, [calculationData, effectiveCalculationOffset, data]);
  const intradayAverage = useMemo(() => calcIntradayAverage(data), [data]);
  const intradayAxis = useMemo(() => (intraday ? buildIntradayAxis(data, market) : null), [data, intraday, market]);

  // Memoize backend indicator series with Map lookup (O(1) instead of O(n) find)
  const extraIndicators = useMemo(() => {
    if (!indicators) return [];
    return Object.entries(indicators).map(([name, points]) => {
      const lookup = new Map(points.map(p => [p.time, p.value]));
      return { name: name.toUpperCase(), values: baseData.dates.map(d => lookup.get(d) ?? null) };
    });
  }, [indicators, baseData.dates]);

  // Init chart instance — only on mount/unmount and dark mode change
  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;
    const chart = echarts.init(containerRef.current);
    chart.group = CHART_GROUP;
    connectCharts();
    chartRef.current = chart;
    chartLayoutKeyRef.current = null;
    initialZoomKeyRef.current = null;
    activeSubSeriesIdsRef.current = [];
    previousSubRef.current = null;

    let resizeFrame: number | null = null;
    const ro = new ResizeObserver(() => {
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null;
        chart.resize();
      });
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      disposeChartSafely(chart);
      chartRef.current = null;
      chartLayoutKeyRef.current = null;
      initialZoomKeyRef.current = null;
      activeSubSeriesIdsRef.current = [];
      previousSubRef.current = null;
    };
  }, [data.length === 0, dark]); // only re-init when going empty↔non-empty or theme changes

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || data.length === 0) return;
    const handleRestore = () => {
      requestAnimationFrame(() => {
        if (chartRef.current !== chart) return;
        resetChartDataZoom(chart, data.length);
        if (!intraday) {
          chart.setOption({ yAxis: [{ id: "main-y", ...getPriceAxisBoundsForRange(data, 0, data.length - 1) }] });
        }
      });
    };
    chart.on("restore", handleRestore);
    return () => {
      chart.off("restore", handleRestore);
    };
  }, [data, data.length, intraday]);

  useEffect(() => {
    const chart = chartRef.current;
    const container = containerRef.current;
    const selection = zoomSelectionRef.current;
    if (!chart || !container || !selection || data.length === 0) return;
    const pointFrom = (event: MouseEvent | PointerEvent | WheelEvent) => {
      const bounds = container.getBoundingClientRect();
      return {
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
        event,
      };
    };
    const clampIndex = (x: number) => {
      const converted = chart.convertFromPixel({ seriesIndex: 0 }, [x, chart.getHeight() / 2]);
      const rawValue = Array.isArray(converted) ? converted[0] : converted;
      const numericValue = typeof rawValue === "number" ? rawValue : Number(rawValue);
      const categoryIndex = Number.isFinite(numericValue)
        ? numericValue
        : data.findIndex((bar) => bar.time === String(rawValue));
      return Math.max(0, Math.min(data.length - 1, Math.round(categoryIndex >= 0 ? categoryIndex : 0)));
    };
    const clearSelection = () => {
      zoomDragRef.current = null;
      selection.style.display = "none";
    };
    const updatePriceAxis = (start: number, end: number) => {
      if (intraday) return;
      chart.setOption({ yAxis: [{ id: "main-y", ...getPriceAxisBoundsForRange(data, start, end) }] });
    };
    let pendingDataZoom: ChartDataZoomRange | null = null;
    let dataZoomFrame: number | null = null;
    const applyPendingDataZoom = () => {
      dataZoomFrame = null;
      const nextRange = pendingDataZoom;
      pendingDataZoom = null;
      if (!nextRange) return;
      // Update both zoom components and the visible price bounds in one
      // option merge. Two sequential dispatchAction calls render the line
      // overlays before the candle/Chan mark series catch up during a drag.
      chart.setOption({
        dataZoom: [
          { startValue: nextRange.start, endValue: nextRange.end },
          { startValue: nextRange.start, endValue: nextRange.end },
        ],
        ...(intraday ? {} : { yAxis: [{ id: "main-y", ...getPriceAxisBoundsForRange(data, nextRange.start, nextRange.end) }] }),
      });
    };
    const dispatchDataZoom = (nextRange: ChartDataZoomRange, immediate = false) => {
      pendingDataZoom = nextRange;
      if (immediate) {
        if (dataZoomFrame !== null) cancelAnimationFrame(dataZoomFrame);
        dataZoomFrame = null;
        applyPendingDataZoom();
        return;
      }
      if (dataZoomFrame === null) dataZoomFrame = requestAnimationFrame(applyPendingDataZoom);
    };
    const handleDataZoom = () => {
      const range = readChartDataZoomRange(chart, data.length);
      updatePriceAxis(range.start, range.end);
    };
    const updateSelection = () => {
      const drag = zoomDragRef.current;
      if (!drag || drag.mode !== "zoom") return;
      const left = Math.min(drag.startX, drag.currentX);
      const top = Math.min(drag.startY, drag.currentY);
      selection.style.display = "block";
      selection.style.left = `${left}px`;
      selection.style.top = `${top}px`;
      selection.style.width = `${Math.abs(drag.currentX - drag.startX)}px`;
      selection.style.height = `${Math.abs(drag.currentY - drag.startY)}px`;
    };
    const beginDrag = (event: MouseEvent | PointerEvent) => {
      const mode = getChartDragMode(event);
      if (!mode) return;
      event.preventDefault();
      if ("pointerId" in event) container.setPointerCapture?.(event.pointerId);
      const point = pointFrom(event);
      const baseRange = readChartDataZoomRange(chart, data.length);
      const visibleSpan = Math.max(1, baseRange.end - baseRange.start);
      const plotWidth = Math.max(1, chart.getWidth() - CHART_GRID_LEFT - CHART_GRID_RIGHT);
      zoomDragRef.current = {
        startX: point.x,
        startY: point.y,
        currentX: point.x,
        currentY: point.y,
        mode,
        baseRange,
        pixelsPerIndex: plotWidth / visibleSpan,
      };
      if (mode === "zoom") updateSelection();
      else selection.style.display = "none";
    };
    const updateDrag = (event: MouseEvent | PointerEvent) => {
      const drag = zoomDragRef.current;
      if (!drag) return;
      event.preventDefault();
      const point = pointFrom(event);
      drag.currentX = point.x;
      drag.currentY = point.y;
      if (drag.mode === "pan") {
        const deltaIndex = getChartPanDelta(drag.startX, drag.currentX, drag.pixelsPerIndex);
        const nextRange = buildChartPanRange(drag.baseRange, data.length, deltaIndex);
        const currentRange = readChartDataZoomRange(chart, data.length);
        if (nextRange.start !== currentRange.start || nextRange.end !== currentRange.end) {
          dispatchDataZoom(nextRange);
        }
        return;
      }
      updateSelection();
    };
    const finishDrag = (event: MouseEvent | PointerEvent) => {
      const drag = zoomDragRef.current;
      if (!drag) return;
      event.preventDefault();
      const point = pointFrom(event);
      drag.currentX = point.x;
      drag.currentY = point.y;
      if (drag.mode === "pan") {
        const deltaIndex = getChartPanDelta(drag.startX, drag.currentX, drag.pixelsPerIndex);
        const nextRange = buildChartPanRange(drag.baseRange, data.length, deltaIndex);
        const currentRange = readChartDataZoomRange(chart, data.length);
        clearSelection();
        if (nextRange.start === currentRange.start && nextRange.end === currentRange.end) return;
        dispatchDataZoom(nextRange, true);
        return;
      }
      const left = Math.min(drag.startX, drag.currentX);
      const right = Math.max(drag.startX, drag.currentX);
      clearSelection();
      if (right - left < 8) return;
      const startValue = clampIndex(left);
      const endValue = clampIndex(right);
      if (endValue <= startValue) return;
      dispatchDataZoom({ start: startValue, end: endValue }, true);
    };
    const handlePointerDown = (event: PointerEvent) => beginDrag(event);
    const handlePointerMove = (event: PointerEvent) => updateDrag(event);
    const handlePointerUp = (event: PointerEvent) => finishDrag(event);
    const handleMouseDown = (event: MouseEvent) => beginDrag(event);
    const handleMouseMove = (event: MouseEvent) => updateDrag(event);
    const handleMouseUp = (event: MouseEvent) => finishDrag(event);
    const handleWheel = (event: WheelEvent) => {
      if (!event.ctrlKey || !(event.target instanceof Node) || !container.contains(event.target)) return;
      const point = pointFrom(event);
      const converted = chart.convertFromPixel({ seriesIndex: 0 }, [point.x, chart.getHeight() / 2]);
      const rawValue = Array.isArray(converted) ? converted[0] : converted;
      const numericValue = typeof rawValue === "number" ? rawValue : Number(rawValue);
      const anchorIndex = Number.isFinite(numericValue) ? numericValue : undefined;
      const currentRange = readChartDataZoomRange(chart, data.length);
      const nextRange = buildChartDataZoomStep(currentRange, data.length, event.deltaY, anchorIndex);
      event.preventDefault();
      clearSelection();
      dispatchDataZoom(nextRange, true);
    };
    const handlePointerCancel = () => clearSelection();

    chart.on("datazoom", handleDataZoom);
    container.addEventListener("pointerdown", handlePointerDown);
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerup", handlePointerUp);
    container.addEventListener("pointercancel", handlePointerCancel);
    container.addEventListener("mousedown", handleMouseDown);
    container.addEventListener("mousemove", handleMouseMove);
    container.addEventListener("mouseup", handleMouseUp);
    window.addEventListener("wheel", handleWheel, { capture: true, passive: false });
    return () => {
      if (dataZoomFrame !== null) cancelAnimationFrame(dataZoomFrame);
      pendingDataZoom = null;
      chart.off("datazoom", handleDataZoom);
      container.removeEventListener("pointerdown", handlePointerDown);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerup", handlePointerUp);
      container.removeEventListener("pointercancel", handlePointerCancel);
      container.removeEventListener("mousedown", handleMouseDown);
      container.removeEventListener("mousemove", handleMouseMove);
      container.removeEventListener("mouseup", handleMouseUp);
      window.removeEventListener("wheel", handleWheel, true);
      clearSelection();
    };
  }, [data, intraday]);

  // Update chart options — setOption on existing instance, no dispose
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || data.length === 0) return;

    const t = getChartTheme();
    const { dates, closes, opens, candle } = baseData;
    const chartDates = intradayAxis?.categories ?? dates;
    const chartCloses = intradayAxis?.prices ?? closes;
    const chartAverage = intradayAxis?.averages ?? intradayAverage;
    const dailyCandle = candle.map((value, index) => {
      const color = dailyLimitColor(data, index, market, symbol);
      return {
        id: dates[index],
        value,
        ...(color ? { itemStyle: { color, color0: color, borderColor: color, borderColor0: color } } : {}),
      };
    });
    // Intraday guides need more contrast than the regular historical-chart
    // grid. Keep them neutral so they do not compete with the price/average
    // lines, and adapt the contrast to the page theme.
    const intradayGridColor = dark ? "#4b5563" : "#94a3b8";
    const intradayZeroAxisColor = dark ? "#9ca3af" : "#94a3b8";

    // Overlay series
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const overlaySeries: any[] = [];
    const legendNames: string[] = intraday ? ["Price", "Average"] : ["K"];
    let colorIdx = 0;

    const overlayMap: Record<string, { name: string; data: (number | null)[] }> = {
      ma5: { name: "MA5", data: indicatorCache.ma5 },
      ma10: { name: "MA10", data: indicatorCache.ma10 },
      ma20: { name: "MA20", data: indicatorCache.ma20 },
      ma60: { name: "MA60", data: indicatorCache.ma60 },
      ema12: { name: "EMA12", data: indicatorCache.ema12 },
      ema26: { name: "EMA26", data: indicatorCache.ema26 },
    };

    for (const [key, { name, data: lineData }] of Object.entries(overlayMap)) {
      if (intraday) break;
      if (overlays.has(key as Overlay)) {
        overlaySeries.push({ id: `overlay-${key}`, name, type: "line", data: lineData, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: OVERLAY_COLORS[colorIdx], width: 1 } });
        legendNames.push(name);
        colorIdx++;
      }
    }

    if (!intraday && overlays.has("boll")) {
      const boll = indicatorCache.boll;
      overlaySeries.push(
        { id: "overlay-boll-upper", name: "BOLL+", type: "line", data: boll.upper, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.upColor, width: 0.8, type: "dashed" } },
        { id: "overlay-boll-mid", name: "BOLL", type: "line", data: boll.mid, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.infoColor, width: 1 } },
        { id: "overlay-boll-lower", name: "BOLL-", type: "line", data: boll.lower, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.downColor, width: 0.8, type: "dashed" } },
      );
      legendNames.push("BOLL");
    }

    // Trade markers (escaped tooltip fields and price anchors outside the
    // candle body keep the marker readable without covering the wick).
    const marks = (markers || []).map(m => {
      const markerBar = data.find((bar) => bar.time === m.time);
      const anchorPrice = markerBar
        ? (m.side === "BUY" ? markerBar.low : markerBar.high)
        : m.price;
      return {
        coord: [m.time, anchorPrice],
        value: m.side === "BUY" ? "B" : "S",
        name: [
          `${escapeHtml(m.side)} @ ${escapeHtml(String(m.price))}`,
          m.qty ? `Qty: ${escapeHtml(String(m.qty))}` : "",
          escapeHtml(m.reason || ""),
        ].filter(Boolean).join("\n"),
        itemStyle: { color: m.side === "BUY" ? t.upColor : t.downColor },
        symbolOffset: [0, m.side === "BUY" ? 30 : -30],
        label: { show: true, color: "#fff", fontSize: 14, fontWeight: "bold" as const },
      };
    });

    // Chan structures are supplied by the session snapshot.  They are keyed
    // by global bar index so masked training bars and review bars can share
    // the same persisted analysis without recalculating it in the browser.
    const timeForChanIndex = (index: number) => data[index - effectiveCalculationOffset]?.time;
    const chanMarks = showChan && !intraday && chanAnalysis ? [
      ...chanAnalysis.fractals.map((point) => {
        const time = timeForChanIndex(point.bar_index);
        if (!time) return null;
        const isTop = point.kind === "top";
        const visual = getChanFractalMarkerStyle(point.kind, t.upColor, t.downColor);
        return {
          coord: [time, point.price],
          value: isTop ? "顶" : "底",
          name: `${isTop ? "顶分型" : "底分型"} · K${point.bar_index + 1}`,
          symbol: "triangle",
          symbolRotate: visual.symbolRotate,
          symbolSize: 12,
          symbolOffset: visual.symbolOffset,
          itemStyle: { color: visual.color, opacity: 0.9 },
          label: { show: false },
        };
      }),
      ...chanAnalysis.signals.map((signal) => {
        const time = timeForChanIndex(signal.bar_index);
        const bar = data[signal.bar_index - effectiveCalculationOffset];
        if (!time || !bar) return null;
        const isBuy = signal.side === "buy";
        return {
          coord: [time, isBuy ? bar.low : bar.high],
          value: signal.label,
          name: `${signal.label} · K${signal.bar_index + 1}`,
          symbol: "roundRect",
          symbolSize: [26, 16],
          symbolOffset: [0, isBuy ? 22 : -22],
          itemStyle: { color: isBuy ? t.upColor : t.downColor, opacity: 0.92 },
          label: { show: true, color: "#fff", fontSize: 9, fontWeight: "bold" as const },
        };
      }),
    ].filter((item): item is NonNullable<typeof item> => item !== null) : [];
    const chanStrokeLines = showChan && !intraday && chanAnalysis
      ? chanAnalysis.strokes.map((stroke) => {
          const startTime = timeForChanIndex(stroke.start_index);
          const endTime = timeForChanIndex(stroke.end_index);
          return startTime && endTime ? [
            { coord: [startTime, stroke.start_price] },
            { coord: [endTime, stroke.end_price] },
          ] : null;
        }).filter((line): line is [{ coord: [string, number] }, { coord: [string, number] }] => line !== null)
      : [];
    const chanSegmentLines = showChan && !intraday && chanAnalysis
      ? chanAnalysis.segments.map((segment) => {
          const startTime = timeForChanIndex(segment.start_index);
          const endTime = timeForChanIndex(segment.end_index);
          return startTime && endTime ? [
            { coord: [startTime, segment.start_price] },
            { coord: [endTime, segment.end_price] },
          ] : null;
        }).filter((line): line is [{ coord: [string, number] }, { coord: [string, number] }] => line !== null)
      : [];
    const chanCenterAreas = showChan && !intraday && chanAnalysis
      ? chanAnalysis.centers.map((center) => {
          const startTime = timeForChanIndex(center.start_index);
          const endTime = timeForChanIndex(center.end_index);
          return startTime && endTime ? [
            { coord: [startTime, center.low] },
            { coord: [endTime, center.high] },
          ] : null;
        }).filter((area): area is [{ coord: [string, number] }, { coord: [string, number] }] => area !== null)
      : [];

    // Volume
    const vol = data.map((d, i) => ({
      value: d.volume,
      itemStyle: { color: closes[i] >= opens[i] ? t.volumeUp : t.volumeDown },
    }));
    const amount = data.map((d, i) => ({
      value: d.amount ?? d.volume * ((d.open + d.high + d.low + d.close) / 4),
      itemStyle: { color: closes[i] >= opens[i] ? t.volumeUp : t.volumeDown },
    }));
    const subDates = intradayAxis?.categories ?? dates;
    const subKeys = intradayAxis?.categoryKeys ?? dates.map((date) => String(date).slice(0, 10));
    const fundFlow = buildFundFlowSeries(fundFlowRows, subDates, subKeys, market, intraday);

    // Sub-chart
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let subSeries: any[] = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let subYAxis: any = { scale: true, gridIndex: 1, splitLine: { lineStyle: { color: intraday ? intradayGridColor : t.gridColor, type: "dashed", width: 1 } }, axisLabel: { color: t.textColor, fontSize: 10 } };

    const axis = intradayAxis;
    const aligned = <T,>(values: T[], fallback: T[]) => axis ? mapIntradayObjects(values, axis) : fallback;
    const alignedValues = (values: Array<number | null>) => axis ? mapIntradayValues(values, axis) : values;
    const histogramData = (values: Array<number | null>) => values.map((value) => value === null ? null : { value, itemStyle: { color: value >= 0 ? t.upColor : t.downColor } });

    if (sub === "vol") {
      subSeries = [{ name: "Vol", type: "bar", data: aligned(vol, vol), xAxisIndex: 1, yAxisIndex: 1 }];
      subYAxis = { ...subYAxis, axisLabel: { ...subYAxis.axisLabel, formatter: (v: number) => abbreviateNum(v) } };
      legendNames.push("Vol");
    } else if (sub === "amount") {
      subSeries = [{ name: "Amount", type: "bar", data: aligned(amount, amount), xAxisIndex: 1, yAxisIndex: 1 }];
      subYAxis = { ...subYAxis, axisLabel: { ...subYAxis.axisLabel, formatter: (v: number) => abbreviateNum(v) } };
      legendNames.push("Amount");
    } else if (sub === "macd") {
      const m = indicatorCache.macd;
      subSeries = [
        { name: "DIF", type: "line", data: alignedValues(m.dif), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", connectNulls: false, lineStyle: { width: 1, color: t.infoColor } },
        { name: "DEA", type: "line", data: alignedValues(m.signal), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", connectNulls: false, lineStyle: { width: 1, color: t.warningColor } },
        { name: "MACD", type: "bar", data: histogramData(alignedValues(m.histogram)), xAxisIndex: 1, yAxisIndex: 1 },
      ];
      legendNames.push("DIF", "DEA", "MACD");
    } else if (sub === "macdfs") {
      const m = indicatorCache.macdfs;
      subSeries = [
        { name: "DIF", type: "line", data: alignedValues(m.dif), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", connectNulls: false, lineStyle: { width: 1, color: t.infoColor } },
        { name: "DEA", type: "line", data: alignedValues(m.signal), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", connectNulls: false, lineStyle: { width: 1, color: t.warningColor } },
        { name: "MACDFS", type: "bar", data: histogramData(alignedValues(m.histogram)), xAxisIndex: 1, yAxisIndex: 1 },
      ];
      legendNames.push("DIF", "DEA", "MACDFS");
    } else if (sub === "boll") {
      const boll = indicatorCache.boll;
      subSeries = [
        { name: "BOLL+", type: "line", data: alignedValues(boll.upper), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.upColor } },
        { name: "BOLL", type: "line", data: alignedValues(boll.mid), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.infoColor } },
        { name: "BOLL-", type: "line", data: alignedValues(boll.lower), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.downColor } },
      ];
      legendNames.push("BOLL+", "BOLL", "BOLL-");
    } else if (sub === "expma") {
      subSeries = [
        { name: "EMA12", type: "line", data: alignedValues(indicatorCache.ema12), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.infoColor } },
        { name: "EMA26", type: "line", data: alignedValues(indicatorCache.ema26), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.warningColor } },
      ];
      legendNames.push("EMA12", "EMA26");
    } else if (sub === "fundflow") {
      const flowLines = [
        { name: "主力", data: fundFlow.main, color: dark ? "#f3f4f6" : "#1f2937" },
        { name: "超大单", data: fundFlow.superLarge, color: "#ef4444" },
        { name: "大单", data: fundFlow.large, color: "#f59e0b" },
        { name: "中单", data: fundFlow.medium, color: "#3b82f6" },
        { name: "小单", data: fundFlow.small, color: "#10b981" },
      ];
      subSeries = [
        { name: "净流入", type: "bar", data: histogramData(fundFlow.histogram), xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 8, barGap: "-100%", itemStyle: { opacity: 0.28 } },
        ...flowLines.map((line) => ({ name: line.name, type: "line", data: line.data, xAxisIndex: 1, yAxisIndex: 1, symbol: "none", connectNulls: false, lineStyle: { width: line.name === "主力" ? 1.8 : 1.2, color: line.color } })),
      ];
      subYAxis = { ...subYAxis, axisLabel: { ...subYAxis.axisLabel, formatter: (v: number) => abbreviateNum(v) } };
      legendNames.push("净流入", ...flowLines.map((line) => line.name));
    } else if (sub === "rsi") {
      subSeries = [{ name: "RSI", type: "line", data: alignedValues(indicatorCache.rsi), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1.5, color: t.infoColor } }];
      subYAxis = { ...subYAxis, min: 0, max: 100 };
      legendNames.push("RSI");
    } else {
      const kdj = indicatorCache.kdj;
      subSeries = [
        { name: "%K", type: "line", data: alignedValues(kdj.k), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.infoColor } },
        { name: "%D", type: "line", data: alignedValues(kdj.d), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: t.warningColor } },
        { name: "%J", type: "line", data: alignedValues(kdj.j), xAxisIndex: 1, yAxisIndex: 1, symbol: "none", lineStyle: { width: 1, color: "#a855f7" } },
      ];
      legendNames.push("%K", "%D", "%J");
    }

    // Backend custom indicators (Map-based O(1) lookup)
    const extraSeries = intraday ? [] : extraIndicators.map((ind, i) => {
      legendNames.push(ind.name);
      return { id: `extra-${ind.name}`, name: ind.name, type: "line" as const, data: ind.values, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { width: 1, color: OVERLAY_COLORS[(colorIdx + i) % OVERLAY_COLORS.length], type: "dashed" as const } };
    });

    const maxBars = RANGE_BARS[range];
    const defaultStart = intraday || maxBars >= data.length ? 0 : Math.max(0, 100 - (maxBars / data.length) * 100);
    const defaultRange = getInitialChartDataZoomRange(data.length, range);
    const hasViewport = !intraday && effectiveViewportStartIndex !== undefined && effectiveViewportEndIndex !== undefined;
    const viewportStart = hasViewport ? Math.max(0, Math.min(data.length - 1, effectiveViewportStartIndex)) : 0;
    const viewportEnd = hasViewport ? Math.max(viewportStart, Math.min(data.length - 1, effectiveViewportEndIndex)) : data.length - 1;
    const hasInitialZoom = !intraday && initialStartIndex !== undefined && initialEndIndex !== undefined;
    const zoomStartIndex = hasInitialZoom ? Math.max(0, Math.min(data.length - 1, initialStartIndex)) : 0;
    const zoomEndIndex = hasInitialZoom ? Math.max(zoomStartIndex, Math.min(data.length - 1, initialEndIndex)) : data.length - 1;
    const initialZoomKey = hasInitialZoom ? `${symbol || ""}:${data.length}:${zoomStartIndex}:${zoomEndIndex}` : null;
    const shouldApplyInitialZoom = hasInitialZoom && initialZoomKey !== initialZoomKeyRef.current;
    const initialZoom = hasViewport
      ? { startValue: viewportStart, endValue: viewportEnd }
      : shouldApplyInitialZoom
        ? { startValue: zoomStartIndex, endValue: zoomEndIndex }
        : {};
    const initialVisibleRange = hasViewport
      ? { start: viewportStart, end: viewportEnd }
      : shouldApplyInitialZoom
        ? { start: zoomStartIndex, end: zoomEndIndex }
        : defaultRange;
    const initialPriceAxisBounds = intraday
      ? {}
      : getPriceAxisBoundsForRange(data, initialVisibleRange.start, initialVisibleRange.end);
    const referencePrice = previousClose && previousClose > 0 ? previousClose : closes[0];
    const intradayCloses = chartCloses.filter((close): close is number => close !== null && Number.isFinite(close));
    const maxRelativeMove = referencePrice
      ? Math.max(...intradayCloses.map((close) => Math.abs((close - referencePrice) / referencePrice)), 0)
      : 0;
    const intradayAxisSpan = Math.max(0.01, maxRelativeMove * 1.25);
    const intradayAxisMin = referencePrice ? referencePrice * (1 - intradayAxisSpan) : undefined;
    const intradayAxisMax = referencePrice ? referencePrice * (1 + intradayAxisSpan) : undefined;
    const intradayHourIndexes = intradayAxis?.guideIndexes ?? [];
    const intradayGuides = referencePrice
      ? [
          { yAxis: referencePrice, lineStyle: { color: intradayZeroAxisColor, type: "dashed", width: 2.5 } },
          { yAxis: referencePrice * (1 + intradayAxisSpan / 2), lineStyle: { color: intradayGridColor, type: "dashed", width: 1 } },
          { yAxis: referencePrice * (1 - intradayAxisSpan / 2), lineStyle: { color: intradayGridColor, type: "dashed", width: 1 } },
        ]
      : [];
    const mainSeries = intraday
      ? [
          { id: "intraday-price", name: "Price", type: "line", data: chartCloses, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", connectNulls: false, smooth: false, lineStyle: { color: t.infoColor, width: 1.5 }, markLine: { symbol: ["none", "none"], silent: true, label: { show: false }, data: intradayGuides } },
          { id: "intraday-average", name: "Average", type: "line", data: chartAverage, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", connectNulls: false, smooth: false, lineStyle: { color: "#facc15", width: 1.5 } },
        ]
      : [{
          id: "K", name: "K", type: "candlestick", data: dailyCandle, xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: { color: t.upColor, color0: t.downColor, borderColor: t.upColor, borderColor0: t.downColor },
          markPoint: chanMarks.length > 0 ? {
            data: chanMarks,
            symbol: "circle",
            symbolSize: 30,
            label: { show: true, color: "#fff", fontSize: 14, fontWeight: "bold" },
            tooltip: { formatter: (p: { name?: string; value?: string }) => p.name || p.value || "" },
          } : undefined,
          markArea: chanCenterAreas.length > 0 ? {
            silent: true,
            itemStyle: { color: t.infoColor, opacity: 0.06 },
            data: chanCenterAreas,
          } : undefined,
        }];

    const chanStructureSeries = showChan && !intraday ? [
      {
        id: "chan-strokes",
        name: "__chan_strokes__",
        type: "line",
        data: [],
        xAxisIndex: 0,
        yAxisIndex: 0,
        silent: true,
        showSymbol: false,
        tooltip: { show: false },
        markLine: chanStrokeLines.length > 0 ? {
          symbol: ["none", "none"],
          silent: true,
          label: { show: false },
          data: chanStrokeLines,
          lineStyle: { color: t.infoColor, width: 1, type: "dashed", opacity: 0.9 },
        } : undefined,
      },
      {
        id: "chan-segments",
        name: "__chan_segments__",
        type: "line",
        data: [],
        xAxisIndex: 0,
        yAxisIndex: 0,
        silent: true,
        showSymbol: false,
        tooltip: { show: false },
        markLine: chanSegmentLines.length > 0 ? {
          symbol: ["none", "none"],
          silent: true,
          label: { show: false },
          data: chanSegmentLines,
          lineStyle: { color: t.warningColor, width: 2.2, type: "solid", opacity: 0.95 },
        } : undefined,
      },
    ] : [];

    const tradeMarkerSeries = !intraday ? [{
      id: "trade-markers",
      name: "__trade_markers__",
      type: "line",
      data: [],
      xAxisIndex: 0,
      yAxisIndex: 0,
      silent: true,
      showSymbol: false,
      tooltip: { show: false },
      markPoint: marks.length > 0 ? {
        data: marks,
        symbol: "circle",
        symbolSize: 30,
        label: { show: true, color: "#fff", fontSize: 14, fontWeight: "bold" },
        tooltip: { formatter: (p: { name?: string; value?: string }) => p.name || p.value || "" },
      } : { data: [] },
    }] : [];

    const renderedSubSeries = subSeries.map((series, index) => ({
      ...series,
      id: `sub-${sub}-${index}`,
      show: true,
    }));
    const chartSeries = [
      ...mainSeries,
      ...chanStructureSeries,
      ...tradeMarkerSeries,
      ...overlaySeries,
      ...extraSeries,
      ...renderedSubSeries,
    ].map((series) => ({ ...series, animation: false, animationDuration: 0, animationDurationUpdate: 0, progressive: 0 }));

    const chartYAxis = intraday
      ? [
          { id: "main-y", scale: true, min: intradayAxisMin, max: intradayAxisMax, gridIndex: 0, axisLine: { show: true, lineStyle: { color: t.axisColor } }, axisTick: { show: true }, splitLine: { show: false }, axisLabel: { color: t.textColor, fontSize: 10, formatter: (value: number) => referencePrice ? `${(((value - referencePrice) / referencePrice) * 100).toFixed(2)}%` : String(value) } },
          { id: "sub-y", ...subYAxis, gridIndex: 1, axisLabel: { ...subYAxis.axisLabel, color: t.textColor, fontSize: 10 } },
        ]
      : [
          { id: "main-y", scale: true, ...initialPriceAxisBounds, gridIndex: 0, splitLine: { lineStyle: { color: t.gridColor } }, axisLabel: { color: t.textColor, fontSize: 10, formatter: formatPriceAxisLabel } },
          { id: "sub-y", ...subYAxis },
        ];

    const chartOption = {
      backgroundColor: "transparent",
      animation: false,
      animationDuration: 0,
      animationDurationUpdate: 0,
      tooltip: {
        trigger: "axis", axisPointer: { type: "cross" },
        backgroundColor: t.tooltipBg, borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (params: any) => {
          if (!Array.isArray(params) || !params.length) return "";
          let html = `<b>${params[0].axisValue}</b>`;
          for (const p of params) {
            if (p.seriesName === "K" && Array.isArray(p.value)) {
              const [open, close, low, high] = p.value;
              const chg = close - open;
              const pct = open ? ((chg / open) * 100).toFixed(2) : "0.00";
              const clr = chg >= 0 ? t.upColor : t.downColor;
              html += `<br/>O: ${open.toFixed(2)}&nbsp; H: ${high.toFixed(2)}`;
              html += `<br/>L: ${low.toFixed(2)}&nbsp; C: <span style="color:${clr}"><b>${close.toFixed(2)}</b> ${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${chg >= 0 ? "+" : ""}${pct}%)</span>`;
            } else if (p.seriesName === "Vol") {
              html += `<br/>Vol: ${abbreviateNum(Number(p.value))}`;
            } else if (p.value != null) {
              html += `<br/>${p.marker} ${p.seriesName}: ${Number(p.value).toFixed(2)}`;
            }
          }
          return html;
        },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      toolbox: {
        feature: { saveAsImage: { title: "下载" } },
        right: 8, top: 0, iconStyle: { borderColor: t.textColor },
      },
      legend: { data: legendNames, textStyle: { color: t.textColor, fontSize: 10 }, right: 80, top: 2, type: "scroll", itemWidth: 12, itemHeight: 8, itemGap: 8 },
      grid: getChartGridLayout(intraday),
      xAxis: intraday
        ? [0, 1].map((gridIndex) => ({
            type: "category",
            data: chartDates,
            gridIndex,
            axisLine: { show: true, lineStyle: { color: t.axisColor } },
            axisTick: { show: gridIndex === 0, alignWithLabel: true },
            axisLabel: { show: gridIndex === 0, color: t.textColor, fontSize: 10, interval: (index: number) => (intradayAxis?.labelIndexes ?? []).includes(index), formatter: (value: string) => value },
            splitLine: { show: true, interval: (index: number) => intradayHourIndexes.includes(index), lineStyle: { color: intradayGridColor, type: "dashed", width: 1 } },
            boundaryGap: false,
          }))
        : [
            { type: "category", data: dates, gridIndex: 0, axisLine: { lineStyle: { color: t.axisColor } }, axisLabel: { color: t.textColor, fontSize: 10 }, boundaryGap: true },
            { type: "category", data: dates, gridIndex: 1, axisLine: { lineStyle: { color: t.axisColor } }, axisLabel: { show: false }, boundaryGap: true },
          ],
      yAxis: chartYAxis,
      dataZoom: [
        { type: "inside", xAxisIndex: intraday ? [0, 1] : [0, 1], start: defaultStart, end: 100, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: false, ...initialZoom },
        { type: "slider", xAxisIndex: intraday ? [0, 1] : [0, 1], bottom: 4, height: 20, labelFormatter: (val: string) => val, ...initialZoom },
      ],
      series: chartSeries,
    };
    const chartLayoutKey = JSON.stringify({
      dark,
      intraday,
      market,
      previousClose,
      initialStartIndex,
      initialEndIndex,
      range,
      showChan,
      chanVersion: getChanAnalysisRenderKey(chanAnalysis),
    });
    const subSeriesIds = renderedSubSeries.map((series) => String(series.id));
    if (chartLayoutKeyRef.current !== chartLayoutKey) {
      // A layout/configuration change needs a complete option replacement.
      chart.setOption(chartOption, true);
      chartLayoutKeyRef.current = chartLayoutKey;
      activeSubSeriesIdsRef.current = subSeriesIds;
      previousSubRef.current = sub;
      if (shouldApplyInitialZoom && initialZoomKey) {
        initialZoomKeyRef.current = initialZoomKey;
        // ECharts can keep the previous dataZoom state when a category axis is
        // replaced. Re-apply the review window after the option is mounted so
        // the full dataset remains loaded while only the requested slice is
        // visible initially.
        requestAnimationFrame(() => {
          if (chartRef.current !== chart) return;
          const zoom = { type: "dataZoom" as const, startValue: zoomStartIndex, endValue: zoomEndIndex };
          chart.dispatchAction({ ...zoom, dataZoomIndex: 0 });
          chart.dispatchAction({ ...zoom, dataZoomIndex: 1 });
        });
      }
    } else {
      const subOnlyChanged = previousSubRef.current !== null && previousSubRef.current !== sub;
      if (subOnlyChanged) {
        // Sub-indicator switches do not submit the main K-line series at all.
        // Old sub series are hidden by id, then the newly selected series are
        // added to the same secondary grid without disturbing dataZoom.
        const hiddenPreviousSubSeries = activeSubSeriesIdsRef.current
          .filter((id) => !subSeriesIds.includes(id))
          .map((id) => ({ id, show: false, data: [] }));
        const currentRange = readChartDataZoomRange(chart, data.length);
        const nextChartYAxis = intraday
          ? chartYAxis
          : [
              { ...chartYAxis[0], ...getPriceAxisBoundsForRange(data, currentRange.start, currentRange.end) },
              { ...chartYAxis[1], ...getSubChartAxisBounds(sub) },
            ];
        chart.setOption({
          legend: { data: legendNames },
          yAxis: nextChartYAxis,
          series: [...hiddenPreviousSubSeries, ...renderedSubSeries],
        }, { replaceMerge: ["yAxis"] });
        activeSubSeriesIdsRef.current = subSeriesIds;
      } else {
        // Price/data refreshes update the complete series set but still omit
        // dataZoom, so the user's current window remains unchanged.
        const currentRange = readChartDataZoomRange(chart, data.length);
        const currentChartYAxis = intraday
          ? chartYAxis
          : [
              { ...chartYAxis[0], ...getPriceAxisBoundsForRange(data, currentRange.start, currentRange.end) },
              chartYAxis[1],
            ];
        chart.setOption({
          ...buildChartDataUpdate(chartDates, chartSeries),
          legend: { data: legendNames },
          yAxis: currentChartYAxis,
          series: chartSeries,
        }, { replaceMerge: ["series"] });
        activeSubSeriesIdsRef.current = subSeriesIds;
      }
      previousSubRef.current = sub;
    }
  }, [data, baseData, indicatorCache, extraIndicators, initialStartIndex, initialEndIndex, intraday, intradayAverage, intradayAxis, previousClose, market, symbol, fundFlowRows, sub, range, overlays, dark, chanAnalysis, showChan]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || intraday || effectiveViewportStartIndex === undefined || effectiveViewportEndIndex === undefined || data.length === 0) return;
    const startValue = Math.max(0, Math.min(data.length - 1, effectiveViewportStartIndex));
    const endValue = Math.max(startValue, Math.min(data.length - 1, effectiveViewportEndIndex));
    const zoom = { type: "dataZoom" as const, startValue, endValue };
    chart.dispatchAction({ ...zoom, dataZoomIndex: 0 });
    chart.dispatchAction({ ...zoom, dataZoomIndex: 1 });
  }, [data.length, effectiveViewportStartIndex, effectiveViewportEndIndex, intraday]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || intraday || data.length === 0) return;
    const t = getChartTheme();
    const marks = (markers || []).map((marker) => {
      const markerBar = data.find((bar) => bar.time === marker.time);
      const anchorPrice = markerBar
        ? (marker.side === "BUY" ? markerBar.low : markerBar.high)
        : marker.price;
      return {
        coord: [marker.time, anchorPrice],
        value: marker.side === "BUY" ? "B" : "S",
        name: [`${marker.side} @ ${marker.price}`, marker.qty ? `Qty: ${marker.qty}` : "", marker.reason || ""].filter(Boolean).join("\n"),
        itemStyle: { color: marker.side === "BUY" ? t.upColor : t.downColor },
        symbolOffset: [0, marker.side === "BUY" ? 30 : -30],
        label: { show: true, color: "#fff", fontSize: 14, fontWeight: "bold" as const },
      };
    });
    chart.setOption({
      series: [{
        id: "trade-markers",
        markPoint: marks.length > 0 ? {
          data: marks,
          symbol: "circle",
          symbolSize: 30,
          label: { show: true, color: "#fff", fontSize: 14, fontWeight: "bold" },
          tooltip: { formatter: (point: { name?: string; value?: string }) => point.name || point.value || "" },
        } : { data: [] },
      }],
    });
  }, [data, dark, intraday, markers, market, symbol]);

  if (data.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("charts.noPriceData")}</div>;
  }

  return (
    <div>
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
        {/* Time range */}
        {!intraday && <div className="flex gap-0.5">
          {(["1M", "3M", "6M", "1Y", "ALL"] as const).map((r) => (
            <button key={r} onClick={() => setRange(r)} className={cn("px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors", range === r ? "bg-primary/15 text-primary font-medium" : "text-muted-foreground/50 hover:text-muted-foreground")}>{r}</button>
          ))}
        </div>}

        {!intraday && <div className="w-px h-3 bg-border/40" />}

        {/* Indicator dropdown */}
        {!intraday && <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            Indicators ({overlays.size}) <ChevronDown className="h-3 w-3" />
          </button>
          {showMenu && (
            <div className="absolute top-full left-0 mt-1 z-50 bg-card border rounded-lg shadow-lg p-2 min-w-[160px]" onMouseLeave={() => setShowMenu(false)}>
              {["MA", "Channel"].map(group => (
                <div key={group}>
                  <p className="text-[9px] text-muted-foreground/50 uppercase tracking-wider px-1 pt-1">{group}</p>
                  {OVERLAY_OPTIONS.filter(o => o.group === group).map(o => (
                    <label key={o.id} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-muted/30 cursor-pointer">
                      <input type="checkbox" checked={overlays.has(o.id)} onChange={() => toggleOverlay(o.id)} className="h-3 w-3 rounded accent-primary" />
                      <span className="text-xs">{o.label}</span>
                    </label>
                  ))}
                </div>
              ))}
              <div className="border-t mt-1 pt-1">
                <button onClick={() => { setOverlays(new Set()); setShowMenu(false); }} className="text-[10px] text-muted-foreground hover:text-foreground px-1 py-0.5 w-full text-left rounded hover:bg-muted/30">
                  Bare K (clear all)
                </button>
              </div>
            </div>
          )}
        </div>}

        <div className="w-px h-3 bg-border/40" />

        {/* Sub-chart selector */}
        <div className="flex gap-0.5 flex-wrap">
          {subOptions.map(([id, label]) => (
            <button key={id} onClick={() => selectSub(id)} className={cn("px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors", sub === id ? "bg-primary/15 text-primary font-medium" : "text-muted-foreground/50 hover:text-muted-foreground")}>{label}</button>
          ))}
        </div>
        </div>
        <div className="relative w-full shrink-0" style={{ height, minHeight: height, maxHeight: height }}>
          <div ref={containerRef} className="h-full w-full overflow-hidden" />
          <div ref={zoomSelectionRef} className="pointer-events-none absolute z-20 hidden border border-primary bg-primary/10" />
        </div>
      </div>
    </div>
  );
}
