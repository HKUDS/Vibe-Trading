import { BarChart3 } from "lucide-react";
import type { RunCard, TriggeredRule } from "@/lib/api";
import type { StructuredIssue } from "./PITWarningsPanel";
import { redactResearchText } from "./redaction";

export interface QuantScorecardSummary {
  scorecard_id?: string;
  schema_version?: string;
  score?: number;
  conclusion_cap?: string;
  score_breakdown?: Record<string, number>;
  warnings?: StructuredIssue[];
  hard_failures?: StructuredIssue[];
  triggered_rules?: TriggeredRule[];
}

export function QuantScorecardPanel({
  card,
  scorecard,
}: {
  card?: RunCard | null;
  scorecard?: QuantScorecardSummary | null;
}) {
  const breakdown = Object.entries(scorecard?.score_breakdown || {}).sort(([a], [b]) => a.localeCompare(b));
  const hardFailures = card?.hard_failures || (scorecard?.hard_failures || []).map((failure) => failure.code);
  const triggeredRules = (card?.triggered_rules || scorecard?.triggered_rules || []) as TriggeredRule[];

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <BarChart3 className="h-4 w-4 text-muted-foreground" />
        Quant Scorecard
      </div>
      {scorecard && (
        <div className="mb-4 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <ScoreStat label="Score" value={formatScore(scorecard.score)} />
            <ScoreStat label="Conclusion Cap" value={redactResearchText(scorecard.conclusion_cap || "unknown")} />
          </div>
          {breakdown.length > 0 && (
            <div className="space-y-1">
              {breakdown.map(([key, value]) => (
                <div key={key} className="grid grid-cols-[minmax(0,1fr)_4rem] items-center gap-3 text-xs">
                  <span className="font-mono">{redactResearchText(key)}</span>
                  <span className="text-right tabular-nums text-muted-foreground">{formatScore(value)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {!scorecard && !card && <p className="text-sm text-muted-foreground">No quant scorecard recorded.</p>}
      {(scorecard || card) && (
        <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Hard Failures</div>
          <ul data-testid="hard-failures" className="space-y-1 text-sm">
            {hardFailures.length > 0 ? (
              hardFailures.map((failure) => (
                <li key={String(failure)} className="rounded-md border border-danger/20 bg-danger/5 px-2 py-1 text-danger">
                  {redactResearchText(failure)}
                </li>
              ))
            ) : (
              <li className="text-muted-foreground">none</li>
            )}
          </ul>
        </div>
        <div>
          <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Triggered Rules</div>
          {triggeredRules.length > 0 ? (
            <div className="space-y-2">
              {triggeredRules.map((rule) => (
                <div key={rule.rule_id} className="rounded-md border bg-background/50 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs">{redactResearchText(rule.rule_id)}</span>
                    <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      {redactResearchText(rule.reason_code)}
                    </span>
                  </div>
                  <p className="mt-2 text-muted-foreground">{redactResearchText(rule.explanation)}</p>
                  {rule.evidence_refs.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {rule.evidence_refs.map((ref) => (
                        <span key={ref} className="rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                          {redactResearchText(ref)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No triggered rules recorded.</p>
          )}
        </div>
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
