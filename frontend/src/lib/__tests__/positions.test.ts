import { computeDrift, exposureSummary, parsePositionRows, topSymbols, toWeightSeries } from "../positions";

describe("positions helpers", () => {
  it("parses wide csv rows, coercing strings and skipping zero/NaN cells", () => {
    const rows = parsePositionRows([
      { timestamp: "2026-02-01", AAPL: "0.5", MSFT: 0.3, EMPTY: "", ZERO: 0 },
      { timestamp: "2026-03-01", AAPL: 0.6, MSFT: 0.25 },
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ time: "2026-02-01", weights: { AAPL: 0.5, MSFT: 0.3 } });
    expect(rows[1].weights).toEqual({ AAPL: 0.6, MSFT: 0.25 });
  });

  it("returns no rows for missing payloads", () => {
    expect(parsePositionRows(undefined)).toEqual([]);
    expect(parsePositionRows(null)).toEqual([]);
  });

  it("ranks top symbols by latest-row absolute weight", () => {
    const rows = parsePositionRows([
      { timestamp: "2026-02-01", AAPL: 0.9, MSFT: 0.05, TSLA: 0.05 },
      { timestamp: "2026-03-01", AAPL: 0.2, MSFT: 0.7, TSLA: -0.1 },
    ]);
    expect(topSymbols(rows, 2)).toEqual(["MSFT", "AAPL"]);
  });

  it("aggregates non-top symbols into the Other bucket per row", () => {
    const rows = parsePositionRows([
      { timestamp: "2026-02-01", AAPL: 0.5, MSFT: 0.3, TSLA: 0.2 },
    ]);
    const series = toWeightSeries(rows, ["AAPL"]);
    expect(series).toEqual([{ time: "2026-02-01", AAPL: 0.5, Other: 0.5 }]);
  });

  it("computes target-vs-actual drift over the union of symbols", () => {
    const target = parsePositionRows([{ timestamp: "2026-03-01", AAPL: 0.65, TSLA: 0.1 }]);
    const actual = parsePositionRows([{ timestamp: "2026-03-01", AAPL: 0.6, MSFT: 0.25 }]);
    const drift = computeDrift(target, actual);
    expect(drift[0]).toEqual({ symbol: "MSFT", target: 0, actual: 0.25, drift: 0.25 });
    expect(drift.find((r) => r.symbol === "AAPL")?.drift).toBeCloseTo(-0.05);
  });

  it("sums gross and net exposure", () => {
    const { gross, net } = exposureSummary({ AAPL: 0.6, TSLA: -0.2 });
    expect(gross).toBeCloseTo(0.8);
    expect(net).toBeCloseTo(0.4);
  });
});
