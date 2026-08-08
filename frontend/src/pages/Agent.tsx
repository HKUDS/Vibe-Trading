import { useTranslation } from 'react-i18next';
import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router";
import { ArrowDown } from "lucide-react";
import { toast } from "sonner";
import {
  useAgentStore,
  type AgentActivity,
  type AgentMessageMeta,
  type StoredAgentMessage,
} from "@/stores/agent";
import { useSSE } from "@/hooks/useSSE";
import { ApiError, AUTH_REQUIRED_MESSAGE, api, isAuthRequiredError, type GoalSnapshot, type MandateProposal, type MandateCommitted, type LiveAction, type LiveHalted, type LLMSettings } from "@/lib/api";
import { isReportWorthyRun } from "@/lib/runReports";
import type { AgentMessage, SwarmRunStatus, ToolCallEntry } from "@/types/agent";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { MarkdownContent, MessageBubble } from "@/components/chat/MessageBubble";
import { ModelRuntimeBar } from "@/components/chat/ModelRuntimeBar";
import { ThinkingTimeline } from "@/components/chat/ThinkingTimeline";
import { ConversationTimeline } from "@/components/chat/ConversationTimeline";
import { ActivityLine } from "@/components/chat/ActivityLine";
import { MandateProposalCard } from "@/components/chat/MandateProposalCard";
import { SwarmStatusCard } from "@/components/chat/SwarmStatusCard";
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
  buildSwarmStatusFromStarted,
  buildSwarmStatusFromToolResultPreview,
} from "@/lib/swarmStatus";
import { buildToolTimelineMessages } from "@/pages/agentToolTimeline";

/* ---------- Message grouping ---------- */
type MsgGroup =
  | { kind: "single"; msg: StoredAgentMessage; msgIdx: number }
  | { kind: "timeline"; msgs: StoredAgentMessage[]; msgIdx: number };

function groupMessages(msgs: StoredAgentMessage[]): MsgGroup[] {
  const out: MsgGroup[] = [];
  let buf: StoredAgentMessage[] = [];
  let bufStartIdx = -1;
  const flush = () => {
    if (buf.length) {
      out.push({ kind: "timeline", msgs: [...buf], msgIdx: bufStartIdx });
      buf = [];
      bufStartIdx = -1;
    }
  };
  for (const [msgIdx, m] of msgs.entries()) {
    if (["thinking", "tool_call", "tool_result", "compact"].includes(m.type)) {
      if (bufStartIdx < 0) bufStartIdx = msgIdx;
      buf.push(m);
    } else {
      flush();
      out.push({ kind: "single", msg: m, msgIdx });
    }
  }
  flush();
  return out;
}

const act = () => useAgentStore.getState();

function eventCallId(data: Record<string, unknown>): string | undefined {
  return typeof data.call_id === "string" && data.call_id
    ? data.call_id
    : undefined;
}

interface PendingToolProgress {
  callId?: string;
  tool: string;
  progress: NonNullable<ToolCallEntry["progress"]>;
}

interface RuntimeIdentity {
  sessionId?: string;
  provider?: string;
  model?: string;
  reasoningEffort?: string;
}

function toolProgressKey(callId: string | undefined, tool: string): string {
  return callId ? `call:${callId}` : `tool:${tool}`;
}

// i18n hook for Agent component — used inside the component below
// (declared at module scope for helper usage is fine since t() reads from i18n singleton)

const STREAM_FLUSH_INTERVAL_MS = 80;
const TIMELINE_WINDOW_SIZE = 160;
const SWARM_PROMPT_PREFIX =
  "[Swarm Team Mode] Use the swarm tool to assemble the best specialist team for this task. Auto-select the most appropriate preset.\n\n";
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
  let display = content;
  const meta: AgentMessageMeta = { requestText: content };
  const attachmentMatch = display.match(
    /^\[Uploaded file: (.+), path: [^\n]*\]\n\n/,
  );
  if (attachmentMatch) {
    meta.attachment = { filename: attachmentMatch[1] };
    display = display.slice(attachmentMatch[0].length);
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
type LiveItem = ProposalItem | LiveActionItem;

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

  /* tool_progress coalescing — keep latest payload per invocation, flush once per rAF. */
  const pendingProgressRef = useRef<Map<string, PendingToolProgress>>(new Map());
  const progressRafRef = useRef(0);
  const pendingTextRef = useRef("");
  const pendingReasoningRef = useRef<boolean | null>(null);
  const streamFlushTimerRef = useRef(0);
  const pendingSwarmEventsRef = useRef<Map<string, unknown[]>>(new Map());
  const swarmRafRef = useRef(0);
  const toolCallSeqRef = useRef(0);
  const replayAttemptSeenRef = useRef(false);
  const replayCheckTimerRef = useRef(0);
  const smoothScrollingRef = useRef(false);
  const smoothScrollTimerRef = useRef(0);
  const titleBeforeCompletionRef = useRef<string | null>(null);
  const completedAttemptIdsRef = useRef<Set<string>>(new Set());

  const [swarmPreset, setSwarmPreset] = useState<{ name: string; title: string } | null>(null);
  const [goalComposerActive, setGoalComposerActive] = useState(false);
  const [goalSnapshot, setGoalSnapshot] = useState<GoalSnapshot | null>(null);

  /* Connector runtime channel state (SPEC Consent §1/§4/§5) */
  const [liveItems, setLiveItems] = useState<LiveItem[]>([]);
  const [visibleRowCount, setVisibleRowCount] = useState(TIMELINE_WINDOW_SIZE);
  const visibleRowsSessionRef = useRef<string | null>(null);
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [runtimeIdentity, setRuntimeIdentity] = useState<RuntimeIdentity>({});

  const messages = useAgentStore(s => s.messages);
  const streamingText = useAgentStore(s => s.streamingText);
  const status = useAgentStore(s => s.status);
  const sessionId = useAgentStore(s => s.sessionId);
  const activity = useAgentStore(s => s.activity);
  const reasoningTail = useAgentStore(s => s.reasoningTail);
  const swarmRuns = useAgentStore(s => s.swarmRuns);
  const sessionLoading = useAgentStore(s => s.sessionLoading);
  const previousStatusRef = useRef(status);

  const { connect, disconnect, onStatusChange } = useSSE();

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

  const archiveActivity = useCallback((
    terminalState: "stopped" | "timeout" | "failed" | "done",
    endedAt = Date.now(),
  ): AgentActivity | null => {
    const store = act();
    store.setActivityState(terminalState, endedAt);
    const finished = act().activity;
    if (!finished) return null;
    const [activityMessage] = buildToolTimelineMessages(finished.steps, {
      activity: finished,
      idPrefix: "live_",
    });
    useAgentStore.setState((state) => ({
      messages: [
        ...state.messages.filter(
          (message) => message.meta?.activity?.attemptId !== finished.attemptId,
        ),
        activityMessage,
      ],
      activity: null,
      toolCalls: [],
    }));
    return finished;
  }, []);

  const persistPartialAnswer = useCallback((
    attempt: AgentActivity | null,
    content: string,
  ) => {
    if (!attempt || !content.trim()) return;
    act().addMessage({
      id: `partial_${attempt.attemptId}`,
      type: "answer",
      content,
      meta: { partialAttemptId: attempt.attemptId },
      timestamp: Date.now(),
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

  const loadSessionMessages = useCallback(async (sid: string, gen: number) => {
    try {
      const msgs = await api.getSessionMessages(sid);
      if (genRef.current !== gen) return;
      const agentMsgs: StoredAgentMessage[] = [];
      let latestRuntimeIdentity: RuntimeIdentity | null = null;
      for (const m of msgs) {
        const meta = m.metadata as Record<string, unknown> | undefined;
        const runId = meta?.run_id as string | undefined;
        const metrics = meta?.metrics as Record<string, number> | undefined;
        const elapsedMs = typeof meta?.elapsed_ms === "number" ? meta.elapsed_ms : undefined;
        if (
          m.role === "assistant"
          && (
            typeof meta?.provider === "string"
            || typeof meta?.model === "string"
            || typeof meta?.reasoning_effort === "string"
          )
        ) {
          latestRuntimeIdentity = {
            sessionId: sid,
            provider: typeof meta?.provider === "string" ? meta.provider : undefined,
            model: typeof meta?.model === "string" ? meta.model : undefined,
            reasoningEffort: typeof meta?.reasoning_effort === "string"
              ? meta.reasoning_effort
              : undefined,
          };
        }
        const ts = new Date(m.created_at).getTime();
        const toolTimeline = m.role === "assistant"
          ? buildToolTimelineMessages(m.tool_trail ?? [], {
              fallbackTimestamp: ts,
              idPrefix: `${m.message_id}_`,
              attemptId: m.linked_attempt_id || `${m.message_id}_attempt`,
              state: meta?.status === "failed"
                ? "failed"
                : meta?.status === "cancelled"
                  ? "stopped"
                  : "done",
              endedAt: ts,
            })
          : [];
        agentMsgs.push(...toolTimeline);
        const lastToolTimestamp = toolTimeline.length > 0
          ? toolTimeline[toolTimeline.length - 1].timestamp
          : ts - 1;
        const assistantTs = Math.max(ts, lastToolTimestamp + 1);
        if (m.role === "user") {
          const displayPrompt = toDisplayPrompt(m.content);
          agentMsgs.push({
            id: m.message_id,
            type: "user",
            content: displayPrompt.content,
            meta: displayPrompt.meta,
            timestamp: ts,
          });
        } else if (runId) {
          // Show text answer first (if non-empty), then chart card
          if (m.content && m.content !== "Strategy execution completed.") {
            agentMsgs.push({ id: m.message_id + "_ans", type: "answer", content: m.content, elapsed_ms: elapsedMs, timestamp: assistantTs });
          }
          if (metrics && Object.keys(metrics).length > 0) {
            agentMsgs.push({ id: m.message_id, type: "run_complete", content: "", runId, metrics, timestamp: assistantTs + 1 });
          } else {
            // Fetch run data to check report-worthiness; show fallback card if fetch fails
            let fetchedMetrics: Record<string, number> | undefined;
            let fetchedCurve: Array<{ time: string; equity: number }> | undefined;
            let showCard = false;
            try {
              const runData = await api.getRun(runId);
              if (isReportWorthyRun(runData)) {
                fetchedMetrics = runData.metrics;
                fetchedCurve = runData.equity_curve?.map((e) => ({ time: e.time, equity: Number(e.equity) }));
                showCard = true;
              }
              // succeeded but not report-worthy (plain chat turn) → skip card
            } catch {
              // fetch failed (auth/404/network) → can't tell, show link as fallback
              showCard = true;
            }
            if (showCard) {
              agentMsgs.push({
                id: m.message_id,
                type: "run_complete",
                content: "",
                runId,
                metrics: fetchedMetrics,
                equityCurve: fetchedCurve,
                timestamp: assistantTs + 1,
              });
            }
          }
        } else {
          agentMsgs.push({ id: m.message_id, type: "answer", content: m.content, elapsed_ms: elapsedMs, timestamp: assistantTs });
        }
      }
      if (genRef.current !== gen) return;
      act().loadHistory(agentMsgs);
      act().setSessionLoading(false);
      act().cacheSession(sid, agentMsgs);
      setRuntimeIdentity(latestRuntimeIdentity ?? {});
      setTimeout(() => forceScrollToBottom(), 50);
    } catch {
      if (genRef.current !== gen) return;
      setRuntimeIdentity({});
      act().setSessionLoading(false);
    }
  }, [forceScrollToBottom]);

  const refreshSessionMessages = useCallback(async (sid: string) => {
    const gen = genRef.current + 1;
    genRef.current = gen;
    await loadSessionMessages(sid, gen);
  }, [loadSessionMessages]);

  const syncCompletedAttempt = useCallback(async (sid: string, attemptId?: string) => {
    if (!attemptId) return false;
    for (let i = 0; i < 3; i += 1) {
      try {
        const storedMessages = await api.getSessionMessages(sid);
        const completed = storedMessages.some(
          (message) => message.role === "assistant" && message.linked_attempt_id === attemptId,
          );
        if (completed) {
          act().clearStreamingSession(sid);
          markBackgroundCompletion(sid, attemptId);
          if (act().sessionId !== sid) return true;
          clearStreamingView();
          act().setStatus("idle");
          useAgentStore.setState({ toolCalls: [], activity: null });
          await refreshSessionMessages(sid);
          return true;
        }
      } catch {
        return false;
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 800));
    }
    return false;
  }, [clearStreamingView, markBackgroundCompletion, refreshSessionMessages]);

  const setupSSE = useCallback((sid: string) => {
    if (sseSessionRef.current === sid) return;
    cancelPendingStreamFlush();
    window.clearTimeout(replayCheckTimerRef.current);
    replayAttemptSeenRef.current = false;
    disconnect();
    sseSessionRef.current = sid;

    const touch = () => { lastEventRef.current = Date.now(); };
    const identifyActivity = (
      data: Record<string, unknown>,
      state: "thinking" | "working" | "responding",
    ): boolean => {
      const store = act();
      const attemptId = String(data.attempt_id || "");
      if (attemptId && store.messages.some((message) => (
        message.meta?.activity?.attemptId === attemptId
        && ["stopped", "timeout"].includes(message.meta.activity.state)
      ))) {
        return false;
      }
      const current = store.activity;
      if (!current) {
        store.startActivity(attemptId || `pending-${Date.now()}`);
      } else if (
        attemptId &&
        current.attemptId !== attemptId &&
        current.attemptId.startsWith("pending-")
      ) {
        store.setActivityAttemptId(attemptId);
      } else if (attemptId && current.attemptId !== attemptId) {
        store.startActivity(attemptId);
      }
      act().setActivityState(state);
      return true;
    };

    connect(api.sseUrl(sid, { replay: "active" }), {
      text_delta: (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (!identifyActivity(d, "responding")) return;
        if (act().status !== "streaming") act().setStatus("streaming");
        queueStreamUpdate(String(d.delta || ""), false);
      },
      reasoning_delta: (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (!identifyActivity(d, "thinking")) return;
        // The backend sends a bounded rolling tail — replace, never append.
        act().setReasoningTail(String(d.tail ?? ""));
        queueStreamUpdate("", true);
        if (act().status !== "streaming") act().setStatus("streaming");
      },
      stream_reset: (d) => {
        touch();
        if (!identifyActivity(d, "thinking")) return;
        clearStreamingView();
        if (act().status !== "streaming") act().setStatus("streaming");
        scrollToBottom();
      },
      thinking_done: () => { touch(); /* don't flush — keep streaming text visible */ },

      tool_call: (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (!identifyActivity(d, "working")) return;
        queueStreamUpdate("", false);
        const toolName = String(d.tool || "");
        const callId = eventCallId(d);
        toolCallSeqRef.current += 1;
        // Only update toolCalls tracker (no message creation during streaming)
        act().addToolCall({
          id: callId ?? `${toolName}#${toolCallSeqRef.current}`, tool: toolName,
          arguments: (d.arguments as Record<string, string>) ?? {},
          status: "running", timestamp: Date.now(),
        });
        scrollToBottom();
      },

      tool_result: (d) => {
        touch();
        const toolName = String(d.tool || "");
        const callId = eventCallId(d);
        // Drop any in-flight coalesced progress for this invocation.
        pendingProgressRef.current.delete(toolProgressKey(callId, toolName));
        // Only update tracker (no message creation during streaming)
        act().updateRunningToolCall(callId, toolName, {
          status: d.status === "ok" ? "ok" : "error",
          preview: String(d.preview || ""),
          elapsed_ms: Number(d.elapsed_ms || 0),
          elapsed_s: undefined,
          progress: undefined,
        });
        if (toolName === "run_swarm") {
          const fallback = buildSwarmStatusFromToolResultPreview(String(d.preview || ""));
          if (fallback && !act().swarmRuns[fallback.runId]) {
            act().upsertSwarmStatus(fallback);
          }
        }
      },

      tool_heartbeat: (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (!identifyActivity(d, "working")) return;
        // Keep streaming state alive during long-running tools (swarm, backtest)
        if (act().status !== "streaming") act().setStatus("streaming");
        const toolName = String(d.tool || "");
        if (!toolName) return;
        act().updateRunningToolCall(eventCallId(d), toolName, {
          elapsed_s: Number(d.elapsed_s || 0),
        });
      },

      tool_progress: (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        const toolName = String(d.tool || "");
        if (!toolName) return;
        const callId = eventCallId(d);
        const payload: NonNullable<ToolCallEntry["progress"]> = {};
        if (typeof d.stage === "string" && d.stage) payload.stage = d.stage;
        if (typeof d.message === "string" && d.message) payload.message = d.message;
        if (typeof d.current === "number") payload.current = d.current;
        if (typeof d.total === "number") payload.total = d.total;
        // Coalesce: keep latest payload per invocation, flush once per animation frame.
        pendingProgressRef.current.set(
          toolProgressKey(callId, toolName),
          { callId, tool: toolName, progress: payload },
        );
        if (progressRafRef.current) return;
        progressRafRef.current = requestAnimationFrame(() => {
          progressRafRef.current = 0;
          const pending = pendingProgressRef.current;
          if (pending.size === 0) return;
          const store = act();
          for (const { callId: pendingCallId, tool, progress } of pending.values()) {
            store.updateRunningToolCall(pendingCallId, tool, { progress });
          }
          pending.clear();
        });
      },

      compact: () => { touch(); },

      "message.received": (d) => {
        touch();
        if (String(d.role || "") !== "user") return;
        const messageId = String(d.message_id || "");
        const requestText = String(d.content || "");
        if (!messageId || !requestText || act().messages.some((msg) => msg.id === messageId)) return;
        const now = Date.now();
        const optimisticDuplicate = act().messages.some((msg) => (
          msg.type === "user" &&
          msg.meta?.requestText === requestText &&
          now - msg.timestamp < 10_000
        ));
        if (optimisticDuplicate) return;
        const displayPrompt = toDisplayPrompt(requestText);
        act().addMessage({
          id: messageId,
          type: "user",
          content: displayPrompt.content,
          meta: displayPrompt.meta,
          timestamp: now,
        });
        scrollToBottom();
      },

      "attempt.created": (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (!identifyActivity(d, "thinking")) return;
        // Backend has created a new attempt — ensure streaming state is active
        // even if we connected mid-stream (SSE replay / page reload).
        if (act().status !== "streaming") act().setStatus("streaming");
      },

      "attempt.started": (d) => {
        touch();
        replayAttemptSeenRef.current = true;
        if (!identifyActivity(d, "thinking")) return;
        // Backend has begun executing the attempt. Re-affirm streaming state
        // so the UI shows a working indicator for reconnects and fresh loads.
        if (act().status !== "streaming") act().setStatus("streaming");
      },

      "attempt.completed": async (d) => {
        touch();
        const attemptId = String(d.attempt_id || "");
        markBackgroundCompletion(sid, attemptId);
        if (act().sessionId !== sid) {
          act().clearStreamingSession(sid);
          return;
        }
        if (attemptId && act().messages.some(
          (message) => (
            message.meta?.activity?.attemptId === attemptId
            && message.meta.activity.state === "done"
          ),
        )) {
          clearStreamingView();
          act().setStatus("idle");
          return;
        }
        const streamedAnswer = act().streamingText + pendingTextRef.current;
        flushPendingStreamUpdate();
        if (!act().activity) {
          act().startActivity(attemptId || `completed-${Date.now()}`);
        } else if (attemptId && act().activity?.attemptId !== attemptId) {
          act().setActivityAttemptId(attemptId);
        }
        const s = act();
        const completedTools = s.activity?.steps ?? s.toolCalls;
        const completedActivity = archiveActivity("done");
        const completedAttemptId = completedActivity?.attemptId || attemptId;
        useAgentStore.setState((state) => ({
          messages: state.messages.filter(
            (message) => message.meta?.partialAttemptId !== completedAttemptId,
          ),
        }));

        // Clear streaming text after freezing the durable activity summary.
        s.clearStreaming();

        // Add final answer
        const runDir = String(d.run_dir || "");
        const runId = runDir ? runDir.split(/[/\\]/).pop() : undefined;
        const summary = String(d.summary || "");
        const finalAnswer = summary.trim() ? summary : streamedAnswer;
        if (finalAnswer) {
          s.addMessage({
            id: "",
            type: "answer",
            content: finalAnswer,
            elapsed_ms: Number(d.elapsed_ms || 0) || undefined,
            timestamp: Date.now(),
          });
        }
        if (d.provider || d.model) {
          setRuntimeIdentity({
            sessionId: sid,
            provider: d.provider ? String(d.provider) : undefined,
            model: d.model ? String(d.model) : undefined,
            reasoningEffort: typeof d.reasoning_effort === "string"
              ? d.reasoning_effort
              : undefined,
          });
        }

        // First completed exchange → ask the backend for a Codex-style
        // summary title, then nudge the sidebar to re-list sessions.
        if (act().messages.filter((message) => message.type === "user").length === 1) {
          api.autoTitleSession(sid)
            .then(() => window.dispatchEvent(new Event("vibe:sessions-refresh")))
            .catch(() => {});
        }

        // Detect Shadow Account id if render_shadow_report fired successfully this turn
        const shadowCall = completedTools.find(
          (tc) => tc.tool === "render_shadow_report" && (tc.status || "ok") === "ok",
        );
        const shadowMatch = shadowCall?.preview?.match(/"shadow_id"\s*:\s*"(shadow_[A-Za-z0-9_]+)"/);
        const shadowId = shadowMatch?.[1];

        // The transcript is already complete. Drop transient state before the
        // optional report fetch so answer/tool progress never overlap.
        s.setStatus("idle");
        scrollToBottom();

        // Show RunCompleteCard when the turn produced backtest metrics or a shadow report
        if (runId) {
          let runMetrics: Record<string, number> | undefined;
          let runCurve: Array<{ time: string; equity: number }> | undefined;
          let showCard = false;
          try {
            const runData = await api.getRun(runId);
            if (isReportWorthyRun(runData)) {
              runMetrics = runData.metrics;
              runCurve = runData.equity_curve?.map(e => ({ time: e.time, equity: Number(e.equity) }));
              showCard = true;
            }
          } catch {
            showCard = true; // fetch failed → show link as fallback
          }
          if (showCard || shadowId) {
            s.addMessage({
              id: "", type: "run_complete", content: "", runId,
              metrics: showCard ? runMetrics : undefined,
              equityCurve: showCard ? runCurve : undefined,
              shadowId,
              timestamp: Date.now(),
            });
          }
        } else if (shadowId) {
          s.addMessage({ id: "", type: "run_complete", content: "", shadowId, timestamp: Date.now() });
        }

        scrollToBottom();
      },

      "attempt.failed": (d) => {
        touch();
        const attemptId = String(d.attempt_id || "");
        if (act().sessionId !== sid) {
          act().clearStreamingSession(sid);
          return;
        }
        const archived = act().messages.find(
          (message) => message.meta?.activity?.attemptId === attemptId,
        )?.meta?.activity;
        if (archived?.state === "stopped") {
          act().setStatus("idle");
          return;
        }
        if (!act().activity && archived) {
          useAgentStore.setState((state) => ({
            messages: state.messages.map((message) => (
              message.meta?.activity?.attemptId === attemptId
                ? {
                    ...message,
                    meta: {
                      ...message.meta,
                      activity: { ...archived, state: "failed", endedAt: Date.now() },
                    },
                  }
                : message
            )),
          }));
        } else {
          if (!act().activity) act().startActivity(attemptId || `failed-${Date.now()}`);
          archiveActivity("failed");
        }
        clearStreamingView();
        act().addMessage({ id: "", type: "error", content: String(d.error || "Execution failed"), timestamp: Date.now() });
        act().setStatus("idle");
        scrollToBottom();
      },

      // A user stop is its own terminal event now, so it no longer arrives as
      // attempt.failed and no longer needs the pre-marked "stopped" workaround
      // to avoid showing an error bubble.
      "attempt.cancelled": (d) => {
        touch();
        const attemptId = String(d.attempt_id || "");
        if (act().sessionId !== sid) {
          act().clearStreamingSession(sid);
          return;
        }
        const archived = act().messages.find(
          (message) => message.meta?.activity?.attemptId === attemptId,
        )?.meta?.activity;
        if (archived && archived.state !== "stopped") {
          useAgentStore.setState((state) => ({
            messages: state.messages.map((message) => (
              message.meta?.activity?.attemptId === attemptId
                ? {
                    ...message,
                    meta: {
                      ...message.meta,
                      activity: { ...archived, state: "stopped", endedAt: Date.now() },
                    },
                  }
                : message
            )),
          }));
        } else if (!archived) {
          if (!act().activity) act().startActivity(attemptId || `cancelled-${Date.now()}`);
          archiveActivity("stopped");
        }
        clearStreamingView();
        act().setStatus("idle");
        scrollToBottom();
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
    archiveActivity,
    cancelPendingStreamFlush,
    clearStreamingView,
    connect,
    disconnect,
    flushPendingStreamUpdate,
    loadGoalSnapshot,
    markBackgroundCompletion,
    queueStreamUpdate,
    scrollToBottom,
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
        setTimeout(() => forceScrollToBottom(), 50);
      }
      // Cached rows provide an instant shell; REST remains authoritative for a
      // turn that completed while this session was off-screen.
      loadSessionMessages(urlSessionId, gen);
      setupSSE(urlSessionId);
    } else if (urlSessionId && urlSessionId === curSid && sseSessionRef.current !== urlSessionId) {
      // #229: returning to the SAME session after the page was unmounted (user
      // navigated away and back). The store kept our messages, but the unmount
      // cleanup tore down the SSE stream, so a running attempt stopped updating
      // and the UI looked frozen until the safety timeout fired. Re-hydrate like
      // a reload: reset the transient streaming view first (so replay=active
      // rebuilds the in-flight turn from the backend ring buffer instead of
      // duplicating deltas onto the preserved text), refresh committed history
      // (covers an attempt that finished while we were away), then re-subscribe.
      const gen = genRef.current + 1;
      genRef.current = gen;
      setRuntimeIdentity({});
      const seed = curMsgs.length > 0 ? curMsgs : getCachedSession(urlSessionId);
      switchSession(urlSessionId, seed);
      loadSessionMessages(urlSessionId, gen);
      setupSSE(urlSessionId);
    } else if (!urlSessionId && curSid) {
      genRef.current += 1;
      doDisconnect();
      setRuntimeIdentity({});
      setLiveItems([]);
      liveRuntimeRef.current?.resetSession();
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);
      reset();
    }
  }, [urlSessionId, doDisconnect, loadSessionMessages, setupSSE, forceScrollToBottom]);

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
        flushPendingStreamUpdate();
        const partialAnswer = act().streamingText;
        const timedOutActivity = archiveActivity("timeout");
        act().clearStreaming();
        persistPartialAnswer(timedOutActivity, partialAnswer);
        act().setStatus("idle");
        toast.warning(t('agent.executionTimedOut'));
      }
    }, 10_000);
    return () => clearInterval(timer);
  }, [archiveActivity, flushPendingStreamUpdate, persistPartialAnswer, status, t]);

  const ensureGoalSession = useCallback(async (title: string): Promise<string> => {
    let sid = act().sessionId;
    if (sid) return sid;
    const session = await api.createSession(title.slice(0, 50));
    sid = session.session_id;
    pendingGoalSessionRef.current = sid;
    act().setSessionId(sid);
    setSearchParams({ session: sid }, { replace: true });
    setupSSE(sid);
    return sid;
  }, [setSearchParams, setupSSE]);

  const runPrompt = useCallback(async (
    prompt: string,
    attachment: ComposerAttachment | null = null,
  ) => {
    if (!prompt.trim() || status === "streaming") return;
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
          meta: { goalMode: true, requestText: kickoff },
          timestamp: Date.now(),
        });
        act().startActivity(`pending-${Date.now()}`);
        act().setStatus("streaming");
        forceScrollToBottom();
        setupSSE(sid);
        const sent = await api.sendMessage(sid, kickoff);
        if (act().activity?.attemptId.startsWith("pending-")) {
          act().setActivityAttemptId(sent.attempt_id);
        }
        void syncCompletedAttempt(sid, sent.attempt_id);
      } catch (error) {
        if (act().activity) archiveActivity("failed");
        act().setStatus("idle");
        const message = error instanceof Error ? error.message : t('agent.failedToStartGoal');
        toast.error(message);
        act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
      }
      return;
    }

    let finalPrompt = prompt;
    const displayPrompt = toDisplayPrompt(prompt);
    const messageMeta: AgentMessageMeta = { ...displayPrompt.meta };

    // Swarm mode: let agent auto-select the right preset
    if (swarmPreset) {
      messageMeta.swarmMode = true;
      setSwarmPreset(null);
      finalPrompt = `${SWARM_PROMPT_PREFIX}${prompt}`;
    }

    if (attachment) {
      messageMeta.attachment = { filename: attachment.filename };
      finalPrompt = `[Uploaded file: ${attachment.filename}, path: ${attachment.filePath}]\n\n${finalPrompt}`;
    }
    messageMeta.requestText = finalPrompt;
    act().addMessage({
      id: "",
      type: "user",
      content: displayPrompt.content,
      meta: Object.keys(messageMeta).length > 0 ? messageMeta : undefined,
      timestamp: Date.now(),
    });
    act().startActivity(`pending-${Date.now()}`);
    act().setStatus("streaming");
    forceScrollToBottom();

    try {
      let sid = act().sessionId;
      if (!sid) {
        const session = await api.createSession(prompt.slice(0, 50));
        sid = session.session_id;
        act().setSessionId(sid);
        setSearchParams({ session: sid }, { replace: true });
      }
      setupSSE(sid);
      const sent = await api.sendMessage(sid, finalPrompt);
      if (act().activity?.attemptId.startsWith("pending-")) {
        act().setActivityAttemptId(sent.attempt_id);
      }
      void syncCompletedAttempt(sid, sent.attempt_id);
    } catch (error) {
      archiveActivity("failed");
      act().setStatus("error");
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE : t('agent.failedToSend');
      toast.error(message);
      act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
    }
  }, [
    archiveActivity,
    clearStreamingView,
    ensureGoalSession,
    forceScrollToBottom,
    goalComposerActive,
    setSearchParams,
    setupSSE,
    status,
    swarmPreset,
    syncCompletedAttempt,
    t,
  ]);

  const submitComposerPrompt = useCallback((prompt: string) => {
    composerRef.current?.submit(prompt);
  }, []);

  const handleCancel = useCallback(async () => {
    if (!sessionId) {
      flushPendingStreamUpdate();
      const partialAnswer = act().streamingText;
      const stoppedActivity = archiveActivity("stopped");
      act().clearStreaming();
      persistPartialAnswer(stoppedActivity, partialAnswer);
      act().setStatus("idle");
      return;
    }
    try {
      await api.cancelSession(sessionId);
      flushPendingStreamUpdate();
      const partialAnswer = act().streamingText;
      const stoppedActivity = archiveActivity("stopped");
      act().clearStreaming();
      persistPartialAnswer(stoppedActivity, partialAnswer);
      act().setStatus("idle");
      toast.info(t('agent.cancelRequestSent'));
    } catch {
      // The attempt is still live. Preserve its activity, buffered text and
      // streaming status so a failed cancel request does not strand the turn.
      toast.error(t('agent.cancelFailed'));
    }
  }, [
    archiveActivity,
    flushPendingStreamUpdate,
    persistPartialAnswer,
    sessionId,
    t,
  ]);

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

  const handleContinueGoal = useCallback(async () => {
    if (!sessionId || !goalSnapshot || status === "streaming") return;
    const prompt = goalContinuePrompt(goalSnapshot);
    act().addMessage({
      id: "",
      type: "user",
      content: t("agent.continueGoalMessage" as never, { goal: goalSnapshot.goal.objective }),
      meta: { goalMode: true, requestText: prompt },
      timestamp: Date.now(),
    });
    act().startActivity(`pending-${Date.now()}`);
    act().setStatus("streaming");
    forceScrollToBottom();
    composerRef.current?.focus();
    try {
      setupSSE(sessionId);
      const sent = await api.sendMessage(sessionId, prompt);
      if (act().activity?.attemptId.startsWith("pending-")) {
        act().setActivityAttemptId(sent.attempt_id);
      }
      void syncCompletedAttempt(sessionId, sent.attempt_id);
    } catch (error) {
      archiveActivity("failed");
      act().setStatus("error");
      const message = isAuthRequiredError(error) ? AUTH_REQUIRED_MESSAGE : t('agent.failedToContinue');
      toast.error(message);
      act().addMessage({ id: "", type: "error", content: message, timestamp: Date.now() });
    }
  }, [archiveActivity, forceScrollToBottom, goalSnapshot, sessionId, setupSSE, status, syncCompletedAttempt, t]);

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
    useAgentStore.setState((state) => ({
      messages: state.messages.filter((message) => (
        message.meta?.activity?.attemptId !== timedOut.attemptId
        && message.meta?.partialAttemptId !== timedOut.attemptId
      )),
      activity: {
        ...timedOut,
        state: "thinking",
        steps: [],
        endedAt: undefined,
      },
      toolCalls: [],
      streamingText: "",
    }));
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
      />
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
          {!sessionLoading && messages.length === 0 && (
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
            const swarmStatus = g.msg.swarmRunId
              ? swarmRuns[g.msg.swarmRunId] ?? g.msg.swarmStatus
              : g.msg.swarmStatus;
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
              </div>
            );
          })}

          {/* Streaming area - single stable wrapper to prevent insertBefore DOM race */}
          {status === "streaming" && (
            <div className="flex gap-3 msg-enter">
              <AgentAvatar />
              <div className="flex-1 min-w-0 space-y-2">
                {activity && <ActivityLine activity={activity} reasoningTail={reasoningTail} />}
                {streamingText && (
                  <div aria-live="polite" aria-atomic="false">
                    <MarkdownContent content={streamingText} streaming showCursor />
                  </div>
                )}
              </div>
            </div>
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
