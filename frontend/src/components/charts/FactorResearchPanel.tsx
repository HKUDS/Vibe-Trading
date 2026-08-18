import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { BarChart3, Grid3x3, LineChart, Sigma } from "lucide-react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";
import { cn } from "@/lib/utils";
import type { FactorReportPayload, FactorResult } from "@/lib/api";
import { RunCardPanel, RunCardStat } from "@/components/run/RunCard";
import { CorrelationMatrix } from "./CorrelationMatrix";

const SLATE = "#8f98a6";
const IC_MA_WINDOW = 20;
const MAX_CHART_POINTS = 500;

function num(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function fixed(value: unknown, digits = 4): string {
  const parsed = num(value);
  return parsed == null ? "—" : parsed.toFixed(digits);
}

function pct(value: unknown, digits = 2): string {
  const parsed = num(value);
  return parsed == null ? "—" : `${(parsed * 100).toFixed(digits)}%`;
}

function signedPct(value: unknown, digits = 2): string {
  const parsed = num(value);
  return parsed == null ? "—" : `${parsed > 0 ? "+" : ""}${(parsed * 100).toFixed(digits)}%`;
}

function signTone(value: unknown): "normal" | "positive" | "negative" {
  const parsed = num(value);
  if (parsed == null || parsed === 0) return "normal";
  return parsed > 0 ? "positive" : "negative";
}

/** Stride-sample long series for rendering, keeping the LAST point pinned. */
function downsample<T>(rows: T[], maxPoints = MAX_CHART_POINTS): T[] {
  if (rows.length <= maxPoints) return rows;
  const stride = Math.floor(rows.length / maxPoints);
  const sampled: T[] = [];
  for (let i = 0; i < rows.length; i += stride) sampled.push(rows[i]);
  if (sampled[sampled.length - 1] !== rows[rows.length - 1]) {
    sampled.push(rows[rows.length - 1]);
  }
  return sampled;
}

/** Simple moving average; the first window-1 points are null (skipped). */
function movingAverage(values: number[], window = IC_MA_WINDOW): Array<number | null> {
  return values.map((_, index) => {
    if (index + 1 < window) return null;
    let sum = 0;
    for (let i = index + 1 - window; i <= index; i += 1) sum += values[i];
    return sum / window;
  });
}

type IcRow = { date: string; ic: number; ma: number | null };

function groupColumnsOf(factor: FactorResult, rows: FactorResult["group_equity"]): string[] {
  const present = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (key !== "date") present.add(key);
    }
  }
  const declared = Array.from({ length: Math.max(0, factor.n_groups || 0) }, (_, i) => `Group_${i + 1}`)
    .filter((col) => present.has(col));
  if (declared.length > 0) return declared;
  return [...present].sort((a, b) => {
    const suffixA = Number(a.split("_")[1] || 0);
    const suffixB = Number(b.split("_")[1] || 0);
    return suffixA - suffixB;
  });
}

export function FactorResearchPanel({ report }: { report: FactorReportPayload }) {
  const { t } = useTranslation();
  const icRef = useRef<HTMLDivElement>(null);
  const equityRef = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  const factors = report.factors;
  const [selectedName, setSelectedName] = useState(factors[0]?.name ?? "");
  const selected = useMemo(
    () => factors.find((factor) => factor.name === selectedName) || factors[0] || null,
    [factors, selectedName],
  );

  const icRows = useMemo<IcRow[]>(() => {
    if (!selected || !selected.ic_series?.length) return [];
    const series = selected.ic_series;
    const ma = movingAverage(series.map((point) => point.ic));
    const rows = series.map((point, index) => ({ date: point.date, ic: point.ic, ma: ma[index] }));
    return downsample(rows);
  }, [selected]);

  const equityData = useMemo(() => {
    if (!selected || !selected.group_equity?.length) {
      return { rows: [] as FactorResult["group_equity"], columns: [] as string[] };
    }
    const rows = downsample(selected.group_equity);
    return { rows, columns: groupColumnsOf(selected, rows) };
  }, [selected]);

  useEffect(() => {
    const theme = getChartTheme();
    const axis = {
      axisLine: { lineStyle: { color: theme.axisColor } },
      axisLabel: { color: theme.textColor, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.gridColor } },
    };
    const charts: ReturnType<typeof echarts.init>[] = [];
    const nodes: HTMLDivElement[] = [];

    if (icRef.current && icRows.length > 0) {
      const icChart = echarts.init(icRef.current);
      icChart.setOption({
        backgroundColor: "transparent",
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        legend: { top: 0, right: 4, textStyle: { color: theme.textColor, fontSize: 10 } },
        grid: { left: 18, right: 22, top: 32, bottom: 18, containLabel: true },
        xAxis: { ...axis, type: "category", data: icRows.map((row) => row.date) },
        yAxis: { ...axis, type: "value" },
        series: [
          {
            name: t("factor.icSeries"),
            type: "bar",
            barMaxWidth: 8,
            // Neutral series color drives the legend swatch; per-point itemStyle below keeps sign coloring.
            color: SLATE,
            data: icRows.map((row) => ({
              value: row.ic,
              itemStyle: { color: row.ic >= 0 ? theme.upColor : theme.downColor },
            })),
            markLine: {
              symbol: "none",
              silent: true,
              label: { show: false },
              lineStyle: { color: theme.axisColor, type: "dashed" },
              data: [{ yAxis: 0 }],
            },
          },
          {
            name: t("factor.icMa"),
            type: "line",
            showSymbol: false,
            connectNulls: false,
            data: icRows.map((row) => row.ma),
            lineStyle: { color: theme.infoColor, width: 1.5 },
            itemStyle: { color: theme.infoColor },
          },
        ],
      });
      charts.push(icChart);
      nodes.push(icRef.current);
    }

    if (equityRef.current && equityData.rows.length > 0 && equityData.columns.length > 0) {
      const equityChart = echarts.init(equityRef.current);
      equityChart.setOption({
        backgroundColor: "transparent",
        tooltip: { trigger: "axis" },
        legend: { top: 0, right: 4, textStyle: { color: theme.textColor, fontSize: 10 } },
        grid: { left: 18, right: 22, top: 32, bottom: 18, containLabel: true },
        xAxis: { ...axis, type: "category", data: equityData.rows.map((row) => row.date), boundaryGap: false },
        yAxis: { ...axis, type: "value", scale: true },
        series: equityData.columns.map((col, index) => {
          const isTop = index === equityData.columns.length - 1;
          const isBottom = index === 0 && equityData.columns.length > 1;
          const color = isTop ? theme.upColor : isBottom ? theme.downColor : SLATE;
          return {
            name: col,
            type: "line",
            showSymbol: false,
            data: equityData.rows.map((row) => num(row[col])),
            lineStyle: { color, width: isTop || isBottom ? 2 : 1.2 },
            itemStyle: { color },
          };
        }),
      });
      charts.push(equityChart);
      nodes.push(equityRef.current);
    }

    if (charts.length === 0) return;

    let frame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (frame != null) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => charts.forEach((chart) => chart.resize()));
    });
    nodes.forEach((node) => observer.observe(node));
    return () => {
      observer.disconnect();
      if (frame != null) cancelAnimationFrame(frame);
      charts.forEach((chart) => chart.dispose());
    };
  }, [dark, icRows, equityData, t]);

  if (factors.length === 0 || !selected) {
    return <div className="p-8 text-center text-sm text-muted-foreground">{t("factor.noFactorData")}</div>;
  }

  const stats = selected.ic_stats;
  const correlation = report.ic_correlation;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight">{t("factor.title")}</h2>
          <p data-testid="factor-selected" className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{selected.name}</p>
        </div>
        {factors.length >= 2 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="mr-1 text-xs text-muted-foreground">{t("factor.selectFactor")}</span>
            {factors.map((factor) => (
              <button
                key={factor.name}
                type="button"
                onClick={() => setSelectedName(factor.name)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                  selected.name === factor.name
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:bg-muted/60",
                )}
              >
                {factor.name}
              </button>
            ))}
          </div>
        )}
      </div>

      <RunCardPanel title={t("factor.icStats")} icon={Sigma}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <RunCardStat label={t("factor.icMean")} value={fixed(stats?.ic_mean)} tone={signTone(stats?.ic_mean)} />
          <RunCardStat label={t("factor.icStd")} value={fixed(stats?.ic_std)} />
          <RunCardStat label={t("factor.ir")} value={fixed(stats?.ir)} tone={signTone(stats?.ir)} />
          <RunCardStat label={t("factor.icPositiveRatio")} value={pct(stats?.ic_positive_ratio)} />
          <RunCardStat label={t("factor.icCount")} value={stats?.ic_count != null ? String(stats.ic_count) : "—"} />
          <RunCardStat label={t("factor.longShortSpread")} value={signedPct(selected.long_short_spread)} tone={signTone(selected.long_short_spread)} />
          <RunCardStat label={t("factor.nGroups")} value={selected.n_groups ? String(selected.n_groups) : "—"} />
        </div>
      </RunCardPanel>

      {icRows.length > 0 && (
        <RunCardPanel title={t("factor.icSeries")} icon={BarChart3}>
          <div ref={icRef} className="h-[320px]" />
        </RunCardPanel>
      )}

      {equityData.rows.length > 0 && equityData.columns.length > 0 && (
        <RunCardPanel title={t("factor.quantileEquity")} icon={LineChart}>
          <div ref={equityRef} className="h-[360px]" />
          <p className="mt-2 text-xs text-muted-foreground">{t("factor.quantileEquityNote")}</p>
        </RunCardPanel>
      )}

      {correlation && (
        <RunCardPanel title={t("factor.correlation")} icon={Grid3x3}>
          <CorrelationMatrix labels={correlation.labels} matrix={correlation.matrix} height={420} />
          <p className="mt-2 text-xs text-muted-foreground">{t("factor.correlationNote")}</p>
        </RunCardPanel>
      )}
      {!correlation && factors.length >= 2 && (
        <p className="text-xs text-muted-foreground">{t("factor.insufficientOverlap")}</p>
      )}
    </div>
  );
}
