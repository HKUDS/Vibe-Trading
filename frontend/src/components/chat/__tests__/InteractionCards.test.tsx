import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PlanCard } from "@/components/chat/PlanCard";
import { QuestionCard } from "@/components/chat/QuestionCard";
import i18n from "@/i18n";
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


it("localizes question controls and image fallback text", async () => {
  await act(() => i18n.changeLanguage("zh-CN").then(() => {}));
  try {
    render(<><QuestionCard questionId="q" prompt="请选择" options={["甲", "乙"]} onAnswer={vi.fn()} /><ImageResult images={[{ path: "/chart.png" }]} /></>);
    expect(await screen.findByRole("textbox", { name: "输入回答" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "发送" })).toBeTruthy();
    expect(screen.getByAltText("工具结果")).toBeTruthy();
  } finally {
    await act(() => i18n.changeLanguage("en").then(() => {}));
  }
});
