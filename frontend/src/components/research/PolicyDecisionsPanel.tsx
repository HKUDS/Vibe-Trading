import { Gavel } from "lucide-react";
import type { PolicyDecisionsResponse } from "@/lib/api";
import { redactResearchText } from "./redaction";

export function PolicyDecisionsPanel({
  policyDecisions,
  decisionIds = [],
}: {
  policyDecisions?: PolicyDecisionsResponse | null;
  decisionIds?: string[];
}) {
  const decisions = policyDecisions?.decisions || [];
  const ids = policyDecisions?.decision_ids?.length ? policyDecisions.decision_ids : decisionIds;

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Gavel className="h-4 w-4 text-muted-foreground" />
        Policy Decisions
      </div>
      {decisions.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-4">Decision</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Risk</th>
                <th className="py-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((decision) => (
                <tr key={decision.decision_id || decision.evidence_refs.join(":")} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-mono text-xs">{redactResearchText(decision.decision_id)}</td>
                  <td className="py-2 pr-4">{redactResearchText(decision.status)}</td>
                  <td className="py-2 pr-4">{redactResearchText(decision.risk_level)}</td>
                  <td className="py-2 text-muted-foreground">{decision.reason_codes.map(redactResearchText).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : ids.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {ids.map((id) => (
            <span key={id} className="rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
              {redactResearchText(id)}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No policy decisions recorded.</p>
      )}
    </section>
  );
}
