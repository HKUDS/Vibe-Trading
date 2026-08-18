import { useRef } from "react";
import i18n from "@/i18n";
import type { AnnualReturn } from "@/lib/tearsheet";
import { getChartTheme } from "@/lib/chart-theme";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";

interface Props {
  data: AnnualReturn[];
  height?: number;
}

export function AnnualReturnsChart({ data, height = 260 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();

    const seriesName = i18n.t("runDetail.annualReturns");

    return {
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
          const v = Number(p.value);
          const pct = `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
          return `<b>${p.axisValue}</b><br/>${p.marker} ${p.seriesName}: <b>${pct}</b>`;
        },
      },
      grid: { left: 8, right: 8, top: 28, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: data.map((d) => String(d.year)),
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10, formatter: "{value}%" },
      },
      series: [
        {
          name: seriesName,
          type: "bar",
          data: data.map((d) => ({
            value: +(d.ret * 100).toFixed(2),
            itemStyle: { color: d.ret >= 0 ? t.upColor : t.downColor },
            label: {
              show: true,
              position: d.ret >= 0 ? "top" : "bottom",
              formatter: `${d.ret > 0 ? "+" : ""}${(d.ret * 100).toFixed(1)}%`,
              fontSize: 10,
              color: t.textColor,
            },
          })),
          barMaxWidth: 36,
          markLine: {
            silent: true,
            symbol: "none",
            data: [{ yAxis: 0 }],
            lineStyle: { color: t.axisColor, width: 1 },
            label: { show: false },
          },
        },
      ],
    };
  }, [data]);

  if (data.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("runDetail.noTearsheetData")}</div>;
  }
  return <div ref={ref} style={{ height }} />;
}
