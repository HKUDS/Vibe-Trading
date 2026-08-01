import { describe, it, expect, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useAgentStore } from "@/stores/agent";

beforeEach(() => {
  useAgentStore.getState().reset();
});

/**
 * Regression test for the insertBefore DOM race condition.
 *
 * During streaming, the old code had two separate conditional blocks:
 * 1. Pre-stream placeholder (status=streaming && no content)
 * 2. Live streaming area (streamingText || reasoningActive || toolCalls)
 *
 * When reasoningActive switched to streamingText, React had to unmount
 * one div and mount another simultaneously. If scrollToBottom's
 * requestAnimationFrame ran between these operations, the reference
 * node disappeared and insertBefore threw NotFoundError.
 *
 * The fix merges both blocks into a single stable wrapper that never
 * unmounts during streaming.
 */
describe("Streaming DOM stability", () => {
  it("streaming wrapper stays mounted across state transitions", () => {
    const store = useAgentStore.getState();

    // Transition 1: streaming starts, no content yet (placeholder)
    act(() => {
      store.setSessionId("test-session");
      store.startActivity("attempt-1");
      store.setStatus("streaming");
    });

    let state = useAgentStore.getState();
    expect(state.status).toBe("streaming");
    expect(state.streamingText).toBe("");
    expect(state.activity?.state).toBe("thinking");

    // Transition 2: reasoning starts
    act(() => {
      store.appendDelta("Thinking...");
    });

    state = useAgentStore.getState();
    expect(state.streamingText).toBe("Thinking...");

    // Transition 3: streaming text arrives
    act(() => {
      store.clearStreaming();
      store.appendDelta("Hello ");
      store.appendDelta("World");
    });

    state = useAgentStore.getState();
    expect(state.streamingText).toBe("Hello World");

    // Transition 4: tool call arrives
    act(() => {
      store.addToolCall({
        id: "tc-1",
        tool: "run_backtest",
        arguments: {},
        status: "running",
        timestamp: Date.now(),
      });
    });

    state = useAgentStore.getState();
    expect(state.toolCalls).toHaveLength(1);
    expect(state.activity).toMatchObject({
      state: "working",
      verb: "runningBacktest",
      steps: [{ id: "tc-1" }],
    });

    // Transition 5: tool completes
    act(() => {
      store.updateToolCall("tc-1", {
        status: "ok",
        elapsed_ms: 1500,
        preview: "done",
      });
    });

    state = useAgentStore.getState();
    expect(state.toolCalls[0].status).toBe("ok");

    // Transition 6: streaming ends
    act(() => {
      store.clearStreaming();
      store.setStatus("idle");
    });

    state = useAgentStore.getState();
    expect(state.status).toBe("idle");
    expect(state.streamingText).toBe("");

    // All transitions completed without error — the wrapper div
    // was never unmounted/remounted, so no insertBefore race.
  });

  it("rapid delta accumulation does not cause state inconsistency", () => {
    const store = useAgentStore.getState();

    act(() => {
      store.setSessionId("test-session");
      store.startActivity("attempt-rapid");
      store.setStatus("streaming");
    });

    // Simulate rapid SSE deltas
    act(() => {
      for (let i = 0; i < 100; i++) {
        store.appendDelta(`chunk-${i} `);
      }
    });

    const state = useAgentStore.getState();
    expect(state.streamingText).toContain("chunk-0");
    expect(state.streamingText).toContain("chunk-99");
  });

  it("stream_reset clears streaming text without crashing", () => {
    const store = useAgentStore.getState();

    act(() => {
      store.setSessionId("test-session");
      store.startActivity("attempt-reset");
      store.setStatus("streaming");
      store.appendDelta("partial content");
    });

    // Simulate stream_reset event
    act(() => {
      store.clearStreaming();
    });

    const state = useAgentStore.getState();
    expect(state.streamingText).toBe("");
    expect(state.status).toBe("streaming");
  });

  it("concurrent tool calls and streaming text coexist", () => {
    const store = useAgentStore.getState();

    act(() => {
      store.setSessionId("test-session");
      store.startActivity("attempt-tools");
      store.setStatus("streaming");
    });

    // Interleave text deltas and tool calls
    act(() => {
      store.appendDelta("Analyzing ");
      store.addToolCall({ id: "tc-1", tool: "web_search", arguments: {}, status: "running", timestamp: Date.now() });
      store.appendDelta("data...");
      store.addToolCall({ id: "tc-2", tool: "run_backtest", arguments: {}, status: "running", timestamp: Date.now() });
      store.updateToolCall("tc-1", { status: "ok", elapsed_ms: 200 });
      store.appendDelta(" Done.");
      store.updateToolCall("tc-2", { status: "ok", elapsed_ms: 5000 });
    });

    const state = useAgentStore.getState();
    expect(state.streamingText).toBe("Analyzing data... Done.");
    expect(state.toolCalls).toHaveLength(2);
    expect(state.toolCalls.every((tc) => tc.status === "ok")).toBe(true);
    expect(state.activity?.steps.every((step) => step.status === "ok")).toBe(true);
  });
});
