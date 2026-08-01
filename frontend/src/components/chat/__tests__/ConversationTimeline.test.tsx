import { createRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { ConversationTimeline } from "../ConversationTimeline";
import type { AgentMessage } from "@/types/agent";

describe("ConversationTimeline", () => {
  it("caps the minimap at the 40 most recent user messages", async () => {
    const messages: AgentMessage[] = Array.from({ length: 50 }, (_, index) => ({
      id: `message-${index}`,
      type: "user",
      content: `Prompt ${index}`,
      timestamp: index,
    }));
    const containerRef = createRef<HTMLDivElement>();

    render(
      <>
        <div ref={containerRef} />
        <ConversationTimeline messages={messages} containerRef={containerRef} />
      </>,
    );

    expect(screen.getAllByRole("button")).toHaveLength(40);
    expect(screen.queryByTitle("Prompt 9")).not.toBeInTheDocument();
    expect(screen.getByTitle("Prompt 10")).toBeInTheDocument();
    expect(screen.getByTitle("Prompt 49")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Prompt 10" })).toHaveAttribute(
        "aria-current",
        "true",
      );
    });
    expect(screen.getByRole("button", { name: "Prompt 49" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
