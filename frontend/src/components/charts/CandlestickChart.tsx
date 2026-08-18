import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import i18n from "@/i18n";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";
import type { PriceBar, TradeMarker, IndicatorPoint, StockFundFlowRow } from "@/lib/api";
import { calcMA, calcBOLL, calcMACD, calcMACDFS, calcRSI, calcKDJ, calcEMA, calcIntradayAverage } from "@/lib/indicators";
import { getChartTheme } from "@/lib/chart-theme";
import { abbreviateNum } from "@/lib/formatters";
import { echarts, CHART_GROUP, connectCharts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

export type Sub = "fundflow" | "vol" | "amount" | "macd" | "macdfs" | "rsi" | "kdj" | "boll" | "expma";
type Range = "1M" | "3M" | "6M" | "1Y" | "ALL";
type Overlay = "ma5" | "ma10" | "ma20" | "ma60" | "ema12" | "ema26" | "boll";

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

export function buildChartDataUpdate(
  chartDates: string[],
  series: Array<{ name: string; data: unknown; [key: string]: unknown }>,
) {
  return {
    xAxis: [{ data: chartDates }, { data: chartDates }],
    series: series.map(({ name, data }) => ({ name, data })),
  };
}

interface Props {
  data: PriceBar[];
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

export function CandlestickChart({ data, markers, indicators, height = 500, intraday = false, previousClose, market = "a_share", symbol, fundFlowRows = [], sub: controlledSub, onSubChange, availableSubs }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const chartLayoutKeyRef = useRef<string | null>(null);
  const [internalSub, setInternalSub] = useState<Sub>("vol");
  const [range, setRange] = useState<Range>("1M");
  const [overlays, setOverlays] = useState<Set<Overlay>>(new Set(["ma5", "ma20"]));
  const [showMenu, setShowMenu] = useState(false);
  const dark = useThemeDark();
  const sub = controlledSub ?? internalSub;
  const subOptions = availableSubs ? SUB_OPTIONS.filter(([id]) => availableSubs.includes(id)) : SUB_OPTIONS;

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
  const indicatorCache = useMemo(() => ({
    ma5: calcMA(baseData.closes, 5),
    ma10: calcMA(baseData.closes, 10),
    ma20: calcMA(baseData.closes, 20),
    ma60: calcMA(baseData.closes, 60),
    ema12: calcEMA(baseData.closes, 12),
    ema26: calcEMA(baseData.closes, 26),
    boll: calcBOLL(baseData.closes, 20, 2),
    macd: calcMACD(baseData.closes),
    macdfs: calcMACDFS(baseData.closes),
    rsi: calcRSI(baseData.closes),
    kdj: calcKDJ(baseData.highs, baseData.lows, baseData.closes),
  }), [baseData]);
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
      chart.dispose();
      chartRef.current = null;
      chartLayoutKeyRef.current = null;
    };
  }, [data.length === 0, dark]); // only re-init when going empty↔non-empty or theme changes

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
      return color
        ? { value, itemStyle: { color, color0: color, borderColor: color, borderColor0: color } }
        : value;
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
        overlaySeries.push({ name, type: "line", data: lineData, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: OVERLAY_COLORS[colorIdx], width: 1 } });
        legendNames.push(name);
        colorIdx++;
      }
    }

    if (!intraday && overlays.has("boll")) {
      const boll = indicatorCache.boll;
      overlaySeries.push(
        { name: "BOLL+", type: "line", data: boll.upper, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.bollColor, width: 0.8, type: "dashed" } },
        { name: "BOLL", type: "line", data: boll.mid, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.bollColor, width: 1 } },
        { name: "BOLL-", type: "line", data: boll.lower, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { color: t.bollColor, width: 0.8, type: "dashed" } },
      );
      legendNames.push("BOLL");
    }

    // Trade markers
    const marks = (markers || []).map(m => ({
      coord: [m.time, m.price],
      value: m.side === "BUY" ? "B" : "S",
      name: [`${m.side} @ ${m.price}`, m.qty ? `Qty: ${m.qty}` : "", m.reason || ""].filter(Boolean).join("\n"),
      itemStyle: { color: m.side === "BUY" ? t.upColor : t.downColor },
      label: { color: "#fff", fontSize: 10, fontWeight: "bold" as const },
    }));

    // Volume
    const vol = data.map((d, i) => ({
      value: d.volume,
      itemStyle: { color: closes[i] >= opens[i] ? t.volumeUp : t.volumeDown },
    }));
    const amount = data.map((d, i) => ({
      value: d.volume * ((d.open + d.high + d.low + d.close) / 4),
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
      return { name: ind.name, type: "line" as const, data: ind.values, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", lineStyle: { width: 1, color: OVERLAY_COLORS[(colorIdx + i) % OVERLAY_COLORS.length], type: "dashed" as const } };
    });

    const maxBars = RANGE_BARS[range];
    const defaultStart = intraday || maxBars >= data.length ? 0 : Math.max(0, 100 - (maxBars / data.length) * 100);
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
          { name: "Price", type: "line", data: chartCloses, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", connectNulls: false, smooth: false, lineStyle: { color: t.infoColor, width: 1.5 }, markLine: { symbol: ["none", "none"], silent: true, label: { show: false }, data: intradayGuides } },
          { name: "Average", type: "line", data: chartAverage, xAxisIndex: 0, yAxisIndex: 0, symbol: "none", connectNulls: false, smooth: false, lineStyle: { color: "#facc15", width: 1.5 } },
        ]
      : [{
          name: "K", type: "candlestick", data: dailyCandle, xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: { color: t.upColor, color0: t.downColor, borderColor: t.upColor, borderColor0: t.downColor },
          markPoint: marks.length > 0 ? { data: marks, symbolSize: 28, tooltip: { formatter: (p: { name?: string; value?: string }) => p.name || p.value || "" } } : undefined,
        }];

    const chartOption = {
      backgroundColor: "transparent",
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
        feature: { saveAsImage: { title: "Save" }, dataZoom: { title: { zoom: "Zoom", back: "Reset" } }, restore: { title: "Reset" } },
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
      yAxis: intraday
        ? [
            { scale: true, min: intradayAxisMin, max: intradayAxisMax, gridIndex: 0, axisLine: { show: true, lineStyle: { color: t.axisColor } }, axisTick: { show: true }, splitLine: { show: false }, axisLabel: { color: t.textColor, fontSize: 10, formatter: (value: number) => referencePrice ? `${(((value - referencePrice) / referencePrice) * 100).toFixed(2)}%` : String(value) } },
            { ...subYAxis, gridIndex: 1, axisLabel: { ...subYAxis.axisLabel, color: t.textColor, fontSize: 10 } },
          ]
        : [
            { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: t.gridColor } }, axisLabel: { color: t.textColor, fontSize: 10 } },
            subYAxis,
          ],
      dataZoom: [
        { type: "inside", xAxisIndex: intraday ? [0, 1] : [0, 1], start: defaultStart, end: 100 },
        { type: "slider", xAxisIndex: intraday ? [0, 1] : [0, 1], bottom: 4, height: 20, labelFormatter: (val: string) => val },
      ],
      series: [
        ...mainSeries,
        ...overlaySeries,
        ...extraSeries,
        ...subSeries,
      ],
    };
    const chartLayoutKey = JSON.stringify({
      dark,
      intraday,
      market,
      symbol,
      previousClose,
      sub,
      range,
      overlays: [...overlays].sort(),
      markers,
    });
    if (chartLayoutKeyRef.current !== chartLayoutKey) {
      // A layout/configuration change needs a complete option replacement.
      chart.setOption(chartOption, true);
      chartLayoutKeyRef.current = chartLayoutKey;
    } else {
      // Live refresh: update only categories and series data. This preserves
      // the existing canvas background, axes, zoom state, and zero reference
      // line instead of rebuilding them on every quote tick.
      chart.setOption(buildChartDataUpdate(chartDates, [
        ...mainSeries,
        ...overlaySeries,
        ...extraSeries,
        ...subSeries,
      ]), { lazyUpdate: true });
    }
  }, [data, markers, baseData, indicatorCache, extraIndicators, intraday, intradayAverage, intradayAxis, previousClose, market, symbol, fundFlowRows, sub, range, overlays, dark]);

  if (data.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("charts.noPriceData")}</div>;
  }

  return (
    <div>
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
      <div ref={containerRef} style={{ height }} />
    </div>
  );
}
