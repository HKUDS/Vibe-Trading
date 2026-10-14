import type { RunPreview } from "@/lib/api";
import type { AgentMessage } from "@/types/agent";

/** Whether a stored reply already carries backtest metrics, so its card needs no preview. */
export function hasStoredMetrics(metrics: Record<string, number> | undefined): boolean {
  return !!metrics && Object.keys(metrics).length > 0;
}

/**
 * Card fields for a finished run, or `null` when the run has nothing to report.
 * A failed preview still gets a card so the report link stays reachable.
 */
export function runCardFields(
  preview: RunPreview | null,
): Pick<AgentMessage, "metrics" | "equityCurve"> | null {
  if (preview && !preview.report_worthy) return null;
  return {
    metrics: preview?.metrics ?? undefined,
    equityCurve: preview?.equity_curve.map((e) => ({ time: e.time, equity: Number(e.equity) })),
  };
}
