import { act, render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

// Regression test for: the "Working · 51s · 12 steps" elapsed clock restarting
// at 0s when the user navigates to another tab (Runtime, Scheduled, …) and
// back while an attempt is still running. The same-session re-hydrate path
// (#229) resets the live activity so SSE replay can rebuild its steps, but the
// attempt's start time is not recoverable from replay once the ring buffer has
// rotated past `attempt.started`, so it must survive the reset. Independently,
// a replayed `attempt.started` now carries the backend's wall-clock start so a
// fresh client resumes the clock from the real start rather than from now.

const apiMock = vi.hoisted(() => ({
  getGoal: vi.fn(),
  getLLMSettings: vi.fn(),
  getRun: vi.fn(),
  getSessionMessages: vi.fn(),
  sseUrl: vi.fn((sid: string) => `/sessions/${sid}/events`),
}));

const sseMock = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
  onStatusChange: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

vi.mock("@/hooks/useSSE", () => ({
  useSSE: () => sseMock,
}));

type Handlers = Record<string, (data: Record<string, unknown>) => void>;

function latestHandlers(): Handlers {
  const call = sseMock.connect.mock.calls.at(-1);
  if (!call) throw new Error("useSSE.connect was never called");
  return call[1] as Handlers;
}

describe("Agent activity elapsed clock survives navigation", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    sseMock.connect.mockClear();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getSessionMessages.mockResolvedValue([]);
    apiMock.getLLMSettings.mockResolvedValue({
      provider: "deepseek",
      model_name: "deepseek-v4-pro",
      base_url: "https://api.deepseek.com/v1",
      api_key_configured: true,
      api_key_required: true,
      temperature: 0,
      timeout_seconds: 120,
      max_retries: 2,
      reasoning_effort: "low",
      sse_timeout_seconds: 90,
      env_path: "agent/.env",
      providers: [],
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("keeps the running attempt's startedAt when leaving the page and coming back", async () => {
    const router = createMemoryRouter(
      [
        { path: "/", element: <Agent /> },
        { path: "/runtime", element: <div>runtime</div> },
      ],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getSessionMessages).toHaveBeenCalledWith("session-one"));

    // An attempt has been running for a while on this session.
    const originalStart = Date.now() - 51_000;
    act(() => {
      const store = useAgentStore.getState();
      store.startActivity("attempt-1", originalStart);
      store.setActivityState("working");
      store.setStatus("streaming");
    });

    // Navigate to another tab (unmounts Agent, tears down SSE) and back.
    await act(async () => {
      await router.navigate("/runtime");
    });
    await act(async () => {
      await router.navigate("/?session=session-one");
    });

    await waitFor(() => {
      expect(sseMock.connect.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    const activity = useAgentStore.getState().activity;
    expect(activity).not.toBeNull();
    expect(activity?.attemptId).toBe("attempt-1");
    expect(activity?.startedAt).toBe(originalStart);
    expect(activity?.endedAt).toBeUndefined();

    // The replayed attempt.started for the same attempt must not restart the clock.
    act(() => {
      latestHandlers()["attempt.started"]({ attempt_id: "attempt-1" });
    });
    expect(useAgentStore.getState().activity?.startedAt).toBe(originalStart);
  });

  it("does not resurrect an activity that had already finished", async () => {
    const router = createMemoryRouter(
      [
        { path: "/", element: <Agent /> },
        { path: "/runtime", element: <div>runtime</div> },
      ],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getSessionMessages).toHaveBeenCalledWith("session-one"));

    act(() => {
      const store = useAgentStore.getState();
      store.startActivity("attempt-done", Date.now() - 5_000);
      store.setActivityState("done", Date.now() - 1_000);
    });

    await act(async () => {
      await router.navigate("/runtime");
    });
    await act(async () => {
      await router.navigate("/?session=session-one");
    });

    await waitFor(() => {
      expect(sseMock.connect.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(useAgentStore.getState().activity).toBeNull();
  });

  it("starts the clock from the backend's started_at on a fresh attempt.started", async () => {
    const router = createMemoryRouter(
      [{ path: "/", element: <Agent /> }],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());

    const startedAtSec = Math.floor(Date.now() / 1000) - 51;
    act(() => {
      latestHandlers()["attempt.started"]({ attempt_id: "attempt-2", started_at: startedAtSec });
    });

    const activity = useAgentStore.getState().activity;
    expect(activity?.attemptId).toBe("attempt-2");
    expect(activity?.startedAt).toBe(startedAtSec * 1000);
  });

  it("falls back to now when attempt.started carries no started_at", async () => {
    const router = createMemoryRouter(
      [{ path: "/", element: <Agent /> }],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());

    const before = Date.now();
    act(() => {
      latestHandlers()["attempt.started"]({ attempt_id: "attempt-3" });
    });
    const startedAt = useAgentStore.getState().activity?.startedAt ?? 0;
    expect(startedAt).toBeGreaterThanOrEqual(before);
    expect(startedAt).toBeLessThanOrEqual(Date.now());
  });
});

describe("Agent activity finished while the page was away", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    sseMock.connect.mockClear();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getRun.mockResolvedValue({});
    apiMock.getLLMSettings.mockResolvedValue({
      provider: "deepseek",
      model_name: "deepseek-v4-pro",
      base_url: "https://api.deepseek.com/v1",
      api_key_configured: true,
      api_key_required: true,
      temperature: 0,
      timeout_seconds: 120,
      max_retries: 2,
      reasoning_effort: "low",
      sse_timeout_seconds: 90,
      env_path: "agent/.env",
      providers: [],
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("replaces the carried live activity with the committed row and keeps the real duration", async () => {
    const startedAtMs = Date.UTC(2026, 7, 1, 0, 0, 0);
    const endedAtMs = startedAtMs + 8_000;
    let committed = false;
    apiMock.getSessionMessages.mockImplementation(() => Promise.resolve(
      committed
        ? [
          {
            message_id: "m-prompt",
            session_id: "session-one",
            role: "user" as const,
            content: "read the snapshot",
            created_at: new Date(startedAtMs - 1_000).toISOString(),
            linked_attempt_id: null,
            tool_trail: [],
            metadata: null,
          },
          {
            message_id: "m-reply",
            session_id: "session-one",
            role: "assistant" as const,
            content: "done",
            created_at: new Date(endedAtMs).toISOString(),
            linked_attempt_id: "attempt-1",
            // The only tool ran 5s in, for 80ms: without the attempt start the
            // row would read 80ms instead of 8s.
            tool_trail: [
              { tool: "read_document", status: "ok" as const, elapsed_ms: 80, timestamp: startedAtMs + 5_000 },
            ],
            metadata: { status: "completed", elapsed_ms: 8_000, started_at: startedAtMs / 1000 },
          },
        ]
        : [],
    ));

    const router = createMemoryRouter(
      [
        { path: "/", element: <Agent /> },
        { path: "/runtime", element: <div>runtime</div> },
      ],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getSessionMessages).toHaveBeenCalledWith("session-one"));

    act(() => {
      const store = useAgentStore.getState();
      store.startActivity("attempt-1", startedAtMs);
      store.setActivityState("working");
      store.setStatus("streaming");
    });

    await act(async () => {
      await router.navigate("/runtime");
    });
    committed = true; // the attempt completed while we were on another tab
    await act(async () => {
      await router.navigate("/?session=session-one");
    });

    await waitFor(() => {
      expect(useAgentStore.getState().activity).toBeNull();
    });
    const state = useAgentStore.getState();
    expect(state.status).toBe("idle");
    const rows = state.messages.filter((m) => m.meta?.activity?.attemptId === "attempt-1");
    expect(rows).toHaveLength(1);
    expect(rows[0].meta?.activity).toMatchObject({
      state: "done",
      startedAt: startedAtMs,
      endedAt: endedAtMs,
    });
  });
});

describe("Agent completion trusts the backend's attempt start", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    sseMock.connect.mockClear();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getRun.mockResolvedValue({});
    apiMock.getSessionMessages.mockResolvedValue([]);
    apiMock.getLLMSettings.mockResolvedValue({
      provider: "deepseek",
      model_name: "deepseek-v4-pro",
      base_url: "https://api.deepseek.com/v1",
      api_key_configured: true,
      api_key_required: true,
      temperature: 0,
      timeout_seconds: 120,
      max_retries: 2,
      reasoning_effort: "low",
      sse_timeout_seconds: 90,
      env_path: "agent/.env",
      providers: [],
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("backdates a late-joined live activity to the backend start when the attempt completes", async () => {
    const router = createMemoryRouter(
      [{ path: "/", element: <Agent /> }],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());

    // We joined 47s into a run whose attempt.started had already rotated out
    // of the ring buffer: the first replayed event was a tool call, so the
    // live clock started late.
    const backendStartSec = Math.floor(Date.now() / 1000) - 165;
    const lateJoinMs = (backendStartSec + 47) * 1000;
    act(() => {
      const store = useAgentStore.getState();
      store.startActivity("attempt-late", lateJoinMs);
      store.setActivityState("working");
      store.setStatus("streaming");
    });

    const endedSec = backendStartSec + 165;
    await act(async () => {
      latestHandlers()["attempt.completed"]({
        attempt_id: "attempt-late",
        status: "completed",
        summary: "done",
        started_at: backendStartSec,
        ended_at: endedSec,
        elapsed_ms: 165_000,
      });
    });

    await waitFor(() => {
      expect(useAgentStore.getState().activity).toBeNull();
    });
    const row = useAgentStore.getState().messages.find(
      (m) => m.meta?.activity?.attemptId === "attempt-late",
    );
    expect(row?.meta?.activity).toMatchObject({
      state: "done",
      startedAt: backendStartSec * 1000,
      endedAt: endedSec * 1000,
    });
  });
});
