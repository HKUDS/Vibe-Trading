import { useRef } from "react";
import i18n from "@/i18n";
import { getChartTheme } from "@/lib/chart-theme";
import { escapeHtml } from "@/lib/escapeHtml";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";
import type { KenyaBoardRow } from "@/lib/api";

interface Props {
  rows: KenyaBoardRow[];
  height?: number;
}

/** Moves beyond this saturate the colour scale (the NSE band is ±10%). */
const SATURATION_PCT = 5;

function mix(hex: string, towards: string, t: number): string {
  const a = parseInt(hex.slice(1), 16);
  const b = parseInt(towards.slice(1), 16);
  const ch = (shift: number) => {
    const x = (a >> shift) & 255;
    const y = (b >> shift) & 255;
    return Math.round(y + (x - y) * t);
  };
  return `#${[16, 8, 0].map((s) => ch(s).toString(16).padStart(2, "0")).join("")}`;
}

/**
 * The session as a treemap: area is value traded (VWAP × volume), colour the
 * day's move. Grouped by the sector headings the price list itself prints.
 * Untraded counters have no turnover and so no area — they are omitted.
 */
export function KenyaBoardTreemap({ rows, height = 420 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(
    ref,
    () => {
      const t = getChartTheme();
      const neutral = document.documentElement.classList.contains("dark") ? "#374151" : "#9ca3af";
      const colourFor = (pct: number | null) => {
        if (pct === null || Math.abs(pct) < 1e-9) return neutral;
        const k = Math.min(1, Math.abs(pct) / SATURATION_PCT);
        return mix(pct > 0 ? t.upColor : t.downColor, neutral, 0.35 + 0.65 * k);
      };

      const bySector = new Map<string, KenyaBoardRow[]>();
      for (const row of rows) {
        if (!row.traded || row.turnover <= 0) continue;
        const key = row.sector ?? i18n.t("kenyaBoard.otherSector");
        const list = bySector.get(key) ?? [];
        list.push(row);
        bySector.set(key, list);
      }

      const data = [...bySector.entries()].map(([sector, list]) => ({
        name: sector,
        children: list.map((row) => ({
          name: row.code ?? row.name,
          value: row.turnover,
          row,
          itemStyle: { color: colourFor(row.change_pct) },
        })),
      }));

      return {
        backgroundColor: "transparent",
        tooltip: {
          backgroundColor: t.tooltipBg,
          borderColor: t.tooltipBorder,
          textStyle: { color: t.tooltipText, fontSize: 12 },
          formatter: (params: unknown) => {
            const p = params as { data?: { row?: KenyaBoardRow; name?: string } };
            const row = p.data?.row;
            if (!row) return escapeHtml(p.data?.name ?? "");
            const pct = row.change_pct === null ? "—" : `${row.change_pct > 0 ? "+" : ""}${row.change_pct.toFixed(2)}%`;
            return [
              `<b>${escapeHtml(row.code ?? "")}</b> ${escapeHtml(row.name)}`,
              `${i18n.t("kenyaBoard.colClose")}: <b>${row.close?.toFixed(2) ?? "—"}</b> (${pct})`,
              `${i18n.t("kenyaBoard.colTurnover")}: KES ${Math.round(row.turnover).toLocaleString()}`,
            ].join("<br/>");
          },
        },
        series: [
          {
            type: "treemap",
            roam: false,
            nodeClick: false,
            breadcrumb: { show: false },
            width: "100%",
            height: "100%",
            top: 0,
            left: 0,
            upperLabel: {
              show: true,
              height: 18,
              color: t.textColor,
              fontSize: 11,
              fontWeight: 600,
            },
            label: {
              show: true,
              formatter: (p: { data?: { row?: KenyaBoardRow }; name: string }) => {
                const pct = p.data?.row?.change_pct;
                return pct === null || pct === undefined
                  ? p.name
                  : `${p.name}\n${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
              },
              color: "#ffffff",
              fontSize: 11,
              lineHeight: 14,
            },
            itemStyle: { borderColor: "transparent", gapWidth: 1 },
            levels: [
              { itemStyle: { borderWidth: 2, borderColor: t.gridColor, gapWidth: 2 } },
              { itemStyle: { gapWidth: 1 } },
            ],
            data,
          },
        ],
      };
    },
    [rows],
  );

  return (
    <div
      ref={ref}
      style={{ height }}
      className="w-full"
      role="img"
      aria-label={i18n.t("kenyaBoard.treemapTitle")}
    />
  );
}
