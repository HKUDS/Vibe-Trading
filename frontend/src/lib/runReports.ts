import type { RunData } from "@/lib/api";

function hasItems(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

function hasObjectKeys(value: unknown): boolean {
  return !!value && typeof value === "object" && Object.keys(value).length > 0;
}

export function isReportWorthyRun(run: Pick<
  RunData,
  "metrics" | "run_card" | "llm_usage" | "equity_curve" | "trade_log" | "price_series" | "trade_markers" | "validation" | "artifacts"
> | null | undefined): boolean {
  if (!run) return false;
  if (hasObjectKeys(run.metrics)) return true;
  if (hasObjectKeys(run.run_card)) return true;
  if (hasObjectKeys(run.llm_usage)) return true;
  if (hasItems(run.equity_curve)) return true;
  if (hasItems(run.trade_log)) return true;
  if (hasItems(run.trade_markers)) return true;
  if (hasObjectKeys(run.validation)) return true;
  if (run.price_series && Object.values(run.price_series).some(hasItems)) return true;
  return (run.artifacts || []).some((artifact) =>
    /(?:metrics|equity|trades|positions|ohlcv|validation|strategy|llm_usage)\.(?:csv|json|pine|py)$/i.test(artifact.name),
  );
}
