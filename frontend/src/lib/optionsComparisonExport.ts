import type {
  OptionsPayoffRequest,
  OptionsStrategyCompareRequest,
  OptionsStrategyCompareResponse,
} from "./options";
import { assertFiniteNumbers, csvText } from "./exportUtils";

export const OPTIONS_STRATEGY_COMPARISON_FORMAT = "vibe-options-strategy-comparison-v1";

export interface OptionsComparisonExportContext {
  source_request: OptionsPayoffRequest;
  baseline_label: string;
  target_label: string;
  target_key: string;
}

const CSV_COLUMNS = [
  "series",
  "iv",
  "spot",
  "baseline",
  "baseline_pnl",
  "target",
  "target_pnl",
  "delta_to_baseline",
] as const;

type CsvColumn = (typeof CSV_COLUMNS)[number];
type CsvRow = Partial<Record<CsvColumn, string | number>>;

interface ResolvedPair {
  baselineName: string;
  targetName: string;
}

function resolvePair(
  request: OptionsStrategyCompareRequest,
  result: OptionsStrategyCompareResponse,
  context: OptionsComparisonExportContext,
): ResolvedPair {
  if (result.status !== "ok") throw new Error("comparison result must be ok");
  if (request.strategies.length !== 2) throw new Error("comparison export requires exactly two strategies");
  const baselineIndex = request.baseline_index ?? 0;
  if (!Number.isInteger(baselineIndex) || baselineIndex < 0 || baselineIndex > 1) {
    throw new Error("comparison baseline index is invalid");
  }
  const targetIndex = baselineIndex === 0 ? 1 : 0;
  const baseline = request.strategies[baselineIndex];
  const target = request.strategies[targetIndex];
  if (context.target_key !== target.name) throw new Error("comparison target key does not match the request");
  if (
    result.comparison.baseline_index !== baselineIndex
    || result.comparison.baseline_name !== baseline.name
  ) {
    throw new Error("comparison baseline does not match the request");
  }
  if (
    typeof context.baseline_label !== "string"
    || typeof context.target_label !== "string"
    || typeof context.target_key !== "string"
  ) {
    throw new Error("comparison pair labels must be strings");
  }
  return { baselineName: baseline.name, targetName: target.name };
}

function validateCurve(values: unknown, spotCount: number, name: string): void {
  if (!Array.isArray(values) || values.length !== spotCount) {
    throw new Error(`${name} expiry curve length differs from spot`);
  }
}

function validateScenarioRows(
  values: unknown,
  ivCount: number,
  spotCount: number,
  name: string,
): void {
  if (
    !Array.isArray(values)
    || values.length !== ivCount
    || values.some((row) => !Array.isArray(row) || row.length !== spotCount)
  ) {
    throw new Error(`${name} scenario grid dimensions differ from IV and spot`);
  }
}

function validateComparison(
  request: OptionsStrategyCompareRequest,
  result: OptionsStrategyCompareResponse,
  context: OptionsComparisonExportContext,
): ResolvedPair {
  assertFiniteNumbers(request, "request");
  assertFiniteNumbers(result, "result");
  assertFiniteNumbers(context.source_request, "source_request");
  const pair = resolvePair(request, result, context);
  const expiry = result.expiry_curve;
  const baselineExpiry = expiry.pnl[pair.baselineName];
  const targetExpiry = expiry.pnl[pair.targetName];
  const deltaExpiry = expiry.delta_to_baseline[pair.targetName];
  validateCurve(baselineExpiry, expiry.spot.length, "baseline");
  validateCurve(targetExpiry, expiry.spot.length, "target");
  validateCurve(deltaExpiry, expiry.spot.length, "delta_to_baseline");

  const scenario = result.scenario_grid;
  if (scenario.spot.length !== expiry.spot.length || scenario.spot.some((spot, index) => spot !== expiry.spot[index])) {
    throw new Error("scenario grid and expiry curve must share one spot grid");
  }
  validateScenarioRows(scenario.pnl[pair.baselineName], scenario.iv_values.length, scenario.spot.length, "baseline");
  validateScenarioRows(scenario.pnl[pair.targetName], scenario.iv_values.length, scenario.spot.length, "target");
  validateScenarioRows(scenario.delta_to_baseline[pair.targetName], scenario.iv_values.length, scenario.spot.length, "delta_to_baseline");
  return pair;
}

function renderRow(row: CsvRow): string {
  return CSV_COLUMNS.map((column) => {
    const value = row[column];
    return typeof value === "number" ? String(value) : csvText(value ?? "");
  }).join(",");
}

export function buildOptionsStrategyComparisonJson(
  request: OptionsStrategyCompareRequest,
  result: OptionsStrategyCompareResponse,
  context: OptionsComparisonExportContext,
): string {
  validateComparison(request, result, context);
  return `${JSON.stringify({
    format: OPTIONS_STRATEGY_COMPARISON_FORMAT,
    request,
    result,
    source_request: context.source_request,
    pair: {
      baseline_label: context.baseline_label,
      target_label: context.target_label,
      target_key: context.target_key,
    },
  }, null, 2)}\n`;
}

export function buildOptionsStrategyComparisonCsv(
  request: OptionsStrategyCompareRequest,
  result: OptionsStrategyCompareResponse,
  context: OptionsComparisonExportContext,
): string {
  const pair = validateComparison(request, result, context);
  const rows: CsvRow[] = [];
  const append = (
    series: "expiry" | "scenario",
    iv: number | undefined,
    spot: number,
    baselinePnl: number,
    targetPnl: number,
    delta: number,
  ) => {
    rows.push({
      series,
      iv,
      spot,
      baseline: context.baseline_label,
      baseline_pnl: baselinePnl,
      target: context.target_label,
      target_pnl: targetPnl,
      delta_to_baseline: delta,
    });
  };

  const expiry = result.expiry_curve;
  expiry.spot.forEach((spot, index) => append(
    "expiry",
    undefined,
    spot,
    expiry.pnl[pair.baselineName][index],
    expiry.pnl[pair.targetName][index],
    expiry.delta_to_baseline[pair.targetName][index],
  ));

  const scenario = result.scenario_grid;
  scenario.iv_values.forEach((iv, ivIndex) => {
    scenario.spot.forEach((spot, spotIndex) => append(
      "scenario",
      iv,
      spot,
      scenario.pnl[pair.baselineName][ivIndex][spotIndex],
      scenario.pnl[pair.targetName][ivIndex][spotIndex],
      scenario.delta_to_baseline[pair.targetName][ivIndex][spotIndex],
    ));
  });

  return `${String.fromCharCode(0xfeff)}${[
    CSV_COLUMNS.join(","),
    ...rows.map(renderRow),
  ].join("\n")}\n`;
}
