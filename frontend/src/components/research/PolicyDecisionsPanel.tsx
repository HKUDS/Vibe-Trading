import { ShieldCheck } from "lucide-react";
import type { PolicyDecisionRecord, PolicyDecisionsResponse } from "@/lib/api";
import { redactResearchText } from "./redaction";

export type PolicyDecisionSummary = PolicyDecisionRecord;

export function PolicyDecisionsPanel({
  policyDecisions,
  decisionIds = [],
  decisions: directDecisions,
}: {
  policyDecisions?: PolicyDecisionsResponse | null;
  decisionIds?: string[];
  decisions?: PolicyDecisionRecord[];
}) {
  const decisions = policyDecisions?.decisions || directDecisions || [];
  const ids = policyDecisions?.decision_ids?.length ? policyDecisions.decision_ids : decisionIds;
  const denied = decisions.filter((decision) => decision.action === "deny").length;
  const warned = decisions.filter((decision) => decision.action === "warn").length;

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
        Policy Decisions
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2">
        <PolicyCount label="Denied" value={denied} tone={denied > 0 ? "danger" : "normal"} />
        <PolicyCount label="Warned" value={warned} tone={warned > 0 ? "warning" : "normal"} />
      </div>
      {decisions.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-4">Decision</th>
                <th className="py-2 pr-4">Tool</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Risk</th>
                <th className="py-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((decision, index) => {
                const reasons = Array.isArray(decision.reason_codes)
                  ? decision.reason_codes
                  : decision.rule_id
                    ? [decision.rule_id]
                    : [];
                const key = decision.decision_id || decision.rule_id || decision.tool_name || index;
                return (
                  <tr key={String(key)} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-mono text-xs">{redactResearchText(decision.decision_id)}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{redactResearchText(decision.tool_name || "unknown_tool")}</td>
                  <td className="py-2 pr-4">{redactResearchText(decision.status || decision.action)}</td>
                  <td className="py-2 pr-4">{redactResearchText(decision.risk_level)}</td>
                  <td className="py-2 text-muted-foreground">{reasons.map(redactResearchText).join(", ")}</td>
                  </tr>
                );
              })}
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

function PolicyCount({ label, value, tone }: { label: string; value: number; tone: "normal" | "warning" | "danger" }) {
  const color = tone === "danger" ? "text-danger" : tone === "warning" ? "text-amber-700 dark:text-amber-300" : "";
  return (
    <div className="rounded-md border p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}
