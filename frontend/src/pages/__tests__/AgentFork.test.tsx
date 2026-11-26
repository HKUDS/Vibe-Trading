import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";
import { useSessionsStore } from "@/stores/sessions";
import i18n from "@/i18n";

const apiMock = vi.hoisted(() => ({
  autoTitleSession: vi.fn(),
  cancelSession: vi.fn(),
  forkSession: vi.fn(),
  getGoal: vi.fn(),
  getLLMSettings: vi.fn(),
  getRunPreview: vi.fn(),
  getRunPine: vi.fn(),
  getSessionMessages: vi.fn(),
  sseUrl: vi.fn((sid: string) => `/sessions/${sid}/events`),
  uploadFile: vi.fn(),
}));

const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

vi.mock("sonner", () => ({ toast: toastMock }));

const sseMock = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
  onStatusChange: vi.fn(),
}));

vi.mock("@/hooks/useSSE", () => ({
  useSSE: () => sseMock,
}));

const sourceSession = { session_id: "source", title: "NVDA research" };
const childSession = {
  session_id: "child",
  title: "NVDA research",
  forked_from_session_id: "source",
  forked_from_message_id: "answer-1",
};

function sourceMessages(status = "completed") {
  return [
    {
      message_id: "question-1",
      session_id: "source",
      role: "user",
      content: "Research NVDA",
      created_at: "2026-11-25T10:00:00Z",
    },
    {
      message_id: "answer-1",
      session_id: "source",
      role: "assistant",
      content: "NVDA analysis",
      created_at: "2026-11-25T10:01:00Z",
      linked_attempt_id: "attempt-1",
      can_fork: status === "completed",
      metadata: { status },
      tool_trail: [],
    },
  ];
}

function renderAgent() {
  const router = createMemoryRouter(
    [{ path: "/agent", element: <Agent /> }],
    { initialEntries: ["/agent?session=source"] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

type Handlers = Record<string, (data: Record<string, unknown>) => void>;

function latestHandlers(): Handlers {
  const call = sseMock.connect.mock.calls.at(-1);
  if (!call) throw new Error("useSSE.connect was never called");
  return call[1] as Handlers;
}

describe("Agent conversation Fork", () => {
  beforeAll(async () => {
    await i18n.changeLanguage("en");
  });

  beforeEach(() => {
    useAgentStore.getState().reset();
    useSessionsStore.getState().reset();
    useSessionsStore.getState().upsert(sourceSession);
    apiMock.autoTitleSession.mockReset().mockResolvedValue({ status: "updated" });
    apiMock.cancelSession.mockReset();
    apiMock.forkSession.mockReset().mockResolvedValue(childSession);
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getLLMSettings.mockResolvedValue({ sse_timeout_seconds: 90, providers: [] });
    apiMock.getRunPreview.mockReset().mockResolvedValue(null);
    apiMock.getRunPine.mockReset().mockResolvedValue({ exists: false });
    apiMock.getSessionMessages.mockReset().mockImplementation(async () => sourceMessages());
    apiMock.uploadFile.mockReset().mockResolvedValue({
      status: "ok",
      filename: "source.csv",
      file_path: "uploads/source.csv",
    });
    toastMock.error.mockReset();
    toastMock.success.mockReset();
    toastMock.warning.mockReset();
    sseMock.connect.mockClear();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it.each([
    { kind: "text answer", summary: "Live completed answer", preview: null },
    {
      kind: "run-only answer",
      summary: "",
      preview: { metrics: { sharpe: 1.25 }, equity_curve: [], report_worthy: true },
    },
  ])("offers Fork on a newly completed $kind using its persisted message id", async ({ summary, preview }) => {
    apiMock.getSessionMessages.mockResolvedValue([]);
    apiMock.getRunPreview.mockResolvedValue(preview);
    renderAgent();
    await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());

    await act(async () => {
      await latestHandlers()["attempt.completed"]({
        attempt_id: "live-attempt",
        message_id: "live-message",
        status: "completed",
        summary,
        run_dir: preview ? "/tmp/runs/live-run" : undefined,
      });
    });

    fireEvent.click(await screen.findByRole("button", { name: "Fork" }));
    expect(apiMock.forkSession).toHaveBeenCalledWith("source", "live-message");
  });

  it("opens the child with a blank draft and restores the source draft on return", async () => {
    const router = renderAgent();
    await screen.findByText("NVDA analysis");
    const composer = screen.getByRole("textbox");
    await userEvent.setup().type(composer, "Keep this draft in the source");

    await userEvent.setup().click(screen.getByRole("button", { name: "Fork" }));

    await waitFor(() => expect(apiMock.forkSession).toHaveBeenCalledWith("source", "answer-1"));
    await waitFor(() => expect(router.state.location.search).toBe("?session=child"));
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
    expect(screen.getByText("Forked from NVDA research")).toBeInTheDocument();
    expect(useSessionsStore.getState().has("child")).toBe(true);

    await userEvent.setup().click(screen.getByRole("link", { name: "View original" }));
    await waitFor(() => expect(router.state.location.search).toBe("?session=source"));
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue("Keep this draft in the source"));
  });

  it.each([
    { mode: "goal", menuItem: "Research Goal", chip: "New Research Goal" },
    { mode: "swarm", menuItem: "Agent Swarm", chip: "Agent Swarm" },
  ])("keeps the $mode composer mode out of the child and restores it on return", async ({ menuItem, chip }) => {
    const router = renderAgent();
    await screen.findByText("NVDA analysis");
    await userEvent.setup().click(screen.getByTitle("More options"));
    await userEvent.setup().click(screen.getByRole("menuitem", { name: menuItem }));
    expect(screen.getByText(chip)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Fork" }));

    await screen.findByText("Forked from NVDA research");
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.queryByText(chip)).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("link", { name: "View original" }));
    await waitFor(() => expect(router.state.location.search).toBe("?session=source"));
    expect(await screen.findByText(chip)).toBeInTheDocument();
  });

  it.each(["failed", "cancelled", "streaming", "running", "interrupted", "waiting_user", "pending"])(
    "does not offer Fork for a %s assistant turn",
    async (status) => {
      apiMock.getSessionMessages.mockResolvedValue(sourceMessages(status));
      renderAgent();

      await screen.findByText("NVDA analysis");
      expect(screen.queryByRole("button", { name: "Fork" })).not.toBeInTheDocument();
    },
  );

  it("does not offer Fork when the backend marks a completed-looking turn ineligible", async () => {
    const messages = sourceMessages();
    messages[1].can_fork = false;
    delete messages[1].linked_attempt_id;
    (messages[1].metadata as Record<string, unknown>).run_id = "orphan-run";
    apiMock.getSessionMessages.mockResolvedValue(messages);
    renderAgent();

    await screen.findByText("NVDA analysis");
    expect(screen.queryByRole("button", { name: "Fork" })).not.toBeInTheDocument();
  });

  it.each(["streaming", "partial", "in_progress", "failed", "cancelled", "interrupted"])(
    "does not offer Fork when a completed turn is marked %s",
    async (flag) => {
      const messages = sourceMessages();
      messages[1].can_fork = false;
      (messages[1].metadata as Record<string, unknown>)[flag] = true;
      apiMock.getSessionMessages.mockResolvedValue(messages);
      renderAgent();

      await screen.findByText("NVDA analysis");
      expect(screen.queryByRole("button", { name: "Fork" })).not.toBeInTheDocument();
    },
  );

  it("waits for source attachments to finish uploading before forking", async () => {
    apiMock.uploadFile.mockReturnValue(new Promise(() => {}));
    renderAgent();
    await screen.findByText("NVDA analysis");
    const form = screen.getByRole("textbox").closest("form");
    expect(form).not.toBeNull();

    fireEvent.drop(form!, {
      dataTransfer: { files: [new File(["data"], "source.csv", { type: "text/csv" })], types: ["Files"] },
    });
    expect(apiMock.uploadFile).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Fork" }));

    expect(toastMock.warning).toHaveBeenCalledWith("Wait for attachments to finish uploading before forking.");
    expect(apiMock.forkSession).not.toHaveBeenCalled();
  });

  it.each(["", "Strategy execution completed."])(
    "offers Fork on a completed run-only answer with content %j",
    async (content) => {
      const messages = sourceMessages();
      messages[1].content = content;
      (messages[1].metadata as Record<string, unknown>).run_id = "run-1";
      apiMock.getSessionMessages.mockResolvedValue(messages);
      renderAgent();

      await waitFor(() => {
        fireEvent.click(screen.getByRole("button", { name: "Fork" }));
        expect(apiMock.forkSession).toHaveBeenCalledWith("source", "answer-1");
      });
    },
  );

  it("keeps the source active and navigates after a successful Fork", async () => {
    const router = renderAgent();
    await screen.findByText("NVDA analysis");
    useAgentStore.getState().setStatus("streaming");

    await userEvent.setup().click(screen.getByRole("button", { name: "Fork" }));

    await waitFor(() => expect(router.state.location.search).toBe("?session=child"));
    expect(apiMock.cancelSession).not.toHaveBeenCalled();
  });

  it("keeps the current session and surfaces the error when Fork fails", async () => {
    apiMock.forkSession.mockRejectedValue(new Error("Fork failed"));
    const router = renderAgent();
    await screen.findByText("NVDA analysis");

    await userEvent.setup().click(screen.getByRole("button", { name: "Fork" }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith("Fork failed"));
    expect(router.state.location.search).toBe("?session=source");
  });
});
