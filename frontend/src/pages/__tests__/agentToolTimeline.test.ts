import { buildToolTimelineMessages } from "../agentToolTimeline";

describe("buildToolTimelineMessages", () => {
  it("rebuilds one durable activity object from a persisted tool trail", () => {
    expect(buildToolTimelineMessages(
      [
        {
          tool: "get_market_data",
          call_id: "call-market-1",
          arguments: { symbol: "AAPL" },
          status: "ok",
          elapsed_ms: 125,
          preview: "AAPL 195.00",
          timestamp: 1_785_342_400_000,
        },
        {
          tool: "write_file",
          arguments: { path: "report.md" },
          status: "error",
          timestamp: 1_785_342_400_000,
        },
      ],
      {
        fallbackTimestamp: 1_785_342_500_000,
        idPrefix: "message-1_",
        attemptId: "attempt-1",
        endedAt: 1_785_342_500_000,
      },
    )).toEqual([
      {
        id: "message-1_activity_attempt-1",
        type: "thinking",
        content: "",
        meta: {
          activity: {
            attemptId: "attempt-1",
            state: "done",
            verb: "writingStrategy",
            steps: [
              {
                id: "call-market-1",
                tool: "get_market_data",
                arguments: { symbol: "AAPL" },
                status: "ok",
                preview: "AAPL 195.00",
                elapsed_ms: 125,
                timestamp: 1_785_342_400_000,
              },
              {
                id: "write_file#2",
                tool: "write_file",
                arguments: { path: "report.md" },
                status: "error",
                preview: undefined,
                elapsed_ms: undefined,
                timestamp: 1_785_342_400_000,
              },
            ],
            startedAt: 1_785_342_400_000,
            endedAt: 1_785_342_500_000,
          },
        },
        timestamp: 1_785_342_400_000,
      },
    ]);
  });

  it("keeps a zero-step attempt visible in history", () => {
    const [message] = buildToolTimelineMessages([], {
      fallbackTimestamp: 1000,
      attemptId: "attempt-empty",
    });

    expect(message.meta?.activity).toMatchObject({
      attemptId: "attempt-empty",
      state: "done",
      verb: "working",
      steps: [],
      startedAt: 1000,
      endedAt: 1000,
    });
  });
});
