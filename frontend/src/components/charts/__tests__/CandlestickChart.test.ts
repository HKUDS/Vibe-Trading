import { describe, expect, it } from "vitest";
import { buildChartDataUpdate, buildChartDataZoomStep, buildFundFlowSeries, disposeChartSafely, getChanFractalMarkerStyle, getChartGridLayout, getStablePriceAxisBounds, resetChartDataZoom } from "../CandlestickChart";

describe("CandlestickChart lifecycle", () => {
  it("does not let an ECharts teardown error escape during unmount", () => {
    const chart = {
      isDisposed: () => false,
      dispose: () => {
        throw new TypeError("Cannot read properties of undefined (reading '__ec_inner_54')");
      },
    };

    expect(() => disposeChartSafely(chart)).not.toThrow();
  });
});

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

  it("resets both main and sub-chart zoom ranges to the complete dataset", () => {
    const actions: unknown[] = [];
    resetChartDataZoom({ dispatchAction: (action: unknown) => actions.push(action) }, 120);

    expect(actions).toEqual([
      { type: "dataZoom", dataZoomIndex: 0, startValue: 0, endValue: 119 },
      { type: "dataZoom", dataZoomIndex: 1, startValue: 0, endValue: 119 },
    ]);
  });
});

describe("CandlestickChart grid layout", () => {
  it("uses identical horizontal bounds for intraday main and sub charts", () => {
    const grids = getChartGridLayout(true);

    expect(new Set(grids.map((grid) => `${grid.left}:${grid.right}`)).size).toBe(1);
    expect(grids.every((grid) => grid.containLabel === false)).toBe(true);
  });
});

describe("CandlestickChart price axis", () => {
  it("uses the complete current dataset so horizontal wheel zoom does not rescale candle height", () => {
    expect(getStablePriceAxisBounds([100, 120, 110], [90, 95, 80])).toEqual({ min: 78, max: 122 });
  });
});

describe("CandlestickChart wheel zoom", () => {
  it("zooms in and out incrementally around the cursor instead of jumping to an endpoint", () => {
    const zoomedIn = buildChartDataZoomStep({ start: 0, end: 119 }, 120, -100, 60);
    expect(zoomedIn.end - zoomedIn.start).toBeLessThan(119);
    expect(zoomedIn.start).toBeGreaterThan(0);
    expect(zoomedIn.end).toBeLessThan(119);

    const zoomedOut = buildChartDataZoomStep(zoomedIn, 120, 100, 60);
    expect(zoomedOut.start).toBeLessThanOrEqual(zoomedIn.start);
    expect(zoomedOut.end).toBeGreaterThanOrEqual(zoomedIn.end);
  });
});

describe("Chan fractal marker mapping", () => {
  it("places top fractals above highs with the up/red color and bottoms below lows with the down/green color", () => {
    expect(getChanFractalMarkerStyle("top", "red", "green")).toEqual({
      symbolRotate: 180,
      symbolOffset: [0, -13],
      color: "red",
    });
    expect(getChanFractalMarkerStyle("bottom", "red", "green")).toEqual({
      symbolRotate: 0,
      symbolOffset: [0, 13],
      color: "green",
    });
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
