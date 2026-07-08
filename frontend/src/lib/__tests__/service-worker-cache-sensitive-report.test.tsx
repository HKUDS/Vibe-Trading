import { shouldCacheAlphaGenesisReport } from "../alphaGenesisSecurity";

describe("Alpha Genesis service-worker/cache policy", () => {
  it("does not cache API report, scorecard, or decision responses", () => {
    expect(shouldCacheAlphaGenesisReport("/api/alpha-genesis/reports/report-1")).toBe(false);
    expect(shouldCacheAlphaGenesisReport("/api/alpha-genesis/scorecards/candidate-1")).toBe(false);
    expect(shouldCacheAlphaGenesisReport("/api/alpha-genesis/quality-decisions/candidate-1")).toBe(false);
  });

  it("does not cache Alpha Genesis artifact payloads by schema", () => {
    expect(
      shouldCacheAlphaGenesisReport("/download/report.json", {
        schema_version: "alpha_genesis_report.v1",
      }),
    ).toBe(false);
  });

  it("allows unrelated public static assets to remain cacheable", () => {
    expect(shouldCacheAlphaGenesisReport("/assets/logo.png")).toBe(true);
  });
});
