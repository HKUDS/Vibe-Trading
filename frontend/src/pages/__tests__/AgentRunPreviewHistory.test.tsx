import { render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

// Every assistant turn owns a run directory, so history loading asks the
// preview endpoint which of them deserve a run card.

const apiMock = vi.hoisted(() => ({
  getGoal: vi.fn(),
  getLLMSettings: vi.fn(),
  getRunPreview: vi.fn(),
  getSessionMessages: vi.fn(),
  sseUrl: vi.fn((sid: string) => `/sessions/${sid}/events`),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

const sseMock = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
  onStatusChange: vi.fn(),
}));

vi.mock("@/hooks/useSSE", () => ({
  useSSE: () => sseMock,
}));

function assistant(id: string, runId: string, minute: number) {
  return {
    message_id: id,
    role: "assistant",
    content: `reply ${id}`,
    created_at: `2025-01-01T00:${String(minute).padStart(2, "0")}:00Z`,
    metadata: { run_id: runId, status: "completed" },
  };
}

function runCards() {
  return useAgentStore.getState().messages.filter((m) => m.type === "run_complete");
}

// Each case uses its own session: the agent store keeps a module-level cache
// of past sessions that reset() does not clear.
function renderAgentAt(sessionId: string) {
  const router = createMemoryRouter(
    [{ path: "/", element: <Agent /> }],
    { initialEntries: [`/?session=${sessionId}`] },
  );
  render(<RouterProvider router={router} />);
}

describe("Agent history run previews", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getLLMSettings.mockResolvedValue({ sse_timeout_seconds: 90 });
    apiMock.getRunPreview.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  });

  it("cards only report-worthy or unknown runs and asks once per run", async () => {
    apiMock.getSessionMessages.mockResolvedValue([
      assistant("m1", "run-chat", 1),
      assistant("m2", "run-backtest", 2),
      assistant("m3", "run-backtest", 3),
      assistant("m4", "run-broken", 4),
    ]);
    apiMock.getRunPreview.mockImplementation(async (runId: string) => {
      if (runId === "run-chat") return { metrics: null, equity_curve: [], report_worthy: false };
      if (runId === "run-backtest") {
        return {
          metrics: { final_value: 110 },
          equity_curve: [{ time: "2025-01-01", equity: "100", drawdown: "0" }],
          report_worthy: true,
        };
      }
      throw new Error("network");
    });

    renderAgentAt("session-one");

    await waitFor(() => expect(runCards()).toHaveLength(3));
    expect(runCards().map((m) => m.runId)).toEqual(["run-backtest", "run-backtest", "run-broken"]);
    expect(runCards()[0].equityCurve).toEqual([{ time: "2025-01-01", equity: 100 }]);
    expect(runCards()[2].metrics).toBeUndefined();
    expect(apiMock.getRunPreview.mock.calls.map(([id]) => id).sort()).toEqual(
      ["run-backtest", "run-broken", "run-chat"],
    );
  });

  it("requests every preview before any of them answers", async () => {
    apiMock.getSessionMessages.mockResolvedValue([
      assistant("m1", "run-a", 1),
      assistant("m2", "run-b", 2),
      assistant("m3", "run-c", 3),
    ]);
    apiMock.getRunPreview.mockImplementation(() => new Promise(() => {}));

    renderAgentAt("session-two");

    await waitFor(() => expect(apiMock.getRunPreview).toHaveBeenCalledTimes(3));
  });
});
