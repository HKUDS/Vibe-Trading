import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PlanCard } from "@/components/chat/PlanCard";
import { QuestionCard } from "@/components/chat/QuestionCard";
import { ImageResult } from "@/components/chat/ImageResult";

describe("interaction cards", () => {
  it("renders plan steps and statuses", () => {
    render(<PlanCard steps={[{ step: "Inspect", status: "completed" }, { step: "Report", status: "pending" }]} />);
    expect(screen.getByText("Inspect")).toBeTruthy();
    expect(screen.getByText("Report")).toBeTruthy();
  });
  it("submits a selected answer", () => {
    const onAnswer = vi.fn();
    render(<QuestionCard questionId="q" prompt="Choose" options={["A", "B"]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "B" }));
    expect(onAnswer).toHaveBeenCalledWith("B");
  });
  it("renders image artifact references", () => {
    render(<ImageResult images={[{ path: "/tmp/chart.png", alt: "Chart" }]} />);
    expect(screen.getByAltText("Chart")).toBeTruthy();
    expect(screen.getByText("/tmp/chart.png")).toBeTruthy();
  });
});
