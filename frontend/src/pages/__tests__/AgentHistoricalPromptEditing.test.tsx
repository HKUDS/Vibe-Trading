import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";
import { ApiError } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  editMessageAndRegenerate: vi.fn(),
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

function message(id: string, role: "user" | "assistant", content: string, minute: number) {
  return {
    message_id: id,
    session_id: "session-edit",
    role,
    content,
    created_at: `2025-01-01T00:${String(minute).padStart(2, "0")}:00Z`,
  };
}

function renderAgent() {
  const router = createMemoryRouter(
    [{ path: "/", element: <Agent /> }],
    { initialEntries: ["/?session=session-edit"] },
  );
  render(<RouterProvider router={router} />);
}

describe("Agent historical prompt editing", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getLLMSettings.mockResolvedValue({
      sse_timeout_seconds: 90,
      provider: "",
      providers: [],
      model_name: "",
      reasoning_effort: null,
    });
    apiMock.getRunPreview.mockResolvedValue(null);
    apiMock.getSessionMessages.mockReset();
    apiMock.editMessageAndRegenerate.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  });

  it("edits a middle prompt, preserves its attachment envelope, and removes the suffix", async () => {
    const user = userEvent.setup();
    const rawPrompt = '[Uploaded files: [{"filename":"positions.csv","path":"/tmp/uploads/positions.csv"}]]\n\nCompare the portfolios';
    const initial = [
      message("a1b2c3d4e5f6", "user", "First prompt", 1),
      message("a1b2c3d4e5f7", "assistant", "First answer", 2),
      message("a1b2c3d4e5f8", "user", rawPrompt, 3),
      message("a1b2c3d4e5f9", "assistant", "Old answer", 4),
      message("a1b2c3d4e5fa", "user", "Later prompt", 5),
      message("a1b2c3d4e5fb", "assistant", "Later answer", 6),
    ];
    const retained = initial.slice(0, 3);
    retained[2] = message(
      "a1b2c3d4e5f8",
      "user",
      '[Uploaded files: [{"filename":"positions.csv","path":"/tmp/uploads/positions.csv"}]]\n\nCompare drawdowns instead',
      3,
    );
    apiMock.getSessionMessages
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(retained)
      .mockResolvedValue([
        ...retained,
        { ...message("a1b2c3d4e5fc", "assistant", "Regenerated answer", 7), linked_attempt_id: "attempt-new" },
      ]);
    apiMock.editMessageAndRegenerate.mockResolvedValue({
      message_id: "a1b2c3d4e5f8",
      attempt_id: "attempt-new",
    });
    useAgentStore.setState({
      swarmRuns: {
        "swarm-before": {
          runId: "swarm-before", preset: "before", status: "completed",
          currentLayer: 0, totalLayers: 0, startedAt: 0, agents: [],
        },
        "swarm-after": {
          runId: "swarm-after", preset: "after", status: "completed",
          currentLayer: 0, totalLayers: 0, startedAt: 0, agents: [],
        },
      },
      messages: [
        {
          id: "swarm_swarm-before", type: "swarm_status", content: "",
          swarmRunId: "swarm-before", timestamp: Date.parse("2025-01-01T00:02:00Z"),
        },
        {
          id: "swarm_swarm-after", type: "swarm_status", content: "",
          swarmRunId: "swarm-after", timestamp: Date.parse("2025-01-01T00:05:00Z"),
        },
      ],
    });
    useAgentStore.getState().cacheSession("session-edit", useAgentStore.getState().messages);

    renderAgent();
    const targetBubble = (await screen.findByText("Compare the portfolios")).closest(".group");
    expect(targetBubble).not.toBeNull();
    await user.click(within(targetBubble as HTMLElement).getByRole("button", { name: "Edit prompt" }));
    const editor = screen.getByRole("textbox", { name: "Edit prompt" });
    await user.clear(editor);
    await user.type(editor, "Compare drawdowns instead");
    await user.click(screen.getByRole("button", { name: "Save and regenerate" }));

    await waitFor(() => expect(apiMock.editMessageAndRegenerate).toHaveBeenCalledWith(
      "session-edit",
      "a1b2c3d4e5f8",
      '[Uploaded files: [{"filename":"positions.csv","path":"/tmp/uploads/positions.csv"}]]\n\nCompare drawdowns instead',
    ));
    await waitFor(() => expect(screen.queryByText("Later prompt")).not.toBeInTheDocument());
    expect(screen.queryByText("Old answer")).not.toBeInTheDocument();
    expect(screen.getByText("Compare drawdowns instead")).toBeInTheDocument();
    expect(screen.getByText("positions.csv")).toBeInTheDocument();
    expect(useAgentStore.getState().messages.some((item) => item.swarmRunId === "swarm-after")).toBe(false);
    expect(useAgentStore.getState().messages.some((item) => item.swarmRunId === "swarm-before")).toBe(true);
    expect(useAgentStore.getState().swarmRuns["swarm-after"]).toBeUndefined();
    expect(useAgentStore.getState().swarmRuns["swarm-before"]).toBeDefined();
  });

  it("reconciles a timed-out edit when the server already accepted it", async () => {
    const user = userEvent.setup();
    const initial = [
      message("a1b2c3d4e5f6", "user", "Original prompt", 1),
      message("a1b2c3d4e5f7", "assistant", "Old answer", 2),
    ];
    const retained = [message("a1b2c3d4e5f6", "user", "Accepted edit", 1)];
    const completed = [
      ...retained,
      { ...message("a1b2c3d4e5fc", "assistant", "Regenerated answer", 3), linked_attempt_id: "attempt-new" },
    ];
    apiMock.getSessionMessages
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(retained)
      .mockResolvedValue(completed);
    apiMock.editMessageAndRegenerate.mockRejectedValue(
      new ApiError("The request timed out; the server may still be processing it.", 0, "request_timeout"),
    );

    renderAgent();
    await user.click(await screen.findByRole("button", { name: "Edit prompt" }));
    const editor = screen.getByRole("textbox", { name: "Edit prompt" });
    await user.clear(editor);
    await user.type(editor, "Accepted edit");
    await user.click(screen.getByRole("button", { name: "Save and regenerate" }));

    expect(await screen.findByText("Regenerated answer")).toBeInTheDocument();
    expect(screen.getByText("Accepted edit")).toBeInTheDocument();
    expect(screen.queryByText("Old answer")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(useAgentStore.getState().status).toBe("idle"));
  });

  it("keeps the inline draft when the edit request is rejected", async () => {
    const user = userEvent.setup();
    apiMock.getSessionMessages.mockResolvedValue([
      message("a1b2c3d4e5f6", "user", "Original prompt", 1),
      message("a1b2c3d4e5f7", "assistant", "Original answer", 2),
    ]);
    apiMock.editMessageAndRegenerate.mockRejectedValue(new ApiError("Session is busy", 409));

    renderAgent();
    await user.click(await screen.findByRole("button", { name: "Edit prompt" }));
    const editor = screen.getByRole("textbox", { name: "Edit prompt" });
    await user.clear(editor);
    await user.type(editor, "Keep this draft");
    await user.click(screen.getByRole("button", { name: "Save and regenerate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Session is busy");
    expect(screen.getByRole("textbox", { name: "Edit prompt" })).toHaveValue("Keep this draft");
    expect(useAgentStore.getState().status).toBe("idle");
    expect(useAgentStore.getState().activity).toBeNull();
  });
});
