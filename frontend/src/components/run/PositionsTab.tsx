import { useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { fetchRunSectorMap, type RunData, type SectorMapResponse } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { escapeHtml } from "@/lib/escapeHtml";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";
import { cn } from "@/lib/utils";
import {
  CASH_SYMBOL,
  aggregateWeights,
  classifyAssetClass,
  downsampleDates,
  latestHoldingDate,
  parsePositionsPanel,
  withCashSlice,
  type AssetClass,
} from "@/lib/positions";

const CASH_COLOR = "#9ca3af";
const MAX_EVOLUTION_DATES = 500;
const MAX_LEGEND_SYMBOLS = 10;

const ASSET_CLASS_LABEL_KEYS = {
  a_share: "runDetail.positions.assetClass.a_share",
  us_equity: "runDetail.positions.assetClass.us_equity",
  hk_equity: "runDetail.positions.assetClass.hk_equity",
  ca_equity: "runDetail.positions.assetClass.ca_equity",
  kr_equity: "runDetail.positions.assetClass.kr_equity",
  india_equity: "runDetail.positions.assetClass.india_equity",
  crypto: "runDetail.positions.assetClass.crypto",
  futures: "runDetail.positions.assetClass.futures",
  forex: "runDetail.positions.assetClass.forex",
  other: "runDetail.positions.assetClass.other",
} as const satisfies Record<AssetClass, string>;

function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function niceAxisCeil(value: number): number {
  if (value <= 0) return 0.01;
  const base = 10 ** Math.floor(Math.log10(value));
  for (const multiplier of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (multiplier * base >= value) return multiplier * base;
  }
  return 10 * base;
}

/**
 * Signed axis range: `[0, nice(max)]` when every value is non-negative,
 * otherwise a symmetric `[-nice, +nice]` so short exposure is never clipped
 * by a hard-coded `[0, 1]` window.
 */
function signedAxisBounds(values: Iterable<number>): { min: number; max: number } {
  let lo = 0;
  let hi = 0;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    if (value < lo) lo = value;
    if (value > hi) hi = value;
  }
  const bound = niceAxisCeil(Math.max(Math.abs(lo), hi));
  return lo < 0 ? { min: -bound, max: bound } : { min: 0, max: bound };
}

function categoryColors(t: ReturnType<typeof getChartTheme>): string[] {
  return [
    t.infoColor, t.warningColor, "#8b5cf6", "#14b8a6", t.upColor, "#f97316",
    "#06b6d4", t.downColor, "#84cc16", "#ec4899", "#6366f1", "#10b981",
  ];
}

interface DistributionItem {
  symbol: string;
  sliceSize: number;
  weight: number;
  assetClassLabel: string;
}

interface GroupedItem {
  group: string;
  weight: number;
  isCash?: boolean;
}

interface EvolutionSeries {
  name: string;
  data: number[];
}

export function PositionsTab({ run }: { run: RunData }) {
  const { t } = useTranslation();

  const panel = useMemo(
    () => parsePositionsPanel(run.artifacts_positions_csv ?? []),
    [run.artifacts_positions_csv],
  );
  const latestDate = useMemo(() => latestHoldingDate(panel), [panel]);
  const hasAShare = useMemo(
    () => panel.symbols.some((symbol) => {
      const assetClass = classifyAssetClass(symbol);
      // The backend sector-map `_detect_market` defaults UNKNOWN symbols to
      // a_share, so symbols the frontend classifier buckets as "other" are
      // still resolvable — include them in the gate.
      return assetClass === "a_share" || assetClass === "other";
    }),
    [panel.symbols],
  );

  const [dateIndex, setDateIndex] = useState<number>(() => {
    const target = latestDate ?? panel.dates[panel.dates.length - 1] ?? "";
    return Math.max(0, panel.dates.indexOf(target));
  });
  const [mode, setMode] = useState<"pie" | "treemap">(() => (panel.symbols.length <= 8 ? "pie" : "treemap"));
  const [sectorMap, setSectorMap] = useState<SectorMapResponse | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState("");

  const selectedDate = panel.dates[dateIndex] ?? "";

  const selectedWeights = useMemo(() => {
    const date = panel.dates[dateIndex];
    return date ? panel.weightByDate.get(date) ?? {} : {};
  }, [panel, dateIndex]);

  const holdingsCount = useMemo(
    () => Object.values(selectedWeights).filter((w) => w !== 0).length,
    [selectedWeights],
  );

  const assetClassLabel = (assetClass: AssetClass) => t(ASSET_CLASS_LABEL_KEYS[assetClass]);
  const cashLabel = t("runDetail.positions.cash");
  const restLabel = t("runDetail.positions.rest");
  const restLongLabel = t("runDetail.positions.restLong");
  const restShortLabel = t("runDetail.positions.restShort");
  const shortLabel = t("runDetail.positions.short");

  const distributionItems = useMemo<DistributionItem[]>(() => {
    const withCash = withCashSlice(selectedWeights);
    return Object.entries(withCash)
      .filter(([, weight]) => weight !== 0)
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .map(([symbol, weight]) => ({
        symbol,
        sliceSize: Math.abs(weight),
        weight,
        assetClassLabel: symbol === CASH_SYMBOL ? cashLabel : assetClassLabel(classifyAssetClass(symbol)),
      }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWeights, cashLabel, t]);

  const sectorItems = useMemo<GroupedItem[]>(() => {
    const withCash = withCashSlice(selectedWeights);
    const grouping = (symbol: string): string => {
      if (symbol === CASH_SYMBOL) return cashLabel;
      const info = sectorMap?.symbols?.[symbol];
      if (info?.industry && info.industry_source === "eastmoney") return info.industry;
      return assetClassLabel(classifyAssetClass(symbol));
    };
    return aggregateWeights(withCash, grouping).map((item) => ({
      group: item.group === "other" ? restLabel : item.group,
      weight: item.weight,
      isCash: item.group === cashLabel,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWeights, sectorMap, cashLabel, restLabel, t]);

  const evolution = useMemo(() => {
    const dates = downsampleDates(panel.dates, MAX_EVOLUTION_DATES);
    // Rank by average ABSOLUTE exposure: ranking by the signed average
    // pushes persistent shorts to the bottom and hides them in the remainder.
    const averageAbsWeight = new Map<string, number>();
    for (const symbol of panel.symbols) {
      let sum = 0;
      for (const date of panel.dates) {
        sum += Math.abs(panel.weightByDate.get(date)?.[symbol] ?? 0);
      }
      averageAbsWeight.set(symbol, panel.dates.length > 0 ? sum / panel.dates.length : 0);
    }
    const ranked = [...panel.symbols].sort(
      (a, b) => (averageAbsWeight.get(b) ?? 0) - (averageAbsWeight.get(a) ?? 0),
    );
    const top = ranked.slice(0, MAX_LEGEND_SYMBOLS);
    const rest = new Set(ranked.slice(MAX_LEGEND_SYMBOLS));

    const series: EvolutionSeries[] = top.map((symbol) => ({
      name: symbol,
      data: dates.map((date) => panel.weightByDate.get(date)?.[symbol] ?? 0),
    }));
    if (rest.size > 0) {
      // Separate long/short remainder series: one signed aggregate would let
      // omitted longs and shorts cancel each other out.
      const restLong = dates.map((date) => {
        const weights = panel.weightByDate.get(date);
        let sum = 0;
        for (const symbol of rest) {
          const weight = weights?.[symbol] ?? 0;
          if (weight > 0) sum += weight;
        }
        return sum;
      });
      const restShort = dates.map((date) => {
        const weights = panel.weightByDate.get(date);
        let sum = 0;
        for (const symbol of rest) {
          const weight = weights?.[symbol] ?? 0;
          if (weight < 0) sum += weight;
        }
        return sum;
      });
      if (restLong.some((value) => value !== 0)) series.push({ name: restLongLabel, data: restLong });
      if (restShort.some((value) => value !== 0)) series.push({ name: restShortLabel, data: restShort });
    }
    return { dates, series };
  }, [panel, restLongLabel, restShortLabel]);

  async function handleResolve(refresh: boolean) {
    if (!run.run_id || resolving) return;
    setResolving(true);
    setResolveError("");
    try {
      const result = await fetchRunSectorMap(run.run_id, refresh);
      setSectorMap(result);
    } catch (error) {
      setResolveError(error instanceof Error ? error.message : String(error));
    } finally {
      setResolving(false);
    }
  }

  if (panel.symbols.length === 0 || panel.dates.length === 0 || !latestDate) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        {t("runDetail.positions.noPositions")}
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      <PositionsPanelCard>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-xs text-muted-foreground">
            {t("runDetail.positions.asOf", { date: selectedDate })}
          </span>
          <span className="text-xs text-muted-foreground">
            {t("runDetail.positions.holdingsCount", { count: holdingsCount })}
          </span>
          <div className="ms-auto flex flex-wrap items-center gap-2">
            <div className="flex gap-1 rounded-md border border-border/60 p-0.5" role="group">
              {(["pie", "treemap"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  aria-pressed={mode === m}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs transition-colors",
                    mode === m
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-muted-foreground hover:bg-muted/60",
                  )}
                >
                  {t(m === "pie" ? "runDetail.positions.pie" : "runDetail.positions.treemap")}
                </button>
              ))}
            </div>
            {hasAShare && (
              <button
                type="button"
                onClick={() => void handleResolve(false)}
                disabled={resolving}
                className="flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted/60 disabled:opacity-60"
              >
                {resolving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {resolving ? t("runDetail.positions.resolving") : t("runDetail.positions.resolveIndustries")}
              </button>
            )}
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={Math.max(0, panel.dates.length - 1)}
            value={dateIndex}
            onChange={(event) => setDateIndex(Number(event.target.value))}
            aria-label={t("runDetail.positions.asOf", { date: selectedDate })}
            className="w-full accent-primary"
          />
          <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{selectedDate}</span>
        </div>
        {resolveError && (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-danger">
            <span>{t("runDetail.positions.resolveFailed")}: {resolveError}</span>
            <button
              type="button"
              onClick={() => void handleResolve(true)}
              disabled={resolving}
              className="rounded-md border border-danger/40 px-2 py-0.5 font-medium transition-colors hover:bg-danger/10 disabled:opacity-60"
            >
              {t("runDetail.positions.retry")}
            </button>
          </p>
        )}
      </PositionsPanelCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <PositionsPanelCard
          title={t("runDetail.positions.weightDistribution")}
          subtitle={t("runDetail.positions.basisGross")}
        >
          <WeightDistributionChart items={distributionItems} mode={mode} cashLabel={cashLabel} shortLabel={shortLabel} />
        </PositionsPanelCard>
        <PositionsPanelCard
          title={t("runDetail.positions.sectorDistribution")}
          subtitle={t("runDetail.positions.basisNet")}
        >
          <SectorDistributionChart items={sectorItems} cashLabel={cashLabel} />
        </PositionsPanelCard>
      </div>

      <PositionsPanelCard
        title={t("runDetail.positions.weightEvolution")}
        subtitle={t("runDetail.positions.basisNet")}
      >
        <WeightEvolutionChart dates={evolution.dates} series={evolution.series} />
      </PositionsPanelCard>
    </div>
  );
}

function PositionsPanelCard({
  title,
  subtitle,
  children,
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      {(title || subtitle) && (
        <header className="mb-3">
          {title && <h3 className="text-sm font-semibold">{title}</h3>}
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  );
}

function WeightDistributionChart({
  items,
  mode,
  cashLabel,
  shortLabel,
}: {
  items: DistributionItem[];
  mode: "pie" | "treemap";
  cashLabel: string;
  shortLabel: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();
    const palette = categoryColors(t);
    const data = items.map((item, index) => ({
      name:
        item.symbol === CASH_SYMBOL
          ? cashLabel
          : item.weight < 0
            ? `${item.symbol} ${shortLabel}`
            : item.symbol,
      value: item.sliceSize,
      assetClassLabel: item.assetClassLabel,
      weight: item.weight,
      itemStyle: {
        color: item.symbol === CASH_SYMBOL ? CASH_COLOR : palette[index % palette.length],
      },
    }));
    const tooltip = {
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 11 },
      formatter: (params: unknown) => {
        const p = params as { name: string; value: number; data?: { assetClassLabel?: string; weight?: number } };
        const label = p.data?.assetClassLabel ?? "";
        const signed = p.data?.weight ?? p.value;
        return `<b>${escapeHtml(p.name)}</b><br/>${label}: <b>${formatPercent(signed, 2)}</b>`;
      },
    };

    if (mode === "treemap") {
      return {
        backgroundColor: "transparent",
        tooltip: { ...tooltip, trigger: "item" },
        series: [
          {
            type: "treemap",
            data,
            width: "100%",
            height: "92%",
            top: 8,
            breadcrumb: { show: false },
            roam: false,
            nodeClick: false,
            label: { show: true, formatter: "{b}", fontSize: 11, color: "#ffffff" },
            itemStyle: { borderColor: t.tooltipBg, borderWidth: 1, gapWidth: 1 },
          },
        ],
      };
    }

    return {
      backgroundColor: "transparent",
      tooltip: { ...tooltip, trigger: "item" },
      legend: {
        type: "scroll",
        bottom: 0,
        textStyle: { color: t.textColor, fontSize: 10 },
        pageTextStyle: { color: t.textColor },
        pageIconColor: t.infoColor,
        pageIconInactiveColor: t.gridColor,
      },
      series: [
        {
          type: "pie",
          radius: ["32%", "62%"],
          center: ["50%", "44%"],
          data,
          label: { show: true, formatter: "{b} {d}%", fontSize: 10, color: t.textColor },
          labelLayout: { hideOverlap: true },
          itemStyle: { borderColor: t.tooltipBg, borderWidth: 1 },
        },
      ],
    };
  }, [items, mode]);

  return <div ref={ref} style={{ height: 320 }} />;
}

function SectorDistributionChart({ items, cashLabel }: { items: GroupedItem[]; cashLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();
    const palette = categoryColors(t);
    const ordered = [...items];
    const names = ordered.map((item) => item.group).reverse();
    const data = ordered.map((item, index) => ({
      value: item.weight,
      itemStyle: {
        color: item.isCash || item.group === cashLabel
          ? CASH_COLOR
          : palette[index % palette.length],
      },
    })).reverse();
    const { min, max } = signedAxisBounds(ordered.map((item) => item.weight));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        formatter: (params: unknown) => {
          const list = params as Array<{ name: string; value: number }>;
          if (!Array.isArray(list) || list.length === 0) return "";
          const p = list[0];
          return `<b>${escapeHtml(p.name)}</b>: <b>${formatPercent(p.value, 2)}</b>`;
        },
      },
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      xAxis: {
        type: "value",
        min,
        max,
        axisLabel: {
          color: t.textColor,
          fontSize: 10,
          formatter: (value: number) => formatPercent(value, 0),
        },
        splitLine: { lineStyle: { color: t.gridColor } },
      },
      yAxis: {
        type: "category",
        data: names,
        axisLabel: { color: t.textColor, fontSize: 10 },
        axisLine: { lineStyle: { color: t.axisColor } },
      },
      series: [
        {
          type: "bar",
          data,
          barMaxWidth: 16,
          label: {
            show: true,
            position: "right",
            fontSize: 10,
            color: t.textColor,
            formatter: (params: unknown) => formatPercent((params as { value: number }).value, 1),
          },
        },
      ],
    };
  }, [items, cashLabel]);

  return <div ref={ref} style={{ height: 320 }} />;
}

function WeightEvolutionChart({ dates, series }: { dates: string[]; series: EvolutionSeries[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();
    const palette = categoryColors(t);
    // ECharts stacks positives above zero and negatives below; bound the axis
    // by the per-date cumulative stack so neither side is clipped.
    const stackExtremes: number[] = [];
    for (let i = 0; i < dates.length; i += 1) {
      let positive = 0;
      let negative = 0;
      for (const s of series) {
        const value = s.data[i] ?? 0;
        if (value > 0) positive += value;
        else negative += value;
      }
      stackExtremes.push(positive, negative);
    }
    const { min, max } = signedAxisBounds(stackExtremes);
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        formatter: (params: unknown) => {
          const list = params as Array<{ seriesName: string; value: number; marker: string }>;
          if (!Array.isArray(list) || list.length === 0) return "";
          const rows = [...list]
            .sort((a, b) => b.value - a.value)
            .map((p) => `${p.marker} ${escapeHtml(p.seriesName)}: <b>${formatPercent(p.value, 2)}</b>`)
            .join("<br/>");
          return `<b>${escapeHtml(String((list[0] as { axisValue?: string }).axisValue ?? ""))}</b><br/>${rows}`;
        },
      },
      legend: {
        type: "scroll",
        top: 0,
        textStyle: { color: t.textColor, fontSize: 10 },
        pageTextStyle: { color: t.textColor },
        pageIconColor: t.infoColor,
        pageIconInactiveColor: t.gridColor,
      },
      grid: { left: 8, right: 16, top: 32, bottom: 24, containLabel: true },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        min,
        max,
        axisLabel: {
          color: t.textColor,
          fontSize: 10,
          formatter: (value: number) => formatPercent(value, 0),
        },
        splitLine: { lineStyle: { color: t.gridColor } },
      },
      series: series.map((s, index) => ({
        name: s.name,
        type: "line",
        stack: "weights",
        symbol: "none",
        smooth: false,
        data: s.data,
        lineStyle: { width: 1, color: palette[index % palette.length] },
        itemStyle: { color: palette[index % palette.length] },
        areaStyle: { opacity: 0.55 },
      })),
    };
  }, [dates, series]);

  return <div ref={ref} style={{ height: 360 }} />;
}
