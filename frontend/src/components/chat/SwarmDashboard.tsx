import { useEffect, useState, useRef } from "react";
import { CheckCircle2, XCircle, Loader2, Clock, Timer } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useI18n } from "@/lib/i18n";

export interface SwarmAgent {
  id: string;
  status: "waiting" | "running" | "done" | "failed" | "retry";
  tool: string;
  iters: number;
  startedAt: number;
  elapsed: number;
  lastText: string;
  summary: string;
}

export interface SwarmDashboardProps {
  preset: string;
  agents: Record<string, SwarmAgent>;
  agentOrder: string[];
  currentLayer: number;
  finished: boolean;
  finalStatus: string;
  startTime: number;
  completedSummaries: Array<{ agentId: string; summary: string }>;
  finalReport: string;
}

const AGENT_COLORS = [
  "text-cyan-400", "text-violet-400", "text-emerald-400",
  "text-amber-400", "text-blue-400", "text-rose-400",
  "text-teal-400", "text-pink-400",
];
const AGENT_BG = [
  "bg-cyan-500/10", "bg-violet-500/10", "bg-emerald-500/10",
  "bg-amber-500/10", "bg-blue-500/10", "bg-rose-500/10",
  "bg-teal-500/10", "bg-pink-500/10",
];

function agentColor(idx: number) { return AGENT_COLORS[idx % AGENT_COLORS.length]; }
function agentBg(idx: number) { return AGENT_BG[idx % AGENT_BG.length]; }

function formatTime(seconds: number) {
  if (seconds <= 0) return "\u2014";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function StatusIcon({ status }: { status: SwarmAgent["status"] }) {
  switch (status) {
    case "running": return <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />;
    case "done": return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
    case "failed": return <XCircle className="h-3.5 w-3.5 text-red-500" />;
    case "retry": return <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />;
    default: return <Clock className="h-3.5 w-3.5 text-muted-foreground/40" />;
  }
}

function StatusLabel({ status }: { status: SwarmAgent["status"] }) {
  const { t } = useI18n();
  const labels: Record<string, string> = {
    running: t.swarmRunning,
    done: t.swarmDone,
    failed: t.swarmFailed,
    retry: t.swarmRetry,
    waiting: t.swarmWaiting,
  };
  switch (status) {
    case "running": return <span className="text-primary font-medium">{labels.running}</span>;
    case "done": return <span className="text-emerald-500 font-medium">{labels.done}</span>;
    case "failed": return <span className="text-red-500 font-medium">{labels.failed}</span>;
    case "retry": return <span className="text-amber-500 font-medium">{labels.retry}</span>;
    default: return <span className="text-muted-foreground/50">{labels.waiting}</span>;
  }
}

export function SwarmDashboard(props: SwarmDashboardProps) {
  const { preset, agents, agentOrder, finished, finalStatus, startTime, completedSummaries, finalReport } = props;
  const [now, setNow] = useState(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    timerRef.current = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timerRef.current);
  }, []);

  const elapsedTotal = (now - startTime) / 1000;
  const doneCount = Object.values(agents).filter(a => a.status === "done" || a.status === "failed").length;
  const totalCount = Math.max(agentOrder.length, 1);
  const pct = Math.round((doneCount / totalCount) * 100);

  const borderColor = finished
    ? (finalStatus === "completed" ? "border-emerald-500/50" : "border-red-500/50")
    : "border-primary/30";
  const headerBg = finished
    ? (finalStatus === "completed" ? "bg-emerald-500/5" : "bg-red-500/5")
    : "bg-primary/5";

  return (
    <div className="space-y-3 w-full">
      {/* Dashboard panel */}
      <div className={`rounded-xl border ${borderColor} overflow-hidden`}>
        {/* Header */}
        <div className={`px-4 py-2.5 ${headerBg} flex items-center justify-between`}>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm">{preset}</span>
            {finished ? (
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                finalStatus === "completed"
                  ? "bg-emerald-500/20 text-emerald-500"
                  : "bg-red-500/20 text-red-500"
              }`}>
                {finalStatus === "completed" ? t.swarmCompleted : t.swarmFailedStatus}
              </span>
            ) : (
              <span className="text-xs px-2 py-0.5 rounded-full bg-primary/20 text-primary font-medium">
                {t.swarmRunningStatus}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Timer className="h-3 w-3" />
            {formatTime(elapsedTotal)}
          </div>
        </div>

        {/* Agent rows */}
        <div className="divide-y divide-border/50">
          {agentOrder.map((agentId, idx) => {
            const agent = agents[agentId];
            if (!agent) return null;
            const elapsed = agent.status === "running" && agent.startedAt
              ? (now - agent.startedAt) / 1000
              : agent.elapsed / 1000;

            return (
              <div key={agentId} className="px-4 py-2 flex items-center gap-3 text-sm">
                {/* Agent name */}
                <div className={`w-40 shrink-0 font-mono text-xs truncate ${agentColor(idx)}`}>
                  {agent.id}
                </div>
                {/* Status */}
                <div className="w-20 shrink-0 flex items-center gap-1.5">
                  <StatusIcon status={agent.status} />
                  <StatusLabel status={agent.status} />
                </div>
                {/* Tool */}
                <div className="w-28 shrink-0 text-xs text-muted-foreground font-mono truncate">
                  {agent.tool || "\u2014"}
                </div>
                {/* Time */}
                <div className="w-16 shrink-0 text-xs text-muted-foreground text-right tabular-nums">
                  {formatTime(elapsed)}
                </div>
                {/* Iters */}
                <div className="w-10 shrink-0 text-xs text-muted-foreground text-right tabular-nums">
                  {agent.iters > 0 ? agent.iters : "\u2014"}
                </div>
                {/* Last output */}
                <div className="flex-1 min-w-0 text-xs text-muted-foreground/60 truncate">
                  {agent.lastText}
                </div>
              </div>
            );
          })}
        </div>

        {/* Progress bar */}
        <div className="px-4 py-2 border-t border-border/50 flex items-center gap-3">
          <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                finished
                  ? (finalStatus === "completed" ? "bg-emerald-500" : "bg-red-500")
                  : "bg-primary"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground tabular-nums w-10 text-right">{pct}%</span>
        </div>
      </div>

      {/* Completed agent summaries */}
      {completedSummaries.length > 0 && (
        <div className="space-y-2">
          {completedSummaries.map(({ agentId, summary }, idx) => {
            const agentIdx = agentOrder.indexOf(agentId);
            const colorIdx = agentIdx >= 0 ? agentIdx : idx;
            const lines = summary.split("\n");
            const preview = lines.slice(0, 8).join("\n") + (lines.length > 8 ? "\n..." : "");
            return (
              <div key={agentId + idx} className={`rounded-lg ${agentBg(colorIdx)} px-4 py-3`}>
                <div className={`text-xs font-semibold mb-1.5 ${agentColor(colorIdx)}`}>
                  {agentId}
                </div>
                <div className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
                  {preview}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Final report */}
      {finalReport && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-5 py-4">
          <div className="text-xs font-semibold text-emerald-500 mb-3">{t.swarmFinalReport}</div>
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{finalReport}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
