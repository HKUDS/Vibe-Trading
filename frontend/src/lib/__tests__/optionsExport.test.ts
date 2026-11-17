import { describe, expect, it } from "vitest";
import type { OptionsPayoffRequest, OptionsPayoffResponse } from "../options";

const request: OptionsPayoffRequest = {
  legs: [{ option_type: "call", strike: 100, qty: 1, premium: 8 }],
  entry_spot: 100,
  expiry_days: 30,
  volatility: 0.3,
};

const result: OptionsPayoffResponse = {
  status: "ok",
  inputs: { entry_spot: 100 },
  summary: {
    net_premium: 800,
    entry_commission: 0.8,
    entry_cost: 800.8,
    entry_side: "debit",
    breakevens: [108.008],
    breakeven_intervals: [],
    max_profit: null,
    max_loss: -800.8,
    profit_unbounded: true,
    loss_unbounded: false,
  },
  greeks: { delta: 0.5, gamma: 0.02, theta: -1, vega: 10, rho: 2 },
  expiry_curve: { spot: [80, 120], pnl: [-500, 300] },
  scenario_grid: {
    iv_values: [0.2, 0.4],
    spot: [80, 120],
    pnl: [[-450, 350], [-500, 250]],
  },
  limitations: ["European model"],
};

describe("options analysis export", () => {
  it("binds the exact request and full result in a deterministic JSON document", async () => {
    const { buildOptionsAnalysisJson, OPTIONS_ANALYSIS_FORMAT } = await import("../optionsExport");

    const first = buildOptionsAnalysisJson(request, result);
    const second = buildOptionsAnalysisJson(request, result);
    const document = JSON.parse(first);

    expect(first).toBe(second);
    expect(first.endsWith("\n")).toBe(true);
    expect(document.format).toBe(OPTIONS_ANALYSIS_FORMAT);
    expect(document.request).toEqual(request);
    expect(document.result).toEqual(result);
    expect(document.updatedAt).toBeUndefined();
    expect(document.result.summary.max_profit).toBeNull();
    expect(document.result.summary.profit_unbounded).toBe(true);
  });

  it("exports every expiry and scenario cell as a long-form CSV", async () => {
    const { buildOptionsScenarioCsv } = await import("../optionsExport");

    const csv = buildOptionsScenarioCsv(result);
    const lines = csv.trimEnd().split("\n");

    expect(lines[0]).toBe("﻿series,iv,spot,pnl");
    expect(lines).toHaveLength(7);
    expect(lines.slice(1)).toEqual([
      "expiry,,80,-500",
      "expiry,,120,300",
      "scenario,0.2,80,-450",
      "scenario,0.2,120,350",
      "scenario,0.4,80,-500",
      "scenario,0.4,120,250",
    ]);
  });

  it("allows an explicitly empty scenario grid while keeping expiry data", async () => {
    const { buildOptionsScenarioCsv } = await import("../optionsExport");
    const expiryOnly: OptionsPayoffResponse = {
      ...result,
      scenario_grid: { iv_values: [], spot: [], pnl: [] },
    };

    expect(buildOptionsScenarioCsv(expiryOnly).trimEnd().split("\n")).toHaveLength(3);
  });

  it("refuses ragged grids instead of exporting a misleading CSV", async () => {
    const { buildOptionsScenarioCsv } = await import("../optionsExport");
    const malformed: OptionsPayoffResponse = {
      ...result,
      scenario_grid: { iv_values: [0.2, 0.4], spot: [80, 120], pnl: [[1, 2]] },
    };

    expect(() => buildOptionsScenarioCsv(malformed)).toThrow("scenario grid");
  });

  it("refuses non-finite values and mismatched expiry arrays", async () => {
    const { buildOptionsScenarioCsv } = await import("../optionsExport");

    expect(() => buildOptionsScenarioCsv({
      ...result,
      expiry_curve: { spot: [80], pnl: [0, 1] },
    })).toThrow("expiry curve");
    expect(() => buildOptionsScenarioCsv({
      ...result,
      expiry_curve: { spot: [80, 120], pnl: [0, Number.POSITIVE_INFINITY] },
    })).toThrow("finite");
  });
});
