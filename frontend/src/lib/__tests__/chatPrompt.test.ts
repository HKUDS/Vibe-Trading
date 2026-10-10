import { describe, expect, it } from "vitest";
import { buildChatPrompt, promptExceedsLimit } from "../chatPrompt";

describe("chat request length", () => {
  it("includes attachment paths and counts Unicode code points", () => {
    const attachments = [{ filename: "研究.pdf", filePath: "uploads/研究.pdf" }];
    const prompt = buildChatPrompt("📈", attachments, false);
    const length = Array.from(prompt).length;
    expect(promptExceedsLimit(prompt, length)).toBe(false);
    expect(promptExceedsLimit(prompt, length - 1)).toBe(true);
    expect(prompt).toContain("uploads/研究.pdf");
  });
});
