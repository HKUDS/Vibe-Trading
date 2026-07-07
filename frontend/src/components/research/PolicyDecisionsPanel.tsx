import { ShieldCheck } from "lucide-react";

import { redactDisplayText } from "./redaction";

export interface PolicyDecisionSummary {
  decision_id?: string;
  tool_name?: string;
  action?: "allow" | "warn" | "deny" | string;
  rule_id?: string | null;
}

export function PolicyDecisionsPanel({ decisions = [] }: { decisions?: PolicyDecisionSummary[] }) {
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
      {decisions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No policy decisions recorded.</p>
      ) : (
        <div className="space-y-1">
          {decisions.map((decision, index) => (
            <div key={decision.decision_id || index} className="flex items-center justify-between gap-3 rounded-md bg-muted/30 px-2 py-1.5 text-xs">
              <span className="truncate font-mono">{redactDisplayText(decision.tool_name || "unknown_tool")}</span>
              <span className="font-mono text-muted-foreground">{redactDisplayText(decision.rule_id || "no_rule")}</span>
            </div>
          ))}
        </div>
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
