import { create } from "zustand";
import type { AgentMessage, SwarmRunStatus, ToolCallEntry } from "@/types/agent";
import type { ThreadView, TurnMeta } from "@/lib/threadItems";

const SESSION_CACHE_MAX = 5;

export type ActivityState =
  | "thinking"
  | "working"
  | "responding"
  | "stopped"
  | "timeout"
  | "failed"
  | "interrupted"
  | "done";

export type ActivityVerb =
  | "readingMarketData"
  | "writingStrategy"
  | "runningBacktest"
  | "validatingNumbers"
  | "working";

export interface AgentActivity {
  attemptId: string;
  state: ActivityState;
  verb: ActivityVerb;
  steps: ToolCallEntry[];
  startedAt: number;
  endedAt?: number;
}

const VALIDATION_TOOL = /(?:validate|validation|monte_carlo|bootstrap|walk_forward|stress_test|sanity_check)/;
const BACKTEST_TOOL = /backtest/;
const STRATEGY_TOOL = /(?:write|edit|patch|strategy|signal|scaffold|generate)/;
const MARKET_DATA_TOOL = /(?:market_data|search|read|fetch|ticker|quote|candle|orderbook|funding|open_interest|financial|filing|news|profile|screener|fred|iwencai|fund_flow|dragon|northbound|margin|block_trade|shareholder|lockup|sector|research|options_chain)/;

/** Map the latest tool stage to the user-facing activity verb key. */
export function deriveActivityVerb(tool: string | undefined): ActivityVerb {
  const normalized = (tool || "").toLowerCase();
  if (VALIDATION_TOOL.test(normalized)) return "validatingNumbers";
  if (BACKTEST_TOOL.test(normalized)) return "runningBacktest";
  if (STRATEGY_TOOL.test(normalized)) return "writingStrategy";
  if (MARKET_DATA_TOOL.test(normalized)) return "readingMarketData";
  return "working";
}

export interface AgentMessageMeta {
  attachment?: { filename: string };
  attachments?: Array<{ filename: string }>;
  swarmMode?: boolean;
  goalMode?: boolean;
  requestText?: string;
  activity?: AgentActivity;
  partialAttemptId?: string;
  /** Turn (attempt) a thread-derived row belongs to. */
  turnId?: string;
  /** Text a stopped turn streamed before it was cut off. */
  partial?: boolean;
  /** What a notice row marks. */
  notice?: "compaction";
  /** Shown on send, before the server records the message. */
  pendingSend?: boolean;
  /** Built from the thread view; replaced whenever the view changes. */
  fromThread?: boolean;
}

export type StoredAgentMessage = AgentMessage & { meta?: AgentMessageMeta };

const _sessionCache = new Map<string, StoredAgentMessage[]>();
const _swarmSessionCache = new Map<string, Record<string, SwarmRunStatus>>();
const _threadSessionCache = new Map<string, { thread: ThreadView; turnMeta: Record<string, TurnMeta> }>();

function emptyThread(): ThreadView {
  return { loaded: false, cursor: 0, entries: [], liveAssistant: null, queued: [] };
}

/** Builds the chat rows of a thread view; `previous` are the rows it built last time. */
export type TranscriptBuilder = (
  thread: ThreadView,
  turnMeta: Readonly<Record<string, TurnMeta>>,
  previous: readonly StoredAgentMessage[],
) => StoredAgentMessage[];

let transcriptBuilder: TranscriptBuilder | null = null;

/** Register how thread views become chat rows (the chat page does, once). */
export function setTranscriptBuilder(builder: TranscriptBuilder | null): void {
  transcriptBuilder = builder;
}

/** Replace the thread-built rows of `messages`, keeping every other row, in time order. */
function withThreadRows(
  messages: StoredAgentMessage[],
  thread: ThreadView,
  turnMeta: Record<string, TurnMeta>,
): StoredAgentMessage[] {
  if (!transcriptBuilder) return messages;
  const previous = messages.filter((message) => message.meta?.fromThread);
  const others = messages.filter((message) => !message.meta?.fromThread);
  const rows = transcriptBuilder(thread, turnMeta, previous);
  // Stable: equal timestamps keep other rows before thread rows.
  return [...others, ...rows].sort((a, b) => a.timestamp - b.timestamp);
}

interface AgentState {
  /** Rows not derived from the thread: pre-thread history, local errors, swarm cards. */
  messages: StoredAgentMessage[];
  /** The session's conversation items (design §6.8); rendered after `messages` rows of older turns. */
  thread: ThreadView;
  /** Per-turn facts from attempt events and the projected reply rows, keyed by turn id. */
  turnMeta: Record<string, TurnMeta>;
  sessionId: string | null;
  status: "idle" | "streaming" | "error";
  streamingText: string;
  /** Rolling tail of the model's live reasoning trace (bounded server-side). */
  reasoningTail: string;

  /** The session currently streaming on the backend. Survives switchSession
   *  so the sidebar spinner persists when the user navigates away. */
  streamingSessionId: string | null;

  toolCalls: ToolCallEntry[];
  activity: AgentActivity | null;
  swarmRuns: Record<string, SwarmRunStatus>;

  sseStatus: "disconnected" | "connected" | "reconnecting";
  sseRetryAttempt: number;

  addMessage: (msg: Omit<StoredAgentMessage, "id"> & { id?: string }) => void;
  appendDelta: (delta: string) => void;
  setStatus: (s: AgentState["status"]) => void;
  setSessionId: (id: string | null) => void;
  loadHistory: (msgs: StoredAgentMessage[]) => void;

  addToolCall: (entry: ToolCallEntry) => void;
  updateToolCall: (id: string, update: Partial<ToolCallEntry>) => void;
  updateRunningToolCall: (
    callId: string | undefined,
    tool: string,
    update: Partial<ToolCallEntry>,
  ) => void;
  updateOldestRunningToolCall: (tool: string, update: Partial<ToolCallEntry>) => void;
  startActivity: (attemptId: string, startedAt?: number) => void;
  setActivityAttemptId: (attemptId: string) => void;
  setActivityState: (state: ActivityState, at?: number) => void;
  clearActivity: () => void;
  upsertSwarmStatus: (status: SwarmRunStatus) => void;
  updateSwarmStatus: (runId: string, updater: (status: SwarmRunStatus) => SwarmRunStatus) => void;

  cacheSession: (sid: string, msgs: StoredAgentMessage[]) => void;
  getCachedSession: (sid: string) => StoredAgentMessage[] | undefined;

  updateThread: (updater: (thread: ThreadView) => ThreadView) => void;
  setTurnMeta: (turnId: string, patch: Partial<TurnMeta>) => void;

  setReasoningTail: (tail: string) => void;
  clearStreaming: () => void;
  clearStreamingSession: (sid: string) => void;

  setSseStatus: (s: AgentState["sseStatus"], retryAttempt?: number) => void;

  switchSession: (sid: string, msgs?: StoredAgentMessage[]) => void;
  sessionLoading: boolean;
  setSessionLoading: (v: boolean) => void;

  reset: () => void;
}

let _id = 0;
const nextId = () => String(++_id);

export const useAgentStore = create<AgentState>((set) => ({
  messages: [],
  thread: emptyThread(),
  turnMeta: {},
  sessionId: null,
  status: "idle",
  streamingText: "",
  reasoningTail: "",
  streamingSessionId: null,
  toolCalls: [],
  activity: null,
  swarmRuns: {},
  sseStatus: "disconnected",
  sseRetryAttempt: 0,
  sessionLoading: false,

  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, { ...msg, id: msg.id || nextId() } as AgentMessage] })),

  appendDelta: (delta) =>
    set((s) => ({ streamingText: s.streamingText + delta })),

  setStatus: (status) =>
    set((s) => {
      const patch: Partial<AgentState> = { status };
      if (status === "streaming" && s.sessionId) {
        patch.streamingSessionId = s.sessionId;
      } else if (status !== "streaming" && s.streamingSessionId === s.sessionId) {
        patch.streamingSessionId = null;
      }
      return patch;
    }),
  setSessionId: (sessionId) => set({ sessionId }),
  loadHistory: (msgs) =>
    set((s) => {
      const historicalSwarmIds = new Set(
        msgs.flatMap((msg) => msg.swarmRunId ? [msg.swarmRunId] : []),
      );
      const liveSwarmPlaceholders = s.messages.filter((msg) => (
        msg.type === "swarm_status" &&
        msg.swarmRunId &&
        s.swarmRuns[msg.swarmRunId] &&
        !historicalSwarmIds.has(msg.swarmRunId)
      ));
      const threadRows = s.messages.filter((msg) => msg.meta?.fromThread);
      return {
        messages: [...msgs, ...liveSwarmPlaceholders, ...threadRows]
          .sort((a, b) => a.timestamp - b.timestamp),
      };
    }),

  addToolCall: (entry) =>
    set((s) => {
      const toolCalls = [...s.toolCalls, entry];
      return {
        toolCalls,
        activity: s.activity ? {
          ...s.activity,
          state: "working",
          verb: deriveActivityVerb(entry.tool),
          steps: toolCalls,
          endedAt: undefined,
        } : null,
      };
    }),
  updateToolCall: (id, update) =>
    set((s) => {
      const toolCalls = s.toolCalls.map((tc) => tc.id === id ? { ...tc, ...update } : tc);
      return {
        toolCalls,
        activity: s.activity ? { ...s.activity, steps: toolCalls } : null,
      };
    }),
  updateRunningToolCall: (callId, tool, update) =>
    set((s) => {
      const idx = callId
        ? s.toolCalls.findIndex(
            (tc) => tc.id === callId && tc.status === "running",
          )
        : s.toolCalls.findIndex(
            (tc) => tc.tool === tool && tc.status === "running",
          );
      if (idx < 0) return {};
      const toolCalls = [...s.toolCalls];
      toolCalls[idx] = { ...toolCalls[idx], ...update };
      return {
        toolCalls,
        activity: s.activity ? { ...s.activity, steps: toolCalls } : null,
      };
    }),
  updateOldestRunningToolCall: (tool, update) =>
    set((s) => {
      let idx = -1;
      for (let i = 0; i < s.toolCalls.length; i += 1) {
        if (s.toolCalls[i].tool === tool && s.toolCalls[i].status === "running") {
          idx = i;
          break;
        }
      }
      if (idx < 0) return {};
      const toolCalls = [...s.toolCalls];
      toolCalls[idx] = { ...toolCalls[idx], ...update };
      return {
        toolCalls,
        activity: s.activity ? { ...s.activity, steps: toolCalls } : null,
      };
    }),
  startActivity: (attemptId, startedAt = Date.now()) =>
    set({
      activity: {
        attemptId,
        state: "thinking",
        verb: "working",
        steps: [],
        startedAt,
      },
      toolCalls: [],
    }),
  setActivityAttemptId: (attemptId) =>
    set((s) => ({
      activity: s.activity ? { ...s.activity, attemptId } : null,
    })),
  setActivityState: (state, at = Date.now()) =>
    set((s) => {
      if (!s.activity) return {};
      const terminal = ["stopped", "timeout", "failed", "interrupted", "done"].includes(state);
      return {
        activity: {
          ...s.activity,
          state,
          endedAt: terminal ? at : undefined,
        },
      };
    }),
  clearActivity: () => set({ activity: null }),
  upsertSwarmStatus: (swarmStatus) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.type === "swarm_status" && m.swarmRunId === swarmStatus.runId);
      if (idx >= 0) {
        return {
          swarmRuns: { ...s.swarmRuns, [swarmStatus.runId]: swarmStatus },
        };
      }
      return {
        swarmRuns: { ...s.swarmRuns, [swarmStatus.runId]: swarmStatus },
        messages: [
          ...s.messages,
          {
            id: `swarm_${swarmStatus.runId}`,
            type: "swarm_status",
            content: "",
            swarmRunId: swarmStatus.runId,
            timestamp: Date.now(),
          },
        ],
      };
    }),
  updateSwarmStatus: (runId, updater) =>
    set((s) => {
      const current = s.swarmRuns[runId];
      if (!current) return {};
      return {
        swarmRuns: { ...s.swarmRuns, [runId]: updater(current) },
      };
    }),

  cacheSession: (sid, msgs) =>
    set((s) => {
      _sessionCache.delete(sid);
      _sessionCache.set(sid, msgs);
      _swarmSessionCache.delete(sid);
      _swarmSessionCache.set(sid, s.swarmRuns);
      _threadSessionCache.delete(sid);
      if (s.sessionId === sid) {
        _threadSessionCache.set(sid, { thread: s.thread, turnMeta: s.turnMeta });
      }
      if (_sessionCache.size > SESSION_CACHE_MAX) {
        const oldest = _sessionCache.keys().next().value;
        if (oldest) {
          _sessionCache.delete(oldest);
          _swarmSessionCache.delete(oldest);
          _threadSessionCache.delete(oldest);
        }
      }
      return {};
    }),
  getCachedSession: (sid) => _sessionCache.get(sid),

  updateThread: (updater) =>
    set((s) => {
      const thread = updater(s.thread);
      if (thread === s.thread) return {};
      return { thread, messages: withThreadRows(s.messages, thread, s.turnMeta) };
    }),
  setTurnMeta: (turnId, patch) =>
    set((s) => {
      const turnMeta = { ...s.turnMeta, [turnId]: { ...s.turnMeta[turnId], ...patch } };
      return { turnMeta, messages: withThreadRows(s.messages, s.thread, turnMeta) };
    }),

  setReasoningTail: (reasoningTail) => set({ reasoningTail }),
  clearStreaming: () => set({ streamingText: "", reasoningTail: "" }),
  clearStreamingSession: (sid) =>
    set((s) => s.streamingSessionId === sid ? { streamingSessionId: null } : {}),

  setSseStatus: (sseStatus, retryAttempt) =>
    set({ sseStatus, sseRetryAttempt: retryAttempt ?? 0 }),

  switchSession: (sid, msgs) => {
    _id = 0;
    const cachedThread = msgs ? _threadSessionCache.get(sid) : undefined;
    set((s) => ({
      sessionId: sid,
      messages: msgs || [],
      // In-progress items of a cached view are stale; the reload and the
      // resumed stream bring back whatever is still running.
      thread: cachedThread
        ? {
            ...cachedThread.thread,
            liveAssistant: null,
            entries: cachedThread.thread.entries.filter((entry) => entry.state !== "live"),
          }
        : emptyThread(),
      turnMeta: cachedThread?.turnMeta ?? {},
      status: "idle",
      streamingText: "",
      reasoningTail: "",
      toolCalls: [],
      activity: null,
      swarmRuns: msgs ? (_swarmSessionCache.get(sid) ?? {}) : {},
      sessionLoading: !msgs,
      // Preserve streamingSessionId so the sidebar spinner stays visible
      // when switching away from a running session.
      streamingSessionId: s.streamingSessionId,
    }));
  },

  setSessionLoading: (sessionLoading) => set({ sessionLoading }),

  reset: () => {
    _id = 0;
    set({
      messages: [], thread: emptyThread(), turnMeta: {},
      status: "idle", streamingText: "", reasoningTail: "",
      sessionId: null, toolCalls: [], activity: null, swarmRuns: {}, sessionLoading: false,
      streamingSessionId: null,
    });
  },
}));
