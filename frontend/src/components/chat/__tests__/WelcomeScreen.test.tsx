import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WelcomeScreen } from "../WelcomeScreen";
import { copy } from "@/i18n/display";

describe("WelcomeScreen", () => {
  const onExample = vi.fn();

  beforeEach(() => onExample.mockClear());

  it("renders the title", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText("Vibe-Trading")).toBeInTheDocument();
  });

  it("renders capability chips", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText("Finance Skills Library")).toBeInTheDocument();
    expect(screen.getByText("Swarm Agent Teams")).toBeInTheDocument();
    expect(screen.getByText("Shadow Account Backtest")).toBeInTheDocument();
  });

  it("renders example categories", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText(copy.welcome.categories[0]!.label)).toBeInTheDocument();
    expect(screen.getByText(copy.welcome.categories[1]!.label)).toBeInTheDocument();
    expect(screen.getByText(copy.welcome.categories[2]!.label)).toBeInTheDocument();
  });

  it("calls onExample with prompt when an example button is clicked", async () => {
    render(<WelcomeScreen onExample={onExample} />);
    const user = userEvent.setup();
    await user.click(screen.getByText(copy.welcome.categories[0]!.examples[0]!.title));
    expect(onExample).toHaveBeenCalledTimes(1);
    expect(onExample).toHaveBeenCalledWith(
      expect.stringContaining("risk-parity portfolio"),
    );
  });

  it("renders the helper text", () => {
    render(<WelcomeScreen onExample={onExample} />);
    expect(screen.getByText(copy.welcome.helper)).toBeInTheDocument();
    expect(screen.getByText(copy.welcome.tryExample)).toBeInTheDocument();
  });
});
