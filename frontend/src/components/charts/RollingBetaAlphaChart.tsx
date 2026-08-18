import { useRef } from "react";
import i18n from "@/i18n";
import type { AttributionRollingPoint } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";
import { escapeHtml } from "@/lib/escapeHtml";

interface Props {
  data: AttributionRollingPoint[];
  height?: number;
}

export function RollingBetaAlphaChart({ data, height = 280 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();

    const betaLabel = i18n.t("runDetail.attrBeta");
    const alphaLabel = i18n.t("runDetail.attrAlpha");
    const dates = data.map((d) => d.date);
    const betas = data.map((d) => +d.beta.toFixed(4));
    const alphas = data.map((d) => +(d.alpha_annualized * 100).toFixed(4));

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
          return `<b>${escapeHtml(point.date)}</b>`
            + `<br/>${betaLabel}: <b>${point.beta.toFixed(2)}</b>`
            + `<br/>${alphaLabel}: <b>${(point.alpha_annualized * 100).toFixed(2)}%</b>`;
        },
      },
      legend: {
        data: [betaLabel, alphaLabel],
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
      yAxis: [
        {
          type: "value",
          name: betaLabel,
          nameTextStyle: { color: t.textColor, fontSize: 10 },
          splitLine: { lineStyle: { color: t.gridColor } },
          axisLabel: { color: t.textColor, fontSize: 10 },
        },
        {
          type: "value",
          name: alphaLabel,
          nameTextStyle: { color: t.textColor, fontSize: 10 },
          splitLine: { show: false },
          axisLabel: { color: t.textColor, fontSize: 10, formatter: "{value}%" },
        },
      ],
      dataZoom: [{ type: "inside" }],
      series: [
        {
          name: betaLabel,
          type: "line",
          yAxisIndex: 0,
          data: betas,
          smooth: false,
          symbol: "none",
          // itemStyle drives the legend swatch; keep it in sync with lineStyle.
          itemStyle: { color: t.infoColor },
          lineStyle: { color: t.infoColor, width: 2 },
        },
        {
          name: alphaLabel,
          type: "line",
          yAxisIndex: 1,
          data: alphas,
          smooth: false,
          symbol: "none",
          itemStyle: { color: t.warningColor },
          lineStyle: { color: t.warningColor, width: 1.5 },
        },
      ],
    };
  }, [data]);

  if (data.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("runDetail.attrNoFactor")}</div>;
  }
  return <div ref={ref} style={{ height }} />;
}
