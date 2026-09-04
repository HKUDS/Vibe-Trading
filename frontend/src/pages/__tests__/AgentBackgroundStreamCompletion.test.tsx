import { act, render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

// Regression test for: a session's sidebar "thinking" spinner (driven by
// streamingSessionId) never clears once you navigate away from it mid-turn,
// even long after that turn actually finishes. The SSE stream for a
// backgrounded session is torn down the moment you switch away
// (doDisconnect() in the session-switch effect), so the session_completed
// event that would normally clear streamingSessionId never arrives. Reopening
// that session must reconcile the marker against its now-committed history
// instead of leaving it stuck for the rest of the tab's life.

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

function storedReply(sessionId: string) {
  return {
    message_id: `${sessionId}-reply`,
    session_id: sessionId,
    role: "assistant" as const,
    content: "done",
    created_at: "2026-08-01T00:00:00Z",
    linked_attempt_id: `${sessionId}-attempt`,
    tool_trail: [],
    metadata: {},
  };
}

function storedPrompt(sessionId: string) {
  return {
    message_id: `${sessionId}-prompt`,
    session_id: sessionId,
    role: "user" as const,
    content: "still working on it",
    created_at: "2026-08-01T00:00:00Z",
    linked_attempt_id: null,
    tool_trail: [],
    metadata: null,
  };
}

describe("Agent background stream completion reconciliation", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    apiMock.getGoal.mockResolvedValue(null);
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

  it("clears a background session's stale streamingSessionId once its reply is committed", async () => {
    apiMock.getSessionMessages.mockImplementation((sid: string) => (
      sid === "session-bg" ? Promise.resolve([storedReply(sid)]) : Promise.resolve([])
    ));

    const router = createMemoryRouter(
      [{ path: "/", element: <Agent /> }],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getSessionMessages).toHaveBeenCalledWith("session-one"));

    // Simulate: session-bg was mid-turn when the user navigated away from it earlier.
    act(() => {
      useAgentStore.setState({ streamingSessionId: "session-bg" });
    });

    await act(async () => {
      await router.navigate("/?session=session-bg");
    });

    await waitFor(() => {
      expect(useAgentStore.getState().streamingSessionId).toBeNull();
    });
  });

  it("leaves streamingSessionId alone when the background session genuinely has no reply yet", async () => {
    apiMock.getSessionMessages.mockImplementation((sid: string) => (
      sid === "session-bg" ? Promise.resolve([storedPrompt(sid)]) : Promise.resolve([])
    ));

    const router = createMemoryRouter(
      [{ path: "/", element: <Agent /> }],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getSessionMessages).toHaveBeenCalledWith("session-one"));

    act(() => {
      useAgentStore.setState({ streamingSessionId: "session-bg" });
    });

    await act(async () => {
      await router.navigate("/?session=session-bg");
    });

    await waitFor(() => {
      expect(apiMock.getSessionMessages).toHaveBeenCalledWith("session-bg");
    });
    expect(useAgentStore.getState().streamingSessionId).toBe("session-bg");
  });
});
