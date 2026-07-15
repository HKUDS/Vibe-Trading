import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WelcomeScreen } from "../WelcomeScreen";

describe("WelcomeScreen", () => {
  const onExample = vi.fn();

  beforeEach(() => onExample.mockClear());

  it("renders the title", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText("Start a New Market Analysis")).toBeInTheDocument();
  });

  it("renders capability chips", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText("Finance Skills Library")).toBeInTheDocument();
    expect(screen.getByText("Research Teams")).toBeInTheDocument();
    expect(screen.getByText("Shadow Account Backtest")).toBeInTheDocument();
  });

  it("renders example categories", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText("A-Share Backtest")).toBeInTheDocument();
    expect(screen.getByText("Research & Analysis")).toBeInTheDocument();
    expect(screen.getByText("Swarm Teams")).toBeInTheDocument();
  });

  it("calls onExample with prompt when an example button is clicked", async () => {
    render(<WelcomeScreen onExample={onExample} />);
    const user = userEvent.setup();
    await user.click(screen.getByText("Validate an Opportunity"));
    expect(onExample).toHaveBeenCalledTimes(1);
    expect(onExample).toHaveBeenCalledWith(
      expect.stringContaining("Evaluate EUR/USD"),
    );
  });

  it("renders the helper text", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText("Describe the opportunity you want to evaluate.")).toBeInTheDocument();
    expect(screen.getByText("Start with a structured analysis template:")).toBeInTheDocument();
  });
});
