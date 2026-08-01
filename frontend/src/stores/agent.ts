import { create } from "zustand";
import type { AgentMessage, SwarmRunStatus, ToolCallEntry } from "@/types/agent";

const SESSION_CACHE_MAX = 5;

export type ActivityState =
  | "thinking"
  | "working"
  | "responding"
  | "stopped"
  | "timeout"
  | "failed"
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
  swarmMode?: boolean;
  goalMode?: boolean;
  requestText?: string;
  activity?: AgentActivity;
  partialAttemptId?: string;
}

export type StoredAgentMessage = AgentMessage & { meta?: AgentMessageMeta };

const _sessionCache = new Map<string, StoredAgentMessage[]>();
const _swarmSessionCache = new Map<string, Record<string, SwarmRunStatus>>();

interface AgentState {
  messages: StoredAgentMessage[];
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
      return {
        messages: [...msgs, ...liveSwarmPlaceholders]
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
      const terminal = ["stopped", "timeout", "failed", "done"].includes(state);
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
      if (_sessionCache.size > SESSION_CACHE_MAX) {
        const oldest = _sessionCache.keys().next().value;
        if (oldest) {
          _sessionCache.delete(oldest);
          _swarmSessionCache.delete(oldest);
        }
      }
      return {};
    }),
  getCachedSession: (sid) => _sessionCache.get(sid),

  setReasoningTail: (reasoningTail) => set({ reasoningTail }),
  clearStreaming: () => set({ streamingText: "", reasoningTail: "" }),
  clearStreamingSession: (sid) =>
    set((s) => s.streamingSessionId === sid ? { streamingSessionId: null } : {}),

  setSseStatus: (sseStatus, retryAttempt) =>
    set({ sseStatus, sseRetryAttempt: retryAttempt ?? 0 }),

  switchSession: (sid, msgs) => {
    _id = 0;
    set((s) => ({
      sessionId: sid,
      messages: msgs || [],
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
      messages: [], status: "idle", streamingText: "", reasoningTail: "",
      sessionId: null, toolCalls: [], activity: null, swarmRuns: {}, sessionLoading: false,
      streamingSessionId: null,
    });
  },
}));
