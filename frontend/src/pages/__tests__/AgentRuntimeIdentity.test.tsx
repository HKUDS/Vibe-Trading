import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

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

vi.mock("@/components/chat/ModelRuntimeBar", () => ({
  ModelRuntimeBar: ({
    runtimeProvider,
    runtimeModel,
    runtimeReasoningEffort,
  }: {
    runtimeProvider?: string;
    runtimeModel?: string;
    runtimeReasoningEffort?: string;
  }) => (
    <output
      data-testid="runtime-identity"
      data-provider={runtimeProvider ?? ""}
      data-model={runtimeModel ?? ""}
      data-reasoning={runtimeReasoningEffort ?? ""}
    />
  ),
}));

function storedReply(sessionId: string) {
  return {
    message_id: `${sessionId}-reply`,
    session_id: sessionId,
    role: "assistant",
    content: "done",
    created_at: "2026-08-01T00:00:00Z",
    linked_attempt_id: `${sessionId}-attempt`,
    tool_trail: [],
    metadata: {
      provider: "deepseek",
      model: "deepseek-history-model",
      reasoning_effort: "high",
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function renderLoadedFirstSession() {
  const router = createMemoryRouter(
    [{ path: "/", element: <Agent /> }],
    { initialEntries: ["/?session=session-one"] },
  );
  render(<RouterProvider router={router} />);

  const identity = await screen.findByTestId("runtime-identity");
  await waitFor(() => {
    expect(identity).toHaveAttribute("data-provider", "deepseek");
    expect(identity).toHaveAttribute("data-model", "deepseek-history-model");
    expect(identity).toHaveAttribute("data-reasoning", "high");
  });
  return { router, identity };
}

describe("Agent runtime identity session transitions", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getLLMSettings.mockResolvedValue({
      provider: "openai",
      model_name: "current-settings-model",
      base_url: "https://api.openai.com/v1",
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
    apiMock.getSessionMessages.mockImplementation((sid: string) => (
      sid === "session-one" ? Promise.resolve([storedReply(sid)]) : Promise.resolve([])
    ));
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("hides the previous identity while the next session load is still pending", async () => {
    const slowLoad = deferred<ReturnType<typeof storedReply>[]>();
    apiMock.getSessionMessages.mockImplementation((sid: string) => (
      sid === "session-one" ? Promise.resolve([storedReply(sid)]) : slowLoad.promise
    ));
    const { router, identity } = await renderLoadedFirstSession();

    await act(async () => {
      await router.navigate("/?session=session-two");
    });

    await waitFor(() => {
      expect(identity).toHaveAttribute("data-provider", "");
      expect(identity).toHaveAttribute("data-model", "");
      expect(identity).toHaveAttribute("data-reasoning", "");
    });
  });

  it("keeps runtime identity clear when the next session load fails", async () => {
    const failedLoad = deferred<ReturnType<typeof storedReply>[]>();
    apiMock.getSessionMessages.mockImplementation((sid: string) => (
      sid === "session-one" ? Promise.resolve([storedReply(sid)]) : failedLoad.promise
    ));
    const { router, identity } = await renderLoadedFirstSession();

    await act(async () => {
      await router.navigate("/?session=session-two");
    });
    failedLoad.reject(new Error("session load failed"));

    await waitFor(() => {
      expect(identity).toHaveAttribute("data-provider", "");
      expect(identity).toHaveAttribute("data-model", "");
      expect(identity).toHaveAttribute("data-reasoning", "");
    });
  });
});
