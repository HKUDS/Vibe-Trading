import { useRef } from "react";
import i18n from "@/i18n";
import { downsampleIndices, ivLabel, type ScenarioGrid } from "@/lib/options";
import { getChartTheme } from "@/lib/chart-theme";
import { getPnlColors } from "@/lib/pnl-colors";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";

const MAX_DISPLAY_COLUMNS = 61;

interface Props {
  grid: ScenarioGrid;
  height?: number;
}

export function OptionsScenarioMatrix({ grid, height = 380 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  const hasData =
    grid.iv_values.length > 0 && grid.spot.length > 0 && grid.pnl.length > 0;

  useChartLifecycle(ref, () => {
    const t = getChartTheme();
    const pnlC = getPnlColors();

    // Downsample the spot axis for display only; cell values keep reading the
    // original grid at the retained indices, so labels stay honest.
    const colIdx = downsampleIndices(grid.spot.length, MAX_DISPLAY_COLUMNS);
    const spotLabels = colIdx.map((i) => grid.spot[i].toLocaleString());
    const ivLabels = grid.iv_values.map((iv) => ivLabel(iv));

    const data: [number, number, number][] = [];
    let minVal = 0;
    let maxVal = 0;
    for (let r = 0; r < grid.iv_values.length; r++) {
      const row = grid.pnl[r] ?? [];
      for (let c = 0; c < colIdx.length; c++) {
        const v = row[colIdx[c]];
        if (!Number.isFinite(v)) continue;
        data.push([c, r, Number(v.toFixed(2))]);
        if (v < minVal) minVal = v;
        if (v > maxVal) maxVal = v;
      }
    }
    const bound = Math.max(Math.abs(minVal), Math.abs(maxVal), 1e-9);

    return {
      backgroundColor: "transparent",
      tooltip: {
        position: "top",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 12 },
        formatter: (params: unknown) => {
          const p = params as { data: [number, number, number] };
          const [x, y, v] = p.data;
          return (
            `<b>${i18n.t("options.scenario.spotAxis")}</b>: ${spotLabels[x] ?? "?"}` +
            `<br/><b>${i18n.t("options.scenario.ivAxis")}</b>: ${ivLabels[y] ?? "?"}` +
            `<br/><b>${i18n.t("options.scenario.pnl")}</b>: ${v.toLocaleString()}`
          );
        },
      },
      grid: { left: "3%", right: "10%", top: "8%", bottom: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: spotLabels,
        name: i18n.t("options.scenario.spotAxis"),
        nameTextStyle: { color: t.textColor, fontSize: 10 },
        nameLocation: "middle",
        nameGap: 30,
        axisLabel: { color: t.textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: t.axisColor } },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: ivLabels,
        name: i18n.t("options.scenario.ivAxis"),
        nameTextStyle: { color: t.textColor, fontSize: 10 },
        axisLabel: { color: t.textColor, fontSize: 10, interval: 0 },
        axisLine: { lineStyle: { color: t.axisColor } },
        splitArea: { show: false },
      },
      visualMap: {
        min: -bound,
        max: bound,
        precision: 0,
        calculable: true,
        orient: "vertical",
        right: 8,
        top: "center",
        textStyle: { color: t.textColor, fontSize: 11 },
        inRange: { color: [pnlC.loss, pnlC.neutral, pnlC.profit] },
      },
      series: [
        {
          name: i18n.t("options.scenario.pnl"),
          type: "heatmap",
          data,
          label: {
            show: colIdx.length <= 16 && grid.iv_values.length <= 6,
            fontSize: 10,
            color: t.textColor,
            formatter: (params: unknown) => {
              const p = params as { value: [number, number, number] };
              return p.value[2].toLocaleString(undefined, { maximumFractionDigits: 0 });
            },
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: "rgba(0, 0, 0, 0.5)" },
          },
        },
      ],
    };
  }, [grid, hasData]);

  if (!hasData) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("options.scenario.noData")}</div>;
  }
  return <div ref={ref} style={{ height }} />;
}
