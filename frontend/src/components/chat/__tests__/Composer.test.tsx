import { memo } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "../../../i18n";
import { api } from "@/lib/api";
import { Composer } from "../Composer";
import { toast } from "sonner";
import { MAX_MESSAGE_CHARS, SWARM_PROMPT_PREFIX } from "@/lib/chatPrompt";

vi.mock("@/lib/api", () => ({
  api: { uploadFile: vi.fn() },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const baseProps = {
  streaming: false,
  hasCompletedTurn: false,
  showExport: false,
  canExport: false,
  goalComposerActive: false,
  swarmPreset: null,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
  onExport: vi.fn(),
  onStartGoal: vi.fn(),
  onCancelGoal: vi.fn(),
  onStartSwarm: vi.fn(),
  onCancelSwarm: vi.fn(),
};

describe("Composer", () => {
  it("retains oversized input and gives an actionable error", () => {
    render(<Composer {...baseProps} />);
    const textarea = screen.getByRole("textbox");
    const prompt = "x".repeat(MAX_MESSAGE_CHARS + 1);
    fireEvent.change(textarea, { target: { value: prompt } });
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });
    expect(baseProps.onSubmit).not.toHaveBeenCalled();
    expect(textarea).toHaveValue(prompt);
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Shorten it"));
  });

  it("counts team instructions in the submitted request", () => {
    render(<Composer {...baseProps} swarmPreset={{ name: "research", title: "Research" }} />);
    const prompt = "x".repeat(MAX_MESSAGE_CHARS - SWARM_PROMPT_PREFIX.length + 1);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: prompt } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", code: "Enter" });
    expect(baseProps.onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toHaveValue(prompt);
  });

  it("accepts the exact Unicode code point boundary", () => {
    render(<Composer {...baseProps} />);
    const prompt = "📈".repeat(MAX_MESSAGE_CHARS);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: prompt } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", code: "Enter" });
    expect(baseProps.onSubmit).toHaveBeenCalledWith(prompt, []);
  });

  beforeAll(async () => {
    await i18n.changeLanguage("en");
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.uploadFile).mockImplementation(async (file: File) => ({
      status: "ok",
      filename: file.name,
      file_path: `uploads/${file.name}`,
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not submit Enter during composition or immediately after compositionend", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 30, 12));
    render(<Composer {...baseProps} />);
    const textarea = screen.getByRole("textbox");

    fireEvent.change(textarea, { target: { value: "你好" } });
    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });
    expect(baseProps.onSubmit).not.toHaveBeenCalled();

    fireEvent.compositionEnd(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });
    expect(baseProps.onSubmit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(81);
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });
    expect(baseProps.onSubmit).toHaveBeenCalledTimes(1);
    expect(baseProps.onSubmit).toHaveBeenCalledWith("你好", []);
  });

  it("keeps composer keystrokes inside the composer render boundary", async () => {
    let messageListRenderCount = 0;
    const MessageListProbe = memo(function MessageListProbe() {
      messageListRenderCount += 1;
      return <div>message list</div>;
    });
    const user = userEvent.setup();

    render(
      <>
        <MessageListProbe />
        <Composer {...baseProps} />
      </>,
    );
    expect(messageListRenderCount).toBe(1);

    await user.type(screen.getByRole("textbox"), "local composer state");

    expect(messageListRenderCount).toBe(1);
  });

  it("uploads multiple dropped files and submits them together", async () => {
    const user = userEvent.setup();
    const { container } = render(<Composer {...baseProps} />);
    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    const files = [
      new File(["trade,date"], "trades.csv", { type: "text/csv" }),
      new File(["chart"], "chart.png", { type: "image/png" }),
    ];

    fireEvent.drop(form!, {
      dataTransfer: { files, types: ["Files"] },
    });

    await waitFor(() => expect(api.uploadFile).toHaveBeenCalledTimes(2));
    expect(screen.getByText("trades.csv")).toBeInTheDocument();
    expect(screen.getByText("chart.png")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox"), "Compare these files");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(baseProps.onSubmit).toHaveBeenCalledWith("Compare these files", [
      { filename: "trades.csv", filePath: "uploads/trades.csv" },
      { filename: "chart.png", filePath: "uploads/chart.png" },
    ]);
  });

  it("uploads an image pasted from the clipboard and allows attachment-only submit", async () => {
    const user = userEvent.setup();
    render(<Composer {...baseProps} />);
    const textarea = screen.getByRole("textbox");
    const image = new File(["pixels"], "clipboard.png", { type: "image/png" });

    fireEvent.paste(textarea, {
      clipboardData: { files: [image] },
    });

    await screen.findByText("clipboard.png");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(baseProps.onSubmit).toHaveBeenCalledWith("", [
      { filename: "clipboard.png", filePath: "uploads/clipboard.png" },
    ]);
  });

  it("shows a drop target while files are dragged over the composer", () => {
    const { container } = render(<Composer {...baseProps} />);
    const form = container.querySelector("form");
    fireEvent.dragEnter(form!, {
      dataTransfer: { files: [], types: ["Files"] },
    });
    expect(screen.getByText("Drop files here")).toBeInTheDocument();
  });

  it("caps one composer turn at five attachments", async () => {
    const { container } = render(<Composer {...baseProps} />);
    const files = Array.from(
      { length: 6 },
      (_, index) => new File([String(index)], `file-${index}.txt`, { type: "text/plain" }),
    );
    fireEvent.drop(container.querySelector("form")!, {
      dataTransfer: { files, types: ["Files"] },
    });
    await waitFor(() => expect(api.uploadFile).toHaveBeenCalledTimes(5));
    expect(screen.queryByText("file-5.txt")).not.toBeInTheDocument();
  });
});
