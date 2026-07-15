import { useState } from "react";
import { calculateJournalCompliance } from "@/lib/journal";
import type { JournalState } from "./performanceShared";

const controls = [
  ["followedSetupRules", "Followed setup rules"],
  ["respectedRiskLimit", "Respected risk limit"],
  ["waitedForConfirmation", "Waited for confirmation"],
  ["avoidedRevengeTrading", "Avoided revenge trading"],
  ["avoidedOvertrading", "Avoided overtrading"],
  ["followedSessionPlan", "Followed session plan"],
  ["recordedPostTradeReview", "Recorded post-trade review"],
] as const;

export function RuleCompliancePanel({ entries }: JournalState) {
  const [state, setState] = useState({ followedSetupRules: true, respectedRiskLimit: true, waitedForConfirmation: true, avoidedRevengeTrading: true, avoidedOvertrading: true, followedSessionPlan: true, recordedPostTradeReview: false });
  const result = calculateJournalCompliance({ ...state, entries });
  return <section className="rounded-2xl border bg-card p-5" aria-labelledby="rule-compliance-title"><h2 id="rule-compliance-title" className="text-xl font-semibold">Rule Compliance</h2><p className="mt-2 text-sm text-muted-foreground">Based only on current local journal entries and selected rules.</p><div className="mt-5 grid gap-4 lg:grid-cols-2"><div className="grid gap-2">{controls.map(([key, label]) => <label key={key} className="flex items-center gap-2 rounded-xl border bg-background/70 p-3 text-sm"><input type="checkbox" checked={state[key]} onChange={(e) => setState({ ...state, [key]: e.target.checked })} />{label}</label>)}</div><div aria-live="polite" className="grid gap-3"><Metric label="Compliance percentage" value={`${result.compliancePercentage.toFixed(1)}%`} /><Metric label="Classification" value={result.classification} /><Metric label="Improvement focus" value={result.improvementFocus} /><div className="rounded-xl border bg-background/70 p-3"><p className="text-xs text-muted-foreground">Violated rules</p><p className="mt-1 text-sm">{result.violatedRules.length ? result.violatedRules.join(", ") : "No selected rule violations"}</p></div></div></div></section>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border bg-background/70 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-mono text-sm font-semibold tabular-nums">{value}</p></div>; }
