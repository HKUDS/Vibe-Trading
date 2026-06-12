import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  Database,
  Gauge,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { api, type LLMUsageSummary, type RunData, type RunListItem } from "@/lib/api";
import { cn } from "@/lib/utils";

const USAGE_RUN_SCAN_LIMIT = 100;
const HEAVY_RUN_LIMIT = 8;

export function Usage() {
  const [runs, setRuns] = useState<UsageRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadUsage(mode: "initial" | "refresh" = "refresh") {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const list = await api.listRuns({ limit: USAGE_RUN_SCAN_LIMIT, with_usage: true });
      const recent = Array.isArray(list) ? list.slice(0, USAGE_RUN_SCAN_LIMIT) : [];
      const details = await Promise.allSettled(
        recent.map(async (run) => [run, run.llm_usage ? null : await api.getRun(run.run_id)] as const),
      );
      const usageRuns = details.flatMap((result) => {
        if (result.status !== "fulfilled") return [];
        const [run, detail] = result.value;
        const usage = toUsageRun(run, detail || null);
        return usage ? [usage] : [];
      });
      setRuns(usageRuns);
    } catch (err) {
      setRuns([]);
      setError(err instanceof Error ? err.message : "Unable to load agent usage.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadUsage("initial");
  }, []);

  const summary = useMemo(() => summarizeUsage(runs), [runs]);
  const modelRows = useMemo(() => summarizeByModel(runs), [runs]);
  const heavyRuns = useMemo(
    () => [...runs].sort((a, b) => b.totalTokens - a.totalTokens).slice(0, HEAVY_RUN_LIMIT),
    [runs],
  );

  return (
    <div className="min-h-screen p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <section className="flex flex-col gap-4 border-b pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium text-muted-foreground">
              <Gauge className="h-3.5 w-3.5" />
              Agent Usage
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Agent Usage Dashboard</h1>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Aggregates persisted <span className="font-mono">artifacts/llm_usage.json</span> from recent runs.
                Token counts are shown as provider-reported usage; prices are intentionally not estimated.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => loadUsage("refresh")}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition hover:bg-muted disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Refresh
          </button>
        </section>

        {loading ? (
          <div className="grid gap-3 md:grid-cols-4">
            {[1, 2, 3, 4].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-md border bg-muted/40" />
            ))}
          </div>
        ) : null}

        {!loading && error ? (
          <section className="rounded-md border border-amber-500/30 bg-amber-500/5 p-5">
            <div className="flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
              <AlertTriangle className="h-5 w-5" />
              Usage dashboard unavailable
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
          </section>
        ) : null}

        {!loading && !error && runs.length === 0 ? (
          <section className="rounded-md border border-dashed p-8 text-center">
            <Bot className="mx-auto h-8 w-8 text-muted-foreground" />
            <h2 className="mt-3 font-medium">No persisted usage found</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Recent runs do not have <span className="font-mono">llm_usage.json</span> artifacts yet.
            </p>
          </section>
        ) : null}

        {!loading && !error && runs.length > 0 ? (
          <>
            <section className="grid gap-3 md:grid-cols-4">
              <SummaryTile label="Runs with usage" value={String(summary.runCount)} icon={Database} />
              <SummaryTile label="LLM calls" value={formatNumber(summary.calls)} icon={Bot} />
              <SummaryTile label="Input tokens" value={formatNumber(summary.inputTokens)} icon={BarChart3} />
              <SummaryTile label="Output tokens" value={formatNumber(summary.outputTokens)} icon={BarChart3} />
            </section>

            <section className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
              <div className="rounded-md border p-4">
                <h2 className="font-semibold">Provider / Model</h2>
                <div className="mt-4 space-y-3">
                  {modelRows.map((row) => (
                    <ModelUsageRow key={row.key} row={row} maxTokens={summary.totalTokens} />
                  ))}
                </div>
              </div>

              <div className="rounded-md border p-4">
                <h2 className="font-semibold">Usage-Heavy Runs</h2>
                <div className="mt-4 divide-y rounded-md border">
                  {heavyRuns.map((run) => (
                    <RunUsageRow key={run.runId} run={run} />
                  ))}
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}

interface UsageRun {
  runId: string;
  createdAt: string;
  prompt?: string;
  provider: string;
  model: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

interface UsageSummary {
  runCount: number;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

interface ModelUsageSummary extends UsageSummary {
  key: string;
  provider: string;
  model: string;
}

function SummaryTile({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Gauge }) {
  return (
    <div className="rounded-md border p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium uppercase text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-3 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function ModelUsageRow({ row, maxTokens }: { row: ModelUsageSummary; maxTokens: number }) {
  const width = maxTokens > 0 ? Math.max(4, Math.min(100, (row.totalTokens / maxTokens) * 100)) : 0;
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <div className="min-w-0">
          <div className="truncate font-medium">{row.provider}</div>
          <div className="truncate font-mono text-xs text-muted-foreground">{row.model}</div>
        </div>
        <div className="text-right font-mono text-sm">{formatNumber(row.totalTokens)}</div>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-sm bg-muted">
        <div className="h-full bg-primary" style={{ width: `${width}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{row.runCount} runs · {formatNumber(row.calls)} calls</span>
        <span>{formatNumber(row.inputTokens)} in / {formatNumber(row.outputTokens)} out</span>
      </div>
    </div>
  );
}

function RunUsageRow({ run }: { run: UsageRun }) {
  return (
    <Link to={`/runs/${run.runId}`} className="block p-3 transition hover:bg-muted/40">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="truncate font-mono text-sm font-medium">{run.runId}</div>
          <div className="mt-1 truncate text-xs text-muted-foreground">{run.prompt || "No prompt recorded."}</div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs md:justify-end">
          <UsagePill label="total" value={formatNumber(run.totalTokens)} />
          <UsagePill label="calls" value={formatNumber(run.calls)} />
          <UsagePill label="created" value={formatRunDate(run.createdAt)} />
        </div>
      </div>
    </Link>
  );
}

function UsagePill({ label, value }: { label: string; value: string }) {
  return (
    <span className={cn("rounded border px-2 py-1 font-mono", label === "total" && "border-primary/30 text-primary")}>
      <span className="mr-1 text-muted-foreground">{label}</span>
      {value}
    </span>
  );
}

function toUsageRun(run: RunListItem, detail: RunData | null): UsageRun | null {
  const usage = run.llm_usage || detail?.llm_usage;
  if (!usage || !hasUsage(usage)) return null;
  const inputTokens = toFiniteNumber(usage.input_tokens);
  const outputTokens = toFiniteNumber(usage.output_tokens);
  const totalTokens = toFiniteNumber(usage.total_tokens) || inputTokens + outputTokens;
  return {
    runId: run.run_id,
    createdAt: run.created_at,
    prompt: run.prompt || detail?.prompt,
    provider: stringOrUnknown(usage.provider),
    model: stringOrUnknown(usage.model),
    calls: toFiniteNumber(usage.calls) || countIterations(usage),
    inputTokens,
    outputTokens,
    totalTokens,
  };
}

function hasUsage(usage: LLMUsageSummary): boolean {
  return Boolean(
    toFiniteNumber(usage.input_tokens) ||
    toFiniteNumber(usage.output_tokens) ||
    toFiniteNumber(usage.total_tokens) ||
    toFiniteNumber(usage.calls) ||
    countIterations(usage),
  );
}

function summarizeUsage(runs: UsageRun[]): UsageSummary {
  return runs.reduce<UsageSummary>((acc, run) => ({
    runCount: acc.runCount + 1,
    calls: acc.calls + run.calls,
    inputTokens: acc.inputTokens + run.inputTokens,
    outputTokens: acc.outputTokens + run.outputTokens,
    totalTokens: acc.totalTokens + run.totalTokens,
  }), { runCount: 0, calls: 0, inputTokens: 0, outputTokens: 0, totalTokens: 0 });
}

function summarizeByModel(runs: UsageRun[]): ModelUsageSummary[] {
  const rows = new Map<string, ModelUsageSummary>();
  for (const run of runs) {
    const key = `${run.provider}:::${run.model}`;
    const current = rows.get(key) || {
      key,
      provider: run.provider,
      model: run.model,
      runCount: 0,
      calls: 0,
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
    };
    current.runCount += 1;
    current.calls += run.calls;
    current.inputTokens += run.inputTokens;
    current.outputTokens += run.outputTokens;
    current.totalTokens += run.totalTokens;
    rows.set(key, current);
  }
  return Array.from(rows.values()).sort((a, b) => b.totalTokens - a.totalTokens);
}

function countIterations(usage: LLMUsageSummary): number {
  return Array.isArray(usage.iterations) ? usage.iterations.length : 0;
}

function toFiniteNumber(value: unknown): number {
  const numeric = typeof value === "number" ? value : Number(value || 0);
  return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
}

function stringOrUnknown(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "unknown";
}

function formatNumber(value: number): string {
  return Math.round(value).toLocaleString();
}

function formatRunDate(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value || "unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
