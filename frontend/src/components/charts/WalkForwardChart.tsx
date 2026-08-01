import { useEffect, useRef } from "react";
import i18n from "@/i18n";
import type { ValidationData } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

type WalkForwardWindow = NonNullable<ValidationData["walk_forward"]>["windows"][number];

interface Props {
  windows: WalkForwardWindow[];
  height?: number;
}

/** Per-window OOS returns as sign-colored bars with the Sharpe line overlaid. */
export function WalkForwardChart({ windows, height = 200 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current || windows.length === 0) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);

    const returnName = i18n.t("validation.return");
    const sharpeName = i18n.t("reports.sharpe");

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
          const w = windows[params[0].dataIndex];
          let html = `<b>${w ? `${w.start} ~ ${w.end}` : params[0].axisValue}</b>`;
          for (const p of params) {
            const suffix = p.seriesName === returnName ? "%" : "";
            html += `<br/>${p.marker} ${p.seriesName}: <b>${Number(p.value).toFixed(2)}${suffix}</b>`;
          }
          return html;
        },
      },
      legend: {
        data: [returnName, sharpeName],
        textStyle: { color: t.textColor, fontSize: 11 },
        top: 0,
      },
      grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
      xAxis: {
        type: "category",
        data: windows.map((w) => `W${w.window}`),
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: [
        {
          type: "value",
          splitLine: { lineStyle: { color: t.gridColor } },
          axisLabel: { color: t.textColor, fontSize: 10, formatter: "{value}%" },
        },
        {
          type: "value",
          splitLine: { show: false },
          axisLabel: { color: t.textColor, fontSize: 10 },
        },
      ],
      series: [
        {
          name: returnName,
          type: "bar",
          yAxisIndex: 0,
          data: windows.map((w) => Number((w.return * 100).toFixed(2))),
          barMaxWidth: 42,
          itemStyle: {
            borderRadius: [2, 2, 0, 0],
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            color: (params: any) => (Number(params.value) >= 0 ? t.upColor : t.downColor),
          },
        },
        {
          name: sharpeName,
          type: "line",
          yAxisIndex: 1,
          data: windows.map((w) => Number(w.sharpe.toFixed(2))),
          symbol: "circle",
          symbolSize: 5,
          lineStyle: { color: t.infoColor, width: 1.5 },
          itemStyle: { color: t.infoColor },
        },
      ],
    });

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current!);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [windows, dark]);

  if (windows.length === 0) return null;
  return <div ref={ref} style={{ height }} />;
}
