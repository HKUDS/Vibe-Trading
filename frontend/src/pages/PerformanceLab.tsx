import { useEffect, useMemo, useState } from "react";
import { BacktestingWorkspace } from "@/components/performance/BacktestingWorkspace";
import { JournalIntelligence } from "@/components/performance/JournalIntelligence";
import { PerformanceBreakdown } from "@/components/performance/PerformanceBreakdown";
import { PerformanceDisclosure } from "@/components/performance/PerformanceDisclosure";
import { PerformanceOverview } from "@/components/performance/PerformanceOverview";
import { RecentAnalysisRuns } from "@/components/performance/RecentAnalysisRuns";
import { RuleCompliancePanel } from "@/components/performance/RuleCompliancePanel";
import { api, type RunListItem } from "@/lib/api";
import type { JournalEntry } from "@/lib/journal";
import { isReportRun, type PerformanceData } from "@/components/performance/performanceShared";

export function PerformanceLab() {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [entries, setEntries] = useState<JournalEntry[]>([]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.listRuns(100)
      .then((list) => { if (alive) setRuns(Array.isArray(list) ? list : []); })
      .catch((err) => { if (alive) setError(err instanceof Error ? err.message : "Unable to load analysis runs."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const data: PerformanceData = useMemo(() => ({ runs, reportRuns: runs.filter(isReportRun), loading, error }), [runs, loading, error]);

  return <main className="mx-auto flex w-full max-w-7xl flex-col gap-5 overflow-x-hidden p-4 md:p-6" aria-labelledby="performance-lab-title"><PerformanceOverview data={data} /><BacktestingWorkspace data={data} /><JournalIntelligence entries={entries} setEntries={setEntries} /><RuleCompliancePanel entries={entries} setEntries={setEntries} /><PerformanceBreakdown {...data} entries={entries} setEntries={setEntries} /><RecentAnalysisRuns data={data} /><PerformanceDisclosure /></main>;
}
