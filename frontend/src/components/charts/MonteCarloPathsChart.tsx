import { useEffect, useRef } from "react";
import i18n from "@/i18n";
import type { MonteCarloEquityPaths } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { abbreviateNum } from "@/lib/formatters";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

interface Props {
  paths: MonteCarloEquityPaths;
  height?: number;
}

/**
 * Monte Carlo fan chart: sampled shuffled-order equity paths (thin), the
 * P5–P95 / P25–P75 percentile envelope (shaded), the median (dashed), and
 * the actual path (bold) — all over trade sequence number, since the
 * simulation permutes trade order rather than calendar time.
 */
export function MonteCarloPathsChart({ paths, height = 260 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current || paths.steps.length === 0) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);

    const actualLabel = i18n.t("validation.actualLabel");
    const medianLabel = i18n.t("validation.medianLabel");
    const diff = (upper: number[], lower: number[]) => upper.map((v, i) => v - lower[i]);

    const bandSeries = (
      stackId: string,
      lower: number[],
      upper: number[],
      name: string,
      opacity: string,
    ) => ([
      {
        name: `${stackId}-base`,
        type: "line",
        stack: stackId,
        data: lower,
        symbol: "none",
        silent: true,
        lineStyle: { opacity: 0 },
        tooltip: { show: false },
        emphasis: { disabled: true },
      },
      {
        name,
        type: "line",
        stack: stackId,
        data: diff(upper, lower),
        symbol: "none",
        silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: { color: t.infoColor + opacity },
        tooltip: { show: false },
        emphasis: { disabled: true },
      },
    ]);

    const sampleSeries = paths.samples.map((row, index) => ({
      name: `sim-${index}`,
      type: "line",
      data: row,
      symbol: "none",
      silent: true,
      animation: false,
      lineStyle: { color: t.textColor, opacity: 0.1, width: 1 },
      tooltip: { show: false },
      emphasis: { disabled: true },
    }));

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
      },
      legend: {
        data: [actualLabel, medianLabel, "P25–P75", "P5–P95"],
        textStyle: { color: t.textColor, fontSize: 11 },
        top: 0,
      },
      grid: { left: 8, right: 8, top: 30, bottom: 22, containLabel: true },
      xAxis: {
        type: "category",
        data: paths.steps,
        name: i18n.t("validation.tradeNumber"),
        nameLocation: "middle",
        nameGap: 22,
        nameTextStyle: { color: t.textColor, fontSize: 10 },
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10, formatter: (v: number) => abbreviateNum(v) },
      },
      series: [
        ...bandSeries("outer", paths.band_p5, paths.band_p95, "P5–P95", "1f"),
        ...bandSeries("inner", paths.band_p25, paths.band_p75, "P25–P75", "33"),
        ...sampleSeries,
        {
          name: medianLabel,
          type: "line",
          data: paths.band_p50,
          symbol: "none",
          lineStyle: { color: t.textColor, width: 1, type: "dashed" },
        },
        {
          name: actualLabel,
          type: "line",
          data: paths.actual,
          symbol: "none",
          z: 10,
          lineStyle: { color: t.warningColor, width: 2.5 },
        },
      ],
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current!);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [paths, dark]);

  if (paths.steps.length === 0) return null;
  return <div ref={ref} style={{ height }} />;
}
