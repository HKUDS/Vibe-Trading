import i18n from '@/i18n';
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { GitCompare, ArrowLeftRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type RunListItem, type RunData, type EquityPoint } from "@/lib/api";
import { echarts, CHART_GROUP, connectCharts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";
import { SkeletonChart, SkeletonMetrics } from "@/components/common/Skeleton";

interface MetricDef {
  key: string;
  label: string;
  type: "pct" | "num" | "int" | "days";
  higherIsBetter: boolean;
}

function fmt(v: unknown, type: "pct" | "num" | "int" | "days" = "num"): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "\u2014";
  if (type === "pct") return (n * 100).toFixed(2) + "%";
  if (type === "int") return n.toFixed(0);
  if (type === "days") return n.toFixed(1);
  return n.toFixed(3);
}

type DiffPresentation = {
  className: string;
  verdict: "better" | "worse" | null;
  glyph: "\u2191" | "\u2193" | null;
};

function diffClass(a: unknown, b: unknown, higherIsBetter: boolean): DiffPresentation {
  const na = Number(a), nb = Number(b);
  if (!Number.isFinite(na) || !Number.isFinite(nb)) {
    return { className: "", verdict: null, glyph: null };
  }
  const better = higherIsBetter ? nb > na : nb < na;
  const worse = higherIsBetter ? nb < na : nb > na;
  if (better) {
    return { className: "text-green-600 dark:text-green-400", verdict: "better", glyph: "\u2191" };
  }
  if (worse) {
    return { className: "text-red-600 dark:text-red-400", verdict: "worse", glyph: "\u2193" };
  }
  return { className: "", verdict: null, glyph: null };
}

function diffStr(a: unknown, b: unknown, type: "pct" | "num" | "int" | "days"): string {
  const na = Number(a), nb = Number(b);
  if (!Number.isFinite(na) || !Number.isFinite(nb)) return "\u2014";
  const d = nb - na;
  return (d > 0 ? "+" : "") + fmt(d, type);
}

function truncatePrompt(prompt: string | undefined, maxLen = 40): string {
  if (!prompt) return "";
  const trimmed = prompt.replace(/\n/g, " ").trim();
  return trimmed.length > maxLen ? trimmed.slice(0, maxLen) + "\u2026" : trimmed;
}

function runLabel(r: RunListItem): string {
  const summary = truncatePrompt(r.prompt);
  if (summary) return summary;
  return r.run_id;
}

const METRICS: MetricDef[] = [
  { key: "total_return",           label: i18n.t("compare.totalReturn"),         type: "pct", higherIsBetter: true },
  { key: "annualized_return",      label: i18n.t("compare.annualizedReturn"),    type: "pct", higherIsBetter: true },
  { key: "sharpe",                 label: i18n.t("compare.sharpeRatio"),         type: "num", higherIsBetter: true },
  { key: "calmar_ratio",           label: i18n.t("compare.calmarRatio"),         type: "num", higherIsBetter: true },
  { key: "sortino_ratio",          label: i18n.t("compare.sortinoRatio"),        type: "num", higherIsBetter: true },
  { key: "max_drawdown",           label: i18n.t("compare.maxDrawdown"),         type: "pct", higherIsBetter: false },
  { key: "volatility",             label: i18n.t("compare.volatility"),           type: "pct", higherIsBetter: false },
  { key: "win_rate",               label: i18n.t("compare.winRate"),             type: "pct", higherIsBetter: true },
  { key: "profit_factor",          label: i18n.t("compare.profitFactor"),        type: "num", higherIsBetter: true },
  { key: "avg_win",                label: i18n.t("compare.avgWin"),              type: "pct", higherIsBetter: true },
  { key: "avg_loss",               label: i18n.t("compare.avgLoss"),             type: "pct", higherIsBetter: false },
  { key: "trade_count",            label: i18n.t("compare.trades"),               type: "int", higherIsBetter: true },
  { key: "max_consecutive_losses", label: i18n.t("compare.maxConsecLosses"),   type: "int", higherIsBetter: false },
  { key: "exposure_time",          label: i18n.t("compare.exposureTime"),        type: "pct", higherIsBetter: true },
  { key: "avg_holding_period",     label: i18n.t("compare.avgHoldingPeriod"),   type: "days", higherIsBetter: false },
];

// Also accept backend aliases
const METRIC_ALIASES: Record<string, string> = {
  annual_return: "annualized_return",
  calmar: "calmar_ratio",
  sortino: "sortino_ratio",
  profit_loss_ratio: "profit_factor",
  max_consec_loss: "max_consecutive_losses",
  max_consecutive_loss: "max_consecutive_losses",
  avg_hold_days: "avg_holding_period",
  avg_holding_days: "avg_holding_period",
};

function resolveMetric(metrics: Record<string, number> | null, key: string): number | undefined {
  if (!metrics) return undefined;
  if (metrics[key] !== undefined) return metrics[key];
  // Check if any alias maps to this key
  for (const [alias, canonical] of Object.entries(METRIC_ALIASES)) {
    if (canonical === key && metrics[alias] !== undefined) return metrics[alias];
  }
  return undefined;
}

interface EquityChartOverlayProps {
  leftCurve: EquityPoint[];
  rightCurve: EquityPoint[];
  leftLabel: string;
  rightLabel: string;
  /** Rebase both curves to 100 at their first bar — runs with different
   * initial capital are only comparable on an indexed scale. */
  rebase: boolean;
}

function EquityChartOverlay({ leftCurve, rightCurve, leftLabel, rightLabel, rebase }: EquityChartOverlayProps) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current) return;
    if (leftCurve.length === 0 && rightCurve.length === 0) return;

    const t = getChartTheme();
    const chart = echarts.init(ref.current);
    chart.group = CHART_GROUP;
    connectCharts();

    // Merge dates from both curves and sort
    const dateSet = new Set<string>();
    for (const p of leftCurve) dateSet.add(p.time);
    for (const p of rightCurve) dateSet.add(p.time);
    const dates = Array.from(dateSet).sort();

    // Build lookup maps, optionally rebased to an index of 100
    const leftBase = Number(leftCurve[0]?.equity) || 0;
    const rightBase = Number(rightCurve[0]?.equity) || 0;
    const scale = (raw: number, base: number) =>
      rebase && base > 0 ? Number(((raw / base) * 100).toFixed(2)) : raw;
    const leftMap = new Map(leftCurve.map((p) => [p.time, scale(Number(p.equity), leftBase)]));
    const rightMap = new Map(rightCurve.map((p) => [p.time, scale(Number(p.equity), rightBase)]));

    const leftData = dates.map((d) => leftMap.get(d) ?? null);
    const rightData = dates.map((d) => rightMap.get(d) ?? null);

    const PRIMARY_COLOR = getComputedStyle(document.documentElement).getPropertyValue("--chart-compare-a").trim() || "#3b82f6";
    const SECONDARY_COLOR = getComputedStyle(document.documentElement).getPropertyValue("--chart-compare-b").trim() || "#f59e0b";

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (params: any) => {
          if (!Array.isArray(params) || !params.length) return "";
          let html = `<b>${params[0].axisValue}</b>`;
          for (const p of params) {
            if (p.value == null) continue;
            const value = rebase ? Number(p.value).toFixed(2) : Number(p.value).toLocaleString();
            html += `<br/>${p.marker} ${p.seriesName}: <b>${value}</b>`;
          }
          return html;
        },
      },
      legend: {
        data: [leftLabel, rightLabel],
        textStyle: { color: t.textColor, fontSize: 11 },
        right: 8,
        top: 4,
      },
      grid: { left: 8, right: 8, top: 36, bottom: 40, containLabel: true },
      xAxis: {
        type: "category",
        data: dates,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 20, bottom: 4 }],
      series: [
        {
          name: leftLabel,
          type: "line",
          data: leftData,
          smooth: false,
          symbol: "none",
          lineStyle: { color: PRIMARY_COLOR, width: 2 },
          connectNulls: true,
        },
        {
          name: rightLabel,
          type: "line",
          data: rightData,
          smooth: false,
          symbol: "none",
          lineStyle: { color: SECONDARY_COLOR, width: 2 },
          connectNulls: true,
        },
      ],
    });

    let resizeFrame: number | null = null;
    const ro = new ResizeObserver(() => {
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null;
        chart.resize();
      });
    });
    ro.observe(ref.current!);
    return () => {
      ro.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      chart.dispose();
    };
  }, [leftCurve, rightCurve, leftLabel, rightLabel, rebase, dark]);

  if (leftCurve.length === 0 && rightCurve.length === 0) return null;

  return <div ref={ref} style={{ height: 320 }} />;
}

export function Compare() {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [leftId, setLeftId] = useState("");
  const [rightId, setRightId] = useState("");
  const [leftData, setLeftData] = useState<Record<string, number> | null>(null);
  const [rightData, setRightData] = useState<Record<string, number> | null>(null);
  const [leftCurve, setLeftCurve] = useState<EquityPoint[]>([]);
  const [rightCurve, setRightCurve] = useState<EquityPoint[]>([]);
  const [leftLoading, setLeftLoading] = useState(false);
  const [rightLoading, setRightLoading] = useState(false);
  const [rebase, setRebase] = useState(true);
  const leftRequestGeneration = useRef(0);
  const rightRequestGeneration = useRef(0);

  useEffect(() => {
    api.listRuns().then((items) => {
      setRuns(Array.isArray(items) ? items : []);
      if (items.length >= 2) { setLeftId(items[1].run_id); setRightId(items[0].run_id); }
      else if (items.length === 1) { setLeftId(items[0].run_id); }
    }).catch((error) => {
      toast.error(error instanceof Error ? error.message : i18n.t("compare.loadError"));
    });
  }, []);

  useEffect(() => {
    const generation = ++leftRequestGeneration.current;
    setLeftData(null);
    setLeftCurve([]);

    if (!leftId) {
      setLeftLoading(false);
      return;
    }

    setLeftLoading(true);
    api.getRun(leftId).then((d: RunData) => {
      if (leftRequestGeneration.current === generation) {
        setLeftData(d.metrics || null);
        setLeftCurve(d.equity_curve || []);
      }
    }).catch((error) => {
      if (leftRequestGeneration.current === generation) {
        setLeftData(null);
        setLeftCurve([]);
        toast.error(error instanceof Error ? error.message : i18n.t("compare.loadError"));
      }
    }).finally(() => {
      if (leftRequestGeneration.current === generation) setLeftLoading(false);
    });

    return () => {
      if (leftRequestGeneration.current === generation) leftRequestGeneration.current += 1;
    };
  }, [leftId]);

  useEffect(() => {
    const generation = ++rightRequestGeneration.current;
    setRightData(null);
    setRightCurve([]);

    if (!rightId) {
      setRightLoading(false);
      return;
    }

    setRightLoading(true);
    api.getRun(rightId).then((d: RunData) => {
      if (rightRequestGeneration.current === generation) {
        setRightData(d.metrics || null);
        setRightCurve(d.equity_curve || []);
      }
    }).catch((error) => {
      if (rightRequestGeneration.current === generation) {
        setRightData(null);
        setRightCurve([]);
        toast.error(error instanceof Error ? error.message : i18n.t("compare.loadError"));
      }
    }).finally(() => {
      if (rightRequestGeneration.current === generation) setRightLoading(false);
    });

    return () => {
      if (rightRequestGeneration.current === generation) rightRequestGeneration.current += 1;
    };
  }, [rightId]);

  const leftRun = runs.find((r) => r.run_id === leftId);
  const rightRun = runs.find((r) => r.run_id === rightId);
  const loading = leftLoading || rightLoading;
  const hasData = Boolean(leftData || rightData);

  return (
    <div className="mx-auto max-w-5xl p-8 space-y-6">
      <h1 className="flex items-center gap-2 text-2xl font-semibold">
        <GitCompare className="h-5 w-5" aria-hidden="true" /> {t("compare.title")}
      </h1>

      {/* Selectors */}
      <div className="flex gap-4 items-end rounded-xl border border-border/60 bg-card p-4 shadow-sm">
        <div className="flex-1">
          <label className="text-xs text-muted-foreground block mb-1">{i18n.t("compare.baseline")}</label>
          <select value={leftId} onChange={(e) => setLeftId(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-border/60 bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" title={leftRun?.prompt || leftId}>
            <option value="">{i18n.t("compare.select")}</option>
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)} ({r.status})</option>)}
          </select>
        </div>
        <button
          type="button"
          onClick={() => { setLeftId(rightId); setRightId(leftId); }}
          title={i18n.t("compare.swapRuns")}
          className="mb-1 shrink-0 rounded-md border border-border/60 p-2 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
        >
          <ArrowLeftRight className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">{i18n.t("compare.swapRuns")}</span>
        </button>
        <div className="flex-1">
          <label className="text-xs text-muted-foreground block mb-1">{i18n.t("compare.compare")}</label>
          <select value={rightId} onChange={(e) => setRightId(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-border/60 bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" title={rightRun?.prompt || rightId}>
            <option value="">{i18n.t("compare.select")}</option>
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)} ({r.status})</option>)}
          </select>
        </div>
      </div>

      {/* Loading state — show skeletons while a selected run's data is in flight */}
      {loading && !hasData && (
        <div className="space-y-6">
          <div className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-muted-foreground mb-2">{i18n.t("compare.equityDrawdown")}</h2>
            <SkeletonChart height={320} />
          </div>
          <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
            <SkeletonMetrics />
          </div>
        </div>
      )}

      {/* Equity curve overlay */}
      {(leftCurve.length > 0 || rightCurve.length > 0) && (
        <div className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-muted-foreground">{i18n.t("compare.equityOverlay")}</h2>
            <div className="flex gap-1 text-xs" role="group">
              {[
                { id: true, label: i18n.t("compare.rebasedMode") },
                { id: false, label: i18n.t("compare.rawMode") },
              ].map((mode) => (
                <button
                  key={String(mode.id)}
                  type="button"
                  onClick={() => setRebase(mode.id)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 transition-colors",
                    rebase === mode.id
                      ? "border-primary/30 bg-primary/10 font-medium text-primary"
                      : "border-border/60 text-muted-foreground hover:bg-muted/60",
                  )}
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </div>
          <EquityChartOverlay
            leftCurve={leftCurve}
            rightCurve={rightCurve}
            leftLabel={leftRun ? truncatePrompt(leftRun.prompt, 20) || t("compare.baseline") : t("compare.baseline")}
            rightLabel={rightRun ? truncatePrompt(rightRun.prompt, 20) || t("compare.compare") : t("compare.compare")}
            rebase={rebase}
          />
        </div>
      )}

      {/* Metrics table */}
      {(leftData || rightData) && (
        <div className="overflow-x-auto rounded-xl border border-border/60 bg-card shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-[11px] uppercase tracking-wide text-muted-foreground [&_th]:font-medium">
                <th className="text-left px-4 py-2.5 font-medium">{i18n.t("compare.metric")}</th>
                <th className="text-right px-4 py-2.5 font-medium">{i18n.t("compare.baselineCol")}</th>
                <th className="text-right px-4 py-2.5 font-medium">{i18n.t("compare.compareCol")}</th>
                <th className="text-right px-4 py-2.5 font-medium">{i18n.t("compare.delta")}</th>
              </tr>
            </thead>
            <tbody>
              {METRICS.map(({ key, label, type, higherIsBetter }) => {
                const lv = resolveMetric(leftData, key);
                const rv = resolveMetric(rightData, key);
                const diff = diffClass(lv, rv, higherIsBetter);
                // Proportional in-cell bars (colored to match the chart legend)
                // make the winner readable at a glance without parsing numbers.
                const la = Number.isFinite(Number(lv)) ? Math.abs(Number(lv)) : null;
                const ra = Number.isFinite(Number(rv)) ? Math.abs(Number(rv)) : null;
                const maxAbs = Math.max(la ?? 0, ra ?? 0);
                const shareL = la != null && maxAbs > 0 ? la / maxAbs : 0;
                const shareR = ra != null && maxAbs > 0 ? ra / maxAbs : 0;
                const leftWins = diff.verdict === "worse";
                const rightWins = diff.verdict === "better";
                return (
                  <tr key={key} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-4 py-2.5 font-medium">{label}</td>
                    <td className="relative px-4 py-2.5 text-right font-mono tabular-nums">
                      {shareL > 0 && (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-1.5 end-2 rounded-sm"
                          style={{ width: `${shareL * 55}%`, backgroundColor: "var(--chart-compare-a)", opacity: 0.14 }}
                        />
                      )}
                      <span className={cn("relative", leftWins && "font-semibold")}>{fmt(lv, type)}</span>
                    </td>
                    <td className="relative px-4 py-2.5 text-right font-mono tabular-nums">
                      {shareR > 0 && (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-1.5 end-2 rounded-sm"
                          style={{ width: `${shareR * 55}%`, backgroundColor: "var(--chart-compare-b)", opacity: 0.14 }}
                        />
                      )}
                      <span className={cn("relative", rightWins && "font-semibold")}>{fmt(rv, type)}</span>
                    </td>
                    <td className={cn("px-4 py-2.5 text-right font-mono tabular-nums font-semibold", diff.className)}>
                      {diff.verdict && (
                        <>
                          <span aria-hidden="true">{diff.glyph} </span>
                          <span className="sr-only">
                            {t(`compare.${diff.verdict}`)}
                            {": "}
                          </span>
                        </>
                      )}
                      {diffStr(lv, rv, type)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!hasData && !loading && (
        <div className="text-center py-16 text-muted-foreground">
          <GitCompare className="h-12 w-12 mx-auto mb-3 opacity-20" />
          <p className="text-sm">{i18n.t("compare.selectTwoRuns")}</p>
        </div>
      )}
    </div>
  );
}
