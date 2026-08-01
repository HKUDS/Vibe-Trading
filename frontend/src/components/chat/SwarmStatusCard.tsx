import { useTranslation } from "react-i18next";
import { memo } from "react";
import { Clock, Users } from "lucide-react";
import { SwarmDashboard } from "@/components/chat/SwarmDashboard";
import {
  localizePreset,
  localizeStatus,
  type ManifestTranslation,
} from "@/lib/swarmI18n";
import type { SwarmRunStatus } from "@/types/agent";

interface Props {
  status: SwarmRunStatus;
}

function LayerStepper({
  status,
  t,
}: {
  status: SwarmRunStatus;
  t: ManifestTranslation;
}) {
  const hasLayerTotal =
    Number.isFinite(status.totalLayers) && status.totalLayers > 0;
  const isActive = status.status === "pending" || status.status === "running";

  if (!hasLayerTotal) {
    if (!isActive) return null;

    return (
      <div
        className="flex min-w-0 items-center gap-2"
        data-layer-state="indeterminate"
        role="status"
      >
        <progress
          className="sr-only"
          aria-label={t("swarm.preparingLayers")}
        />
        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/3 rounded-full bg-primary animate-[pulse-slide_2s_ease-in-out_infinite]" />
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 text-[10px] text-muted-foreground">
          <span
            className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse"
            aria-hidden="true"
          />
          {t("swarm.preparingLayers")}
        </span>
      </div>
    );
  }

  const layerTotal = status.totalLayers;
  const layerCurrent = Math.min(
    Math.max(
      Number.isFinite(status.currentLayer) ? status.currentLayer + 1 : 1,
      1,
    ),
    layerTotal,
  );
  const label = t("swarmStatus.layer", {
    current: layerCurrent,
    total: layerTotal,
  });
  const isRunComplete = status.status === "completed";

  return (
    <div
      aria-label={label}
      aria-valuemax={layerTotal}
      aria-valuemin={0}
      aria-valuenow={layerCurrent}
      aria-valuetext={label}
      className="grid h-1.5 min-w-0 gap-1"
      data-layer-state="determinate"
      role="progressbar"
      style={{
        gridTemplateColumns: `repeat(${layerTotal}, minmax(0, 1fr))`,
      }}
    >
      {Array.from({ length: layerTotal }, (_, index) => {
        const isDone = isRunComplete || index < layerCurrent - 1;
        const isCurrent = !isRunComplete && index === layerCurrent - 1;

        return (
          <span
            aria-hidden="true"
            className={[
              "relative h-1.5 min-w-0 overflow-hidden rounded-full transition-colors duration-300",
              isDone
                ? "bg-primary"
                : isCurrent
                  ? "bg-primary/30"
                  : "bg-muted",
            ].join(" ")}
            key={index}
          >
            {isActive && isCurrent && (
              <span className="absolute inset-0 rounded-full bg-primary animate-pulse motion-reduce:animate-none" />
            )}
          </span>
        );
      })}
    </div>
  );
}

function runTone(status: SwarmRunStatus["status"]): string {
  switch (status) {
    case "completed":
      return "text-emerald-600 dark:text-emerald-400";
    case "failed":
      return "text-destructive";
    case "cancelled":
      return "text-muted-foreground";
    case "running":
      return "text-primary";
    case "pending":
    case "unknown":
    default:
      return "text-muted-foreground";
  }
}

export const SwarmStatusCard = memo(function SwarmStatusCard({ status }: Props) {
  const { t: typedT } = useTranslation();
  const t = typedT as unknown as ManifestTranslation;
  const done = status.agents.filter((agent) =>
    ["done", "failed", "blocked", "cancelled"].includes(agent.status),
  ).length;
  const total = status.agents.length;
  const hasAgentTotal = total > 0;
  const isActive = status.status === "pending" || status.status === "running";

  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Users className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1 rounded-lg border bg-background p-3 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">
              {localizePreset(status.preset, t)}
            </span>
            <span
              className={[
                "shrink-0 text-xs font-medium capitalize",
                runTone(status.status),
              ].join(" ")}
            >
              {localizeStatus(status.status, t)}
            </span>
          </div>
          {(hasAgentTotal || isActive) && (
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              {hasAgentTotal ? (
                <span>{t("swarmStatus.agents", { done, total })}</span>
              ) : (
                <span className="inline-flex items-center gap-1.5" role="status">
                  <span
                    className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse"
                    aria-hidden="true"
                  />
                  <span>{t("swarm.assemblingTeam")}</span>
                </span>
              )}
            </div>
          )}
        </div>

        {(status.totalLayers > 0 || isActive) && (
          <div className="mt-3">
            <LayerStepper status={status} t={t} />
          </div>
        )}

        <SwarmDashboard
          agents={status.agents}
          emptyStatus={localizeStatus(status.status, t)}
          isActive={isActive}
        />
      </div>
    </div>
  );
});
