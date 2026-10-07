import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
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

  describe("history scroll lifecycle", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => {
      cleanup();
      vi.useRealTimers();
    });

    async function mountSession() {
      const router = createMemoryRouter(
        [{ path: "/", element: <Agent /> }],
        { initialEntries: ["/?session=session-one"] },
      );
      let view!: ReturnType<typeof render>;
      await act(async () => {
        view = render(<RouterProvider router={router} />);
      });
      return { ...view, router };
    }

    it("still scrolls after a mounted session finishes loading", async () => {
      const raf = vi.spyOn(window, "requestAnimationFrame");
      await mountSession();
      raf.mockClear();

      await act(async () => { await vi.advanceTimersByTimeAsync(50); });

      expect(raf).toHaveBeenCalled();
    });

    it("cancels the loaded history scroll when the page unmounts", async () => {
      const raf = vi.spyOn(window, "requestAnimationFrame");
      const view = await mountSession();
      view.unmount();
      raf.mockClear();

      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      expect(raf).not.toHaveBeenCalled();
    });

    it("cancels the previous session scroll while the next history is pending", async () => {
      const next = deferred<ReturnType<typeof storedReply>[]>();
      apiMock.getSessionMessages.mockImplementation((sid: string) => (
        sid === "session-one" ? Promise.resolve([storedReply(sid)]) : next.promise
      ));
      const raf = vi.spyOn(window, "requestAnimationFrame");
      const { router } = await mountSession();
      await act(async () => { await router.navigate("/?session=session-two"); });
      raf.mockClear();

      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      expect(raf).not.toHaveBeenCalled();
    });

    it("ignores a history response that arrives after unmount", async () => {
      const pending = deferred<ReturnType<typeof storedReply>[]>();
      apiMock.getSessionMessages.mockReturnValue(pending.promise);
      const view = await mountSession();
      const messages = useAgentStore.getState().messages;
      view.unmount();

      await act(async () => {
        pending.resolve([storedReply("session-one")]);
        await vi.advanceTimersByTimeAsync(100);
      });

      expect(useAgentStore.getState().messages).toBe(messages);
    });

    it("cancels the cached history scroll when the page unmounts", async () => {
      useAgentStore.getState().cacheSession("session-one", [
        { id: "cached", type: "answer", content: "cached reply", timestamp: 1 },
      ]);
      apiMock.getSessionMessages.mockReturnValue(new Promise(() => {}));
      const raf = vi.spyOn(window, "requestAnimationFrame");
      const view = await mountSession();
      view.unmount();
      raf.mockClear();

      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      expect(raf).not.toHaveBeenCalled();
    });
  });
});
