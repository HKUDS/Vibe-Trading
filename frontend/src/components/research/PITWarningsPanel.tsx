import { AlertTriangle } from "lucide-react";
import { redactResearchText } from "./redaction";

export interface StructuredIssue {
  code: string;
  severity?: string;
  message?: string;
}

export function PITWarningsPanel({
  warnings = [],
  hardFailures = [],
}: {
  warnings?: StructuredIssue[];
  hardFailures?: StructuredIssue[];
}) {
  const pitWarnings = warnings.filter((item) => /PIT|AVAILABLE_AT|DATA_/i.test(item.code));
  const pitFailures = hardFailures.filter((item) => /PIT|AVAILABLE_AT|DATA_/i.test(item.code));
  const items = [...pitFailures, ...pitWarnings];

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <AlertTriangle className="h-4 w-4 text-muted-foreground" />
        PIT Status
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No PIT warnings recorded.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {items.map((item) => (
            <li key={`${item.severity || "warning"}-${item.code}`} className="rounded-md border border-amber-500/25 bg-amber-500/5 p-2">
              <div className="font-mono text-xs font-medium">{redactResearchText(item.code)}</div>
              {item.message && <div className="mt-1 text-xs text-muted-foreground">{redactResearchText(item.message)}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
