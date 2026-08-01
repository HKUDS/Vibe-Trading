import { useEffect, useRef } from "react";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

interface Props {
  /** Raw simulation samples (e.g. simulated Sharpe ratios). */
  samples: number[];
  /** Observed value highlighted with a vertical marker line. */
  markerValue: number;
  markerLabel: string;
  /** Optional shaded interval (e.g. P5–P95 or a bootstrap CI). */
  bandFrom?: number;
  bandTo?: number;
  bandLabel?: string;
  height?: number;
}

/** Histogram of a simulation distribution with an observed-value marker. */
export function DistributionChart({
  samples,
  markerValue,
  markerLabel,
  bandFrom,
  bandTo,
  bandLabel,
  height = 200,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current || samples.length === 0) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);

    let lo = Math.min(markerValue, ...samples);
    let hi = Math.max(markerValue, ...samples);
    if (lo === hi) { lo -= 0.5; hi += 0.5; }
    const binCount = Math.min(60, Math.max(20, Math.round(Math.sqrt(samples.length))));
    const binWidth = (hi - lo) / binCount;
    const counts = new Array<number>(binCount).fill(0);
    for (const sample of samples) {
      const bin = Math.min(binCount - 1, Math.max(0, Math.floor((sample - lo) / binWidth)));
      counts[bin] += 1;
    }
    const labels = counts.map((_, i) => (lo + (i + 0.5) * binWidth).toFixed(2));
    const toIndex = (value: number) =>
      Math.max(0, Math.min(binCount - 1, (value - lo) / binWidth - 0.5));

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 8, right: 8, top: 28, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
      },
      xAxis: {
        type: "category",
        data: labels,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10, interval: Math.max(1, Math.ceil(binCount / 8)) },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      series: [{
        type: "bar",
        data: counts,
        barCategoryGap: "12%",
        itemStyle: { color: t.infoColor + "99", borderRadius: [2, 2, 0, 0] },
        markLine: {
          silent: true,
          symbol: "none",
          data: [{
            xAxis: toIndex(markerValue),
            label: { formatter: markerLabel, color: t.warningColor, fontSize: 10, position: "insideEndTop" },
          }],
          lineStyle: { color: t.warningColor, width: 2 },
        },
        ...(bandFrom != null && bandTo != null ? {
          markArea: {
            silent: true,
            itemStyle: { color: t.infoColor + "14" },
            label: { color: t.textColor, fontSize: 10 },
            data: [[
              { xAxis: toIndex(bandFrom), ...(bandLabel ? { name: bandLabel } : {}) },
              { xAxis: toIndex(bandTo) },
            ]],
          },
        } : {}),
      }],
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current!);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [samples, markerValue, markerLabel, bandFrom, bandTo, bandLabel, dark]);

  if (samples.length === 0) return null;
  return <div ref={ref} style={{ height }} />;
}
