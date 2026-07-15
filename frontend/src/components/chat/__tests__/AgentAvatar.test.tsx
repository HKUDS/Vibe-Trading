import { render, screen } from "@testing-library/react";
import { AgentAvatar } from "../AgentAvatar";

describe("AgentAvatar", () => {
  it("renders the TradeCoreFX initials", () => {
    render(<AgentAvatar />);
    expect(screen.getByText("TC")).toBeInTheDocument();
  });

  it("has professional badge styling", () => {
    const { container } = render(<AgentAvatar />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toMatch(/border-primary/);
  });
});
