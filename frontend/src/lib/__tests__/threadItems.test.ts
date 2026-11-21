import { buildTranscript, emptyThreadView, type ThreadView } from "@/lib/threadItems";
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
});
