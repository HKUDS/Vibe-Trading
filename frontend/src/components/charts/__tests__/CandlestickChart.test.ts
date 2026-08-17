import { describe, expect, it } from "vitest";
import { buildFundFlowSeries, getChartGridLayout } from "../CandlestickChart";

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
