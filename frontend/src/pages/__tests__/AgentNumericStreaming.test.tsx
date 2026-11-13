import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

const apiMock = vi.hoisted(() => ({
  getGoal: vi.fn(),
  getLLMSettings: vi.fn(),
  getRunPreview: vi.fn(),
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

describe("Agent numeric streaming", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    sseMock.connect.mockClear();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getRunPreview.mockResolvedValue({ metrics: null, equity_curve: [], report_worthy: false });
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

  it("shows numbers and dates immediately without a checking gate", async () => {
    await renderStreamingAttempt("attempt-1");
    expect(latestHandlers().grounding_status).toBeUndefined();
    act(() => {
      latestHandlers().text_delta({ attempt_id: "attempt-1", delta: "On Oct 13, revenue was USD 96.22B; growth 13%." });
    });
    await waitFor(() => expect(screen.getByText(/On Oct 13, revenue was USD 96.22B; growth 13%/)).toBeInTheDocument());
    expect(screen.queryByText(STATUS_TEXT)).not.toBeInTheDocument();
  });
});
