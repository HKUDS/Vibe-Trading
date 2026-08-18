import { describe, expect, it } from "vitest";
import { buildChartDataUpdate, buildFundFlowSeries, getChartGridLayout } from "../CandlestickChart";

describe("CandlestickChart data refresh", () => {
  it("updates series and categories without rebuilding background or zero-axis options", () => {
    const update = buildChartDataUpdate(["09:30", "09:31"], [
      { name: "Price", data: [100, 101], markLine: { data: [{ yAxis: 100 }] } },
      { name: "Average", data: [100, 100.5] },
    ]);

    expect(update.xAxis).toEqual([{ data: ["09:30", "09:31"] }, { data: ["09:30", "09:31"] }]);
    expect(update.series).toEqual([
      { name: "Price", data: [100, 101] },
      { name: "Average", data: [100, 100.5] },
    ]);
    expect(update).not.toHaveProperty("backgroundColor");
    expect(update).not.toHaveProperty("yAxis");
  });
});

describe("CandlestickChart grid layout", () => {
  it("uses identical horizontal bounds for intraday main and sub charts", () => {
    const grids = getChartGridLayout(true);

    expect(new Set(grids.map((grid) => `${grid.left}:${grid.right}`)).size).toBe(1);
    expect(grids.every((grid) => grid.containLabel === false)).toBe(true);
  });
});

describe("CandlestickChart fund-flow alignment", () => {
  it("aligns minute rows that include seconds with minute category keys", () => {
    const series = buildFundFlowSeries(
      [{ timestamp: "2026-08-17 09:31:00", main: 120, super_large: 80, large: 40, medium: -10, small: -110 }],
      ["09:30", "09:31"],
      ["09:30", "09:31"],
      "a_share",
      true,
    );

    expect(series.main).toEqual([null, 120]);
    expect(series.histogram).toEqual([null, 120]);
  });

  it("keeps a daily fallback visible on an intraday axis", () => {
    const series = buildFundFlowSeries(
      [{ timestamp: "2026-08-17", main: 120, super_large: 80, large: 40, medium: -10, small: -110 }],
      ["09:30", "09:31"],
      ["09:30", "09:31"],
      "a_share",
      true,
    );

    expect(series.main).toEqual([120, 120]);
    expect(series.histogram).toEqual([null, 120]);
  });
});
