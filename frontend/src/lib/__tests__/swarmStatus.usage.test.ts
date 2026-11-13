import {
  applySwarmEvent,
  buildSwarmStatusFromRunDetail,
  buildSwarmStatusFromToolResultPreview,
  mergeSwarmRunUsage,
} from "../swarmStatus";
import type { SwarmRunStatus } from "@/types/agent";

function baseStatus(): SwarmRunStatus {
  return {
    runId: "run-usage",
    preset: "demo_team",
    status: "running",
    currentLayer: 0,
    totalLayers: 2,
    startedAt: 0,
    agents: [
      { agentId: "analyst", taskId: "t1", status: "running" },
      { agentId: "risk", taskId: "t2", status: "running" },
    ],
  };
}

function completedEvent(
  agentId: string,
  taskId: string,
  data: Record<string, unknown>,
) {
  return {
    type: "task_completed",
    agent_id: agentId,
    task_id: taskId,
    timestamp: "2026-07-29T12:01:00.000Z",
    data,
  };
}

describe("swarmStatus task token telemetry", () => {
  it("stores per-task tokens and derives the run totals on task_completed", () => {
    const next = applySwarmEvent(baseStatus(), completedEvent("analyst", "t1", {
      iterations: 4,
      input_tokens: 4200,
      output_tokens: 1300,
      cache_read_tokens: 900,
      cache_creation_tokens: 120,
      token_source: "provider",
    }));

    const agent = next.agents.find((a) => a.agentId === "analyst");
    expect(agent?.input_tokens).toBe(4200);
    expect(agent?.output_tokens).toBe(1300);
    expect(agent?.cache_read_tokens).toBe(900);
    expect(agent?.cache_creation_tokens).toBe(120);
    expect(next.total_input_tokens).toBe(4200);
    expect(next.total_output_tokens).toBe(1300);
    expect(next.token_source).toBe("provider");
  });

  it("does not double the run totals when the same event is replayed", () => {
    const event = completedEvent("analyst", "t1", {
      input_tokens: 4200,
      output_tokens: 1300,
      token_source: "provider",
    });
    const once = applySwarmEvent(baseStatus(), event);
    const twice = applySwarmEvent(once, event);

    expect(twice.total_input_tokens).toBe(4200);
    expect(twice.total_output_tokens).toBe(1300);
    expect(twice.token_source).toBe("provider");
  });

  it("sums totals across agents as each task completes", () => {
    let status = applySwarmEvent(baseStatus(), completedEvent("analyst", "t1", {
      input_tokens: 4200,
      output_tokens: 1300,
      token_source: "provider",
    }));
    status = applySwarmEvent(status, completedEvent("risk", "t2", {
      input_tokens: 800,
      output_tokens: 200,
      token_source: "estimated",
    }));

    expect(status.total_input_tokens).toBe(5000);
    expect(status.total_output_tokens).toBe(1500);
    expect(status.token_source).toBe("estimated");
  });

  it("keeps a real label when a replayed event carries a null token_source", () => {
    let status = applySwarmEvent(baseStatus(), completedEvent("analyst", "t1", {
      input_tokens: 4200,
      output_tokens: 1300,
      token_source: "provider",
    }));
    status = applySwarmEvent(status, completedEvent("risk", "t2", {
      input_tokens: 800,
      output_tokens: 200,
      token_source: null,
    }));

    expect(status.token_source).toBe("provider");
    expect(status.total_input_tokens).toBe(5000);
  });

  it("leaves run totals undefined — never 0 — when no event reports tokens", () => {
    const status = applySwarmEvent(baseStatus(), completedEvent("analyst", "t1", {
      iterations: 2,
      summary: "done",
    }));

    expect(status.total_input_tokens).toBeUndefined();
    expect(status.total_output_tokens).toBeUndefined();
    expect(status.token_source).toBeUndefined();
    expect(status.agents[0].status).toBe("done");
  });

  it("a tokenless worker_completed does not wipe existing task totals", () => {
    let status = applySwarmEvent(baseStatus(), completedEvent("analyst", "t1", {
      input_tokens: 4200,
      output_tokens: 1300,
      token_source: "provider",
    }));
    status = applySwarmEvent(status, {
      type: "worker_completed",
      agent_id: "analyst",
      task_id: "t1",
      timestamp: "2026-07-29T12:02:00.000Z",
      data: { iterations: 5 },
    });

    expect(status.total_input_tokens).toBe(4200);
    expect(status.total_output_tokens).toBe(1300);
    expect(status.token_source).toBe("provider");
  });
});

describe("swarmStatus tool-result preview token_usage", () => {
  function previewWith(tokenUsage: unknown): string {
    return JSON.stringify({
      status: "completed",
      run_id: "run-9",
      preset: "demo_team",
      final_report: "",
      tasks: [],
      token_usage: tokenUsage,
    });
  }

  it("parses run totals and token_source from the run_swarm result preview", () => {
    const status = buildSwarmStatusFromToolResultPreview(
      previewWith({
        total_input_tokens: 5000,
        total_output_tokens: 1500,
        token_source: "estimated",
      }),
    );

    expect(status?.runId).toBe("run-9");
    expect(status?.total_input_tokens).toBe(5000);
    expect(status?.total_output_tokens).toBe(1500);
    expect(status?.token_source).toBe("estimated");
  });

  it("treats a null token_source in the preview as unlabeled, not provider", () => {
    const status = buildSwarmStatusFromToolResultPreview(
      previewWith({ total_input_tokens: 10, total_output_tokens: 2, token_source: null }),
    );

    expect(status?.total_input_tokens).toBe(10);
    expect(status?.token_source).toBeUndefined();
  });

  it("keeps the pre-existing parse behaviour for results without token_usage", () => {
    const status = buildSwarmStatusFromToolResultPreview(
      previewWith(undefined),
    );

    expect(status?.runId).toBe("run-9");
    expect(status?.status).toBe("completed");
    expect(status?.total_input_tokens).toBeUndefined();
    expect(status?.total_output_tokens).toBeUndefined();
    expect(status?.token_source).toBeUndefined();
  });

  it("the truncated-JSON fallback path still recovers identity fields", () => {
    const truncated = '{"status": "completed", "run_id": "run-9", "preset": "demo_team", "token_u';
    const status = buildSwarmStatusFromToolResultPreview(truncated);

    expect(status?.runId).toBe("run-9");
    expect(status?.preset).toBe("demo_team");
    expect(status?.status).toBe("completed");
    expect(status?.total_input_tokens).toBeUndefined();
  });
});

describe("swarmStatus failed/cancelled task token telemetry", () => {
  it("counts tokens from a failed task so the live card matches the run total", () => {
    const next = applySwarmEvent(baseStatus(), {
      type: "task_failed",
      agent_id: "analyst",
      task_id: "t1",
      timestamp: "2026-07-29T12:01:00.000Z",
      data: {
        error: "boom",
        input_tokens: 1000,
        output_tokens: 200,
        cache_read_tokens: 50,
        cache_creation_tokens: 10,
        token_source: "estimated",
      },
    });

    expect(next.total_input_tokens).toBe(1000);
    expect(next.total_output_tokens).toBe(200);
    expect(next.token_source).toBe("estimated");
  });

  it("counts tokens from a cancelled task", () => {
    const next = applySwarmEvent(baseStatus(), {
      type: "task_cancelled",
      agent_id: "risk",
      task_id: "t2",
      timestamp: "2026-07-29T12:01:00.000Z",
      data: { input_tokens: 300, output_tokens: 40 },
    });

    expect(next.total_input_tokens).toBe(300);
    expect(next.total_output_tokens).toBe(40);
  });

  it("does not wipe totals when a failure event carries no token fields", () => {
    const withTokens = applySwarmEvent(
      baseStatus(),
      completedEvent("analyst", "t1", { input_tokens: 500, output_tokens: 60 }),
    );
    const next = applySwarmEvent(withTokens, {
      type: "worker_failed",
      agent_id: "risk",
      task_id: "t2",
      timestamp: "2026-07-29T12:02:00.000Z",
      data: { error: "network" },
    });

    expect(next.total_input_tokens).toBe(500);
    expect(next.total_output_tokens).toBe(60);
  });
});

describe("swarmStatus REST usage hydration", () => {
  it("merges run-level totals and the provenance label from the detail payload", () => {
    const hydrated = mergeSwarmRunUsage(baseStatus(), {
      total_input_tokens: 853341,
      total_output_tokens: 34681,
      provider: "dashscope",
      model: "glm-5.1",
      token_source: "provider",
    });

    expect(hydrated.runId).toBe("run-usage");
    expect(hydrated.total_input_tokens).toBe(853341);
    expect(hydrated.total_output_tokens).toBe(34681);
    expect(hydrated.provider).toBe("dashscope");
    expect(hydrated.model).toBe("glm-5.1");
    expect(hydrated.token_source).toBe("provider");
  });

  it("keeps existing totals and label when the payload redacts or omits them", () => {
    const current: SwarmRunStatus = {
      ...baseStatus(),
      total_input_tokens: 10,
      token_source: "provider",
    };

    const hydrated = mergeSwarmRunUsage(current, { token_source: "[redacted]" });

    expect(hydrated.total_input_tokens).toBe(10);
    expect(hydrated.token_source).toBe("provider");
  });
});

describe("swarmStatus roster repair from the run detail", () => {
  // Shape of a real 4-task run whose card rendered as a partial "2/2 agents".
  const detail = {
    id: "swarm-real",
    preset_name: "global_allocation_committee",
    status: "failed",
    created_at: "2026-10-16T12:16:23.000Z",
    completed_at: "2026-10-16T12:50:19.000Z",
    total_input_tokens: 423957,
    total_output_tokens: 52128,
    token_source: "provider",
    provider: "openai",
    model: "deepseek-v4.1-flash",
    tasks: [
      { id: "task-allocate", agent_id: "allocator", status: "blocked", worker_iterations: 0, input_tokens: null, output_tokens: null },
      { id: "task-ashare", agent_id: "a_share_analyst", status: "completed", worker_iterations: 9, input_tokens: null, output_tokens: null },
      { id: "task-crypto", agent_id: "crypto_analyst", status: "completed", worker_iterations: 21, input_tokens: null, output_tokens: null },
      { id: "task-ushk", agent_id: "us_hk_analyst", status: "failed", worker_iterations: 8, input_tokens: null, output_tokens: null },
    ],
  };

  it("restores the agents a partial event stream dropped", () => {
    const partial: SwarmRunStatus = {
      ...baseStatus(),
      agents: [
        { agentId: "us_hk_analyst", taskId: "task-ushk", status: "failed", input_tokens: 88000, output_tokens: 8281 },
        { agentId: "allocator", taskId: "task-allocate", status: "blocked" },
      ],
    };

    const merged = mergeSwarmRunUsage(partial, detail);

    expect(merged.agents.map((agent) => agent.agentId).sort()).toEqual([
      "a_share_analyst",
      "allocator",
      "crypto_analyst",
      "us_hk_analyst",
    ]);
    expect(merged.agents.find((a) => a.agentId === "crypto_analyst")?.status).toBe("done");
    expect(merged.agents.find((a) => a.agentId === "crypto_analyst")?.iterations).toBe(21);
    expect(merged.agents.find((a) => a.agentId === "us_hk_analyst")?.input_tokens).toBe(88000);
    expect(merged.total_input_tokens).toBe(423957);
    expect(merged.token_source).toBe("provider");
  });

  it("builds a complete status from the detail alone on a cold load", () => {
    const built = buildSwarmStatusFromRunDetail(detail, "swarm-real");

    expect(built?.runId).toBe("swarm-real");
    expect(built?.preset).toBe("global_allocation_committee");
    expect(built?.status).toBe("failed");
    expect(built?.total_input_tokens).toBe(423957);
    expect(built?.provider).toBe("openai");
    expect(built?.model).toBe("deepseek-v4.1-flash");

    const hydrated = built && mergeSwarmRunUsage(built, detail);
    expect(hydrated?.agents).toHaveLength(4);
  });

  it("does not regress a terminal status to a stale pending from the detail", () => {
    const live: SwarmRunStatus = {
      ...baseStatus(),
      agents: [
        { agentId: "a_share_analyst", taskId: "task-ashare", status: "done", input_tokens: 10 },
      ],
    };
    const stale = { ...detail, tasks: [{ ...detail.tasks[1], status: "pending" }] };

    const merged = mergeSwarmRunUsage(live, stale);

    expect(merged.agents.find((a) => a.agentId === "a_share_analyst")?.status).toBe("done");
    expect(merged.agents.find((a) => a.agentId === "a_share_analyst")?.input_tokens).toBe(10);
  });
});

describe("partial research delivery", () => {
  it("accepts saved results after a local cancel without changing its status", () => {
    const cancelled = { ...baseStatus(), status: "cancelled" as const, completedAt: 12 };
    const next = applySwarmEvent(cancelled, {
      type: "run_completed", data: { status: "failed", final_report: "Revenue $26B", report_is_partial: true },
    });
    expect(next.status).toBe("cancelled");
    expect(next.completedAt).toBe(12);
    expect(next.finalReport).toBe("Revenue $26B");
    expect(next.reportIsPartial).toBe(true);
  });
  it("rehydrates partial delivery from persisted run data", () => {
    const next = buildSwarmStatusFromRunDetail({ id: "r", status: "failed", final_report: "Hold", report_is_partial: true }, "r");
    expect(next?.finalReport).toBe("Hold");
    expect(next?.reportIsPartial).toBe(true);
  });
});
