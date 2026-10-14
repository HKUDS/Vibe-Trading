import { hasStoredMetrics, runCardFields } from "../runCards";

describe("runCardFields", () => {
  it("skips plain replies", () => {
    expect(runCardFields({ metrics: null, equity_curve: [], report_worthy: false })).toBeNull();
  });

  it("keeps a card without data when the preview failed", () => {
    expect(runCardFields(null)).toEqual({ metrics: undefined, equityCurve: undefined });
  });

  it("maps metrics and equity points for report runs", () => {
    const metrics = {
      final_value: 110, total_return: 0.1, annual_return: 0.05, max_drawdown: -0.02,
      sharpe: 1.1, win_rate: 0.5, trade_count: 3,
    };
    expect(runCardFields({
      metrics,
      equity_curve: [{ time: "2025-01-01", equity: "100", drawdown: "0" }],
      report_worthy: true,
    })).toEqual({ metrics, equityCurve: [{ time: "2025-01-01", equity: 100 }] });
  });
});

describe("hasStoredMetrics", () => {
  it("treats a missing or empty object as no metrics", () => {
    expect(hasStoredMetrics(undefined)).toBe(false);
    expect(hasStoredMetrics({})).toBe(false);
    expect(hasStoredMetrics({ sharpe: 1 })).toBe(true);
  });
});
