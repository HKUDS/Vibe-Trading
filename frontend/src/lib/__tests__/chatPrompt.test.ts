import { describe, expect, it } from "vitest";
import {
  buildChatPrompt,
  GOAL_CONTINUE_PREFIX,
  GOAL_KICKOFF_PREFIX,
  promptExceedsLimit,
  replacePromptText,
  SWARM_PROMPT_PREFIX,
} from "../chatPrompt";

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

describe("historical prompt reconstruction", () => {
  it("preserves attachment paths and swarm mode", () => {
    const raw = buildChatPrompt(
      "Original prompt",
      [{ filename: "positions.csv", filePath: "/tmp/uploads/positions.csv" }],
      true,
    );

    expect(replacePromptText(raw, "Edited prompt")).toBe(
      buildChatPrompt(
        "Edited prompt",
        [{ filename: "positions.csv", filePath: "/tmp/uploads/positions.csv" }],
        true,
      ),
    );
  });

  it("preserves hidden goal criteria when editing a continuation", () => {
    const suffix = "\nOpen criteria:\n- criterion-one";
    const raw = `${GOAL_CONTINUE_PREFIX}Original objective${suffix}`;

    expect(replacePromptText(raw, "Edited objective")).toBe(
      `${GOAL_CONTINUE_PREFIX}Edited objective${suffix}`,
    );
  });

  it("preserves the goal kickoff wrapper", () => {
    expect(replacePromptText(`${GOAL_KICKOFF_PREFIX}Original`, "Edited")).toBe(
      `${GOAL_KICKOFF_PREFIX}Edited`,
    );
  });

  it("keeps malformed attachment envelopes editable as ordinary text", () => {
    const raw = "[Uploaded files: not-json]\n\nOriginal";
    expect(replacePromptText(raw, "Edited")).toBe("Edited");
  });

  it("retains the swarm prefix when the visible prompt is edited", () => {
    expect(replacePromptText(`${SWARM_PROMPT_PREFIX}Original`, "Edited")).toBe(
      `${SWARM_PROMPT_PREFIX}Edited`,
    );
  });
});
