import { CheckCircle2, FileText, FlaskConical, TrendingDown } from "lucide-react";
import { formatMetricVal } from "@/lib/formatters";
import type { PerformanceData } from "./performanceShared";

export function PerformanceOverview({ data }: { data: PerformanceData }) {
  const latest = data.reportRuns[0];
  const cards = [
    { label: "Completed Analyses", value: data.loading ? "Loading…" : String(data.runs.filter((run) => ["success", "done", "completed", "complete"].includes((run.status || "").toLowerCase())).length), hint: data.runs.length ? "Verified from existing analysis runs" : "Run an analysis to populate this metric", icon: CheckCircle2 },
    { label: "Available Reports", value: data.loading ? "Loading…" : String(data.reportRuns.length), hint: data.reportRuns.length ? "Reports with available return or Sharpe metrics" : "No verified data available", icon: FileText },
    { label: "Latest Validation Status", value: latest ? latest.status || "unknown" : "No verified data available", hint: latest ? "From the latest available report run" : "Run a historical validation to populate this metric", icon: CheckCircle2 },
    { label: "Recent Drawdown", value: "No verified data available", hint: "Run-list summaries do not expose drawdown; open an analysis report for verified drawdown details.", icon: TrendingDown },
    { label: "Strategy Tests", value: data.loading ? "Loading…" : String(data.reportRuns.length), hint: "Counted from existing report-worthy analysis runs", icon: FlaskConical },
  ];
  return <section className="rounded-2xl border bg-card p-5" aria-labelledby="performance-lab-title"><p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">Performance Lab</p><h1 id="performance-lab-title" className="mt-2 text-2xl font-bold tracking-tight">Test the Strategy. Review the Trader. Improve the Process.</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">TradeCoreFX combines historical validation, journal review and behavioural analysis to help traders understand both strategy performance and execution discipline.</p>{data.error && <p className="mt-3 rounded-xl border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">{data.error}</p>}<div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{cards.map(({ label, value, hint, icon: Icon }) => <article key={label} className="rounded-xl border bg-background/70 p-4"><div className="flex items-center justify-between gap-2"><p className="text-xs text-muted-foreground">{label}</p><Icon className="h-4 w-4 text-primary" /></div><p className="mt-2 font-mono text-lg font-semibold tabular-nums">{label === "Recent Drawdown" && latest?.total_return != null ? formatMetricVal("total_return", latest.total_return) : value}</p><p className="mt-2 text-xs text-muted-foreground">{hint}</p></article>)}</div></section>;
}
