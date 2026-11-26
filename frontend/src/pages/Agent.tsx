import { useTranslation } from 'react-i18next';
import i18n from "@/i18n";
import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router";
import { ArrowDown } from "lucide-react";
import { toast } from "sonner";
import {
  setTranscriptBuilder,
  useAgentStore,
  type AgentActivity,
  type AgentMessageMeta,
} from "@/stores/agent";
import { useSessionsStore } from "@/stores/sessions";
import { useSSE } from "@/hooks/useSSE";
import { useLlmUsageCounter } from "@/hooks/useLlmUsageCounter";
import { ApiError, AUTH_REQUIRED_MESSAGE, api, isAuthRequiredError, isQueuedMessage, type GoalSnapshot, type MandateProposal, type MandateCommitted, type ScheduledResearchProposal, type LiveAction, type LiveHalted, type LLMSettings, type SessionModelSelection } from "@/lib/api";
import {
  addQueuedInput,
  applyThreadEvent,
  buildTranscript,
  contentText,
  discardLiveAssistant,
  endedTurns,
  historyReply,
  mergeThreadPage,
  removeQueuedInput,
  reuseRows,
  withPendingInputs,
  type TurnMeta,
} from "@/lib/threadItems";
import {
  extractUploadedAttachments,
} from "@/lib/attachments";
import { hasStoredMetrics, runCardFields } from "@/lib/runCards";
import { buildChatPrompt, MAX_GOAL_CHARS, MAX_MESSAGE_CHARS, promptExceedsLimit, SWARM_PROMPT_PREFIX } from "@/lib/chatPrompt";
import type { AgentMessage, SwarmRunStatus } from "@/types/agent";
import { QueuedInputs } from "@/components/chat/QueuedInputs";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { MarkdownContent, MessageBubble } from "@/components/chat/MessageBubble";
import { ModelRuntimeBar } from "@/components/chat/ModelRuntimeBar";
import { ThinkingTimeline } from "@/components/chat/ThinkingTimeline";
import { ConversationTimeline } from "@/components/chat/ConversationTimeline";
import { ActivityLine } from "@/components/chat/ActivityLine";
import { LlmUsageCounter } from "@/components/chat/LlmUsageCounter";
import { MandateProposalCard } from "@/components/chat/MandateProposalCard";
import { ScheduledResearchProposalCard } from "@/components/chat/ScheduledResearchProposalCard";
import { SwarmStatusCard } from "@/components/chat/SwarmStatusCard";
import { PlanCard } from "@/components/chat/PlanCard";
import { QuestionCard } from "@/components/chat/QuestionCard";
import { ImageResult } from "@/components/chat/ImageResult";
import {
  Composer,
  type ComposerAttachment,
  type ComposerHandle,
} from "@/components/chat/Composer";
import { GoalPanel } from "@/components/chat/GoalPanel";
import {
  LiveActionChip,
  LiveRuntimePanel,
  type LiveRuntimePanelHandle,
} from "@/components/chat/LiveRuntimePanel";
import {
  applySwarmEvent,
  buildSwarmStatusFromRunDetail,
  buildSwarmStatusFromStarted,
  buildSwarmStatusFromToolResultPreview,
  mergeSwarmRunUsage,
  stopSwarmRun,
} from "@/lib/swarmStatus";
import { readThread } from "@/pages/agentHydration";

import { groupMessages, type MsgGroup } from "@/pages/agentTranscript";

const act = () => useAgentStore.getState();

function hydrateSwarmRunUsage(runId: string): void {
  void api.getSwarmRun(runId).then((payload) => {
    const current = act().swarmRuns[runId]
      ?? buildSwarmStatusFromRunDetail(payload, runId);
    if (!current) return;
    act().upsertSwarmStatus(mergeSwarmRunUsage(current, payload));
  }).catch(() => undefined);
}

interface RuntimeIdentity {
  sessionId?: string;
  provider?: string;
  model?: string;
  reasoningEffort?: string;
}

// i18n hook for Agent component — used inside the component below
// (declared at module scope for helper usage is fine since t() reads from i18n singleton)

const STREAM_FLUSH_INTERVAL_MS = 80;
const TIMELINE_WINDOW_SIZE = 160;
const GOAL_KICKOFF_PREFIX = [
  "Start working on this research goal now.",
  "Keep it research-only, use available tools when evidence is needed, add concrete evidence to the goal ledger, and keep going until the goal is complete, blocked, waiting for user input, or budget-limited.",
  "",
  "Goal: ",
].join("\n");
const GOAL_CONTINUE_PREFIX = [
  "Continue the active research goal.",
  "Use real available tools as needed, add evidence to the goal ledger, and only stop when the goal is complete, blocked, waiting for user input, or budget-limited.",
  "",
  "Goal: ",
].join("\n");

function toDisplayPrompt(content: string): {
  content: string;
  meta?: AgentMessageMeta;
} {
  const extractedAttachments = extractUploadedAttachments(content);
  let display = extractedAttachments.content;
  const meta: AgentMessageMeta = { requestText: content };
  if (extractedAttachments.filenames.length > 0) {
    meta.attachments = extractedAttachments.filenames.map((filename) => ({ filename }));
  }
  if (display.startsWith(SWARM_PROMPT_PREFIX)) {
    meta.swarmMode = true;
    display = display.slice(SWARM_PROMPT_PREFIX.length);
  }
  if (display.startsWith(GOAL_KICKOFF_PREFIX)) {
    meta.goalMode = true;
    display = display.slice(GOAL_KICKOFF_PREFIX.length);
  } else if (display.startsWith(GOAL_CONTINUE_PREFIX)) {
    meta.goalMode = true;
    display = display.slice(GOAL_CONTINUE_PREFIX.length);
    const detailsStart = [
      display.indexOf("\nOpen criteria:"),
      display.indexOf("\nAll criteria appear covered;"),
    ].filter((index) => index >= 0);
    if (detailsStart.length > 0) {
      display = display.slice(0, Math.min(...detailsStart));
    }
  }
  return {
    content: display,
    meta,
  };
}

/* Thread rows are rebuilt by the store whenever the thread view changes. */
setTranscriptBuilder((thread, turnMeta, previous) => reuseRows(
  previous,
  buildTranscript(thread, turnMeta, {
    displayUser: toDisplayPrompt,
    interruptedLabel: i18n.t("agent.activity.interruptedStep" as never),
    failedLabel: i18n.t("agent.turnFailed" as never),
  }),
));

function runIdFromDir(runDir: unknown): string | undefined {
  return typeof runDir === "string" && runDir ? runDir.split(/[/\\]/).pop() || undefined : undefined;
}

/* ---------- Connector runtime channel ----------
 * Mandate proposals and live-action chips render as standalone timeline items,
 * never folded into the thinking timeline (SPEC Consent §2 grouping note). They
 * are driven by dedicated state rather than the chat message store because they
 * are privileged-surface artifacts, not chat messages, and the proposal card
 * needs commit/adjust callbacks the generic MessageBubble does not carry. */
interface ProposalItem {
  kind: "proposal";
  timestamp: number;
  proposal: MandateProposal;
  committed: MandateCommitted | null;
}
interface LiveActionItem {
  kind: "live_action";
  timestamp: number;
  action: LiveAction;
}
interface ScheduledProposalItem {
  kind: "scheduled_proposal";
  timestamp: number;
  proposal: ScheduledResearchProposal;
}
type LiveItem = ProposalItem | ScheduledProposalItem | LiveActionItem;

function isCriterionStatusMet(status: string): boolean {
  return !["", "pending", "open", "unsatisfied"].includes(status.toLowerCase());
}

function isTerminalGoalStatus(status: string): boolean {
  return ["complete", "cancelled", "blocked", "superseded", "usage_limited"].includes(status);
}

function criterionEvidenceCount(snapshot: GoalSnapshot, criterionId: string): number {
  return snapshot.evidence.filter((item) => item.criterion_id === criterionId).length;
}

function criterionCovered(snapshot: GoalSnapshot, criterion: GoalSnapshot["criteria"][number]): boolean {
  return isCriterionStatusMet(criterion.status) || criterionEvidenceCount(snapshot, criterion.criterion_id) > 0;
}

function goalKickoffPrompt(objective: string): string {
  return `${GOAL_KICKOFF_PREFIX}${objective}`;
}

function goalContinuePrompt(snapshot: GoalSnapshot): string {
  const openCriteria = snapshot.criteria
    .filter((item) => item.required && !criterionCovered(snapshot, item))
    .map((item) => `- ${item.text}`)
    .join("\n");
  return [
    "Continue the active research goal.",
    "Use real available tools as needed, add evidence to the goal ledger, and only stop when the goal is complete, blocked, waiting for user input, or budget-limited.",
    "",
    `Goal: ${snapshot.goal.objective}`,
    openCriteria ? `Open criteria:\n${openCriteria}` : "All criteria appear covered; audit the ledger and update the goal status if completion is justified.",
  ].join("\n");
}

/* ---------- Component ---------- */
export function Agent() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const listRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<ComposerHandle>(null);
  const liveRuntimeRef = useRef<LiveRuntimePanelHandle>(null);
  const goalOpenRequestRef = useRef(0);
  const sseSessionRef = useRef<string | null>(null);
  const prevSseStatusRef = useRef<string>("disconnected");
  const genRef = useRef(0);
  const pendingGoalSessionRef = useRef<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const lastEventRef = useRef(0);
  const sseTimeoutMsRef = useRef(90_000);

  /* tool.progress coalescing — keep the latest delta per live item, apply once per rAF. */
  const pendingProgressRef = useRef<Map<string, Record<string, unknown>>>(new Map());
  const progressRafRef = useRef(0);
  const pendingTextRef = useRef("");
  const pendingReasoningRef = useRef<boolean | null>(null);
  const streamFlushTimerRef = useRef(0);
  const pendingSwarmEventsRef = useRef<Map<string, unknown[]>>(new Map());
  const swarmRafRef = useRef(0);
  const replayAttemptSeenRef = useRef(false);
  const replayCheckTimerRef = useRef(0);
  const smoothScrollingRef = useRef(false);
  const smoothScrollTimerRef = useRef(0);
  const historyScrollTimerRef = useRef(0);
  const titleBeforeCompletionRef = useRef<string | null>(null);
  const completedAttemptIdsRef = useRef<Set<string>>(new Set());
  /* Turns whose terminal attempt event is already handled (or that had ended
     before this stream connected), so a replayed one changes nothing. */
  const settledTurnsRef = useRef<Set<string>>(new Set());

  const [swarmPreset, setSwarmPreset] = useState<{ name: string; title: string } | null>(null);
  const [goalComposerActive, setGoalComposerActive] = useState(false);
  const [goalSnapshot, setGoalSnapshot] = useState<GoalSnapshot | null>(null);

  /* Connector runtime channel state (SPEC Consent §1/§4/§5) */
  const [liveItems, setLiveItems] = useState<LiveItem[]>([]);
  const [visibleRowCount, setVisibleRowCount] = useState(TIMELINE_WINDOW_SIZE);
  const visibleRowsSessionRef = useRef<string | null>(null);
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [runtimeIdentity, setRuntimeIdentity] = useState<RuntimeIdentity>({});
  const [sessionModel, setSessionModel] = useState<SessionModelSelection | null>(null);

  const messages = useAgentStore(s => s.messages);
  const streamingText = useAgentStore(s => s.streamingText);
  const status = useAgentStore(s => s.status);
  const sessionId = useAgentStore(s => s.sessionId);
  const activity = useAgentStore(s => s.activity);
  const reasoningTail = useAgentStore(s => s.reasoningTail);
  const swarmRuns = useAgentStore(s => s.swarmRuns);
  const sessionLoading = useAgentStore(s => s.sessionLoading);
  const queuedInputs = useAgentStore(s => s.thread.queued);
  const previousStatusRef = useRef(status);

  const { connect, disconnect, onStatusChange } = useSSE();

  /* Live token totals for the in-flight attempt, fed by `llm_usage` events. */
  const {
    input: usageInput,
    output: usageOutput,
    record: recordLlmUsage,
    reset: resetLlmUsage,
  } = useLlmUsageCounter();

  const urlSessionId = searchParams.get("session");
  const visibleRuntimeIdentity = runtimeIdentity.sessionId === urlSessionId
    ? runtimeIdentity
    : {};

  /* Smart scroll — only auto-scroll when near bottom */
  const isNearBottom = useCallback(() => {
    const el = listRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  }, []);

  const rafRef = useRef(0);
  const scrollToBottom = useCallback(() => {
    if (smoothScrollingRef.current) return;
    if (!isNearBottom()) {
      setShowScrollBtn(true);
      return;
    }
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    });
  }, [isNearBottom]);

  const forceScrollToBottom = useCallback((smooth = false) => {
    setShowScrollBtn(false);
    window.clearTimeout(smoothScrollTimerRef.current);
    smoothScrollingRef.current = smooth;
    requestAnimationFrame(() => {
      if (!listRef.current) return;
      if (smooth) {
        listRef.current.scrollTo({
          top: listRef.current.scrollHeight,
          behavior: "smooth",
        });
        smoothScrollTimerRef.current = window.setTimeout(() => {
          smoothScrollingRef.current = false;
          if (isNearBottom()) setShowScrollBtn(false);
        }, 500);
      } else {
        listRef.current.scrollTop = listRef.current.scrollHeight;
        smoothScrollingRef.current = false;
      }
    });
  }, [isNearBottom]);

  const scheduleHistoryScroll = useCallback(() => {
    window.clearTimeout(historyScrollTimerRef.current);
    historyScrollTimerRef.current = window.setTimeout(() => {
      historyScrollTimerRef.current = 0;
      forceScrollToBottom();
    }, 50);
  }, [forceScrollToBottom]);

  const flushPendingStreamUpdate = useCallback(() => {
    window.clearTimeout(streamFlushTimerRef.current);
    streamFlushTimerRef.current = 0;
    const pendingText = pendingTextRef.current;
    const pendingReasoning = pendingReasoningRef.current;
    pendingTextRef.current = "";
    pendingReasoningRef.current = null;
    if (pendingText) act().appendDelta(pendingText);
    if (pendingText || pendingReasoning !== null) scrollToBottom();
    return pendingText;
  }, [scrollToBottom]);

  const cancelPendingStreamFlush = useCallback(() => {
    window.clearTimeout(streamFlushTimerRef.current);
    streamFlushTimerRef.current = 0;
    pendingTextRef.current = "";
    pendingReasoningRef.current = null;
  }, []);

  const queueStreamUpdate = useCallback((text: string, reasoning: boolean) => {
    pendingTextRef.current += text;
    pendingReasoningRef.current = reasoning;
    if (streamFlushTimerRef.current) return;
    streamFlushTimerRef.current = window.setTimeout(
      flushPendingStreamUpdate,
      STREAM_FLUSH_INTERVAL_MS,
    );
  }, [flushPendingStreamUpdate]);

  const clearStreamingView = useCallback(() => {
    cancelPendingStreamFlush();
    act().clearStreaming();
  }, [cancelPendingStreamFlush]);

  /** End the in-flight turn on this page; whatever it streamed stays as a cut-off response. */
  const endLiveTurn = useCallback(() => {
    const streamed = act().streamingText + pendingTextRef.current;
    cancelPendingStreamFlush();
    act().updateThread((thread) => discardLiveAssistant(thread, streamed, Date.now()));
    act().clearStreaming();
    useAgentStore.setState({ activity: null, toolCalls: [] });
    act().setStatus("idle");
  }, [cancelPendingStreamFlush]);

  /** Drop the optimistic copy of a message once the thread records it. */
  const dropPendingSend = useCallback((requestText: string) => {
    useAgentStore.setState((state) => {
      const messages = state.messages.filter((message) => !(
        message.meta?.pendingSend && message.meta.requestText === requestText
      ));
      return messages.length === state.messages.length ? {} : { messages };
    });
  }, []);

  const markBackgroundCompletion = useCallback((
    completedSessionId: string,
    attemptId?: string,
  ) => {
    if (attemptId && completedAttemptIdsRef.current.has(attemptId)) return;
    if (attemptId) completedAttemptIdsRef.current.add(attemptId);
    if (document.hidden) {
      titleBeforeCompletionRef.current ??= document.title;
      document.title = `● ${t("agent.doneMarker" as never)}`;
    }
    if (act().sessionId !== completedSessionId) {
      toast.success(t("agent.backgroundRunComplete" as never));
    }
  }, [t]);

  useEffect(() => {
    const restoreTitle = () => {
      if (document.hidden || titleBeforeCompletionRef.current === null) return;
      document.title = titleBeforeCompletionRef.current;
      titleBeforeCompletionRef.current = null;
    };
    document.addEventListener("visibilitychange", restoreTitle);
    return () => {
      document.removeEventListener("visibilitychange", restoreTitle);
      if (titleBeforeCompletionRef.current !== null) {
        document.title = titleBeforeCompletionRef.current;
        titleBeforeCompletionRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!urlSessionId) {
      setSessionModel(null);
      return;
    }
    let active = true;
    if (typeof api.getSessionModel !== "function") return;
    api.getSessionModel(urlSessionId).then((selection) => {
      if (active) setSessionModel(selection);
    }).catch(() => {
      if (active) setSessionModel(null);
    });
    return () => { active = false; };
  }, [urlSessionId]);

  const fillComposer = useCallback((prompt: string) => {
    composerRef.current?.fill(prompt);
  }, []);

  useEffect(() => {
    const previous = previousStatusRef.current;
    previousStatusRef.current = status;
    if (previous === "streaming" && status !== "streaming") {
      requestAnimationFrame(() => {
        const selection = window.getSelection();
        if (selection && !selection.isCollapsed) return;
        const active = document.activeElement;
        if (
          active &&
          active !== document.body &&
          !active.closest("[data-agent-composer]")
        ) {
          return;
        }
        composerRef.current?.focus();
      });
    }
  }, [status]);

  /* Track scroll position to show/hide scroll button */
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => {
      if (smoothScrollingRef.current) return;
      if (isNearBottom()) setShowScrollBtn(false);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [isNearBottom]);

  useEffect(() => {
    onStatusChange((s) => {
      act().setSseStatus(s);
      if (s === "connected") {
        const connectedSid = sseSessionRef.current;
        window.clearTimeout(replayCheckTimerRef.current);
        replayCheckTimerRef.current = window.setTimeout(() => {
          const store = act();
          if (
            connectedSid &&
            sseSessionRef.current === connectedSid &&
            !replayAttemptSeenRef.current &&
            store.status !== "streaming"
          ) {
            store.clearStreamingSession(connectedSid);
          }
        }, 300);
      }
      if (s === "reconnecting" && prevSseStatusRef.current === "connected") toast.warning(t('agent.connectionLostReconnect'));
      else if (s === "connected" && prevSseStatusRef.current === "reconnecting") toast.success(t('agent.connectionRestored'));
      prevSseStatusRef.current = s;
    });
  }, [onStatusChange, t]);

  const doDisconnect = useCallback(() => {
    cancelPendingStreamFlush();
    window.clearTimeout(replayCheckTimerRef.current);
    window.clearTimeout(historyScrollTimerRef.current);
    disconnect();
    sseSessionRef.current = null;
  }, [cancelPendingStreamFlush, disconnect]);

  const loadGoalSnapshot = useCallback(async (sid?: string | null) => {
    const targetSession = sid || act().sessionId;
    goalOpenRequestRef.current = 0;
    if (!targetSession) {
      setGoalSnapshot(null);
      return;
    }
    try {
      const snapshot = await api.getGoal(targetSession);
      if (act().sessionId !== targetSession) return;
      setGoalSnapshot(snapshot);
    } catch (error) {
      if (act().sessionId !== targetSession) return;
      if (error instanceof ApiError && error.status === 404) {
        setGoalSnapshot(null);
      } else {
        toast.error(error instanceof Error ? error.message : t('agent.failedToLoadGoal'));
      }
    }
  }, []);

  const loadSessionMessages = useCallback(async (sid: string, gen: number): Promise<boolean> => {
    setHistoryError(null);
    try {
      const [thread, pending] = await Promise.all([
        readThread((after, limit) => api.getSessionThread(sid, { after, limit })),
        api.listPendingInputs(sid).catch(() => null),
      ]);
      if (genRef.current !== gen) return false;
      const previewIds = new Set<string>();
      for (const item of thread.items) {
        if (item.type !== "turn_end") continue;
        const runId = item.display?.run_id || runIdFromDir(item.run_dir);
        if (runId) previewIds.add(runId);
      }
      const previewEntries = await Promise.all(
        [...previewIds].map(async (runId) => [runId, await api.getRunPreview(runId).catch(() => null)] as const),
      );
      const previews = new Map(previewEntries);
      let latestRuntimeIdentity: RuntimeIdentity | null = null;
      for (const item of thread.items) {
        if (item.type === "turn_start" && (item.provider || item.model)) {
          latestRuntimeIdentity = {
            sessionId: sid,
            provider: item.provider || undefined,
            model: item.model || undefined,
          };
        }
      }
      for (const item of thread.items) {
        if (item.type === "turn_end" && item.display?.reasoning_effort !== undefined && latestRuntimeIdentity) {
          latestRuntimeIdentity.reasoningEffort = item.display.reasoning_effort;
        }
      }
      const historyMeta: Record<string, TurnMeta> = {};
      for (const item of thread.items) {
        if (item.type !== "turn_end") continue;
        const runId = item.display?.run_id || runIdFromDir(item.run_dir);
        const turnMeta: TurnMeta = historyReply(item);
        if (runId) {
          turnMeta.runId = runId;
          turnMeta.card = hasStoredMetrics(item.display?.metrics)
            ? { metrics: item.display!.metrics } : runCardFields(previews.get(runId) ?? null);
          if (turnMeta.card && !turnMeta.card.equityCurve) turnMeta.card.equityCurve = [];
        }
        const start = thread.items.find((candidate) => candidate.type === "turn_start" && candidate.turn_id === item.turn_id);
        if (start?.ts) turnMeta.startedAt = start.ts * 1000;
        historyMeta[item.turn_id] = turnMeta;
      }
      if (genRef.current !== gen) return false;
      useAgentStore.setState((state) => {
        const turnMeta = { ...historyMeta };
        for (const [turnId, live] of Object.entries(state.turnMeta)) {
          turnMeta[turnId] = { ...turnMeta[turnId], ...live };
        }
        return { turnMeta };
      });
      act().updateThread((view) => mergeThreadPage(view, thread, Date.now()));
      if (pending) {
        act().updateThread((view) => withPendingInputs(view, pending.items ?? []));
      }
      if (act().streamingSessionId === sid && thread.items[thread.items.length - 1]?.type === "turn_end") act().clearStreamingSession(sid);
      const liveActivity = act().activity;
      if (liveActivity && endedTurns(act().thread).has(liveActivity.attemptId)) {
        useAgentStore.setState({ activity: null, toolCalls: [] });
        if (act().status === "streaming") act().setStatus("idle");
      }
      act().setSessionLoading(false);
      act().cacheSession(sid, act().messages);
      setRuntimeIdentity(latestRuntimeIdentity ?? {});
      scheduleHistoryScroll();
      return true;
    } catch (error) {
      if (genRef.current !== gen) return false;
      setRuntimeIdentity({});
      act().setSessionLoading(false);
      setHistoryError(error instanceof Error ? error.message : t("settings.unknownError"));
      return true;
    }
  }, [scheduleHistoryScroll, t]);

  const refreshSessionMessages = useCallback(async (sid: string) => {
    const gen = genRef.current + 1;
    genRef.current = gen;
    await loadSessionMessages(sid, gen);
  }, [loadSessionMessages]);

  const changeSessionModel = useCallback(async (selection: { provider: string; model: string; reasoning_effort: string }) => {
    if (!sessionId) return;
    try {
      setSessionModel(await api.setSessionModel(sessionId, selection));
      toast.success(t("agent.modelUpdated" as never));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.modelUpdateFailed" as never));
    }
  }, [sessionId, t]);

  const clearSessionModel = useCallback(async () => {
    if (!sessionId) return;
    try {
      setSessionModel(await api.clearSessionModel(sessionId));
      toast.success(t("agent.modelUpdated" as never));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.modelUpdateFailed" as never));
    }
  }, [sessionId, t]);

  const compactSession = useCallback(async () => {
    if (!sessionId || status === "streaming") return;
    try {
      await api.compactSession(sessionId);
      await refreshSessionMessages(sessionId);
      toast.success(t("agent.contextCompacted" as never));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.compactFailed" as never));
    }
  }, [refreshSessionMessages, sessionId, status, t]);

  const forkFromTurn = useCallback(async (turnId: string) => {
    if (!sessionId) return;
    try {
      const fork = await api.forkSession(sessionId, turnId);
      useSessionsStore.getState().upsert(fork);
      setSearchParams({ session: fork.session_id });
      toast.success(t("agent.sessionForked" as never));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.forkFailed" as never));
    }
  }, [sessionId, setSearchParams, t]);

  const setupSSE = useCallback((sid: string) => {
    if (sseSessionRef.current === sid) return;
    cancelPendingStreamFlush();
    window.clearTimeout(replayCheckTimerRef.current);
    replayAttemptSeenRef.current = false;
    disconnect();
    sseSessionRef.current = sid;
    // A turn that had ended before this stream connected is old news: its
    // terminal event may be replayed, but it must not toast, retitle or
    // re-add anything.
    settledTurnsRef.current = new Set(endedTurns(act().thread).keys());

    const touch = () => { lastEventRef.current = Date.now(); };
    const turnIsOver = (turnId: string): boolean => {
      if (!turnId) return false;
      const store = act();
      const meta = store.turnMeta[turnId];
      return Boolean(meta?.timedOut || meta?.stopRequested) || endedTurns(store.thread).has(turnId);
    };
    const identifyActivity = (
      turnId: string,
      state: "thinking" | "working" | "responding",
      startedAtSec?: unknown,
    ): boolean => {
      if (turnIsOver(turnId)) return false;
      const store = act();
      const current = store.activity;
      // `run.started` carries the backend's wall-clock start (epoch
      // seconds). On a replayed stream that is the original start, so the
      // elapsed timer resumes from the truth rather than from reconnect time.
      const startedAtNumber = Number(startedAtSec);
      const startedAt = Number.isFinite(startedAtNumber) && startedAtNumber > 0
        ? startedAtNumber * 1000
        : undefined;
      if (!current) {
        store.startActivity(turnId || `pending-${Date.now()}`, startedAt);
      } else if (
        turnId &&
        current.attemptId !== turnId &&
        current.attemptId.startsWith("pending-")
      ) {
        store.setActivityAttemptId(turnId);
      } else if (turnId && current.attemptId !== turnId) {
        store.startActivity(turnId, startedAt);
      }
      act().setActivityState(state);
      return true;
    };
    const markStreaming = () => {
      if (act().status !== "streaming") act().setStatus("streaming");
    };
    /** The turn ended: drop this page's live state for it. */
    const endTurnHere = (turnId: string) => {
      const activity = act().activity;
      if (activity && activity.attemptId !== turnId) return;
      endLiveTurn();
    };
    const applyItem = (eventType: string, data: Record<string, unknown>, streamed = "") => {
      act().updateThread((view) => applyThreadEvent(view, eventType, data, Date.now(), streamed));
    };
    const shadowIdOf = (turnId: string): string | undefined => {
      for (const entry of act().thread.entries) {
        if (
          entry.turnId !== turnId
          || entry.type !== "tool_result"
          || entry.item.name !== "render_shadow_report"
          || entry.item.status !== "ok"
        ) continue;
        const match = contentText(entry.item.content).match(/"shadow_id"\s*:\s*"(shadow_[A-Za-z0-9_]+)"/);
        if (match) return match[1];
      }
      return undefined;
    };
    const userMessageCount = () => act().messages.filter((message) => message.type === "user").length;

    const onItem = (eventType: "item.started" | "item.delta" | "item.completed") => (d: Record<string, unknown>) => {
      touch();
      replayAttemptSeenRef.current = true;
      const kind = String(d.kind || "");
      const turnId = String(d.turn_id || "");
      const liveId = typeof d.live_id === "string" ? d.live_id : undefined;
      const item = (d.item && typeof d.item === "object" ? d.item : {}) as Record<string, unknown>;
      const recorded = typeof d.seq === "number";

      if (eventType === "item.delta") {
        if (kind === "text.delta" || kind === "reasoning.delta") {
          if (!identifyActivity(turnId, kind === "text.delta" ? "responding" : "thinking")) return;
          markStreaming();
          if (liveId && act().thread.liveAssistant?.liveId !== liveId) {
            // Joined mid-response: whatever was shown belongs to an older one.
            cancelPendingStreamFlush();
            act().clearStreaming();
          }
          applyItem(eventType, d);
          if (kind === "text.delta") {
            queueStreamUpdate(String(d.delta || ""), false);
          } else {
            // The backend sends a bounded rolling tail — replace, never append.
            act().setReasoningTail(String(d.tail ?? ""));
            queueStreamUpdate("", true);
          }
          return;
        }
        if (kind === "text.reset") {
          if (turnIsOver(turnId)) return;
          clearStreamingView();
          markStreaming();
          scrollToBottom();
          return;
        }
        if (kind === "tool.progress") {
          if (identifyActivity(turnId, "working")) markStreaming();
          // Coalesce: keep the latest delta per live item, apply once per frame.
          pendingProgressRef.current.set(liveId ?? turnId, d);
          if (progressRafRef.current) return;
          progressRafRef.current = requestAnimationFrame(() => {
            progressRafRef.current = 0;
            const pendingDeltas = [...pendingProgressRef.current.values()];
            pendingProgressRef.current.clear();
            if (pendingDeltas.length === 0) return;
            act().updateThread((view) => pendingDeltas.reduce(
              (next, delta) => applyThreadEvent(next, "item.delta", delta, Date.now()),
              view,
            ));
          });
          return;
        }
        if (kind === "run.waiting") {
          if (identifyActivity(turnId, "thinking")) markStreaming();
          return;
        }
        applyItem(eventType, d);
        return;
      }

      const liveResponse = act().thread.liveAssistant;
      const closesResponse = eventType === "item.completed" && liveId !== undefined && liveResponse?.liveId === liveId;
      const opensResponse = eventType === "item.started" && !recorded && item.type === "assistant";
      let streamed = "";
      if (closesResponse || opensResponse) {
        // The streamed text becomes the recorded item (or, discarded, a cut-off one).
        streamed = act().streamingText + pendingTextRef.current;
        cancelPendingStreamFlush();
        act().clearStreaming();
      }
      if (liveId && eventType === "item.completed") pendingProgressRef.current.delete(liveId);
      applyItem(eventType, d, kind === "item.discarded" ? streamed : "");

      if (item.type === "user" && recorded) dropPendingSend(contentText(item.content));
      if (opensResponse && identifyActivity(turnId, "thinking")) markStreaming();
      if (kind === "tool.started" && identifyActivity(turnId, "working")) {
        markStreaming();
        act().addToolCall({
          id: String(item.tool_call_id || liveId || ""),
          tool: String(item.name || ""),
          arguments: (item.arguments as Record<string, string> | undefined) ?? {},
          status: "running",
          timestamp: Date.now(),
        });
      }
      if (kind === "tool.completed" || kind === "tool.failed") {
        act().updateRunningToolCall(
          typeof item.tool_call_id === "string" ? item.tool_call_id : undefined,
          String(item.name || ""),
          { status: kind === "tool.completed" ? "ok" : "error" },
        );
        if (item.name === "run_swarm") {
          const fallback = buildSwarmStatusFromToolResultPreview(contentText(item.content));
          if (fallback && !act().swarmRuns[fallback.runId]) {
            act().upsertSwarmStatus(fallback);
            hydrateSwarmRunUsage(fallback.runId);
          }
        }
      }
      scrollToBottom();
    };

    const onRunEnd = async (eventType: "run.completed" | "run.failed" | "run.cancelled", d: Record<string, unknown>) => {
      touch();
      const turnId = String(d.turn_id || "");
      if (!turnId || settledTurnsRef.current.has(turnId)) return;
      settledTurnsRef.current.add(turnId);
      markBackgroundCompletion(sid, turnId);
      applyItem(eventType, d);
      if (act().sessionId !== sid) {
        act().clearStreamingSession(sid);
        return;
      }
      const runId = runIdFromDir(d.run_dir);
      const startedAt = Number(d.started_at);
      act().setTurnMeta(turnId, {
        content: String(d.summary || ""),
        ...(runId ? { runId } : {}),
        ...(Number.isFinite(startedAt) && startedAt > 0 ? { startedAt: startedAt * 1000 } : {}),
        ...(eventType === "run.failed" ? { error: String(d.error || t("agent.turnFailed" as never)) } : {}),
      });
      if (d.provider || d.model) {
        setRuntimeIdentity({
          sessionId: sid,
          provider: d.provider ? String(d.provider) : undefined,
          model: d.model ? String(d.model) : undefined,
          reasoningEffort: typeof d.reasoning_effort === "string" ? d.reasoning_effort : undefined,
        });
      }
      endTurnHere(turnId);
      if (userMessageCount() === 1 && eventType === "run.completed") {
        api.autoTitleSession(sid).then(() => useSessionsStore.getState().refresh()).catch(() => {});
      }
      const shadowId = shadowIdOf(turnId);
      if (runId) {
        const card = runCardFields(await api.getRunPreview(runId).catch(() => null));
        if (card || shadowId) act().setTurnMeta(turnId, { card: { ...card, shadowId } });
      } else if (shadowId) {
        act().setTurnMeta(turnId, { card: { shadowId } });
      }
      scrollToBottom();
    };

    connect(() => {
      // Resume from the newest item this page holds: every recorded item
      // after it is re-read from the thread, however long the stream was down.
      const view = act().sessionId === sid ? act().thread : null;
      return api.sseUrl(
        sid,
        view?.loaded ? { replay: "active", cursor: view.cursor } : { replay: "active" },
      );
    }, {
      "item.started": onItem("item.started"),
      "item.delta": onItem("item.delta"),
      "item.completed": onItem("item.completed"),

      "run.started": (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        applyItem("run.started", d);
        if (identifyActivity(String(d.turn_id || ""), "thinking", d.started_at)) markStreaming();
      },
      "run.completed": (d) => { void onRunEnd("run.completed", d); },
      "run.failed": (d) => { void onRunEnd("run.failed", d); },
      "run.cancelled": (d) => { void onRunEnd("run.cancelled", d); },

      "run.usage": (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        recordLlmUsage(String(d.turn_id || ""), Number(d.iter || 0), d);
      },

      "goal.created": () => {
        touch();
        loadGoalSnapshot(sid);
      },

      "swarm.started": (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        const status = buildSwarmStatusFromStarted(d);
        if (!status) return;
        act().upsertSwarmStatus(status);
        scrollToBottom();
      },

      "swarm.event": (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (act().status !== "streaming") act().setStatus("streaming");
        const runId = String(d.run_id || "");
        const event = d.event;
        if (!runId || !event) return;
        const pending = pendingSwarmEventsRef.current.get(runId) ?? [];
        pending.push(event);
        pendingSwarmEventsRef.current.set(runId, pending);
        if (swarmRafRef.current) return;
        swarmRafRef.current = requestAnimationFrame(() => {
          swarmRafRef.current = 0;
          const batches = pendingSwarmEventsRef.current;
          pendingSwarmEventsRef.current = new Map();
          const store = act();
          for (const [pendingRunId, events] of batches) {
            store.updateSwarmStatus(pendingRunId, (current) => (
              events.reduce<SwarmRunStatus>(
                (next, pendingEvent) => applySwarmEvent(next, pendingEvent),
                current,
              )
            ));
          }
          scrollToBottom();
        });
      },

      "goal.evidence": () => {
        touch();
        loadGoalSnapshot(sid);
      },

      "goal.updated": (d) => {
        touch();
        const snapshot = d.snapshot as GoalSnapshot | undefined;
        const goal = (d.goal as GoalSnapshot["goal"] | undefined) ?? snapshot?.goal;
        if (goal && isTerminalGoalStatus(goal.status)) {
          setGoalSnapshot(null);
          return;
        }
        if (snapshot) {
          setGoalSnapshot(snapshot);
          return;
        }
        loadGoalSnapshot(sid);
      },

      "mandate.proposal": (d) => {
        touch();
        const proposal = d as unknown as MandateProposal;
        if (!proposal.proposal_id || !Array.isArray(proposal.profiles)) return;
        setLiveItems((items) => [
          ...items,
          { kind: "proposal", timestamp: Date.now(), proposal, committed: null },
        ]);
        scrollToBottom();
      },

      "mandate.committed": (d) => {
        touch();
        const committed = d as unknown as MandateCommitted;
        if (!committed.proposal_id) return;
        setLiveItems((items) => items.map((item) => (
          item.kind === "proposal" && item.proposal.proposal_id === committed.proposal_id
            ? { ...item, committed }
            : item
        )));
        // A fresh mandate may bring up the runner; refresh the runtime panel now.
        liveRuntimeRef.current?.handleMandateCommitted();
        scrollToBottom();
      },

      "scheduled_research.proposal": (d) => {
        touch();
        const proposal = d as unknown as ScheduledResearchProposal;
        if (!proposal.proposal_id || !proposal.job) return;
        setLiveItems((items) => [
          ...items,
          { kind: "scheduled_proposal", timestamp: Date.now(), proposal },
        ]);
        scrollToBottom();
      },

      "live.halted": (d) => {
        touch();
        const halted = d as unknown as LiveHalted;
        // Preemptive kill switch: the server has cancelled resting orders and may have
        // flattened positions (SPEC §7.5 #6). Reflect the halted state across surfaces;
        // the RunnerStatus panel re-polls so its per-broker rows show "halted".
        liveRuntimeRef.current?.handleHalted(halted);
        toast.warning(t('agent.connectorHalted'));
      },

      "live.resumed": (d) => {
        touch();
        // Kill switch cleared via a privileged surface action (SPEC Consent §4);
        // clear the halted banner and re-poll runtime status.
        void d;
        liveRuntimeRef.current?.handleResumed();
        toast.success(t('agent.connectionRestored'));
      },

      "live.action": (d) => {
        touch();
        const action = d as unknown as LiveAction;
        if (!action.kind) return;
        setLiveItems((items) => [...items, { kind: "live_action", timestamp: Date.now(), action }]);
        liveRuntimeRef.current?.handleLiveAction(action);
        scrollToBottom();
      },

      heartbeat: () => {},
      reconnect: (d) => { act().setSseStatus("reconnecting", Number(d.attempt ?? 0)); },
    });
  }, [
    cancelPendingStreamFlush,
    clearStreamingView,
    connect,
    disconnect,
    dropPendingSend,
    endLiveTurn,
    loadGoalSnapshot,
    markBackgroundCompletion,
    queueStreamUpdate,
    recordLlmUsage,
    scrollToBottom,
    t,
  ]);

  useEffect(() => {
    const { sessionId: curSid, messages: curMsgs, cacheSession, reset, getCachedSession, switchSession } = act();

    if (urlSessionId && urlSessionId !== curSid) {
      const gen = genRef.current + 1;
      genRef.current = gen;
      doDisconnect();
      setRuntimeIdentity({});
      // Live-channel timeline items are per-session; clear on switch.
      setLiveItems([]);
      liveRuntimeRef.current?.resetSession();
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);

      // Atomic switch: cache hit = instant, cache miss = show loading skeleton
      const cached = getCachedSession(urlSessionId);
      switchSession(urlSessionId, cached);
      if (cached) {
        scheduleHistoryScroll();
      }
      // Cached rows provide an instant shell; REST remains authoritative for a
      // turn that completed while this session was off-screen.
      // Connect once the history is in: the stream resumes from its cursor.
      void loadSessionMessages(urlSessionId, gen).then((current) => {
        if (current) setupSSE(urlSessionId);
      });
    } else if (urlSessionId && urlSessionId === curSid && sseSessionRef.current !== urlSessionId) {
      // #229: returning to the SAME session after the page was unmounted (user
      // navigated away and back). The store kept our messages, but the unmount
      // cleanup tore down the SSE stream, so a running attempt stopped updating
      // and the UI looked frozen until the safety timeout fired. Re-hydrate like
      // a reload: reset the transient streaming view first (so replay=active
      // rebuilds the in-flight turn from the active item stream instead of
      // duplicating deltas onto the preserved text), refresh committed history
      // (covers an attempt that finished while we were away), then re-subscribe.
      const gen = genRef.current + 1;
      genRef.current = gen;
      setRuntimeIdentity({});
      const seed = curMsgs.length > 0 ? curMsgs : getCachedSession(urlSessionId);
      // switchSession() drops the live activity so replay can rebuild its
      // steps without duplicating them — but the attempt's start time is not
      // something replay can restore once the active stream has rotated past
      // `run.started`. Re-seed the still-running activity with its
      // original startedAt so the elapsed clock does not restart at 0s.
      const liveActivity = act().activity;
      switchSession(urlSessionId, seed);
      if (liveActivity && liveActivity.endedAt === undefined) {
        const store = act();
        store.startActivity(liveActivity.attemptId, liveActivity.startedAt);
        store.setActivityState(liveActivity.state);
      }
      // Connect once the history is in: the stream resumes from its cursor.
      void loadSessionMessages(urlSessionId, gen).then((current) => {
        if (current) setupSSE(urlSessionId);
      });
    } else if (!urlSessionId && curSid) {
      genRef.current += 1;
      doDisconnect();
      setRuntimeIdentity({});
      setHistoryError(null);
      setLiveItems([]);
      liveRuntimeRef.current?.resetSession();
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);
      reset();
    }
  }, [urlSessionId, doDisconnect, loadSessionMessages, setupSSE, scheduleHistoryScroll]);

  /* The live token counter belongs to one session; zero it on a real switch,
     not on callback-identity churn of the rehydration effect above. */
  useEffect(() => {
    resetLlmUsage();
  }, [sessionId, resetLlmUsage]);

  useEffect(() => {
    if (!sessionId) {
      setGoalSnapshot(null);
      return;
    }
    if (pendingGoalSessionRef.current === sessionId) {
      pendingGoalSessionRef.current = null;
      return;
    }
    loadGoalSnapshot(sessionId);
  }, [sessionId, loadGoalSnapshot]);

  useEffect(() => () => {
    // Invalidate pending history loads before they can schedule another scroll.
    genRef.current += 1;
    doDisconnect();
    cancelAnimationFrame(progressRafRef.current);
    pendingProgressRef.current.clear();
    cancelAnimationFrame(swarmRafRef.current);
    pendingSwarmEventsRef.current.clear();
    cancelAnimationFrame(rafRef.current);
    window.clearTimeout(smoothScrollTimerRef.current);
    window.clearTimeout(replayCheckTimerRef.current);
  }, [doDisconnect]);

  useEffect(() => {
    api.getLLMSettings().then((s) => {
      sseTimeoutMsRef.current = s.sse_timeout_seconds * 1000;
      setLlmSettings(s);
    }).catch(() => {});
  }, []);

  /* Safety timeout: if streaming but no SSE event for sseTimeoutMsRef.current ms, reset to idle */
  useEffect(() => {
    if (status !== "streaming") return;
    // Arm the clock at the start of every streaming turn. Without this, a turn
    // whose very first event never arrives (e.g. the LLM provider hangs before
    // emitting a single token) left lastEventRef at its 0 / stale value, so the
    // guard below short-circuited and the activity line stayed live forever.
    // forever. touch() refreshes this on every real event; the no-op heartbeat
    // deliberately does not, so a connection that only keep-alives still trips.
    lastEventRef.current = Date.now();
    const timer = setInterval(() => {
      if (lastEventRef.current && Date.now() - lastEventRef.current > sseTimeoutMsRef.current && act().status === "streaming") {
        // Stop waiting, not the turn: it may still finish, and Re-attach
        // resumes the stream from the thread cursor.
        const activity = act().activity;
        if (activity) {
          act().setTurnMeta(activity.attemptId, {
            timedOut: true,
            localEndedAt: Date.now(),
            startedAt: act().turnMeta[activity.attemptId]?.startedAt ?? activity.startedAt,
          });
        }
        endLiveTurn();
        toast.warning(t('agent.executionTimedOut'));
      }
    }, 10_000);
    return () => clearInterval(timer);
  }, [endLiveTurn, status, t]);

  /** A session this page just created has an empty thread: its stream starts at cursor 0. */
  const adoptNewSession = useCallback((sid: string) => {
    act().setSessionId(sid);
    act().updateThread((view) => ({ ...view, loaded: true }));
  }, []);

  const ensureGoalSession = useCallback(async (title: string): Promise<string> => {
    let sid = act().sessionId;
    if (sid) return sid;
    const session = await api.createSession(title.slice(0, 50));
    useSessionsStore.getState().upsert(session);
    sid = session.session_id;
    pendingGoalSessionRef.current = sid;
    adoptNewSession(sid);
    setSearchParams({ session: sid }, { replace: true });
    setupSSE(sid);
    return sid;
  }, [adoptNewSession, setSearchParams, setupSSE]);

  /** Send a message that starts a turn. A session busy elsewhere queues it instead. */
  const sendTurn = useCallback(async (sid: string, requestText: string) => {
    setupSSE(sid);
    const sent = await api.sendMessage(sid, requestText);
    if (isQueuedMessage(sent)) {
      dropPendingSend(requestText);
      act().updateThread((view) => addQueuedInput(view, { inputId: sent.input_id, content: requestText }));
      if (sent.attempt_id && act().activity?.attemptId.startsWith("pending-")) {
        act().setActivityAttemptId(sent.attempt_id);
      }
      return;
    }
    if (act().activity?.attemptId.startsWith("pending-")) {
      act().setActivityAttemptId(sent.attempt_id);
    }
  }, [dropPendingSend, setupSSE]);

  /** While a turn runs, a message waits on the server and joins after the current step. */
  const queuePrompt = useCallback(async (
    prompt: string,
    attachments: ComposerAttachment[],
  ) => {
    const sid = act().sessionId;
    if (!sid) return;
    const finalPrompt = buildChatPrompt(prompt, attachments, Boolean(swarmPreset));
    if (promptExceedsLimit(finalPrompt, MAX_MESSAGE_CHARS)) {
      toast.error(t('agent.messageTooLong', { limit: MAX_MESSAGE_CHARS.toLocaleString() }));
      composerRef.current?.fill(prompt);
      return;
    }
    if (swarmPreset) setSwarmPreset(null);
    try {
      const sent = await api.sendMessage(sid, finalPrompt);
      if (isQueuedMessage(sent)) {
        act().updateThread((view) => addQueuedInput(view, { inputId: sent.input_id, content: finalPrompt }));
      } else {
        // The running turn ended meanwhile, so this message started the next one.
        const displayPrompt = toDisplayPrompt(finalPrompt);
        act().addMessage({
          id: "",
          type: "user",
          content: displayPrompt.content,
          meta: { ...displayPrompt.meta, requestText: finalPrompt, pendingSend: true },
          timestamp: Date.now(),
        });
        if (!act().activity) act().startActivity(sent.attempt_id);
        act().setStatus("streaming");
      }
      forceScrollToBottom();
    } catch (error) {
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE
        : error instanceof ApiError && error.status === 409 ? error.message : t('agent.queue.failed' as never);
      toast.error(message);
      composerRef.current?.fill(prompt);
    }
  }, [forceScrollToBottom, swarmPreset, t]);

  const runPrompt = useCallback(async (
    prompt: string,
    attachments: ComposerAttachment[] = [],
  ) => {
    if (!prompt.trim() && attachments.length === 0) return;
    if (status === "streaming") {
      if (!goalComposerActive) void queuePrompt(prompt, attachments);
      return;
    }
    const finalPrompt = buildChatPrompt(prompt, attachments, Boolean(swarmPreset));
    const limit = goalComposerActive ? MAX_GOAL_CHARS : MAX_MESSAGE_CHARS;
    if (promptExceedsLimit(goalComposerActive ? prompt : finalPrompt, limit)) {
      toast.error(t('agent.messageTooLong', { limit: limit.toLocaleString() }));
      composerRef.current?.fill(prompt);
      return;
    }
    clearStreamingView();

    if (goalComposerActive) {
      try {
        const sid = await ensureGoalSession(prompt);
        const snapshot = await api.createGoal(sid, { objective: prompt });
        goalOpenRequestRef.current += 1;
        setGoalSnapshot(snapshot);
        setGoalComposerActive(false);
        toast.success(t('agent.researchGoalAttached'));
        const kickoff = goalKickoffPrompt(prompt);
        act().addMessage({
          id: "",
          type: "user",
          content: prompt,
          meta: { goalMode: true, requestText: kickoff, pendingSend: true },
          timestamp: Date.now(),
        });
        act().startActivity(`pending-${Date.now()}`);
        act().setStatus("streaming");
        forceScrollToBottom();
        await sendTurn(sid, kickoff);
      } catch (error) {
        useAgentStore.setState({ activity: null, toolCalls: [] });
        act().setStatus("idle");
        const message = error instanceof Error ? error.message : t('agent.failedToStartGoal');
        toast.error(message);
        act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
      }
      return;
    }

    const displayPrompt = toDisplayPrompt(prompt);
    const messageMeta: AgentMessageMeta = { ...displayPrompt.meta };

    // Swarm mode: let agent auto-select the right preset
    if (swarmPreset) {
      messageMeta.swarmMode = true;
      setSwarmPreset(null);
    }

    if (attachments.length > 0) {
      messageMeta.attachments = attachments.map(({ filename }) => ({ filename }));
    }
    messageMeta.requestText = finalPrompt;
    messageMeta.pendingSend = true;
    act().addMessage({
      id: "",
      type: "user",
      content: displayPrompt.content,
      meta: messageMeta,
      timestamp: Date.now(),
    });
    act().startActivity(`pending-${Date.now()}`);
    act().setStatus("streaming");
    forceScrollToBottom();

    try {
      let sid = act().sessionId;
      if (!sid) {
        const sessionTitle = prompt.trim()
          || attachments.map(({ filename }) => filename).join(", ");
        const session = await api.createSession(sessionTitle.slice(0, 50));
        useSessionsStore.getState().upsert(session);
        sid = session.session_id;
        adoptNewSession(sid);
        setSearchParams({ session: sid }, { replace: true });
      }
      await sendTurn(sid, finalPrompt);
    } catch (error) {
      useAgentStore.setState({ activity: null, toolCalls: [] });
      act().setStatus("error");
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE
        : error instanceof ApiError && ['message_too_long', 'network_error', 'request_timeout'].includes(error.code || '') ? error.message : t('agent.failedToSend');
      toast.error(message);
      act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
    }
  }, [
    adoptNewSession,
    clearStreamingView,
    ensureGoalSession,
    forceScrollToBottom,
    goalComposerActive,
    queuePrompt,
    sendTurn,
    setSearchParams,
    status,
    swarmPreset,
    t,
  ]);

  const submitComposerPrompt = useCallback((prompt: string) => {
    composerRef.current?.submit(prompt);
  }, []);

  const handleCancel = useCallback(async () => {
    if (!sessionId) {
      endLiveTurn();
      return;
    }
    try {
      const result = await api.cancelSession(sessionId);
      // Cancelling the session only stops the ReAct loop; a swarm tool call that
      // already returned keeps its workers running. Tell the swarm endpoint too
      // and settle the cards locally, so the user sees "cancelled" immediately
      // instead of a card that stays "running" until the last worker notices.
      const activeSwarmRuns = Object.values(swarmRuns).filter(
        (run) => run.status === "pending" || run.status === "running",
      );
      for (const run of activeSwarmRuns) {
        act().updateSwarmStatus(run.runId, stopSwarmRun);
        void api.cancelSwarmRun(run.runId).catch(() => {
          // Already finished or unknown to this runtime — the local status is
          // what the card shows either way.
        });
      }
      // The turn shows as stopped now; its recorded end confirms it. Events
      // still in flight for it no longer restart the live view.
      const turnId = act().activity?.attemptId;
      if (turnId) act().setTurnMeta(turnId, { stopRequested: true, localEndedAt: Date.now() });
      endLiveTurn();
      const pending = result?.pending_inputs;
      if (pending) act().updateThread((view) => withPendingInputs(view, pending));
      toast.info(t('agent.cancelRequestSent'));
    } catch {
      // The attempt is still live. Preserve its activity, buffered text and
      // streaming status so a failed cancel request does not strand the turn.
      toast.error(t('agent.cancelFailed'));
    }
  }, [endLiveTurn, sessionId, swarmRuns, t]);

  useEffect(() => {
    if (status !== "streaming") return;
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.repeat) return;
      event.preventDefault();
      void handleCancel();
    };
    document.addEventListener("keydown", cancelOnEscape);
    return () => document.removeEventListener("keydown", cancelOnEscape);
  }, [handleCancel, status]);

  const handleDiscardQueued = useCallback(async (inputId: string) => {
    if (!sessionId) return;
    try {
      await api.discardPendingInput(sessionId, inputId);
      act().updateThread((view) => removeQueuedInput(view, inputId));
    } catch {
      // 404: a turn is taking it right now; its delivered event moves it.
      toast.error(t("agent.queue.discardFailed" as never));
    }
  }, [sessionId, t]);

  const handleContinueGoal = useCallback(async () => {
    if (!sessionId || !goalSnapshot || status === "streaming") return;
    const prompt = goalContinuePrompt(goalSnapshot);
    act().addMessage({
      id: "",
      type: "user",
      content: t("agent.continueGoalMessage" as never, { goal: goalSnapshot.goal.objective }),
      meta: { goalMode: true, requestText: prompt, pendingSend: true },
      timestamp: Date.now(),
    });
    act().startActivity(`pending-${Date.now()}`);
    act().setStatus("streaming");
    forceScrollToBottom();
    composerRef.current?.focus();
    try {
      await sendTurn(sessionId, prompt);
    } catch (error) {
      useAgentStore.setState({ activity: null, toolCalls: [] });
      act().setStatus("error");
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE : t('agent.failedToContinue');
      toast.error(message);
      act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
    }
  }, [forceScrollToBottom, goalSnapshot, sendTurn, sessionId, status, t]);

  const handleRetry = useCallback((errorMsg: AgentMessage) => {
    if (status === "streaming") return;
    const msgs = act().messages;
    const errorIdx = msgs.findIndex(m => m.id === errorMsg.id);
    if (errorIdx === -1) return;
    // Find the most recent user message before this error
    let userContent: string | null = null;
    for (let i = errorIdx - 1; i >= 0; i--) {
      if (msgs[i].type === "user") {
        userContent = msgs[i].meta?.requestText || msgs[i].content;
        break;
      }
    }
    if (!userContent) return;
    submitComposerPrompt(userContent);
  }, [status, submitComposerPrompt]);

  const handleContinueActivity = useCallback(() => {
    submitComposerPrompt(t("agent.continuePrompt" as never));
  }, [submitComposerPrompt, t]);

  const handleReattachActivity = useCallback((timedOut: AgentActivity) => {
    if (!sessionId || status === "streaming") return;
    // Follow the turn again: the stream resumes from the thread cursor, so
    // everything it recorded meanwhile arrives first.
    act().setTurnMeta(timedOut.attemptId, { timedOut: false, localEndedAt: undefined });
    act().startActivity(timedOut.attemptId, timedOut.startedAt);
    act().setStatus("streaming");
    sseSessionRef.current = null;
    setupSSE(sessionId);
    forceScrollToBottom();
  }, [forceScrollToBottom, sessionId, setupSSE, status]);

  const handleGoalSnapshotChange = useCallback((snapshot: GoalSnapshot | null) => {
    setGoalSnapshot(snapshot);
  }, []);

  const handleStartGoal = useCallback(() => {
    setSwarmPreset(null);
    setGoalComposerActive(true);
  }, []);

  const handleCancelGoalComposer = useCallback(() => {
    setGoalComposerActive(false);
  }, []);

  const handleStartSwarm = useCallback(() => {
    setGoalComposerActive(false);
    setSwarmPreset({ name: "auto", title: "Agent Swarm" });
  }, []);

  const handleCancelSwarm = useCallback(() => {
    setSwarmPreset(null);
  }, []);

  const handleExport = useCallback(() => {
    if (messages.length === 0) return;
    const lines: string[] = [`# Chat Export`, ``, `Export time: ${new Date().toLocaleString()}`, ``];
    for (const msg of messages) {
      const time = new Date(msg.timestamp).toLocaleString();
      if (msg.type === "user") {
        lines.push(`## User (${time})`, ``, msg.content, ``);
      } else if (msg.type === "answer") {
        lines.push(`## Assistant (${time})`, ``, msg.content, ``);
      } else if (msg.type === "commentary") {
        lines.push(`> ${msg.content.split("\n").join("\n> ")}`, ``);
      } else if (msg.type === "error") {
        lines.push(`## Error (${time})`, ``, msg.content, ``);
      } else if (msg.type === "tool_call") {
        lines.push(`> Tool call: ${msg.tool || "unknown"}`, ``);
      } else if (msg.type === "swarm_status") {
        const swarmStatus = msg.swarmRunId ? swarmRuns[msg.swarmRunId] : msg.swarmStatus;
        lines.push(`> Swarm status: ${swarmStatus?.preset || "swarm"} ${swarmStatus?.status || ""}`, ``);
      } else if (msg.type === "run_complete") {
        lines.push(`> Backtest complete: ${msg.runId || ""}`, ``);
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chat_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [messages, swarmRuns]);

  const groups = useMemo(() => groupMessages(messages), [messages]);
  const hasCompletedTurn = useMemo(() => {
    let latestUserIndex = -1;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].type === "user") {
        latestUserIndex = index;
        break;
      }
    }
    return latestUserIndex >= 0 && messages
      .slice(latestUserIndex + 1)
      .some((message) => message.type === "answer" || message.type === "run_complete");
  }, [messages]);
  useEffect(() => {
    visibleRowsSessionRef.current = sessionId;
    setVisibleRowCount(TIMELINE_WINDOW_SIZE);
  }, [sessionId]);

  /* Merge message groups with live-channel items, ordered by timestamp, so a
   * mandate proposal / live-action chip renders inline at the point it arrived. */
  type TimelineRow =
    | { sort: number; render: "group"; group: MsgGroup; key: string }
    | { sort: number; render: "live"; item: LiveItem; key: string };
  const timelineRows = useMemo<TimelineRow[]>(() => {
    const rows: TimelineRow[] = groups.map((g, i) => {
      const ts = g.kind === "timeline" ? g.msgs[0].timestamp : g.msg.timestamp;
      const key = g.kind === "timeline"
        ? `${sessionId ?? "draft"}_timeline_${g.msgIdx}_${g.msgs[0].id || g.msgs[0].timestamp}`
        : `${sessionId ?? "draft"}_message_${g.msgIdx}_${g.msg.id || g.msg.timestamp}_${i}`;
      return { sort: ts, render: "group", group: g, key };
    });
    for (const item of liveItems) {
      const key = item.kind === "proposal"
        ? `${sessionId ?? "draft"}_lp_${item.proposal.proposal_id}`
        : item.kind === "scheduled_proposal"
          ? `${sessionId ?? "draft"}_srp_${item.proposal.proposal_id}`
          : `${sessionId ?? "draft"}_la_${item.action.audit_id || item.timestamp}`;
      rows.push({ sort: item.timestamp, render: "live", item, key });
    }
    return rows.sort((a, b) => a.sort - b.sort);
  }, [groups, liveItems, sessionId]);

  const visibleCountForSession = visibleRowsSessionRef.current === sessionId
    ? visibleRowCount
    : TIMELINE_WINDOW_SIZE;
  const visibleTimelineStart = Math.max(0, timelineRows.length - visibleCountForSession);
  const visibleTimelineRows = timelineRows.slice(visibleTimelineStart);
  const mountRowSessionRef = useRef<string | null | undefined>(undefined);
  const mountRowCountRef = useRef<number | null>(null);
  if (mountRowSessionRef.current !== sessionId) {
    mountRowSessionRef.current = sessionId;
    mountRowCountRef.current = sessionLoading ? null : timelineRows.length;
  } else if (mountRowCountRef.current === null && !sessionLoading) {
    mountRowCountRef.current = timelineRows.length;
  }

  const handleLoadEarlier = useCallback(() => {
    const container = listRef.current;
    const previousScrollHeight = container?.scrollHeight ?? 0;
    setVisibleRowCount((count) => Math.min(
      timelineRows.length,
      count + TIMELINE_WINDOW_SIZE,
    ));
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!container) return;
        container.scrollTop += container.scrollHeight - previousScrollHeight;
      });
    });
  }, [timelineRows.length]);

  return (
    <div className="flex flex-col flex-1 min-w-0 overflow-hidden h-full">
      <ModelRuntimeBar
        settings={llmSettings}
        runtimeProvider={visibleRuntimeIdentity.provider}
        runtimeModel={visibleRuntimeIdentity.model}
        runtimeReasoningEffort={visibleRuntimeIdentity.reasoningEffort}
        sessionModel={sessionModel}
        onSelectionChange={changeSessionModel}
        onClearSelection={clearSessionModel}
      />
      {sessionId && (
        <div className="flex justify-end border-b border-border/40 px-6 py-1">
          <button
            type="button"
            onClick={() => void compactSession()}
            disabled={status === "streaming"}
            className="rounded px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("agent.compactContext" as never)}
          </button>
        </div>
      )}
      {historyError && (
        <div role="alert" className="flex flex-wrap items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs">
          <span>{t("layout.sessionsLoadFailed")} {historyError}</span>
          <button type="button" onClick={() => {
            if (!sessionId) return;
            act().setSessionLoading(true);
            void refreshSessionMessages(sessionId);
          }} className="ms-auto rounded-md border px-2 py-1">{t("connection.retry")}</button>
        </div>
      )}
      <div
        ref={listRef}
        data-streaming={status === "streaming" ? "true" : undefined}
        className="chat-scroll-container flex-1 overflow-auto p-6 relative"
      >
        <div
          className={[
            "max-w-3xl mx-auto space-y-8",
            !sessionLoading && messages.length === 0 ? "min-h-full flex flex-col" : "",
          ].join(" ")}
        >
          {sessionLoading && (
            <div className="space-y-4 py-4">
              {[1, 2, 3].map(i => (
                <div key={i} className="flex gap-3 animate-pulse">
                  <div className="h-8 w-8 rounded-full bg-muted shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-muted rounded w-3/4" />
                    <div className="h-3 bg-muted/60 rounded w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          )}
          {!sessionLoading && !historyError && messages.length === 0 && (
            // my-auto (not justify-*) centers the hero vertically while staying
            // scroll-reachable once the example library expands past the viewport.
            <div className="msg-enter my-auto">
              <WelcomeScreen onExample={fillComposer} />
            </div>
          )}

          {visibleTimelineStart > 0 && (
            <button
              type="button"
              onClick={handleLoadEarlier}
              className="mx-auto block rounded-full border border-border/60 bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {t("agent.loadEarlier" as never)}
            </button>
          )}

          {visibleTimelineRows.map((row, visibleRowIdx) => {
            const rowIdx = visibleTimelineStart + visibleRowIdx;
            const shouldAnimate = (
              mountRowCountRef.current !== null &&
              rowIdx >= mountRowCountRef.current
            );
            if (row.render === "live") {
              if (row.item.kind === "proposal") {
                return (
                  <div key={row.key} className={shouldAnimate ? "msg-enter" : undefined}>
                    <MandateProposalCard
                      proposal={row.item.proposal}
                      committed={row.item.committed}
                      onAdjust={submitComposerPrompt}
                    />
                  </div>
                );
              }
              if (row.item.kind === "scheduled_proposal") {
                return (
                  <div key={row.key} className={shouldAnimate ? "msg-enter" : undefined}>
                    <ScheduledResearchProposalCard proposal={row.item.proposal} />
                  </div>
                );
              }
              return (
                <div key={row.key} className={shouldAnimate ? "msg-enter" : undefined}>
                  <LiveActionChip action={row.item.action} />
                </div>
              );
            }
            const g = row.group;
            if (g.kind === "timeline") {
              const isLastRow = rowIdx === timelineRows.length - 1;
              return (
                <div
                  key={row.key}
                  data-msg-idx={g.msgIdx}
                  className={shouldAnimate ? "msg-enter" : undefined}
                >
                  <ThinkingTimeline
                    messages={g.msgs}
                    isLatest={isLastRow && status === "streaming"}
                    onContinue={handleContinueActivity}
                    onReattach={handleReattachActivity}
                  />
                </div>
              );
            }
            if (g.msg.type === "turn_status" && g.msg.meta?.activity) {
              const turnActivity = g.msg.meta.activity;
              return (
                <div
                  key={row.key}
                  data-msg-idx={g.msgIdx}
                  className={shouldAnimate ? "msg-enter" : undefined}
                >
                  <ActivityLine
                    activity={turnActivity}
                    variant="summary"
                    onContinue={handleContinueActivity}
                    onReattach={() => handleReattachActivity(turnActivity)}
                  />
                </div>
              );
            }
            const swarmStatus = g.msg.swarmRunId
              ? swarmRuns[g.msg.swarmRunId] ?? g.msg.swarmStatus
              : g.msg.swarmStatus;
            if (g.msg.type === "plan" && g.msg.plan) return <div key={row.key} data-msg-idx={g.msgIdx}><PlanCard steps={g.msg.plan.steps} /></div>;
            if (g.msg.type === "question" && g.msg.question) return <div key={row.key} data-msg-idx={g.msgIdx}><QuestionCard questionId={g.msg.question.question_id} prompt={g.msg.question.prompt} options={g.msg.question.options} allowFreeText={g.msg.question.allow_free_text} onAnswer={submitComposerPrompt} /></div>;
            if (g.msg.type === "image" && g.msg.images) return <div key={row.key} data-msg-idx={g.msgIdx}><ImageResult images={g.msg.images} /></div>;
            if (g.msg.type === "swarm_status" && swarmStatus) {
              return (
                <div
                  key={row.key}
                  data-msg-idx={g.msgIdx}
                  className={shouldAnimate ? "msg-enter" : undefined}
                >
                  <SwarmStatusCard status={swarmStatus} />
                </div>
              );
            }
            return (
              <div
                key={row.key}
                data-msg-idx={g.msgIdx}
                className={shouldAnimate ? "msg-enter" : undefined}
              >
                <MessageBubble msg={g.msg} onRetry={g.msg.type === "error" ? handleRetry : undefined} />
                {g.msg.type === "answer" && g.msg.meta?.turnId && (
                  <button
                    type="button"
                    onClick={() => void forkFromTurn(g.msg.meta?.turnId || "")}
                    className="mt-2 rounded border border-border/60 px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted"
                  >
                    {t("agent.forkFromHere" as never)}
                  </button>
                )}
              </div>
            );
          })}

          {/* Streaming area - single stable wrapper to prevent insertBefore DOM race */}
          {status === "streaming" && (
            <div className="flex gap-3 msg-enter">
              <AgentAvatar />
              <div className="flex-1 min-w-0 space-y-2">
                {/* The steps themselves are rows above; this line is the turn's clock and verb. */}
                {activity && <ActivityLine activity={activity} reasoningTail={reasoningTail} showSteps={false} />}
                <LlmUsageCounter input={usageInput} output={usageOutput} />
                {streamingText && (
                  <div aria-live="polite" aria-atomic="false">
                    <MarkdownContent content={streamingText} streaming showCursor />
                  </div>
                )}
              </div>
            </div>
          )}

          {queuedInputs.length > 0 && (
            <QueuedInputs
              inputs={queuedInputs}
              display={toDisplayPrompt}
              onDiscard={handleDiscardQueued}
            />
          )}

        </div>

        {/* Scroll to bottom button */}
        {showScrollBtn && (
          <button
            onClick={() => forceScrollToBottom(true)}
            className="sticky bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 px-3 py-1.5 rounded-full bg-primary text-primary-foreground text-xs font-medium shadow-lg hover:opacity-90 transition-opacity z-10"
          >
            <ArrowDown className="h-3 w-3" /> {t('agent.newMessages')}
          </button>
        )}
        <ConversationTimeline messages={messages} containerRef={listRef} />
      </div>

      <div
        data-agent-composer
        className="border-t p-4 bg-background/80 backdrop-blur-sm"
      >
        <div className="max-w-3xl mx-auto">
          <LiveRuntimePanel
            ref={liveRuntimeRef}
            sessionId={sessionId}
            hasLiveItems={liveItems.length > 0}
          >
            <Composer
              ref={composerRef}
              streaming={status === "streaming"}
              canQueue={sessionId != null && !goalComposerActive}
              activityVerb={activity?.verb}
              hasCompletedTurn={hasCompletedTurn}
              showExport={sessionId != null}
              canExport={messages.length > 0}
              goalComposerActive={goalComposerActive}
              swarmPreset={swarmPreset}
              panels={
                goalSnapshot && !goalComposerActive ? (
                  <GoalPanel
                    key={goalSnapshot.goal.goal_id}
                    snapshot={goalSnapshot}
                    sessionId={sessionId}
                    streaming={status === "streaming"}
                    openRequest={goalOpenRequestRef.current}
                    onSnapshotChange={handleGoalSnapshotChange}
                    onContinue={handleContinueGoal}
                  />
                ) : undefined
              }
              onSubmit={runPrompt}
              onCancel={handleCancel}
              onExport={handleExport}
              onStartGoal={handleStartGoal}
              onCancelGoal={handleCancelGoalComposer}
              onStartSwarm={handleStartSwarm}
              onCancelSwarm={handleCancelSwarm}
            />
          </LiveRuntimePanel>
        </div>
      </div>
    </div>
  );
}
