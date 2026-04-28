import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { CheckCircle2, XCircle, BarChart3, List, Code2, ArrowLeft, Download, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { api, type RunData, type BacktestMetrics } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { EquityChart } from "@/components/charts/EquityChart";
import { MetricsCard } from "@/components/chat/MetricsCard";
import { ValidationPanel } from "@/components/charts/ValidationPanel";
import { Skeleton, SkeletonMetrics, SkeletonChart } from "@/components/common/Skeleton";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";

const rehypePlugins = [rehypeHighlight];

type Tab = "chart" | "trades" | "code" | "validation";

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
  const { t } = useI18n();
  const navigate = useNavigate();
  const [run, setRun] = useState<RunData | null>(null);
  const [code, setCode] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<Tab>("chart");
  const [loading, setLoading] = useState(true);

  const hasValidation = !!run?.validation;
  const TABS: { id: Tab; label: string; icon: typeof BarChart3; hidden?: boolean }[] = [
    { id: "chart", label: t.chart, icon: BarChart3 },
    { id: "trades", label: t.trades, icon: List },
    { id: "validation", label: t.validation, icon: ShieldCheck, hidden: !hasValidation },
    { id: "code", label: t.code, icon: Code2 },
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
  if (!run) return <div className="p-8 text-red-500">{t.runNotFound}</div>;

  const ok = run.status === "success";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b p-4 space-y-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="p-1 rounded-md hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            title={t.goBack}
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
                title={t.downloadTradesCsv}
              >
                <Download className="h-3.5 w-3.5" /> {t.downloadTradesCsv}
              </button>
            )}
            {run.metrics && (
              <button
                onClick={() => downloadCsv(`metrics_${runId}.csv`, buildMetricsCsv(run.metrics!))}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted transition-colors"
                title={t.downloadMetricsCsv}
              >
                <Download className="h-3.5 w-3.5" /> {t.downloadMetricsCsv}
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
          {tab === "code" && <CodeTab code={code} />}
        </ErrorBoundary>
      </div>
    </div>
  );
}

function ChartTab({ run }: { run: RunData }) {
  const { t } = useI18n();
  const entries = run.price_series ? Object.entries(run.price_series) : [];
  const hasEquity = run.equity_curve && run.equity_curve.length > 0;

  if (entries.length === 0 && !hasEquity) {
    return (
      <div className="p-8 text-center text-muted-foreground space-y-2">
        <p className="text-sm">{t.noChartData}</p>
        <p className="text-xs">{t.noChartDataHint}</p>
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
          <h3 className="text-sm font-medium mb-1">{t.equityDrawdown}</h3>
          <EquityChart data={run.equity_curve!} height={280} />
        </div>
      )}
    </div>
  );
}

function TradesTab({ run }: { run: RunData }) {
  const { t } = useI18n();
  const trades = run.trade_log || [];
  if (trades.length === 0) return <div className="p-8 text-muted-foreground text-sm">{t.noTrades}</div>;
  return (
    <div className="p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4">{t.colTime}</th>
            <th className="py-2 pr-4">{t.colCode}</th>
            <th className="py-2 pr-4">{t.colSide}</th>
            <th className="py-2 pr-4">{t.colPrice}</th>
            <th className="py-2 pr-4">{t.colQty}</th>
            <th className="py-2">{t.colReason}</th>
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
  const { t } = useI18n();
  const files = Object.entries(code);
  const [active, setActive] = useState(files[0]?.[0] || "");
  if (files.length === 0) return <div className="p-8 text-muted-foreground text-sm">{t.noCode}</div>;
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

