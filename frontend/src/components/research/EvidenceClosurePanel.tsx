import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import type { EvidenceClosureSummary } from "@/lib/api";
import { redactResearchText } from "./redaction";

export function EvidenceClosurePanel({ summary }: { summary?: EvidenceClosureSummary | null }) {
  const passed = summary?.passed === true;
  const degraded = summary?.degraded === true;
  const statusLabel = passed ? "Passed" : "Failed";
  const Icon = passed ? CheckCircle2 : XCircle;
  const verifiedFrom = summary?.verified_from || [];
  const problemRefs = [
    ...(summary?.missing_refs || []),
    ...(summary?.dangling_refs || []),
    ...(summary?.inconsistent_ids || []),
    ...(summary?.outbox_pending || []),
  ];

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <ShieldAlert className="h-4 w-4 text-muted-foreground" />
        Evidence Closure
      </div>
      {summary ? (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium">
              <Icon className="h-3.5 w-3.5" />
              {statusLabel}
            </span>
            {degraded && (
              <span className="rounded-md border border-amber-500/30 px-2 py-1 text-xs text-amber-700 dark:text-amber-300">
                Degraded
              </span>
            )}
          </div>
          {verifiedFrom.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {verifiedFrom.map((source) => (
                <span key={source} className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                  {source}
                </span>
              ))}
            </div>
          )}
          {problemRefs.length > 0 && (
            <ul className="space-y-1 text-xs text-danger">
              {problemRefs.map((ref) => <li key={ref}>{redactResearchText(ref)}</li>)}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No evidence closure report recorded.</p>
      )}
    </section>
  );
}
