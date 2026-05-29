import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Code2,
  Database,
  Download,
  FileCheck2,
  Fingerprint,
  List,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type BacktestMetrics, type RunCard, type RunData } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { EquityChart } from "@/components/charts/EquityChart";
import { MetricsCard } from "@/components/chat/MetricsCard";
import { ValidationPanel } from "@/components/charts/ValidationPanel";
import { Skeleton, SkeletonMetrics, SkeletonChart } from "@/components/common/Skeleton";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";

const rehypePlugins = [rehypeHighlight];

type Tab = "chart" | "trades" | "runCard" | "code" | "validation";

function downloadCsv(filename: string, csvContent: string) {
  const blob = new Blob(["\uFEFF" + csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function escapeCsvField(value: unknown): string {
  const str = String(value ?? "");
  if (str.includes(",") || str.includes('"') || str.includes("\n")) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function buildTradesCsv(trades: Array<Record<string, string>>): string {
  if (trades.length === 0) return "";
  const keys = [...new Set(trades.flatMap(Object.keys))];
  const header = keys.map(escapeCsvField).join(",");
  const rows = trades.map(tr => keys.map(k => escapeCsvField(tr[k])).join(","));
  return [header, ...rows].join("\n");
}

function buildMetricsCsv(metrics: BacktestMetrics): string {
  const header = "metric,value";
  const rows = Object.entries(metrics).map(([k, v]) => `${escapeCsvField(k)},${escapeCsvField(v)}`);
  return [header, ...rows].join("\n");
}

export function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<RunData | null>(null);
  const [code, setCode] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<Tab>("chart");
  const [loading, setLoading] = useState(true);

  const hasValidation = !!run?.validation;
  const hasRunCard = !!run?.run_card;
  const TABS: { id: Tab; label: string; icon: typeof BarChart3; hidden?: boolean }[] = [
    { id: "chart", label: "Chart", icon: BarChart3 },
    { id: "trades", label: "Trades", icon: List },
    { id: "validation", label: "Validation", icon: ShieldCheck, hidden: !hasValidation },
    { id: "runCard", label: "Run Card", icon: FileCheck2, hidden: !hasRunCard },
    { id: "code", label: "Code", icon: Code2 },
  ];

  useEffect(() => {
    if (!runId) return;
    Promise.all([
      api.getRun(runId).catch(() => null),
      api.getRunCode(runId).catch(() => ({})),
    ]).then(([r, c]) => { setRun(r); setCode(c || {}); }).finally(() => setLoading(false));
  }, [runId]);

  if (loading) {
    return (
      <div className="p-8 space-y-4">
        <Skeleton className="h-6 w-48" />
        <SkeletonMetrics />
        <SkeletonChart height={400} />
      </div>
    );
  }
  if (!run) return <div className="p-8 text-red-500">Run not found</div>;

  const ok = run.status === "success";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b p-4 space-y-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="p-1 rounded-md hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            title="Go back"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          {ok ? <CheckCircle2 className="h-5 w-5 text-success" /> : <XCircle className="h-5 w-5 text-danger" />}
          <h1 className="font-mono text-sm font-medium">{runId}</h1>
          {run.elapsed_seconds && <span className="text-xs text-muted-foreground">{run.elapsed_seconds.toFixed(1)}s</span>}
        </div>
        {run.prompt && <p className="text-sm text-muted-foreground">{run.prompt}</p>}
        {run.metrics && <MetricsCard metrics={run.metrics as Record<string, number>} />}

        <div className="flex items-center gap-1">
          {TABS.filter(t => !t.hidden).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                tab === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
              )}
            >
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}

          <div className="ml-auto flex gap-1">
            {run.trade_log && run.trade_log.length > 0 && (
              <button
                onClick={() => downloadCsv(`trades_${runId}.csv`, buildTradesCsv(run.trade_log!))}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
                title="Download Trades CSV"
              >
                <Download className="h-3.5 w-3.5" /> Download Trades CSV
              </button>
            )}
            {run.metrics && (
              <button
                onClick={() => downloadCsv(`metrics_${runId}.csv`, buildMetricsCsv(run.metrics!))}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
                title="Download Metrics CSV"
              >
                <Download className="h-3.5 w-3.5" /> Download Metrics CSV
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <ErrorBoundary>
          {tab === "chart" && <ChartTab run={run} />}
          {tab === "trades" && <TradesTab run={run} />}
          {tab === "validation" && run.validation && <ValidationPanel data={run.validation} />}
          {tab === "runCard" && run.run_card && <RunCardTab card={run.run_card} />}
          {tab === "code" && <CodeTab code={code} />}
        </ErrorBoundary>
      </div>
    </div>
  );
}

function RunCardTab({ card }: { card: RunCard }) {
  const backtest = card.backtest || {};
  const reproducibility = card.reproducibility || {};
  const metrics = card.metrics || {};
  const artifacts = card.artifacts || [];
  const warnings = card.warnings || [];
  const dataSources = card.data_sources || [];

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <RunCardStat label="Schema" value={card.schema_version || "unknown"} />
        <RunCardStat label="Generated" value={formatRunCardValue(card.generated_at)} />
        <RunCardStat label="Data sources" value={dataSources.length ? dataSources.join(", ") : "None recorded"} />
        <RunCardStat label="Warnings" value={String(warnings.length)} tone={warnings.length ? "warning" : "normal"} />
      </div>

      {warnings.length > 0 && (
        <section className="rounded-md border border-amber-500/25 bg-amber-500/5 p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4" />
            Warnings
          </div>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {warnings.map((warning, index) => <li key={index}>{warning}</li>)}
          </ul>
        </section>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <RunCardPanel title="Backtest Summary" icon={Database}>
          <KeyValueTable data={backtest} empty="No backtest summary recorded." />
        </RunCardPanel>
        <RunCardPanel title="Reproducibility" icon={Fingerprint}>
          <KeyValueTable data={reproducibility} empty="No reproducibility hashes recorded." monospaceValues />
        </RunCardPanel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <RunCardPanel title="Metrics" icon={BarChart3}>
          <KeyValueTable data={metrics} empty="No scalar metrics recorded." />
        </RunCardPanel>
        <RunCardPanel title="Validation" icon={ShieldCheck}>
          {card.validation ? (
            <pre className="max-h-80 overflow-auto rounded-md bg-muted/40 p-3 text-xs leading-relaxed">
              {JSON.stringify(card.validation, null, 2)}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">No validation payload recorded.</p>
          )}
        </RunCardPanel>
      </div>

      <RunCardPanel title="Artifact Checksums" icon={FileCheck2}>
        {artifacts.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4">Path</th>
                  <th className="py-2 pr-4">Size</th>
                  <th className="py-2">SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((artifact) => (
                  <tr key={`${artifact.path}-${artifact.sha256}`} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">{artifact.path}</td>
                    <td className="py-2 pr-4 tabular-nums text-muted-foreground">{formatBytes(artifact.size_bytes)}</td>
                    <td className="py-2 font-mono text-xs text-muted-foreground">{shortHash(artifact.sha256)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No artifact checksums recorded.</p>
        )}
      </RunCardPanel>
    </div>
  );
}

function RunCardStat({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "warning" }) {
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 truncate text-sm font-medium", tone === "warning" ? "text-amber-700 dark:text-amber-300" : "")}>{value}</div>
    </div>
  );
}

function RunCardPanel({ title, icon: Icon, children }: { title: string; icon: typeof FileCheck2; children: ReactNode }) {
  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Icon className="h-4 w-4 text-muted-foreground" />
        {title}
      </div>
      {children}
    </section>
  );
}

function KeyValueTable({ data, empty, monospaceValues = false }: { data: Record<string, unknown>; empty: string; monospaceValues?: boolean }) {
  const entries = Object.entries(data).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <table className="w-full table-fixed text-sm">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key} className="border-b last:border-0">
            <td className="w-36 py-2 pr-4 align-top text-muted-foreground">{key}</td>
            <td className={cn("py-2 align-top", monospaceValues ? "break-all font-mono text-xs" : "break-words text-right tabular-nums")}>{formatRunCardValue(value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatRunCardValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value ?? "");
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value)) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 12)}...${value.slice(-6)}` : value;
}

function ChartTab({ run }: { run: RunData }) {
  const entries = run.price_series ? Object.entries(run.price_series) : [];
  const hasEquity = run.equity_curve && run.equity_curve.length > 0;

  if (entries.length === 0 && !hasEquity) {
    return (
      <div className="p-8 text-center text-muted-foreground space-y-2">
        <p className="text-sm">No chart data available</p>
        <p className="text-xs">The backtest engine may not have generated price data. Check the artifacts/ directory.</p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      {entries.map(([sym, bars]) => (
        <div key={sym}>
          <h3 className="text-sm font-medium mb-1">{sym}</h3>
          <CandlestickChart data={bars} markers={run.trade_markers?.filter(m => m.code === sym)} indicators={run.indicator_series?.[sym]} height={500} />
        </div>
      ))}
      {hasEquity && (
        <div>
          <h3 className="text-sm font-medium mb-1">Equity & Drawdown</h3>
          <EquityChart data={run.equity_curve!} height={280} />
        </div>
      )}
    </div>
  );
}

function TradesTab({ run }: { run: RunData }) {
  const trades = run.trade_log || [];
  if (trades.length === 0) return <div className="p-8 text-muted-foreground text-sm">No trades recorded.</div>;
  return (
    <div className="p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4">Time</th>
            <th className="py-2 pr-4">Code</th>
            <th className="py-2 pr-4">Side</th>
            <th className="py-2 pr-4">Price</th>
            <th className="py-2 pr-4">Qty</th>
            <th className="py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((tr, i) => (
            <tr key={i} className="border-b last:border-0 hover:bg-muted/20">
              <td className="py-2 pr-4 font-mono text-xs">{tr.time || tr.timestamp}</td>
              <td className="py-2 pr-4">{tr.code}</td>
              <td className={cn("py-2 pr-4 font-medium", tr.side === "BUY" ? "text-success" : "text-danger")}>{tr.side}</td>
              <td className="py-2 pr-4 tabular-nums">{tr.price}</td>
              <td className="py-2 pr-4 tabular-nums">{tr.qty}</td>
              <td className="py-2 text-muted-foreground">{tr.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeTab({ code }: { code: Record<string, string> }) {
  const files = Object.entries(code);
  const [active, setActive] = useState(files[0]?.[0] || "");
  if (files.length === 0) return <div className="p-8 text-muted-foreground text-sm">No code files.</div>;
  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 p-2 border-b">
        {files.map(([name]) => (
          <button key={name} onClick={() => setActive(name)} className={cn("px-3 py-1 rounded text-xs font-mono", active === name ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}>{name}</button>
        ))}
      </div>
      <div className="flex-1 overflow-auto p-3 text-[11px] leading-relaxed bg-muted/20 [&_pre]:m-0 [&_pre]:bg-transparent [&_code]:text-[11px]">
        <ReactMarkdown rehypePlugins={rehypePlugins}>
          {`\`\`\`python\n${code[active] || ""}\n\`\`\``}
        </ReactMarkdown>
      </div>
    </div>
  );
}
