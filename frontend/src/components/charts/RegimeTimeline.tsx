import { useEffect, useRef } from "react";
import i18n from "@/i18n";
import type { CorrelationRegimeResponse } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

interface Props {
  data: CorrelationRegimeResponse;
  height?: number;
}

export function RegimeTimeline({ data, height = 260 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current || data.dates.length === 0) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);

    const { dates, density, smoothed, episodes, params } = data;
    const densityName = i18n.t("correlation.regimeDensity");
    const smoothedName = i18n.t("correlation.regimeSmoothed");
    const fusedLabel = i18n.t("correlation.regimeFused");
    const lastDate = dates[dates.length - 1];
    const markAreas = episodes.map((e) => [
      {
        name: fusedLabel,
        xAxis: e.start,
        label: { color: t.downColor, fontSize: 10, position: "insideTop" },
      },
      { xAxis: e.end ?? lastDate },
    ]);

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (params_: any) => {
          if (!Array.isArray(params_) || !params_.length) return "";
          let html = `<b>${params_[0].axisValue}</b>`;
          for (const p of params_) {
            const val = p.value === null || p.value === undefined ? "—" : Number(p.value).toFixed(4);
            html += `<br/>${p.marker} ${p.seriesName}: <b>${val}</b>`;
          }
          return html;
        },
      },
      legend: {
        data: [densityName, smoothedName],
        textStyle: { color: t.textColor, fontSize: 11 },
        right: 8,
        top: 4,
      },
      grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: dates,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 1,
        splitLine: { lineStyle: { color: t.gridColor } },
        axisLabel: { color: t.textColor, fontSize: 10 },
      },
      series: [
        {
          name: densityName,
          type: "line",
          data: density,
          color: t.axisColor,
          smooth: false,
          symbol: "none",
          lineStyle: { color: t.axisColor, width: 1, opacity: 0.7 },
        },
        {
          name: smoothedName,
          type: "line",
          data: smoothed,
          color: t.infoColor,
          smooth: false,
          symbol: "none",
          lineStyle: { color: t.infoColor, width: 2 },
          markArea: {
            silent: true,
            itemStyle: { color: t.downColor + "22" },
            data: markAreas,
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: t.textColor, type: "dashed", width: 1 },
            data: [
              {
                yAxis: params.enter_threshold,
                label: {
                  formatter: `${i18n.t("correlation.regimeEnterThreshold")}: ${params.enter_threshold}`,
                  position: "insideEndTop",
                  fontSize: 10,
                  color: t.textColor,
                },
              },
              {
                yAxis: params.exit_threshold,
                label: {
                  formatter: `${i18n.t("correlation.regimeExitThreshold")}: ${params.exit_threshold}`,
                  position: "insideEndBottom",
                  fontSize: 10,
                  color: t.textColor,
                },
              },
            ],
          },
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
  }, [data, dark]);

  if (data.dates.length === 0) return null;
  return <div ref={ref} style={{ height }} />;
}
