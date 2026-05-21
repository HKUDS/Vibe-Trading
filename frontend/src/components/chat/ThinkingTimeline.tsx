import { useState, useEffect, useMemo, memo } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { localizeToolName } from "@/lib/tools";
import type { AgentMessage } from "@/types/agent";

interface Props {
  messages: AgentMessage[];
  isLatest?: boolean;
}

export const ThinkingTimeline = memo(function ThinkingTimeline({ messages, isLatest = false }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(isLatest);

  const toolLabel = (tool?: string): string => {
    if (!tool) return t.toolProcessing;
    const key = localizeToolName(tool);
    if (key === tool) return tool;
    return (t as Record<string, string>)[key] || tool;
  };

  useEffect(() => {
    if (!isLatest) setExpanded(false);
  }, [isLatest]);

  const { steps, hasError, isRunning, totalMs, latestTool, latestThinking } = useMemo(() => {
    let totalMs = 0;
    let latestTool = "";
    let latestThinking = "";
    const steps: Array<{ tool: string; label: string; status: "running" | "ok" | "error"; elapsed_ms?: number }> = [];

    for (const m of messages) {
      if (m.type === "thinking" && m.content) latestThinking = m.content;
      if (m.type === "tool_call") {
        steps.push({ tool: m.tool || "", label: toolLabel(m.tool), status: m.status === "running" ? "running" : "ok", elapsed_ms: undefined });
        if (m.status === "running") latestTool = m.tool || "";
      }
      if (m.type === "tool_result") {
        const existing = [...steps].reverse().find((s) => s.tool === m.tool);
        if (existing) {
          existing.status = m.status === "ok" ? "ok" : "error";
          existing.elapsed_ms = m.elapsed_ms;
        }
        if (m.elapsed_ms) totalMs += m.elapsed_ms;
      }
    }

    return {
      steps,
      hasError: steps.some((s) => s.status === "error"),
      isRunning: steps.some((s) => s.status === "running"),
      totalMs,
      latestTool,
      latestThinking,
    };
  }, [messages]);

  const stepCount = steps.length;
  const summaryText = isRunning
    ? t.thinkingRunning.replace("{tool}", toolLabel(latestTool))
    : t.thinkingDone.replace("{count}", String(stepCount)) + (totalMs > 0 ? `（用时 ${(totalMs / 1000).toFixed(1)} 秒）` : "");

  return (
    <div className="rounded-lg border border-border/40 bg-muted/5 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-muted/10 transition-colors"
      >
        {expanded
          ? <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
          : <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
        {isRunning ? (
          <Loader2 className="h-3 w-3 text-primary animate-spin shrink-0" />
        ) : hasError ? (
          <XCircle className="h-3 w-3 text-danger shrink-0" />
        ) : (
          <CheckCircle2 className="h-3 w-3 text-success/70 shrink-0" />
        )}
        <span className={cn("text-muted-foreground", isRunning && "text-foreground")}>
          {summaryText}
        </span>
      </button>

      {!expanded && isRunning && latestThinking && (
        <div className="px-3 pb-2 -mt-1">
          <p className="text-[11px] text-muted-foreground/40 line-clamp-1 pl-5 italic">
            {latestThinking.slice(-100)}
          </p>
        </div>
      )}

      {expanded && steps.length > 0 && (
        <div className="border-t border-border/30 px-3 py-1.5 space-y-0.5">
          {steps.map((step, i) => (
            <div key={`${step.tool}-${i}`} className="flex items-center gap-2 py-1 text-xs">
              <span className="text-border/60 shrink-0 w-3 text-center" aria-hidden="true">
                {i < steps.length - 1 ? "├" : "└"}
              </span>

              {step.status === "running" ? (
                <Loader2 className="h-3 w-3 text-primary animate-spin shrink-0" />
              ) : step.status === "error" ? (
                <XCircle className="h-3 w-3 text-danger shrink-0" />
              ) : (
                <Circle className="h-3 w-3 text-success/50 shrink-0" fill="currentColor" />
              )}

              <span className={cn(
                "flex-1",
                step.status === "running" ? "text-foreground" : "text-muted-foreground/60",
              )}>
                {step.label}
              </span>

              {step.status === "running" ? (
                <span className="text-[10px] text-primary/60">{t.toolRunning}</span>
              ) : step.elapsed_ms != null ? (
                <span className="text-[10px] text-muted-foreground/40 tabular-nums">{(step.elapsed_ms / 1000).toFixed(1)}s</span>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {expanded && steps.length === 0 && latestThinking && (
        <div className="border-t border-border/30 px-3 py-2">
          <p className="text-xs text-muted-foreground/50 leading-relaxed line-clamp-4">
            {latestThinking}
          </p>
        </div>
      )}
    </div>
  );
});
