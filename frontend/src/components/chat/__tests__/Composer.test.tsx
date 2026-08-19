import { memo } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "../../../i18n";
import { Composer } from "../Composer";

const baseProps = {
  capabilities: {
    skills: [{ name: "technical-basic", category: "analysis", description: "Trend and momentum analysis" }],
    tools: [{ name: "get_market_data", category: "market-data", read_only: true, description: "Fetch market data" }],
  },
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
  beforeAll(async () => {
    await i18n.changeLanguage("en");
  });

  beforeEach(() => {
    vi.clearAllMocks();
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
    expect(baseProps.onSubmit).toHaveBeenCalledWith("你好", null);
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

  it("renders the loaded skills and tools after selecting slash categories", () => {
    render(<Composer {...baseProps} />);
    const textarea = screen.getByRole("textbox");

    fireEvent.change(textarea, { target: { value: "/skills" } });
    expect(screen.getByText("technical-basic")).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: "/tools" } });
    expect(screen.getByText("get_market_data")).toBeInTheDocument();
  });

  it("scrolls the active slash option into view during keyboard navigation", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const capabilities = {
      skills: Array.from({ length: 14 }, (_, index) => ({
        name: `skill-${index}`,
        category: "analysis",
        description: `Description ${index}`,
      })),
      tools: [],
    };
    render(<Composer {...baseProps} capabilities={capabilities} />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "/skills" } });
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  });
});
