import type { OptionsPayoffRequest, OptionsPayoffResponse } from "./options";

export const OPTIONS_ANALYSIS_FORMAT = "vibe-options-analysis-v1";

type GridResult = Pick<OptionsPayoffResponse, "expiry_curve" | "scenario_grid">;

const CSV_COLUMNS = [
  "series",
  "iv",
  "spot",
  "pnl",
  "strategy",
  "right_label",
  "metric",
  "left_decimal",
  "right_decimal",
  "relation",
  "difference_percentage_points",
  "status",
  "reason",
] as const;

type CsvColumn = (typeof CSV_COLUMNS)[number];
type CsvRow = Partial<Record<CsvColumn, string | number>>;

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

function validateGrids(result: GridResult): void {
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

function csvText(value: string): string {
  const safe = /^\s*[=+\-@]/.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

function renderRow(row: CsvRow): string {
  return CSV_COLUMNS.map((column) => {
    const value = row[column];
    return typeof value === "number" ? String(value) : csvText(value ?? "");
  }).join(",");
}

function appendGridRows(
  rows: CsvRow[],
  result: GridResult,
  strategy: string,
  alternative: boolean,
): void {
  validateGrids(result);
  const prefix = alternative ? "alternative_" : "";
  result.expiry_curve.spot.forEach((spot, index) => {
    rows.push({
      series: `${prefix}expiry`,
      spot,
      pnl: result.expiry_curve.pnl[index],
      strategy,
    });
  });
  result.scenario_grid.iv_values.forEach((iv, ivIndex) => {
    result.scenario_grid.spot.forEach((spot, spotIndex) => {
      rows.push({
        series: `${prefix}scenario`,
        iv,
        spot,
        pnl: result.scenario_grid.pnl[ivIndex][spotIndex],
        strategy,
      });
    });
  });
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

/** Full long-form strategy, scenario, and comparison data for spreadsheet analysis. */
export function buildOptionsScenarioCsv(
  result: OptionsPayoffResponse,
  request?: OptionsPayoffRequest,
): string {
  assertFiniteNumbers(result, "result");
  if (request) assertFiniteNumbers(request, "request");
  const rows: CsvRow[] = [];
  appendGridRows(rows, result, request?.label ?? "", false);

  for (const alternative of result.alternatives ?? []) {
    if (alternative.status !== "ok") {
      rows.push({
        series: "alternative_error",
        strategy: alternative.label,
        status: "error",
        reason: alternative.error ?? "Calculation failed",
      });
      continue;
    }
    if (!alternative.expiry_curve || !alternative.scenario_grid) {
      throw new Error(`alternative ${alternative.label} is missing curve data`);
    }
    appendGridRows(rows, {
      expiry_curve: alternative.expiry_curve,
      scenario_grid: alternative.scenario_grid,
    }, alternative.label, true);
  }

  for (const comparison of result.comparisons ?? []) {
    const metrics = Object.entries(comparison.metrics ?? {});
    if (comparison.status !== "ok" || metrics.length === 0) {
      rows.push({
        series: "comparison",
        strategy: comparison.left_label,
        right_label: comparison.right_label,
        status: comparison.status,
        reason: comparison.reason,
      });
      continue;
    }
    for (const [metric, values] of metrics) {
      rows.push({
        series: "comparison",
        strategy: comparison.left_label,
        right_label: comparison.right_label,
        metric,
        left_decimal: values.left_decimal,
        right_decimal: values.right_decimal,
        relation: values.relation,
        difference_percentage_points: values.difference_percentage_points,
        status: values.status ?? "ok",
        reason: values.reason,
      });
    }
  }

  return `${String.fromCharCode(0xfeff)}${[
    CSV_COLUMNS.join(","),
    ...rows.map(renderRow),
  ].join("\n")}\n`;
}
