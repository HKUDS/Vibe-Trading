import { describe, expect, it } from "vitest";
import type {
  OptionsPayoffRequest,
  OptionsStrategyCompareRequest,
  OptionsStrategyCompareResponse,
} from "../options";
import type { OptionsComparisonExportContext } from "../optionsComparisonExport";

const sourceRequest: OptionsPayoffRequest = {
  label: "Current strategy",
  legs: [{ option_type: "call", strike: 100, qty: 1, premium: 5 }],
  alternatives: [{ label: "Alt A", legs: [{ option_type: "call", strike: 105, qty: 1, premium: 4 }] }],
  entry_spot: 100,
  expiry_days: 30,
  volatility: 0.3,
};

const request: OptionsStrategyCompareRequest = {
  strategies: [
    { name: "strategy-0", legs: sourceRequest.legs },
    { name: "strategy-1", legs: sourceRequest.alternatives![0].legs },
  ],
  baseline_index: 1,
  entry_spot: 100,
  expiry_days: 30,
  volatility: 0.3,
  spot_min: 80,
  spot_max: 120,
  spot_points: 2,
  scenario_iv_values: [0.2, 0.4],
};

const result: OptionsStrategyCompareResponse = {
  status: "ok",
  comparison: { baseline_index: 1, baseline_name: "strategy-1" },
  strategies: [],
  expiry_curve: {
    spot: [80, 120],
    pnl: {
      "strategy-0": [-100, 200],
      "strategy-1": [-150, 150],
    },
    delta_to_baseline: { "strategy-0": [50, 50] },
  },
  scenario_grid: {
    iv_values: [0.2, 0.4],
    spot: [80, 120],
    pnl: {
      "strategy-0": [[-110, 190], [-120, 180]],
      "strategy-1": [[-160, 140], [-170, 130]],
    },
    delta_to_baseline: { "strategy-0": [[50, 50], [50, 50]] },
  },
  limitations: ["European model"],
};

const context: OptionsComparisonExportContext = {
  source_request: sourceRequest,
  baseline_label: "Alt A",
  target_label: "Current strategy",
  target_key: "strategy-0",
};

const header = "series,iv,spot,baseline,baseline_pnl,target,target_pnl,delta_to_baseline";

describe("options strategy comparison export", () => {
  it("binds the accepted request, response, source request, and pair labels", async () => {
    const { buildOptionsStrategyComparisonJson, OPTIONS_STRATEGY_COMPARISON_FORMAT } = await import("../optionsComparisonExport");

    const first = buildOptionsStrategyComparisonJson(request, result, context);
    const second = buildOptionsStrategyComparisonJson(request, result, context);
    const document = JSON.parse(first);

    expect(first).toBe(second);
    expect(first.endsWith("\n")).toBe(true);
    expect(document.format).toBe(OPTIONS_STRATEGY_COMPARISON_FORMAT);
    expect(document.request).toEqual(request);
    expect(document.result).toEqual(result);
    expect(document.source_request).toEqual(sourceRequest);
    expect(document.pair).toEqual({
      baseline_label: "Alt A",
      target_label: "Current strategy",
      target_key: "strategy-0",
    });
    expect(document.updatedAt).toBeUndefined();
  });

  it("exports baseline, target, and delta values for every grid cell", async () => {
    const { buildOptionsStrategyComparisonCsv } = await import("../optionsComparisonExport");

    const lines = buildOptionsStrategyComparisonCsv(request, result, context).trimEnd().split("\n");

    expect(lines[0]).toBe(`﻿${header}`);
    expect(lines).toHaveLength(7);
    expect(lines.slice(1).map((line) => line.split(","))).toEqual([
      ["expiry", "", "80", "Alt A", "-150", "Current strategy", "-100", "50"],
      ["expiry", "", "120", "Alt A", "150", "Current strategy", "200", "50"],
      ["scenario", "0.2", "80", "Alt A", "-160", "Current strategy", "-110", "50"],
      ["scenario", "0.2", "120", "Alt A", "140", "Current strategy", "190", "50"],
      ["scenario", "0.4", "80", "Alt A", "-170", "Current strategy", "-120", "50"],
      ["scenario", "0.4", "120", "Alt A", "130", "Current strategy", "180", "50"],
    ]);
  });

  it("rejects mismatched pairs, missing series, ragged grids, and non-finite values", async () => {
    const { buildOptionsStrategyComparisonCsv } = await import("../optionsComparisonExport");
    const call = (body: OptionsStrategyCompareResponse, pair = context) => () => buildOptionsStrategyComparisonCsv(request, body, pair);

    expect(call({ ...result, comparison: { baseline_index: 0, baseline_name: "strategy-0" } })).toThrow("baseline");
    expect(call(result, { ...context, target_key: "strategy-1" })).toThrow("target");
    expect(call({
      ...result,
      expiry_curve: { ...result.expiry_curve, delta_to_baseline: {} },
    })).toThrow("delta");
    expect(call({
      ...result,
      scenario_grid: {
        ...result.scenario_grid,
        pnl: { ...result.scenario_grid.pnl, "strategy-0": [[1, 2]] },
      },
    })).toThrow("scenario");
    expect(call({
      ...result,
      expiry_curve: {
        ...result.expiry_curve,
        pnl: { ...result.expiry_curve.pnl, "strategy-0": [Number.NaN, 200] },
      },
    })).toThrow("finite");
    expect(call(result, {
      ...context,
      source_request: { ...sourceRequest, entry_spot: Number.POSITIVE_INFINITY },
    })).toThrow("source_request");
  });

  it("quotes pair labels without allowing spreadsheet formulas", async () => {
    const { buildOptionsStrategyComparisonCsv } = await import("../optionsComparisonExport");

    const csv = buildOptionsStrategyComparisonCsv(request, result, {
      ...context,
      baseline_label: "@Alt,\n\"A\"",
      target_label: "=Current",
    });

    expect(csv).toContain("\"'@Alt,\n\"\"A\"\"\"");
    expect(csv).toContain("'=Current");
  });
});
