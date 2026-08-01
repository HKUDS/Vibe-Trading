import { render } from "@testing-library/react";
import { MarkdownContent, MessageBubble } from "../MessageBubble";
import type { AgentMessage } from "@/types/agent";

// Unlike MessageBubble.test.tsx, react-markdown is NOT mocked here: these tests
// exercise the real remark-math/rehype-katex pipeline end to end.
vi.mock("../RunCompleteCard", () => ({ RunCompleteCard: () => null }));

function answer(content: string): AgentMessage {
  return { id: "msg-1", type: "answer", content, timestamp: Date.now() };
}

describe("MessageBubble LaTeX rendering", () => {
  it("renders \\(...\\) as KaTeX inline math", () => {
    const { container } = render(
      <MessageBubble msg={answer("Sharpe: \\(\\frac{R_p - R_f}{\\sigma_p}\\)")} />,
    );
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("renders \\[...\\] as KaTeX display math", () => {
    const { container } = render(
      <MessageBubble msg={answer("\\[\\sum_{i=1}^n w_i r_i\\]")} />,
    );
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });

  it("renders $$...$$ as KaTeX math", () => {
    const { container } = render(<MessageBubble msg={answer("Vol: $$\\sigma^2$$")} />);
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("does NOT treat dollar amounts as math", () => {
    const { container } = render(
      <MessageBubble msg={answer("AAPL fell from $150 to $120 today")} />,
    );
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("from $150 to $120");
  });

  it("does NOT transform LaTeX-like text inside code blocks", () => {
    const { container } = render(
      <MessageBubble msg={answer('```python\nre.match(r"\\(x\\)", s)\n```')} />,
    );
    expect(container.querySelector(".katex")).toBeNull();
  });

  it("keeps streaming markdown structural without running KaTeX enhancement", () => {
    const { container } = render(
      <MarkdownContent content={"Sharpe: \\(\\frac{R_p}{\\sigma_p}\\)"} streaming showCursor />,
    );
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("Sharpe:");
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("wraps markdown tables in a horizontal scroll container", () => {
    const { container } = render(
      <MarkdownContent content={"| Symbol | Return |\n| --- | ---: |\n| AAPL | 12% |"} />,
    );
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.parentElement).toHaveClass("overflow-x-auto");
  });

  it("opens markdown links in a separate, isolated tab", () => {
    const { container } = render(
      <MarkdownContent content={"[Source](https://example.com/report)"} />,
    );
    const link = container.querySelector("a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
