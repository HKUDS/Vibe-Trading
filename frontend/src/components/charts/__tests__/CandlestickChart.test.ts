import { describe, expect, it } from "vitest";
import { buildChartDataUpdate, buildChartDataZoomStep, buildFundFlowSeries, buildChartPanRange, canStartChartDrag, disposeChartSafely, formatPriceAxisLabel, getChanAnalysisRenderKey, getChanFractalMarkerStyle, getChartDragMode, getChartGridLayout, getChartPanDelta, getInitialChartDataZoomRange, getPriceAxisBoundsForRange, getStablePriceAxisBounds, getSubChartAxisBounds, resetChartDataZoom } from "../CandlestickChart";

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

  it("formats price-axis labels to two decimal places", () => {
    expect(formatPriceAxisLabel(12.3)).toBe("12.30");
    expect(formatPriceAxisLabel(0.456)).toBe("0.46");
  });

  it("recalculates bounds from the visible range after zooming", () => {
    expect(getPriceAxisBoundsForRange([
      { high: 100, low: 90 },
      { high: 120, low: 80 },
      { high: 105, low: 95 },
    ], 1, 2)).toEqual({ min: 78, max: 122 });
  });

  it("uses the initial visible range instead of the full dataset", () => {
    expect(getInitialChartDataZoomRange(100, "1M")).toEqual({ start: 78, end: 99 });
    expect(getPriceAxisBoundsForRange([
      ...Array.from({ length: 78 }, () => ({ high: 100, low: 1 })),
      ...Array.from({ length: 22 }, () => ({ high: 12, low: 8 })),
    ], 78, 99)).toEqual({ min: 7.8, max: 12.2 });
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

describe("CandlestickChart sub-chart switching", () => {
  it("clears RSI bounds when switching to a non-RSI sub-chart", () => {
    expect(getSubChartAxisBounds("rsi")).toEqual({ min: 0, max: 100 });
    expect(getSubChartAxisBounds("vol")).toEqual({ min: null, max: null });
    expect(getSubChartAxisBounds("macd")).toEqual({ min: null, max: null });
  });
});

describe("CandlestickChart mouse drag", () => {
  it("uses pan mode for plain left drag and box zoom for Ctrl-left drag", () => {
    expect(canStartChartDrag({ button: 0, ctrlKey: false })).toBe(true);
    expect(getChartDragMode({ button: 0, ctrlKey: false })).toBe("pan");
    expect(getChartDragMode({ button: 0, ctrlKey: true })).toBe("zoom");
  });

  it("moves the visible window by the horizontal drag delta", () => {
    expect(buildChartPanRange({ start: 10, end: 30 }, 100, 5)).toEqual({ start: 15, end: 35 });
    expect(buildChartPanRange({ start: 0, end: 20 }, 100, -5)).toEqual({ start: 0, end: 20 });
    expect(getChartPanDelta(200, 150, 10)).toBe(5);
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

  it("changes the render key when Chan structures change", () => {
    const base = { fractals: [], strokes: [], segments: [], centers: [], signals: [] };
    const withFractal = { ...base, fractals: [{ kind: "top" as const, bar_index: 2, confirmed_index: 3, price: 12 }] };

    expect(getChanAnalysisRenderKey(base)).not.toBe(getChanAnalysisRenderKey(withFractal));
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
