import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "@/i18n";
import { MessageBubble } from "../MessageBubble";
import type { AgentMessage } from "@/types/agent";
import type { StoredAgentMessage } from "@/stores/agent";

// Mock react-markdown (heavy dependency, renders raw content in tests)
vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => <div data-testid="markdown">{children}</div>,
}));
vi.mock("remark-gfm", () => ({ default: () => {} }));
vi.mock("rehype-highlight", () => ({ default: () => {} }));

// Mock RunCompleteCard (complex component with ECharts)
vi.mock("../RunCompleteCard", () => ({
  RunCompleteCard: ({ msg }: { msg: AgentMessage }) => (
    <div data-testid="run-complete-card">Run: {msg.runId}</div>
  ),
}));

function makeMsg(overrides: Partial<StoredAgentMessage> = {}): StoredAgentMessage {
  return {
    id: "msg-1",
    type: "answer",
    content: "test",
    timestamp: new Date(2024, 0, 1, 14, 30).getTime(),
    ...overrides,
  };
}

describe("MessageBubble", () => {
  beforeAll(() => {
    i18n.addResource("en", "translation", "messageBubble.retry", "Try again");
  });

  describe("user messages", () => {
    it("renders user content in the bounded neutral bubble without an avatar or timestamp", () => {
      const { container } = render(
        <MessageBubble msg={makeMsg({ type: "user", content: "Hello agent!" })} />,
      );
      const bubble = screen.getByText("Hello agent!");
      expect(bubble).toHaveClass(
        "max-h-[40vh]",
        "overflow-y-auto",
        "break-words",
        "rounded-[18px]",
        "bg-muted",
        "px-4",
        "py-3",
        "text-[15px]",
        "text-foreground",
      );
      expect(bubble).not.toHaveClass("rounded-tr-sm");
      expect(screen.queryByText("14:30")).not.toBeInTheDocument();
      expect(container.querySelector("svg")).toBeNull();
    });

    it("renders safe request metadata without exposing an attachment path", () => {
      render(
        <MessageBubble
          msg={makeMsg({
            type: "user",
            content: "Analyze this",
            meta: {
              attachment: { filename: "trades.csv" },
              swarmMode: true,
            },
          })}
        />,
      );
      expect(screen.getByText("trades.csv")).toBeInTheDocument();
      expect(screen.getByText(i18n.t("agent.swarmModeChip" as never))).toBeInTheDocument();
      expect(screen.queryByText(/\/private\/tmp|file_path|path:/i)).not.toBeInTheDocument();
      expect(screen.getByText("trades.csv").parentElement).toHaveClass(
        "bg-background/60",
        "text-muted-foreground",
      );
    });
  });

  describe("answer messages", () => {
    it("renders markdown content", () => {
      render(<MessageBubble msg={makeMsg({ type: "answer", content: "Here is the **analysis**" })} />);
      expect(screen.getByTestId("markdown")).toHaveTextContent("Here is the **analysis**");
    });

    it("uses the streaming-compatible content shape and omits the timestamp", () => {
      const { container } = render(
        <MessageBubble msg={makeMsg({ type: "answer", content: "Analysis" })} />,
      );
      expect(screen.getByTestId("markdown").parentElement).toHaveClass(
        "prose",
        "text-[15px]",
      );
      expect(container.firstElementChild?.children[1]).toHaveClass(
        "flex-1",
        "min-w-0",
        "space-y-1.5",
      );
      expect(screen.queryByText("14:30")).not.toBeInTheDocument();
    });

    it("exposes the copy action to keyboard focus and announces success", async () => {
      render(<MessageBubble msg={makeMsg({ type: "answer", content: "Analysis" })} />);
      const copyButton = screen.getByRole("button", { name: "Copy" });
      expect(copyButton).toHaveClass("focus-visible:opacity-100");

      const user = userEvent.setup();
      await user.click(copyButton);

      expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Copied");
    });

    it("shows the total response time without exposing token counts", () => {
      render(<MessageBubble msg={makeMsg({ type: "answer", elapsed_ms: 2340 })} />);
      expect(screen.getByText("2.3 s")).toBeInTheDocument();
      expect(screen.queryByText(/token/i)).not.toBeInTheDocument();
    });

  });

  describe("error messages", () => {
    it("renders error content with danger styling", () => {
      render(<MessageBubble msg={makeMsg({ type: "error", content: "Execution failed" })} />);
      expect(screen.getByText("Execution failed")).toBeInTheDocument();
    });

    it("shows retry button when onRetry is provided", () => {
      const onRetry = vi.fn();
      render(<MessageBubble msg={makeMsg({ type: "error", content: "Something broke" })} onRetry={onRetry} />);
      expect(screen.getByRole("button")).toBeInTheDocument();
    });

    it("calls onRetry when retry button is clicked", async () => {
      const onRetry = vi.fn();
      const msg = makeMsg({ type: "error", content: "Something broke" });
      render(<MessageBubble msg={msg} onRetry={onRetry} />);

      const user = userEvent.setup();
      await user.click(screen.getByRole("button"));
      expect(onRetry).toHaveBeenCalledWith(msg);
    });

    it("shows the timeout hint as muted text above a short retry action", () => {
      render(
        <MessageBubble
          msg={makeMsg({ type: "error", content: "Execution timed out after 600s" })}
          onRetry={vi.fn()}
        />,
      );
      const hint = screen.getByText(/Timed out/);
      const retry = screen.getByRole("button", { name: "Try again" });

      expect(hint.tagName).toBe("P");
      expect(hint).toHaveClass("text-muted-foreground");
      expect(retry).toHaveTextContent("Try again");
      expect(retry).not.toHaveTextContent(hint.textContent ?? "");
      expect(hint.compareDocumentPosition(retry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  });

  describe("run_complete messages", () => {
    it("renders RunCompleteCard when runId is present", () => {
      render(<MessageBubble msg={makeMsg({ type: "run_complete", runId: "run-42" })} />);
      expect(screen.getByTestId("run-complete-card")).toBeInTheDocument();
      expect(screen.getByText("Run: run-42")).toBeInTheDocument();
    });
  });

  describe("fallback", () => {
    it("renders content for unknown message types", () => {
      render(<MessageBubble msg={makeMsg({ type: "thinking", content: "analyzing data..." })} />);
      expect(screen.getByText("analyzing data...")).toBeInTheDocument();
    });

    it("renders null for empty content on unknown types", () => {
      const { container } = render(<MessageBubble msg={makeMsg({ type: "thinking", content: "" })} />);
      expect(container.innerHTML).toBe("");
    });
  });
});
