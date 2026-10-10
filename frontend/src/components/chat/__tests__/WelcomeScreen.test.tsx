import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "../../../i18n";
import { WelcomeScreen } from "../WelcomeScreen";

describe("WelcomeScreen", () => {
  const onExample = vi.fn();

  beforeAll(async () => {
    i18n.addResourceBundle(
      "en",
      "translation",
      {
        welcome: {
          taskSubtitle: "What would you like to research, test, or understand today?",
          quickActions: "Quick actions",
          browseAllExamples: "Browse all examples",
          greetings: {
            morning1: "Good morning.",
            morning2: "Morning — ready when you are.",
            morning3: "Good morning. Let's get started.",
            afternoon1: "Good afternoon.",
            afternoon2: "Ready for the next question?",
            afternoon3: "What are we exploring this afternoon?",
            evening1: "Good evening.",
            evening2: "Let's make sense of the market.",
            evening3: "Ready for some focused research?",
            night1: "Still thinking?",
            night2: "Let's work through it.",
            night3: "One more idea before you wrap up?",
          },
        },
      },
      true,
      true,
    );
    await i18n.changeLanguage("en");
  });

  beforeEach(() => onExample.mockClear());

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it.each([
    [5, "Good morning."],
    [12, "Good afternoon."],
    [17, "Good evening."],
    [22, "Still thinking?"],
  ])("renders the local-hour greeting for %i:00", (hour, greeting) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 29, hour));
    vi.spyOn(Math, "random").mockReturnValue(0);

    render(<WelcomeScreen onExample={onExample} />);

    expect(screen.getByRole("heading", { name: greeting })).toBeInTheDocument();
    expect(
      screen.getByText("What would you like to research, test, or understand today?"),
    ).toBeInTheDocument();
  });

  it("fills the three beginner task prompts without submitting a request", async () => {
    const actions = [
      {
        label: "Research a stock",
        prompt: "Research AAPL: summarize its business, recent financial performance, and key risks using current data. State the sources and dates, and flag missing information.",
      },
      {
        label: "Test a strategy",
        prompt: "Backtest a 20/60-day moving-average strategy on AAPL over the past year. Compare returns and drawdowns with buy-and-hold, and include trading costs. Keep this research-only.",
      },
      {
        label: "Review my holdings",
        prompt: "Summarize my connected accounts and holdings, including concentration and portfolio risks. If no account is connected, explain how to set one up first. Do not place or modify orders.",
      },
    ];
    const user = userEvent.setup();
    render(<WelcomeScreen onExample={onExample} />);

    const quickActions = screen.getByRole("group", { name: "Quick actions" });
    expect(within(quickActions).getAllByRole("button")).toHaveLength(3);

    for (const [index, action] of actions.entries()) {
      await user.click(
        within(quickActions).getByRole("button", { name: action.label }),
      );
      expect(onExample).toHaveBeenNthCalledWith(index + 1, action.prompt);
    }
    expect(onExample).toHaveBeenCalledTimes(3);
  });

  it("marks the clicked quick action as selected and moves the selection", async () => {
    const user = userEvent.setup();
    render(<WelcomeScreen onExample={onExample} />);

    const quickActions = screen.getByRole("group", { name: "Quick actions" });
    const buttons = within(quickActions).getAllByRole("button");
    for (const button of buttons) {
      expect(button).toHaveAttribute("aria-pressed", "false");
      expect(button).not.toHaveClass("text-primary");
    }

    const portfolio = within(quickActions).getByRole("button", {
      name: "Review my holdings",
    });
    await user.click(portfolio);
    expect(portfolio).toHaveAttribute("aria-pressed", "true");
    expect(portfolio).toHaveClass("text-primary");
    expect(onExample).toHaveBeenCalledTimes(1);

    const research = within(quickActions).getByRole("button", {
      name: "Research a stock",
    });
    await user.click(research);
    expect(portfolio).toHaveAttribute("aria-pressed", "false");
    expect(portfolio).not.toHaveClass("text-primary");
    expect(research).toHaveAttribute("aria-pressed", "true");
    expect(research).toHaveClass("text-primary");
    expect(onExample).toHaveBeenCalledTimes(2);
  });

  it("reveals eight category tabs and switches example cards from the disclosure", async () => {
    const user = userEvent.setup();
    render(<WelcomeScreen onExample={onExample} />);

    const trigger = screen.getByRole("button", { name: "Browse all examples" });
    const library = document.getElementById("welcome-example-library");
    expect(library).not.toBeNull();
    expect(library).toHaveAttribute("aria-hidden", "true");
    expect(
      screen.queryByRole("button", { name: /A-Share MACD Strategy/ }),
    ).not.toBeInTheDocument();

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(library).toHaveAttribute("aria-hidden", "false");
    // One category at a time: 8 tab chips, only the active category's cards.
    expect(within(library!).getAllByRole("tab")).toHaveLength(8);
    expect(within(library!).getAllByRole("button")).toHaveLength(3);
    expect(within(library!).getAllByRole("button")[0]).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-primary/40",
    );
    for (const category of [
      "A-Share Backtest",
      "Research & Analysis",
      "Value Investing",
      "AI Analyst Teams",
      "Document & Web Research",
      "Trade Journal",
      "Trading Connectors",
      "Shadow Account",
    ]) {
      expect(within(library!).getByText(category)).toBeInTheDocument();
    }

    await user.click(within(library!).getByRole("tab", { name: /Value Investing/ }));
    expect(within(library!).getByRole("tab", { name: /Value Investing/ })).toHaveAttribute("aria-selected", "true");
    expect(within(library!).getAllByRole("button")).toHaveLength(4);
    expect(
      within(library!).getByRole("button", { name: /Check if a stock is expensive/ }),
    ).toBeInTheDocument();
  });

  it("closes the example library with Escape and restores focus to its trigger", async () => {
    const user = userEvent.setup();
    render(<WelcomeScreen onExample={onExample} />);

    const trigger = screen.getByRole("button", { name: "Browse all examples" });
    await user.click(trigger);
    const library = document.getElementById("welcome-example-library")!;
    const firstExample = within(library).getAllByRole("button")[0];
    firstExample.focus();

    await user.keyboard("{Escape}");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(library).toHaveAttribute("aria-hidden", "true");
    expect(trigger).toHaveFocus();
  });

  it("does not render capability chips", () => {
    render(<WelcomeScreen onExample={onExample} />);

    expect(screen.queryByText("Finance Skills Library")).not.toBeInTheDocument();
    expect(screen.queryByText("Swarm Agent Teams")).not.toBeInTheDocument();
    expect(screen.queryByText("Shadow Account Backtest")).not.toBeInTheDocument();
  });
});
