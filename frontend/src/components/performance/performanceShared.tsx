import type { RunListItem } from "@/lib/api";
import type { JournalEntry } from "@/lib/journal";

export interface PerformanceData {
  runs: RunListItem[];
  reportRuns: RunListItem[];
  loading: boolean;
  error: string | null;
}

export interface JournalState {
  entries: JournalEntry[];
  setEntries: (entries: JournalEntry[]) => void;
}

export function EmptyState({ title = "No verified performance data yet.", body = "Run a market analysis or historical validation to populate this section." }: { title?: string; body?: string }) {
  return <div className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground"><p className="font-medium text-foreground">{title}</p><p className="mt-1">{body}</p></div>;
}

export function formatRunDate(value?: string): string {
  if (!value) return "No date available";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function isReportRun(run: RunListItem): boolean {
  return Number.isFinite(run.total_return) || Number.isFinite(run.sharpe);
}
