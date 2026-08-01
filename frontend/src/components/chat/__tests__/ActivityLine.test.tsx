import { act, fireEvent, render, screen } from "@testing-library/react";
import { ActivityLine, formatActivityElapsed } from "../ActivityLine";
import type { AgentActivity } from "@/stores/agent";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string | number>) => {
      const labels: Record<string, string> = {
        "agent.activity.verbs.working": "Working",
        "agent.activity.verbs.readingMarketData": "Reading the market data",
        "agent.activity.verbs.writingStrategy": "Writing the strategy",
        "agent.activity.verbs.runningBacktest": "Running the backtest",
        "agent.activity.verbs.validatingNumbers": "Double-checking the numbers",
        "agent.activity.done": "Done",
        "agent.activity.failed": "Failed",
        "agent.activity.stopped": "Stopped by you",
        "agent.activity.continue": "Continue",
        "agent.activity.reattach": "Re-attach",
      };
      if (key === "agent.activity.steps") return `${values?.count} steps`;
      if (key === "agent.activity.timeout") {
        return `Stopped waiting after ${values?.elapsed} — the run may still be finishing`;
      }
      if (key === "toolProgress.step") return `Step ${values?.step} · ${values?.tool}`;
      return labels[key] ?? key;
    },
  }),
}));

function makeActivity(overrides: Partial<AgentActivity> = {}): AgentActivity {
  return {
    attemptId: "attempt-1",
    state: "working",
    verb: "runningBacktest",
    steps: [{
      id: "tool-1",
      tool: "backtest",
      arguments: {},
      status: "running",
      timestamp: 5000,
    }],
    startedAt: 5000,
    ...overrides,
  };
}

describe("ActivityLine", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders the compact verb, newest step, timer and count", () => {
    vi.spyOn(Date, "now").mockReturnValue(10_000);
    render(<ActivityLine activity={makeActivity()} />);

    expect(screen.getByText(
      "Running the backtest · Run the backtest · 5s · 1 steps",
    )).toBeInTheDocument();
  });

  it("ticks only while the page is visible and freezes at endedAt", () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const { rerender } = render(<ActivityLine activity={makeActivity()} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/6s/)).toBeInTheDocument();

    hidden.mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    act(() => {
      vi.setSystemTime(20_000);
      vi.advanceTimersByTime(9000);
    });
    expect(screen.getByText(/6s/)).toBeInTheDocument();

    rerender(<ActivityLine activity={makeActivity({
      state: "done",
      endedAt: 12_000,
    })} />);
    expect(screen.getByText("Done · 1 steps · 7s")).toBeInTheDocument();
  });

  it("auto-collapses 900ms after a terminal state", () => {
    vi.useFakeTimers();
    render(<ActivityLine activity={makeActivity({
      state: "done",
      endedAt: 6000,
    })} />);

    const disclosure = screen.getByRole("button");
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    act(() => vi.advanceTimersByTime(900));
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
  });

  it("respects an explicit user disclosure choice across state changes", () => {
    vi.useFakeTimers();
    const { rerender } = render(<ActivityLine activity={makeActivity()} />);
    const disclosure = screen.getByRole("button");
    fireEvent.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "false");

    rerender(<ActivityLine activity={makeActivity({
      state: "done",
      endedAt: 6000,
    })} />);
    act(() => vi.advanceTimersByTime(900));
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
  });

  it("renders stopped and timeout terminal affordances", () => {
    const onContinue = vi.fn();
    const onReattach = vi.fn();
    const { rerender } = render(
      <ActivityLine
        activity={makeActivity({ state: "stopped", endedAt: 8000 })}
        onContinue={onContinue}
      />,
    );
    expect(screen.getByText("Stopped by you · 1 steps · 3s")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onContinue).toHaveBeenCalledOnce();

    rerender(
      <ActivityLine
        activity={makeActivity({ state: "timeout", endedAt: 10_000 })}
        onReattach={onReattach}
      />,
    );
    expect(screen.getByText(
      "Stopped waiting after 5s — the run may still be finishing · 1 steps",
    )).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-attach" }));
    expect(onReattach).toHaveBeenCalledOnce();
  });

  it("uses one elapsed format for seconds and minutes", () => {
    expect(formatActivityElapsed(59_999)).toBe("59s");
    expect(formatActivityElapsed(65_000)).toBe("1m 5s");
  });
});
