import { memo } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  Circle,
  Loader2,
  RotateCcw,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import {
  localizeStatus,
  type ManifestTranslation,
} from "@/lib/swarmI18n";
import { localizeToolName } from "@/lib/tools";
import type {
  SwarmAgentDisplayStatus,
  SwarmAgentStatus,
  SwarmRunStatus,
} from "@/types/agent";

interface Props {
  agents: SwarmRunStatus["agents"];
  emptyStatus?: string;
  isActive?: boolean;
}

const WIDE_GRID_COLUMNS =
  "grid-cols-[minmax(0,1.25fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,0.55fr)_minmax(0,1.5fr)]";
const AGENT_ENTER_ANIMATION =
  "animate-[msg-enter_300ms_cubic-bezier(0.16,1,0.3,1)_both] motion-reduce:animate-none";

function formatElapsed(
  seconds: number | undefined,
  t: ManifestTranslation,
): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "-";
  if (seconds < 60) {
    return t("swarm.elapsed.seconds", {
      value: seconds.toFixed(seconds < 10 ? 1 : 0),
    });
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return t("swarm.elapsed.minutesSeconds", { minutes: mins, seconds: secs });
}

function statusTone(status: SwarmAgentDisplayStatus): string {
  switch (status) {
    case "done":
      return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
    case "failed":
      return "bg-destructive/10 text-destructive";
    case "blocked":
      return "bg-amber-500/10 text-amber-600 dark:text-amber-400";
    case "retry":
      return "bg-sky-500/10 text-sky-600 dark:text-sky-400";
    case "running":
      return "bg-primary/10 text-primary";
    case "cancelled":
    case "waiting":
    default:
      return "bg-muted text-muted-foreground";
  }
}

function StatusIcon({
  animate,
  status,
}: {
  animate: boolean;
  status: SwarmAgentDisplayStatus;
}) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="h-3 w-3" />;
    case "failed":
      return <XCircle className="h-3 w-3" />;
    case "blocked":
      return <ShieldAlert className="h-3 w-3" />;
    case "retry":
      return <RotateCcw className="h-3 w-3" />;
    case "running":
      return (
        <Loader2 className={animate ? "h-3 w-3 animate-spin" : "h-3 w-3"} />
      );
    case "cancelled":
      return <XCircle className="h-3 w-3" />;
    case "waiting":
    default:
      return <Circle className="h-3 w-3" />;
  }
}

function StatusPill({
  agentStatus,
  animate,
  t,
}: {
  agentStatus: SwarmAgentDisplayStatus;
  animate: boolean;
  t: ManifestTranslation;
}) {
  return (
    <span
      className={[
        "inline-flex max-w-full min-w-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium capitalize",
        "transition-colors duration-300",
        statusTone(agentStatus),
      ].join(" ")}
    >
      <span className="shrink-0">
        <StatusIcon animate={animate} status={agentStatus} />
      </span>
      <span className="truncate">{localizeStatus(agentStatus, t)}</span>
    </span>
  );
}

function agentKey(agent: SwarmAgentStatus): string {
  return agent.taskId || agent.agentId;
}

function WideAgentRow({
  agent,
  isActive,
  t,
}: {
  agent: SwarmAgentStatus;
  isActive: boolean;
  t: ManifestTranslation;
}) {
  const output = agent.error || agent.lastText || "-";

  return (
    <div
      className={[
        "grid min-w-0 items-center gap-2 rounded-md px-2 py-2 text-xs hover:bg-muted/30",
        WIDE_GRID_COLUMNS,
        AGENT_ENTER_ANIMATION,
      ].join(" ")}
      role="row"
    >
      <div className="min-w-0" role="cell">
        <div className="truncate font-medium text-foreground">
          {agent.agentId}
        </div>
        {agent.role && (
          <div className="truncate text-[10px] text-muted-foreground">
            {agent.role}
          </div>
        )}
      </div>
      <div className="min-w-0" role="cell">
        <StatusPill
          agentStatus={agent.status}
          animate={isActive}
          t={t}
        />
      </div>
      <div
        className="truncate font-mono text-[11px] text-muted-foreground"
        role="cell"
        title={agent.tool || ""}
      >
        {agent.tool ? localizeToolName(agent.tool, agent.tool) : "-"}
      </div>
      <div
        className="min-w-0 text-end font-mono text-[11px] text-muted-foreground"
        role="cell"
      >
        <div className="truncate">{formatElapsed(agent.elapsed_s, t)}</div>
        {agent.iterations != null && (
          <div
            className="inline-flex items-center justify-end gap-1 text-[10px]"
            title={t("swarmStatus.iters")}
          >
            <RotateCcw className="h-2.5 w-2.5" aria-hidden="true" />
            {agent.iterations}
          </div>
        )}
      </div>
      <div
        className={[
          "min-w-0 truncate text-[11px]",
          agent.error ? "text-destructive" : "text-muted-foreground",
        ].join(" ")}
        role="cell"
        title={output}
      >
        {output}
      </div>
    </div>
  );
}

function NarrowAgentCard({
  agent,
  isActive,
  t,
}: {
  agent: SwarmAgentStatus;
  isActive: boolean;
  t: ManifestTranslation;
}) {
  return (
    <div
      className={[
        "min-w-0 rounded-md border bg-muted/20 px-2.5 py-2",
        AGENT_ENTER_ANIMATION,
      ].join(" ")}
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-foreground">
            {agent.agentId}
          </div>
          {agent.role && (
            <div className="truncate text-[10px] text-muted-foreground">
              {agent.role}
            </div>
          )}
        </div>
        <StatusPill
          agentStatus={agent.status}
          animate={isActive}
          t={t}
        />
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-3 font-mono text-[10px] text-muted-foreground">
        <span className="min-w-0 truncate" title={agent.tool || ""}>
          <span className="sr-only">{t("swarmStatus.tool")}</span>
          {agent.tool ? localizeToolName(agent.tool, agent.tool) : "-"}
        </span>
        <span className="shrink-0">
          <span className="sr-only">{t("swarmStatus.time")}</span>
          {formatElapsed(agent.elapsed_s, t)}
        </span>
      </div>
    </div>
  );
}

export const SwarmDashboard = memo(function SwarmDashboard({
  agents,
  emptyStatus,
  isActive = true,
}: Props) {
  const { t: typedT } = useTranslation();
  const t = typedT as unknown as ManifestTranslation;

  return (
    <div className="mt-3 min-w-0">
      {agents.length === 0 ? (
        <div className="py-3 text-xs text-muted-foreground">
          {isActive ? (
            t("swarmStatus.teamStarting")
          ) : (
            <>
              {emptyStatus || localizeStatus("unknown", t)}
              {" — "}
              {t("swarmStatus.detailsUnavailable")}
            </>
          )}
        </div>
      ) : (
        <>
          <div
            className="hidden min-w-0 md:block"
            data-agent-layout="wide"
            role="table"
          >
            <div
              className={[
                "grid min-w-0 gap-2 border-b px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground",
                WIDE_GRID_COLUMNS,
              ].join(" ")}
              role="row"
            >
              <span className="truncate" role="columnheader">
                {t("swarmStatus.agent")}
              </span>
              <span className="truncate" role="columnheader">
                {t("swarmStatus.status")}
              </span>
              <span className="truncate" role="columnheader">
                {t("swarmStatus.tool")}
              </span>
              <span className="truncate text-end" role="columnheader">
                {t("swarmStatus.time")}
              </span>
              <span className="truncate" role="columnheader">
                {t("swarmStatus.output")}
              </span>
            </div>
            <div className="divide-y" role="rowgroup">
              {agents.map((agent) => (
                <WideAgentRow
                  agent={agent}
                  isActive={isActive}
                  key={agentKey(agent)}
                  t={t}
                />
              ))}
            </div>
          </div>

          <div className="space-y-2 md:hidden" data-agent-layout="narrow">
            {agents.map((agent) => (
              <NarrowAgentCard
                agent={agent}
                isActive={isActive}
                key={agentKey(agent)}
                t={t}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
});
