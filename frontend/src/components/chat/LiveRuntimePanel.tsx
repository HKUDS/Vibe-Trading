import {
  createContext,
  forwardRef,
  memo,
  useCallback,
  useContext,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { Activity, Ban, CheckCircle2, Loader2, OctagonX, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import {
  ApiError,
  api,
  type LiveAction,
  type LiveHalted,
  type LiveStatus,
} from "@/lib/api";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { RunnerStatus } from "@/components/chat/RunnerStatus";

const LIVE_STATUS_POLL_INTERVAL_MS = 15_000;

function normalizeBrokerScope(broker: string | null | undefined): string | null {
  const normalized = broker?.trim().toLowerCase();
  return normalized || null;
}

function isGlobalLiveHalt(halt: LiveHalted | null): boolean {
  return halt != null && normalizeBrokerScope(halt.broker) == null;
}

function haltScopeStillActive(halt: LiveHalted, status: LiveStatus): boolean {
  const broker = normalizeBrokerScope(halt.broker);
  if (!broker) return status.global_halted;
  return status.global_halted || status.brokers.some((item) => (
    normalizeBrokerScope(item.auth.broker) === broker && item.halted
  ));
}

function liveActionStyle(kind: string): { icon: typeof Activity; tone: string } {
  switch (kind) {
    case "order_rejected":
    case "breach":
      return { icon: Ban, tone: "border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400" };
    case "halt_tripped":
      return { icon: OctagonX, tone: "border-destructive/40 bg-destructive/5 text-destructive" };
    case "mandate_committed":
    case "halt_cleared":
      return { icon: CheckCircle2, tone: "border-emerald-500/40 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400" };
    default:
      return { icon: Activity, tone: "border-sky-500/40 bg-sky-500/5 text-sky-600 dark:text-sky-400" };
  }
}

function liveActionLabel(action: LiveAction): string {
  return action.kind.replace(/_/g, " ");
}

export const LiveActionChip = memo(function LiveActionChip({ action }: { action: LiveAction }) {
  const { t } = useTranslation();
  const { icon: Icon, tone } = liveActionStyle(action.kind);
  return (
    <div className="flex gap-3">
      <AgentAvatar />
      <div className="flex-1 min-w-0">
        <div className={["inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs", tone].join(" ")}>
          <Icon className="h-3 w-3 shrink-0" />
          <span className="shrink-0 font-medium uppercase tracking-wide text-[10px]">{t("agent.runtimeBadge")}</span>
          <span className="shrink-0 font-medium">{liveActionLabel(action)}</span>
          {action.intent_normalized && (
            <span className="truncate text-foreground/80">· {action.intent_normalized}</span>
          )}
          {action.outcome && (
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">· {action.outcome}</span>
          )}
          {action.remote_tool && (
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">· {action.remote_tool}</span>
          )}
          {action.error && <span className="truncate text-destructive">· {action.error}</span>}
        </div>
      </div>
    </div>
  );
});

export interface LiveRuntimePanelHandle {
  resetSession(): void;
  handleMandateCommitted(): void;
  handleHalted(halted: LiveHalted): void;
  handleResumed(): void;
  handleLiveAction(action: LiveAction): void;
}

interface RuntimeContextValue {
  liveStatus: LiveStatus | null;
  liveStatusUnavailable: boolean;
  liveActive: boolean;
  liveIsHalted: boolean;
  halting: boolean;
  resuming: boolean;
  refreshLiveStatus: () => Promise<void>;
  haltLive: () => Promise<void>;
  resumeLive: () => Promise<void>;
}

const RuntimeContext = createContext<RuntimeContextValue | null>(null);

interface Props {
  sessionId: string | null;
  hasLiveItems: boolean;
  children: ReactNode;
}

export const LiveRuntimePanel = memo(forwardRef<LiveRuntimePanelHandle, Props>(
  function LiveRuntimePanel({ sessionId, hasLiveItems, children }, ref) {
    const { t } = useTranslation();
    const [hasCommittedMandate, setHasCommittedMandate] = useState(false);
    const [liveHalted, setLiveHalted] = useState<LiveHalted | null>(null);
    const [halting, setHalting] = useState(false);
    const [resuming, setResuming] = useState(false);
    const [liveStatusRefresh, setLiveStatusRefresh] = useState(0);
    const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
    const [liveStatusUnavailable, setLiveStatusUnavailable] = useState(false);

    const refreshLiveStatus = useCallback(async () => {
      try {
        const next = await api.getLiveStatus();
        setLiveStatus(next);
        setLiveHalted((current) => (
          current && !haltScopeStillActive(current, next) ? null : current
        ));
        setLiveStatusUnavailable(false);
      } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 501)) {
          setLiveStatus(null);
          setLiveStatusUnavailable(true);
        }
      }
    }, []);

    useEffect(() => {
      refreshLiveStatus();
      const timer = setInterval(refreshLiveStatus, LIVE_STATUS_POLL_INTERVAL_MS);
      return () => clearInterval(timer);
    }, [refreshLiveStatus]);

    useEffect(() => {
      if (liveStatusRefresh > 0) refreshLiveStatus();
    }, [liveStatusRefresh, refreshLiveStatus]);

    useImperativeHandle(ref, () => ({
      resetSession() {
        setHasCommittedMandate(false);
        setLiveHalted(null);
        setLiveStatusRefresh((value) => value + 1);
      },
      handleMandateCommitted() {
        setHasCommittedMandate(true);
        setLiveStatusRefresh((value) => value + 1);
      },
      handleHalted(halted: LiveHalted) {
        setLiveHalted(halted);
        setLiveStatusRefresh((value) => value + 1);
      },
      handleResumed() {
        setLiveHalted(null);
        setLiveStatusRefresh((value) => value + 1);
      },
      handleLiveAction(action: LiveAction) {
        if (action.kind === "mandate_committed") setHasCommittedMandate(true);
        if (action.kind === "halt_tripped") {
          setLiveHalted({ broker: action.broker, reason: action.intent_normalized });
        }
        if (action.kind === "halt_cleared") setLiveHalted(null);
        if (["mandate_committed", "halt_tripped", "halt_cleared"].includes(action.kind)) {
          setLiveStatusRefresh((value) => value + 1);
        }
      },
    }), []);

    const haltLive = useCallback(async () => {
      if (halting) return;
      setHalting(true);
      try {
        await api.haltLive(sessionId ?? undefined);
        setLiveHalted((current) => current ?? {
          broker: null,
          by: "frontend",
          tripped_at: new Date().toISOString(),
        });
        setLiveStatusRefresh((value) => value + 1);
        toast.success(t("agent.connectorHalted"));
      } catch (error) {
        toast.error(error instanceof Error ? error.message : t("agent.failedToHaltConnector"));
      } finally {
        setHalting(false);
      }
    }, [halting, sessionId, t]);

    const resumeLive = useCallback(async () => {
      if (resuming) return;
      setResuming(true);
      try {
        await api.resumeLive(sessionId ?? undefined);
        setLiveHalted(null);
        setLiveStatusRefresh((value) => value + 1);
        toast.success(t("agent.connectorResumed"));
      } catch (error) {
        toast.error(error instanceof Error ? error.message : t("agent.failedToResumeConnector"));
      } finally {
        setResuming(false);
      }
    }, [resuming, sessionId, t]);

    const liveStatusActive =
      liveStatus != null &&
      (liveStatus.global_halted ||
        liveStatus.brokers.some((broker) => (
          broker.auth.oauth_token_present || broker.runner?.alive || broker.mandate != null
        )));
    const liveActive =
      hasLiveItems ||
      hasCommittedMandate ||
      liveHalted != null ||
      liveStatusActive;
    const liveIsHalted =
      isGlobalLiveHalt(liveHalted) || (liveStatus?.global_halted ?? false);

    const value = useMemo<RuntimeContextValue>(() => ({
      liveStatus,
      liveStatusUnavailable,
      liveActive,
      liveIsHalted,
      halting,
      resuming,
      refreshLiveStatus,
      haltLive,
      resumeLive,
    }), [
      haltLive,
      halting,
      liveActive,
      liveIsHalted,
      liveStatus,
      liveStatusUnavailable,
      refreshLiveStatus,
      resumeLive,
      resuming,
    ]);

    return (
      <RuntimeContext.Provider value={value}>
        {children}
      </RuntimeContext.Provider>
    );
  },
));

export function LiveRuntimeStatus() {
  const runtime = useContext(RuntimeContext);
  if (!runtime) return null;
  return (
    <RunnerStatus
      status={runtime.liveStatus}
      unavailable={runtime.liveStatusUnavailable}
      halted={runtime.liveIsHalted}
      onRefresh={runtime.refreshLiveStatus}
    />
  );
}

export function LiveRuntimeControl() {
  const { t } = useTranslation();
  const runtime = useContext(RuntimeContext);
  if (!runtime?.liveActive) return null;
  return (
    <div className="flex items-center gap-2 border-t border-border/60 pt-2">
      {runtime.liveIsHalted ? (
        <>
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive">
            <OctagonX className="h-3 w-3" />
            {t("agent.connectorHalted")}
          </span>
          <button
            type="button"
            onClick={runtime.resumeLive}
            disabled={runtime.resuming}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
            title={t("agent.resumeConnectorTitle")}
          >
            {runtime.resuming
              ? <Loader2 className="h-3 w-3 animate-spin" />
              : <RotateCcw className="h-3 w-3" />}
            {t("agent.resumeConnector")}
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={runtime.haltLive}
          disabled={runtime.halting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/40 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-40"
          title={t("agent.haltConnectorTitle")}
        >
          {runtime.halting
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <OctagonX className="h-3 w-3" />}
          {t("agent.haltConnector")}
        </button>
      )}
    </div>
  );
}
