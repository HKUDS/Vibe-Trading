import type { OptionsPayoffRequest, OptionsPayoffResponse } from "./options";

export const OPTIONS_ANALYSIS_FORMAT = "vibe-options-analysis-v1";

function assertFiniteNumbers(value: unknown, path = "export"): void {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error(`${path} must contain finite numbers`);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertFiniteNumbers(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => assertFiniteNumbers(item, `${path}.${key}`));
  }
}

function validateGrids(result: OptionsPayoffResponse): void {
  const expiry = result.expiry_curve;
  if (expiry.spot.length !== expiry.pnl.length) {
    throw new Error("expiry curve spot and P&L lengths differ");
  }
  const scenario = result.scenario_grid;
  if (scenario.iv_values.length === 0 && scenario.spot.length === 0 && scenario.pnl.length === 0) {
    return;
  }
  if (scenario.iv_values.length !== scenario.pnl.length) {
    throw new Error("scenario grid IV and P&L row counts differ");
  }
  if (scenario.pnl.some((row) => row.length !== scenario.spot.length)) {
    throw new Error("scenario grid spot and P&L column counts differ");
  }
  if (
    scenario.spot.length !== expiry.spot.length
    || scenario.spot.some((value, index) => value !== expiry.spot[index])
  ) {
    throw new Error("scenario grid and expiry curve must share one spot grid");
  }
}

function validateExport(request: OptionsPayoffRequest, result: OptionsPayoffResponse): void {
  assertFiniteNumbers(request, "request");
  assertFiniteNumbers(result, "result");
  validateGrids(result);
}

/** A self-contained, timestamp-free snapshot of the exact analysis request and result. */
export function buildOptionsAnalysisJson(
  request: OptionsPayoffRequest,
  result: OptionsPayoffResponse,
): string {
  validateExport(request, result);
  return `${JSON.stringify({
    format: OPTIONS_ANALYSIS_FORMAT,
    request,
    result,
  }, null, 2)}\n`;
}

/** Full long-form expiry and spot-by-IV data, suitable for spreadsheet analysis. */
export function buildOptionsScenarioCsv(result: OptionsPayoffResponse): string {
  assertFiniteNumbers(result, "result");
  validateGrids(result);
  const rows = ["series,iv,spot,pnl"];
  result.expiry_curve.spot.forEach((spot, index) => {
    rows.push(`expiry,,${spot},${result.expiry_curve.pnl[index]}`);
  });
  result.scenario_grid.iv_values.forEach((iv, ivIndex) => {
    result.scenario_grid.spot.forEach((spot, spotIndex) => {
      rows.push(`scenario,${iv},${spot},${result.scenario_grid.pnl[ivIndex][spotIndex]}`);
    });
  });
  return `${String.fromCharCode(0xfeff)}${rows.join("\n")}\n`;
}
