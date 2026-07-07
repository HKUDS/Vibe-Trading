import { BarChart3 } from "lucide-react";

import type { StructuredIssue } from "./PITWarningsPanel";
import { redactDisplayText } from "./redaction";

export interface QuantScorecardSummary {
  scorecard_id?: string;
  schema_version?: string;
  score?: number;
  conclusion_cap?: string;
  score_breakdown?: Record<string, number>;
  warnings?: StructuredIssue[];
  hard_failures?: StructuredIssue[];
}

export function QuantScorecardPanel({ scorecard }: { scorecard?: QuantScorecardSummary | null }) {
  const breakdown = Object.entries(scorecard?.score_breakdown || {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <BarChart3 className="h-4 w-4 text-muted-foreground" />
        Quant Scorecard
      </div>
      {!scorecard ? (
        <p className="text-sm text-muted-foreground">No quant scorecard recorded.</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <ScoreStat label="Score" value={formatScore(scorecard.score)} />
            <ScoreStat label="Conclusion Cap" value={redactDisplayText(scorecard.conclusion_cap || "unknown")} />
          </div>
          {breakdown.length > 0 && (
            <div className="space-y-1">
              {breakdown.map(([key, value]) => (
                <div key={key} className="grid grid-cols-[minmax(0,1fr)_4rem] items-center gap-3 text-xs">
                  <span className="font-mono">{redactDisplayText(key)}</span>
                  <span className="text-right tabular-nums text-muted-foreground">{formatScore(value)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ScoreStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-medium">{value}</div>
    </div>
  );
}

function formatScore(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "unknown";
}
