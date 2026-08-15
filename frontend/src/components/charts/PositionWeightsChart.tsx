import { useEffect, useRef } from "react";
import i18n from "@/i18n";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";
import type { WeightPoint } from "@/lib/positions";

interface Props {
  points: WeightPoint[];
  symbols: string[];
  height?: number;
}

/** Per-rebalance weight evolution as a stacked area, top symbols plus Other. */
export function PositionWeightsChart({ points, symbols, height = 300 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current || points.length === 0) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);
    const hasOther = points.some((p) => p.Other !== undefined);
    const seriesNames = hasOther ? [...symbols, "Other"] : symbols;

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (params: any) => {
          if (!Array.isArray(params) || !params.length) return "";
          const lines = params
            .filter((p) => Number(p.value) !== 0)
            .map((p) => `${p.marker} ${p.seriesName}: <b>${(Number(p.value) * 100).toFixed(1)}%</b>`);
          return `<b>${params[0].axisValue}</b><br/>${lines.join("<br/>")}`;
        },
      },
      legend: {
        bottom: 0,
        textStyle: { color: t.textColor, fontSize: 10 },
        type: "scroll",
      },
      grid: { left: 8, right: 8, top: 16, bottom: 28, containLabel: true },
      xAxis: {
        type: "category",
        data: points.map((p) => p.time),
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10, formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: seriesNames.map((name) => ({
        name: name === "Other" ? i18n.t("runDetail.other") : name,
        type: "line",
        stack: "weights",
        areaStyle: { opacity: 0.35 },
        showSymbol: false,
        emphasis: { focus: "series" },
        data: points.map((p) => +(Number(p[name] ?? 0)).toFixed(6)),
      })),
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, symbols, dark]);

  return <div ref={ref} style={{ height, width: "100%" }} />;
}
