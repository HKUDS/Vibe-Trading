import { useRef } from "react";
import i18n from "@/i18n";
import type { AnnualReturn, MonthlyReturn } from "@/lib/tearsheet";
import { getChartTheme } from "@/lib/chart-theme";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";

interface Props {
  data: MonthlyReturn[];
  annual: AnnualReturn[];
  height?: number;
}

function fmtSignedPct(v: number, digits = 1): string {
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

export function MonthlyReturnsHeatmap({ data, annual, height = 300 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();

    const monthFmt = new Intl.DateTimeFormat(i18n.language || "en", { month: "short" });
    const monthLabels = Array.from({ length: 12 }, (_, i) => monthFmt.format(new Date(2024, i, 15)));
    const xLabels = [...monthLabels, i18n.t("runDetail.tearsheetYear")];

    const years = [...new Set(data.map((d) => d.year))].sort((a, b) => a - b);
    const yLabels = years.map(String);

    const cells: Array<[number, number, number]> = [];
    for (const m of data) {
      if (m.ret === null || !Number.isFinite(m.ret)) continue;
      const yIdx = years.indexOf(m.year);
      if (yIdx < 0) continue;
      cells.push([m.month - 1, yIdx, m.ret]);
    }
    for (const a of annual) {
      if (!Number.isFinite(a.ret)) continue;
      const yIdx = years.indexOf(a.year);
      if (yIdx < 0) continue;
      cells.push([12, yIdx, a.ret]);
    }

    let maxAbs = 0;
    for (const [, , v] of cells) maxAbs = Math.max(maxAbs, Math.abs(v));
    if (maxAbs === 0) maxAbs = 1;

    const returnLabel = i18n.t("runDetail.returnPct");

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 11 },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (params: any) => {
          const value = params?.value as [number, number, number] | undefined;
          if (!Array.isArray(value) || value.length < 3) return "";
          const [xIdx, yIdx, v] = value;
          const year = yLabels[yIdx] ?? "";
          const head = xIdx < 12 ? `${year}-${String(xIdx + 1).padStart(2, "0")}` : year;
          return `<b>${head}</b><br/>${returnLabel}: <b>${fmtSignedPct(v, 2)}</b>`;
        },
      },
      grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: { color: t.textColor, fontSize: 10 },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: yLabels,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisTick: { show: false },
        axisLabel: { color: t.textColor, fontSize: 10 },
        splitArea: { show: false },
      },
      visualMap: {
        show: false,
        type: "continuous",
        min: -maxAbs,
        max: maxAbs,
        inRange: { color: [t.downColor, t.tooltipBorder || "#9ca3af", t.upColor] },
      },
      series: [
        {
          name: returnLabel,
          type: "heatmap",
          data: cells.map(([x, y, v]) => {
            const saturated = Math.abs(v) > 0.55 * maxAbs;
            return {
              value: [x, y, v],
              label: {
                show: true,
                formatter: fmtSignedPct(v),
                fontSize: 10,
                color: saturated ? "#ffffff" : t.textColor,
                ...(saturated ? { textShadowColor: "rgba(0,0,0,0.45)", textShadowBlur: 2 } : {}),
              },
            };
          }),
          itemStyle: { borderColor: t.gridColor, borderWidth: 1 },
          emphasis: { itemStyle: { borderColor: t.axisColor, borderWidth: 1 } },
        },
      ],
    };
  }, [data, annual]);

  if (data.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("runDetail.noTearsheetData")}</div>;
  }
  return <div ref={ref} style={{ height }} />;
}
