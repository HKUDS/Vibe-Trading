import { useEffect, useRef } from "react";
import i18n from "@/i18n";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

interface Props {
  weights: Record<string, number>;
  height?: number;
}

/** Latest basket weights. Long-only books get a donut; any short leg flips to signed bars. */
export function PositionsPieChart({ weights, height = 280 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current) return;
    const entries = Object.entries(weights)
      .filter(([, w]) => w !== 0)
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    if (entries.length === 0) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);
    const hasShort = entries.some(([, w]) => w < 0);

    if (!hasShort) {
      chart.setOption({
        backgroundColor: "transparent",
        tooltip: {
          trigger: "item",
          backgroundColor: t.tooltipBg,
          borderColor: t.tooltipBorder,
          textStyle: { color: t.tooltipText, fontSize: 11 },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter: (p: any) => `${p.marker} ${p.name}: <b>${(Number(p.value) * 100).toFixed(2)}%</b>`,
        },
        legend: {
          bottom: 0,
          textStyle: { color: t.textColor, fontSize: 10 },
          type: "scroll",
        },
        series: [
          {
            name: i18n.t("runDetail.latestWeights"),
            type: "pie",
            radius: ["42%", "68%"],
            center: ["50%", "46%"],
            label: { show: false },
            data: entries.map(([symbol, w]) => ({ name: symbol, value: +w.toFixed(6) })),
          },
        ],
      });
    } else {
      chart.setOption({
        backgroundColor: "transparent",
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          backgroundColor: t.tooltipBg,
          borderColor: t.tooltipBorder,
          textStyle: { color: t.tooltipText, fontSize: 11 },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter: (params: any) => {
            if (!Array.isArray(params) || !params.length) return "";
            const p = params[0];
            return `${p.marker} ${p.name}: <b>${(Number(p.value) * 100).toFixed(2)}%</b>`;
          },
        },
        grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
        xAxis: {
          type: "value",
          splitLine: { lineStyle: { color: t.gridColor } },
          axisLabel: { color: t.textColor, fontSize: 10, formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
        },
        yAxis: {
          type: "category",
          inverse: true,
          data: entries.map(([symbol]) => symbol),
          axisLine: { lineStyle: { color: t.axisColor } },
          axisLabel: { color: t.textColor, fontSize: 10 },
        },
        series: [
          {
            name: i18n.t("runDetail.latestWeights"),
            type: "bar",
            data: entries.map(([, w]) => ({
              value: +w.toFixed(6),
              itemStyle: { color: w >= 0 ? t.upColor : t.downColor },
            })),
            barMaxWidth: 18,
          },
        ],
      });
    }

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
  }, [weights, dark]);

  return <div ref={ref} style={{ height, width: "100%" }} />;
}
