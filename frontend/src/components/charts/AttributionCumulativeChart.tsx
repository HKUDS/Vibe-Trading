import { useRef } from "react";
import i18n from "@/i18n";
import type { AttributionCumulativePoint } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { getPnlColors } from "@/lib/pnl-colors";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";
import { escapeHtml } from "@/lib/escapeHtml";

interface Props {
  data: AttributionCumulativePoint[];
  height?: number;
}

export function AttributionCumulativeChart({ data, height = 300 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();
    const pnl = getPnlColors();

    const portfolioLabel = i18n.t("runDetail.attrPortfolio");
    const benchmarkLabel = i18n.t("runDetail.attrBenchmark");
    const activeLabel = i18n.t("runDetail.attrActive");
    const dates = data.map((d) => d.date);

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        formatter: (raw: unknown) => {
          const params = raw as Array<{ dataIndex?: number }>;
          if (!Array.isArray(params) || !params.length) return "";
          const point = data[params[0].dataIndex ?? 0];
          if (!point) return "";
          const pct = (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
          return `<b>${escapeHtml(point.date)}</b>`
            + `<br/>${portfolioLabel}: <b>${pct(point.portfolio)}</b>`
            + `<br/>${benchmarkLabel}: <b>${pct(point.benchmark)}</b>`
            + `<br/>${activeLabel}: <b>${pct(point.active)}</b>`;
        },
      },
      legend: {
        data: [portfolioLabel, benchmarkLabel, activeLabel],
        textStyle: { color: t.textColor, fontSize: 11 },
        right: 60,
        top: 4,
      },
      toolbox: {
        feature: {
          saveAsImage: { title: "Save" },
          restore: { title: "Reset" },
        },
        right: 8,
        top: 0,
        iconStyle: { borderColor: t.textColor },
      },
      grid: { left: 8, right: 8, top: 36, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: dates,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10, formatter: "{value}%" },
      },
      dataZoom: [{ type: "inside" }],
      series: [
        {
          name: portfolioLabel,
          type: "line",
          data: data.map((d) => +(d.portfolio * 100).toFixed(4)),
          smooth: false,
          symbol: "none",
          // itemStyle drives the legend swatch; keep it in sync with lineStyle.
          itemStyle: { color: t.infoColor },
          lineStyle: { color: t.infoColor, width: 2 },
        },
        {
          name: benchmarkLabel,
          type: "line",
          data: data.map((d) => +(d.benchmark * 100).toFixed(4)),
          smooth: false,
          symbol: "none",
          itemStyle: { color: t.textColor },
          lineStyle: { color: t.textColor, width: 1.5 },
        },
        {
          name: activeLabel,
          type: "line",
          data: data.map((d) => +(d.active * 100).toFixed(4)),
          smooth: false,
          symbol: "none",
          itemStyle: { color: pnl.profit },
          lineStyle: { color: pnl.profit, width: 1.5, type: "dashed" },
        },
      ],
    };
  }, [data]);

  if (data.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("runDetail.attrNoFactor")}</div>;
  }
  return <div ref={ref} style={{ height }} />;
}
