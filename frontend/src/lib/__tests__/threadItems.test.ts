import { buildTranscript, emptyThreadView, historyReply, type ThreadView } from "@/lib/threadItems";
import type { ThreadDisplayItem } from "@/lib/api";

function item(partial: Partial<ThreadDisplayItem>): ThreadDisplayItem {
  return {
    seq: 1,
    ts: 100,
    turn_id: "turn-1",
    type: "turn_start",
    ...partial,
  };
}

function interruptedView(): ThreadView {
  const view = emptyThreadView();
  return {
    ...view,
    loaded: true,
    entries: [
      { key: "start", seq: 1, turnId: "turn-1", type: "turn_start", state: "recorded", item: item({ seq: 1 }), receivedAt: 100_000 },
      { key: "end", seq: 2, turnId: "turn-1", type: "turn_end", state: "recorded", item: item({ seq: 2, ts: 101, type: "turn_end", status: "interrupted" }), receivedAt: 101_000 },
    ],
  };
}

describe("buildTranscript", () => {
  it("shows the recovered reply text for an interrupted turn", () => {
    const rows = buildTranscript(interruptedView(), {
      "turn-1": { content: "Recovered partial response" },
    }, {
      displayUser: (content) => ({ content }),
      interruptedLabel: "Interrupted",
      failedLabel: "Failed",
    });

    expect(rows.map((row) => row.type)).toEqual(["turn_status", "commentary"]);
    expect(rows[1]).toMatchObject({
      content: "Recovered partial response",
      meta: { turnId: "turn-1", partial: true },
    });
  });

  it("shows a failed turn's retained answer once and its reason in the error row after a reload", () => {
    const end = item({
      seq: 3, ts: 102, type: "turn_end", status: "failed",
      summary: "Observed findings\n\nExecution failed: provider output truncated",
      error: "provider output truncated",
    });
    const view: ThreadView = {
      ...emptyThreadView(),
      loaded: true,
      entries: [
        { key: "start", seq: 1, turnId: "turn-1", type: "turn_start", state: "recorded", item: item({ seq: 1 }), receivedAt: 100_000 },
        { key: "final", seq: 2, turnId: "turn-1", type: "assistant", state: "recorded",
          item: item({ seq: 2, ts: 101, type: "assistant", content: "Observed findings", phase: "final" }), receivedAt: 101_000 },
        { key: "end", seq: 3, turnId: "turn-1", type: "turn_end", state: "recorded", item: end, receivedAt: 102_000 },
      ],
    };
    const rows = buildTranscript(view, { "turn-1": historyReply(end) }, {
      displayUser: (content) => ({ content }),
      interruptedLabel: "Interrupted",
      failedLabel: "Failed",
    });

    const shown = rows.map((row) => row.content).join("\n");
    expect(shown.split("Observed findings").length - 1).toBe(1);
    expect(rows.some((row) => row.content === "provider output truncated")).toBe(true);
  });
});
