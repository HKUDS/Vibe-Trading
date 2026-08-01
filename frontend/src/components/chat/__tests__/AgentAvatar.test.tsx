import { render } from "@testing-library/react";
import { AgentAvatar } from "../AgentAvatar";

describe("AgentAvatar", () => {
  it("renders the brand mark as a decorative 32px avatar", () => {
    const { container } = render(<AgentAvatar />);
    const wrapper = container.firstElementChild;
    const mark = wrapper?.querySelector("svg");

    expect(wrapper).toHaveAttribute("aria-hidden", "true");
    expect(wrapper).toHaveClass("h-8", "w-8");
    expect(mark).toHaveClass("h-8", "w-8");
    expect(container).not.toHaveTextContent("P");
  });
});
