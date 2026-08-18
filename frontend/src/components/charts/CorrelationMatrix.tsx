import { useRef } from "react";
import i18n from "@/i18n";
import { getChartTheme } from "@/lib/chart-theme";
import { escapeHtml } from "@/lib/escapeHtml";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";

interface Props {
  labels: string[];
  matrix: number[][];
  height?: number;
}

const RDBU_STOPS = ["#2166ac", "#4393c3", "#92c5de", "#d1e5f0", "#f7f7f7", "#fddbc7", "#f4a582", "#d6604d", "#b2182b"];

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function cellTextColor(value: number): string {
  const pos = Math.min(1, Math.max(0, (value + 1) / 2)) * (RDBU_STOPS.length - 1);
  const idx = Math.min(RDBU_STOPS.length - 2, Math.floor(pos));
  const frac = pos - idx;
  const [r1, g1, b1] = hexToRgb(RDBU_STOPS[idx]);
  const [r2, g2, b2] = hexToRgb(RDBU_STOPS[idx + 1]);
  const luminance = (0.299 * (r1 + (r2 - r1) * frac) + 0.587 * (g1 + (g2 - g1) * frac) + 0.114 * (b1 + (b2 - b1) * frac)) / 255;
  return luminance > 0.55 ? "#1f2937" : "#ffffff";
}

export function CorrelationMatrix({ labels, matrix, height = 500 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(ref, () => {
    const t = getChartTheme();

    // Build heatmap data: [xIdx, yIdx, value] with per-cell label color for readability on saturated cells
    const data: { value: [number, number, number]; label: { color: string } }[] = [];
    for (let i = 0; i < labels.length; i++) {
      for (let j = 0; j < labels.length; j++) {
        const val = parseFloat((matrix[i]?.[j] ?? 0).toFixed(4));
        data.push({ value: [j, i, val], label: { color: cellTextColor(val) } });
      }
    }

    const minVal = -1;
    const maxVal = 1;

    return {
      backgroundColor: "transparent",
      tooltip: {
        position: "top",
        backgroundColor: t.tooltipBg,
        borderColor: t.tooltipBorder,
        textStyle: { color: t.tooltipText, fontSize: 12 },
        formatter: (params: unknown) => {
          const p = params as { data: { value: [number, number, number] } };
          const [x, y, v] = p.data.value;
          return `<b>${escapeHtml(labels[x] ?? "")}</b> vs <b>${escapeHtml(labels[y] ?? "")}</b><br/>r = <b>${v.toFixed(4)}</b>`;
        },
      },
      grid: { left: "3%", right: "8%", top: "8%", bottom: "12%", containLabel: true },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: {
          color: t.textColor,
          fontSize: 11,
          rotate: 30,
          interval: 0,
        },
        axisLine: { lineStyle: { color: t.axisColor } },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: t.textColor, fontSize: 11, interval: 0 },
        axisLine: { lineStyle: { color: t.axisColor } },
        splitArea: { show: false },
      },
      visualMap: {
        min: minVal,
        max: maxVal,
        precision: 2,
        calculable: true,
        orient: "vertical",
        right: 8,
        top: "center",
        textStyle: { color: t.textColor, fontSize: 11 },
        inRange: {
          color: RDBU_STOPS,
        },
      },
      series: [
        {
          name: "Correlation",
          type: "heatmap",
          data,
          label: {
            show: labels.length <= 8,
            fontSize: 10,
            formatter: (params: unknown) => {
              const p = params as { value: [number, number, number] };
              return p.value[2].toFixed(2);
            },
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: "rgba(0, 0, 0, 0.5)" },
          },
        },
      ],
    };
  }, [labels, matrix]);

  if (labels.length === 0 || matrix.length === 0) {
    return <div className="text-muted-foreground text-sm p-4">{i18n.t("charts.noCorrelationData")}</div>;
  }
  return <div ref={ref} style={{ height }} />;
}
