import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { Mock } from "vitest";
import { AttributionCumulativeChart } from "../AttributionCumulativeChart";
import { RollingBetaAlphaChart } from "../RollingBetaAlphaChart";
import { OptionsPayoffChart } from "../OptionsPayoffChart";

vi.mock("@/lib/echarts", () => ({
  echarts: { init: vi.fn() },
  CHART_GROUP: "quant-charts",
  connectCharts: vi.fn(),
}));

import { echarts } from "@/lib/echarts";

interface FakeChart {
  setOption: Mock;
  resize: Mock;
  dispose: Mock;
  group: string;
}

interface SeriesSlice {
  name?: string;
  itemStyle?: { color?: string };
  lineStyle?: { color?: string };
}

const charts: FakeChart[] = [];

function lastOption(): Record<string, unknown> {
  const chart = charts[charts.length - 1];
  const call = chart.setOption.mock.calls[chart.setOption.mock.calls.length - 1];
  return call[0] as Record<string, unknown>;
}

beforeEach(() => {
  charts.length = 0;
  vi.mocked(echarts.init).mockImplementation((() => {
    const chart: FakeChart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), group: "" };
    charts.push(chart);
    return chart;
  }) as unknown as typeof echarts.init);
});

describe("legend swatch colors stay in sync with line colors", () => {
  it("AttributionCumulativeChart sets itemStyle color equal to lineStyle color on every series", () => {
    render(
      <AttributionCumulativeChart
        data={[
          { date: "2024-01-01", portfolio: 0.01, benchmark: 0.008, active: 0.002 },
          { date: "2024-01-02", portfolio: 0.02, benchmark: 0.015, active: 0.005 },
        ]}
      />,
    );

    const series = lastOption().series as SeriesSlice[];
    expect(series).toHaveLength(3);
    for (const entry of series) {
      expect(entry.itemStyle?.color).toBeDefined();
      expect(entry.itemStyle?.color).toBe(entry.lineStyle?.color);
    }
  });

  it("RollingBetaAlphaChart sets itemStyle color equal to lineStyle color on every series", () => {
    render(
      <RollingBetaAlphaChart
        data={[
          { date: "2024-01-01", beta: 0.2, alpha_annualized: -0.04 },
          { date: "2024-01-02", beta: 0.3, alpha_annualized: -0.05 },
        ]}
      />,
    );

    const series = lastOption().series as SeriesSlice[];
    expect(series).toHaveLength(2);
    for (const entry of series) {
      expect(entry.itemStyle?.color).toBeDefined();
      expect(entry.itemStyle?.color).toBe(entry.lineStyle?.color);
    }
  });

  it("OptionsPayoffChart pins the spot axis to the data extents and syncs the legend color", () => {
    render(
      <OptionsPayoffChart
        curve={{ spot: [80, 90, 100, 110, 120], pnl: [-120, -60, 40, 140, 240] }}
        entrySpot={100}
        breakevens={[96]}
      />,
    );

    const option = lastOption();
    const xAxis = option.xAxis as { min?: unknown; max?: unknown };
    expect(xAxis.min).toBe("dataMin");
    expect(xAxis.max).toBe("dataMax");

    const pnlSeries = (option.series as SeriesSlice[])[0];
    expect(pnlSeries.itemStyle?.color).toBeDefined();
    expect(pnlSeries.itemStyle?.color).toBe(pnlSeries.lineStyle?.color);
  });
});
