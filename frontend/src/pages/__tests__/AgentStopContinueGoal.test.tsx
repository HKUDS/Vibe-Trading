import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

// Stopping a turn must not leave swarm events ignored for the next turn. A
// goal continuation starts a new turn without going through runPrompt, so it
// has to clear the stopped flag too.

const apiMock = vi.hoisted(() => ({
  cancelSession: vi.fn(),
  getGoal: vi.fn(),
  getLLMSettings: vi.fn(),
  getRunPreview: vi.fn(),
  getSessionMessages: vi.fn(),
  sendMessage: vi.fn(),
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

const goalSnapshot = {
  goal: {
    goal_id: "goal-1",
    objective: "Research 02285",
    status: "active",
    criteria: [],
    token_budget: null,
    turn_budget: null,
    time_budget_seconds: null,
    created_at: 0,
    updated_at: 0,
  },
  claims: [],
  criteria: [],
  evidence: [],
  evidence_count: 0,
};

describe("Agent stop then continue goal", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    sseMock.connect.mockClear();
    apiMock.cancelSession.mockResolvedValue({ status: "cancelled" });
    apiMock.getGoal.mockResolvedValue(goalSnapshot);
    apiMock.getLLMSettings.mockResolvedValue({
      provider: "opencode",
      model_name: "m",
      providers: [{ name: "opencode", label: "OpenCode" }],
    });
    apiMock.getRunPreview.mockResolvedValue(null);
    apiMock.getSessionMessages.mockResolvedValue([]);
    apiMock.sendMessage.mockResolvedValue({ message_id: "m1", attempt_id: "a2" });
  });

  it("re-enables streaming from swarm events after continuing a goal that was stopped", async () => {
    const router = createMemoryRouter(
      [{ path: "/", element: <Agent /> }],
      { initialEntries: ["/?session=session-one"] },
    );
    render(<RouterProvider router={router} />);
    await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());
    await waitFor(() => expect(apiMock.getGoal).toHaveBeenCalled());

    act(() => {
      latestHandlers()["attempt.started"]({ attempt_id: "a1" });
    });
    expect(useAgentStore.getState().status).toBe("streaming");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(apiMock.cancelSession).toHaveBeenCalled());
    await waitFor(() => expect(useAgentStore.getState().status).toBe("idle"));

    fireEvent.click(await screen.findByRole("button", { name: "Active research goal" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await waitFor(() => expect(apiMock.sendMessage).toHaveBeenCalled());
    expect(String(apiMock.sendMessage.mock.calls[0][1])).toMatch(/^Continue the active research goal\./);
    expect(useAgentStore.getState().status).toBe("streaming");

    act(() => {
      useAgentStore.getState().setStatus("idle");
      latestHandlers()["swarm.event"]({
        run_id: "run-1",
        event: { type: "run_started", data: {}, timestamp: "2026-10-26T03:00:00Z" },
      });
    });
    expect(useAgentStore.getState().status).toBe("streaming");
  });
});
