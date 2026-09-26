import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

// While the grounding gate holds a rejected draft back, the answer text is
// buffered server-side and nothing streams for up to a few minutes. The
// backend announces that window with `grounding_status`; the chat shows one
// status line for it and drops the line the moment the answer text arrives.

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

const STATUS_TEXT = /Checking the figures in this answer/;

async function renderStreamingAttempt(attemptId: string): Promise<void> {
  const router = createMemoryRouter(
    [{ path: "/", element: <Agent /> }],
    { initialEntries: ["/?session=session-one"] },
  );
  render(<RouterProvider router={router} />);
  await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());
  act(() => {
    latestHandlers()["attempt.started"]({ attempt_id: attemptId });
  });
  expect(useAgentStore.getState().status).toBe("streaming");
}

describe("Agent grounding status line", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    sseMock.connect.mockClear();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getRun.mockResolvedValue({});
    apiMock.getSessionMessages.mockResolvedValue([]);
    apiMock.getLLMSettings.mockResolvedValue({
      provider: "deepseek",
      model_name: "deepseek-flash",
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

  it("shows the revision round and clears it when the answer text arrives", async () => {
    await renderStreamingAttempt("attempt-1");
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();

    act(() => {
      latestHandlers().grounding_status({
        attempt_id: "attempt-1",
        stage: "revising",
        round: 2,
        issues: 3,
      });
    });
    expect(
      screen.getByText("Checking the figures in this answer (round 2)…"),
    ).toBeInTheDocument();

    act(() => {
      latestHandlers().text_delta({ attempt_id: "attempt-1", delta: "Verified answer", iter: 6 });
    });
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();
  });

  it("follows the round number of the latest revising event", async () => {
    await renderStreamingAttempt("attempt-1");

    act(() => {
      latestHandlers().grounding_status({ attempt_id: "attempt-1", stage: "revising", round: 1, issues: 1 });
    });
    expect(screen.getByText("Checking the figures in this answer (round 1)…")).toBeInTheDocument();

    act(() => {
      latestHandlers().grounding_status({ attempt_id: "attempt-1", stage: "revising", round: 3, issues: 1 });
    });
    expect(screen.getByText("Checking the figures in this answer (round 3)…")).toBeInTheDocument();
    expect(screen.getAllByText(STATUS_TEXT)).toHaveLength(1);
  });

  it("clears on released_redacted before the redacted answer streams", async () => {
    await renderStreamingAttempt("attempt-1");

    act(() => {
      latestHandlers().grounding_status({ attempt_id: "attempt-1", stage: "revising", round: 1, issues: 2 });
    });
    expect(screen.getByText(STATUS_TEXT)).toBeInTheDocument();

    act(() => {
      latestHandlers().grounding_status({ attempt_id: "attempt-1", stage: "released_redacted", removed: 2 });
    });
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();
    expect(useAgentStore.getState().status).toBe("streaming");
  });

  it("does not carry a failed attempt's status line into the next attempt", async () => {
    await renderStreamingAttempt("attempt-1");

    act(() => {
      latestHandlers().grounding_status({ attempt_id: "attempt-1", stage: "revising", round: 1, issues: 2 });
    });
    expect(screen.getByText(STATUS_TEXT)).toBeInTheDocument();

    act(() => {
      latestHandlers()["attempt.failed"]({ attempt_id: "attempt-1", error: "provider down" });
    });
    expect(useAgentStore.getState().status).toBe("idle");
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();

    act(() => {
      latestHandlers()["attempt.started"]({ attempt_id: "attempt-2" });
    });
    expect(useAgentStore.getState().status).toBe("streaming");
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();
  });

  it("steps aside when a recovery round starts a tool call", async () => {
    await renderStreamingAttempt("attempt-1");

    act(() => {
      latestHandlers().grounding_status({ attempt_id: "attempt-1", stage: "revising", round: 1, issues: 2 });
    });
    expect(screen.getByText("Checking the figures in this answer (round 1)…")).toBeInTheDocument();

    act(() => {
      latestHandlers().tool_call({
        attempt_id: "attempt-1",
        tool: "get_market_data",
        call_id: "call-recovery",
        arguments: { codes: ["159516.SZ"] },
      });
    });
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();
  });

});
