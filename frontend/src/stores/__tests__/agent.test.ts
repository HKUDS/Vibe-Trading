import { useAgentStore } from "../agent";
import { makeMessage, makeToolCall, resetFactories } from "@/tests/helpers/factories";
import type { SwarmRunStatus } from "@/types/agent";

beforeEach(() => {
  useAgentStore.getState().reset();
  resetFactories();
});

describe("agent store — initial state", () => {
  it("has correct defaults", () => {
    const s = useAgentStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.sessionId).toBeNull();
    expect(s.status).toBe("idle");
    expect(s.streamingText).toBe("");
    expect(s.streamingSessionId).toBeNull();
    expect(s.toolCalls).toEqual([]);
    expect(s.activity).toBeNull();
    expect(s.swarmRuns).toEqual({});
    expect(s.sseStatus).toBe("disconnected");
    expect(s.sseRetryAttempt).toBe(0);
    expect(s.sessionLoading).toBe(false);
  });
});

describe("addMessage", () => {
  it("appends a message with auto-generated id", () => {
    useAgentStore.getState().addMessage({ type: "answer", content: "hello", timestamp: Date.now() });
    const msgs = useAgentStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].content).toBe("hello");
    expect(msgs[0].id).toBeTruthy();
  });

  it("preserves provided id", () => {
    useAgentStore.getState().addMessage(makeMessage({ id: "custom-id" }));
    expect(useAgentStore.getState().messages[0].id).toBe("custom-id");
  });

  it("accumulates multiple messages in order", () => {
    useAgentStore.getState().addMessage(makeMessage({ content: "first" }));
    useAgentStore.getState().addMessage(makeMessage({ content: "second" }));
    const msgs = useAgentStore.getState().messages;
    expect(msgs.map((m) => m.content)).toEqual(["first", "second"]);
  });
});

describe("appendDelta / clearStreaming", () => {
  it("accumulates streaming text", () => {
    const { appendDelta } = useAgentStore.getState();
    appendDelta("Hello ");
    appendDelta("World");
    expect(useAgentStore.getState().streamingText).toBe("Hello World");
  });

  it("clearStreaming resets to empty", () => {
    useAgentStore.getState().appendDelta("data");
    useAgentStore.getState().clearStreaming();
    expect(useAgentStore.getState().streamingText).toBe("");
  });
});

describe("setStatus", () => {
  it("sets status to streaming and records streamingSessionId", () => {
    const store = useAgentStore.getState();
    store.setSessionId("sess-1");
    store.setStatus("streaming");
    const s = useAgentStore.getState();
    expect(s.status).toBe("streaming");
    expect(s.streamingSessionId).toBe("sess-1");
  });

  it("clears streamingSessionId when status leaves streaming", () => {
    const store = useAgentStore.getState();
    store.setSessionId("sess-1");
    store.setStatus("streaming");
    store.setStatus("idle");
    const s = useAgentStore.getState();
    expect(s.streamingSessionId).toBeNull();
  });

  it("does not set streamingSessionId when sessionId is null", () => {
    useAgentStore.getState().setStatus("streaming");
    expect(useAgentStore.getState().streamingSessionId).toBeNull();
  });

  it("clears only the matching replay session spinner", () => {
    const store = useAgentStore.getState();
    store.setSessionId("sess-1");
    store.setStatus("streaming");
    store.switchSession("sess-2");

    store.clearStreamingSession("sess-2");
    expect(useAgentStore.getState().streamingSessionId).toBe("sess-1");
    store.clearStreamingSession("sess-1");
    expect(useAgentStore.getState().streamingSessionId).toBeNull();
  });
});

describe("setSessionId / loadHistory", () => {
  it("sets session id", () => {
    useAgentStore.getState().setSessionId("abc");
    expect(useAgentStore.getState().sessionId).toBe("abc");
  });

  it("loadHistory replaces messages", () => {
    useAgentStore.getState().addMessage(makeMessage({ content: "old" }));
    const newMsgs = [makeMessage({ content: "new1" }), makeMessage({ content: "new2" })];
    useAgentStore.getState().loadHistory(newMsgs);
    expect(useAgentStore.getState().messages).toHaveLength(2);
    expect(useAgentStore.getState().messages[0].content).toBe("new1");
  });
});

describe("tool calls", () => {
  it("addToolCall appends entry", () => {
    const tc = makeToolCall({ tool: "run_backtest" });
    useAgentStore.getState().addToolCall(tc);
    expect(useAgentStore.getState().toolCalls).toHaveLength(1);
    expect(useAgentStore.getState().toolCalls[0].tool).toBe("run_backtest");
  });

  it("updateToolCall patches matching entry", () => {
    const tc = makeToolCall({ id: "tc-1", status: "running" });
    useAgentStore.getState().addToolCall(tc);
    useAgentStore.getState().updateToolCall("tc-1", { status: "ok", elapsed_ms: 500 });
    const updated = useAgentStore.getState().toolCalls[0];
    expect(updated.status).toBe("ok");
    expect(updated.elapsed_ms).toBe(500);
  });

  it("updateToolCall ignores non-matching id", () => {
    useAgentStore.getState().addToolCall(makeToolCall({ id: "tc-1" }));
    useAgentStore.getState().updateToolCall("nonexistent", { status: "error" });
    expect(useAgentStore.getState().toolCalls[0].status).toBe("running");
  });

  it("matches interleaved parallel same-name calls by call_id", () => {
    const store = useAgentStore.getState();
    store.addToolCall(makeToolCall({ id: "call-1", tool: "search" }));
    store.addToolCall(makeToolCall({ id: "call-2", tool: "search" }));

    store.updateRunningToolCall("call-2", "search", {
      elapsed_s: 2,
      progress: { stage: "second", current: 8, total: 10 },
    });
    store.updateRunningToolCall("call-1", "search", {
      elapsed_s: 4,
      progress: { stage: "first", current: 3, total: 10 },
    });
    store.updateRunningToolCall("call-2", "search", {
      status: "ok",
      preview: "second-result",
    });

    expect(useAgentStore.getState().toolCalls).toMatchObject([
      {
        id: "call-1",
        status: "running",
        elapsed_s: 4,
        progress: { stage: "first", current: 3, total: 10 },
      },
      {
        id: "call-2",
        status: "ok",
        elapsed_s: 2,
        preview: "second-result",
        progress: { stage: "second", current: 8, total: 10 },
      },
    ]);

    store.updateRunningToolCall("call-1", "search", {
      status: "error",
      preview: "first-result",
    });
    expect(useAgentStore.getState().toolCalls.map((tc) => tc.status)).toEqual([
      "error",
      "ok",
    ]);
  });

  it("does not fall back to tool name when a call_id is unknown", () => {
    const store = useAgentStore.getState();
    store.addToolCall(makeToolCall({ id: "call-1", tool: "search" }));
    store.updateRunningToolCall("missing-call", "search", { status: "ok" });
    expect(useAgentStore.getState().toolCalls[0].status).toBe("running");
  });

  it("updates repeated running tool calls in FIFO order", () => {
    const store = useAgentStore.getState();
    store.addToolCall(makeToolCall({ id: "search#1", tool: "search" }));
    store.addToolCall(makeToolCall({ id: "search#2", tool: "search" }));

    store.updateRunningToolCall(undefined, "search", { status: "ok" });
    expect(useAgentStore.getState().toolCalls.map((tc) => tc.status)).toEqual([
      "ok",
      "running",
    ]);

    store.updateRunningToolCall(undefined, "search", { status: "error" });
    expect(useAgentStore.getState().toolCalls.map((tc) => tc.status)).toEqual([
      "ok",
      "error",
    ]);
  });

  it("live-updates one activity object from thinking through tool work", () => {
    const store = useAgentStore.getState();
    store.startActivity("attempt-1", 1000);
    expect(useAgentStore.getState().activity).toMatchObject({
      attemptId: "attempt-1",
      state: "thinking",
      verb: "working",
      steps: [],
      startedAt: 1000,
    });

    store.addToolCall(makeToolCall({
      id: "market-1",
      tool: "get_market_data",
      timestamp: 1100,
    }));
    expect(useAgentStore.getState().activity).toMatchObject({
      state: "working",
      verb: "readingMarketData",
      steps: [{ id: "market-1", status: "running" }],
    });

    store.updateToolCall("market-1", { status: "ok", elapsed_ms: 500 });
    expect(useAgentStore.getState().activity?.steps[0]).toMatchObject({
      status: "ok",
      elapsed_ms: 500,
    });
  });

  it("derives strategy, backtest, validation and fallback verbs", () => {
    const store = useAgentStore.getState();
    store.startActivity("attempt-map", 1000);
    const tools = [
      ["write_file", "writingStrategy"],
      ["run_backtest", "runningBacktest"],
      ["walk_forward_validation", "validatingNumbers"],
      ["run_swarm", "working"],
    ] as const;

    for (const [tool, verb] of tools) {
      store.addToolCall(makeToolCall({ id: tool, tool }));
      expect(useAgentStore.getState().activity?.verb).toBe(verb);
    }
  });

  it("freezes terminal activity timing and can replace a pending attempt id", () => {
    const store = useAgentStore.getState();
    store.startActivity("pending-1", 1000);
    store.setActivityAttemptId("attempt-final");
    store.setActivityState("responding", 1500);
    store.setActivityState("stopped", 4000);

    expect(useAgentStore.getState().activity).toMatchObject({
      attemptId: "attempt-final",
      state: "stopped",
      startedAt: 1000,
      endedAt: 4000,
    });
  });
});

describe("swarm status ordering", () => {
  it("keeps a stable placeholder message while status updates in its own slice", () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(100);
    const status: SwarmRunStatus = {
      runId: "swarm-1",
      preset: "research",
      status: "running",
      currentLayer: 0,
      totalLayers: 2,
      startedAt: 100,
      agents: [],
    };

    const store = useAgentStore.getState();
    store.upsertSwarmStatus(status);
    const placeholderMessages = useAgentStore.getState().messages;
    now.mockReturnValue(200);
    store.upsertSwarmStatus({ ...status, currentLayer: 1 });
    store.updateSwarmStatus("swarm-1", (current) => ({
      ...current,
      status: "completed",
    }));

    expect(useAgentStore.getState().messages).toHaveLength(1);
    expect(useAgentStore.getState().messages).toBe(placeholderMessages);
    expect(useAgentStore.getState().messages[0].timestamp).toBe(100);
    expect(useAgentStore.getState().messages[0].swarmStatus).toBeUndefined();
    expect(useAgentStore.getState().swarmRuns["swarm-1"]).toMatchObject({
      currentLayer: 1,
      status: "completed",
    });
    now.mockRestore();
  });
});

describe("session cache", () => {
  it("caches and retrieves session messages", () => {
    const msgs = [makeMessage({ content: "cached" })];
    useAgentStore.getState().cacheSession("sess-1", msgs);
    const cached = useAgentStore.getState().getCachedSession("sess-1");
    expect(cached).toHaveLength(1);
    expect(cached![0].content).toBe("cached");
  });

  it("returns undefined for uncached session", () => {
    expect(useAgentStore.getState().getCachedSession("unknown")).toBeUndefined();
  });

  it("evicts oldest when cache exceeds SESSION_CACHE_MAX (5)", () => {
    for (let i = 1; i <= 6; i++) {
      useAgentStore.getState().cacheSession(`sess-${i}`, [makeMessage()]);
    }
    expect(useAgentStore.getState().getCachedSession("sess-1")).toBeUndefined();
    expect(useAgentStore.getState().getCachedSession("sess-6")).toBeDefined();
  });

  it("re-caching same key moves it to newest", () => {
    for (let i = 1; i <= 5; i++) {
      useAgentStore.getState().cacheSession(`sess-${i}`, [makeMessage()]);
    }
    // Re-cache sess-1 → now it's the newest
    useAgentStore.getState().cacheSession("sess-1", [makeMessage({ content: "refreshed" })]);
    // Add one more → sess-2 should be evicted (oldest)
    useAgentStore.getState().cacheSession("sess-6", [makeMessage()]);
    expect(useAgentStore.getState().getCachedSession("sess-2")).toBeUndefined();
    expect(useAgentStore.getState().getCachedSession("sess-1")).toBeDefined();
  });

  it("restores cached swarm state without mutating placeholder messages", () => {
    const status: SwarmRunStatus = {
      runId: "swarm-cache",
      preset: "research",
      status: "running",
      currentLayer: 1,
      totalLayers: 2,
      startedAt: 100,
      agents: [],
    };
    const store = useAgentStore.getState();
    store.upsertSwarmStatus(status);
    store.cacheSession("swarm-session", useAgentStore.getState().messages);

    store.switchSession("other-session");
    store.switchSession(
      "swarm-session",
      useAgentStore.getState().getCachedSession("swarm-session"),
    );

    expect(useAgentStore.getState().swarmRuns["swarm-cache"]).toEqual(status);
    expect(useAgentStore.getState().messages[0].swarmStatus).toBeUndefined();
  });
});

describe("setSseStatus", () => {
  it("sets status and retry attempt", () => {
    useAgentStore.getState().setSseStatus("reconnecting", 3);
    const s = useAgentStore.getState();
    expect(s.sseStatus).toBe("reconnecting");
    expect(s.sseRetryAttempt).toBe(3);
  });

  it("defaults retryAttempt to 0", () => {
    useAgentStore.getState().setSseStatus("connected");
    expect(useAgentStore.getState().sseRetryAttempt).toBe(0);
  });
});

describe("switchSession", () => {
  it("sets new session, clears messages/status/toolCalls", () => {
    const store = useAgentStore.getState();
    store.addMessage(makeMessage());
    store.addToolCall(makeToolCall());
    store.appendDelta("streaming...");
    store.setStatus("streaming");

    store.switchSession("new-sess");
    const s = useAgentStore.getState();
    expect(s.sessionId).toBe("new-sess");
    expect(s.messages).toEqual([]);
    expect(s.toolCalls).toEqual([]);
    expect(s.activity).toBeNull();
    expect(s.swarmRuns).toEqual({});
    expect(s.streamingText).toBe("");
    expect(s.status).toBe("idle");
    expect(s.sessionLoading).toBe(true);
  });

  it("pre-loads messages when provided", () => {
    const msgs = [makeMessage({ content: "history" })];
    useAgentStore.getState().switchSession("s1", msgs);
    const s = useAgentStore.getState();
    expect(s.messages).toHaveLength(1);
    expect(s.sessionLoading).toBe(false);
  });

  it("preserves streamingSessionId from prior session", () => {
    const store = useAgentStore.getState();
    store.setSessionId("old-sess");
    store.setStatus("streaming");
    store.switchSession("new-sess");
    expect(useAgentStore.getState().streamingSessionId).toBe("old-sess");
  });
});

describe("setSessionLoading", () => {
  it("sets loading flag", () => {
    useAgentStore.getState().setSessionLoading(true);
    expect(useAgentStore.getState().sessionLoading).toBe(true);
    useAgentStore.getState().setSessionLoading(false);
    expect(useAgentStore.getState().sessionLoading).toBe(false);
  });
});

describe("reset", () => {
  it("returns store to initial state", () => {
    const store = useAgentStore.getState();
    store.addMessage(makeMessage());
    store.setSessionId("sess");
    store.appendDelta("data");
    store.addToolCall(makeToolCall());
    store.setSseStatus("connected");

    store.reset();
    const s = useAgentStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.sessionId).toBeNull();
    expect(s.streamingText).toBe("");
    expect(s.toolCalls).toEqual([]);
    expect(s.activity).toBeNull();
    expect(s.swarmRuns).toEqual({});
    expect(s.status).toBe("idle");
    expect(s.streamingSessionId).toBeNull();
    expect(s.sessionLoading).toBe(false);
  });
});
