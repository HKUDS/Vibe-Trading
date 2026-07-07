import { ShieldCheck } from "lucide-react";
import type { RunCard, TriggeredRule } from "@/lib/api";
import { redactResearchText } from "./redaction";

export function QuantScorecardPanel({ card }: { card: RunCard }) {
  const hardFailures = card.hard_failures || [];
  const triggeredRules = (card.triggered_rules || []) as TriggeredRule[];

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
        Scorecard Triggered Rules
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Hard Failures</div>
          <ul data-testid="hard-failures" className="space-y-1 text-sm">
            {hardFailures.length > 0 ? (
              hardFailures.map((failure) => (
                <li key={failure} className="rounded-md border border-danger/20 bg-danger/5 px-2 py-1 text-danger">
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
    </section>
  );
}
