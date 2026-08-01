// @vitest-environment node

import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../../i18n";
import { SwarmStatusCard } from "../SwarmStatusCard";
import {
  applySwarmEvent,
  buildSwarmStatusFromStarted,
  buildSwarmStatusFromToolResultPreview,
} from "@/lib/swarmStatus";
import type { SwarmRunStatus } from "@/types/agent";

function makeStatus(overrides: Partial<SwarmRunStatus> = {}): SwarmRunStatus {
  return {
    runId: "r1",
    preset: "demo_team",
    status: "running",
    currentLayer: 0,
    totalLayers: 2,
    startedAt: Date.now(),
    agents: [
      { agentId: "macro", status: "waiting", iterations: 0 },
      { agentId: "risk", status: "running", tool: "read_file", elapsed_s: 12, iterations: 2, lastText: "checking exposure" },
      { agentId: "pm", status: "done", tool: "write_file ok", elapsed_s: 30, iterations: 4, lastText: "report complete" },
      { agentId: "qa", status: "failed", error: "missing data" },
      { agentId: "ops", status: "blocked", error: "Blocked by qa" },
      { agentId: "retry_agent", status: "retry", tool: "retry 2" },
    ],
    ...overrides,
  };
}

describe("SwarmStatusCard", () => {
  beforeAll(async () => {
    i18n.addResourceBundle(
      "en",
      "translation",
      {
        swarmStatus: {
          detailsUnavailable: "details unavailable",
          teamStarting:
            "The team is spinning up — first updates in a few seconds…",
        },
        swarm: {
          presets: {
            investment_committee: "Investment Committee Review",
            quant_strategy_desk: "Quant Strategy Desk",
            value_investing_committee: "Value Investing Committee",
          },
        },
      },
      true,
      true,
    );
    await i18n.changeLanguage("en");
  });

  it("renders agent status rows", () => {
    const html = renderToStaticMarkup(<SwarmStatusCard status={makeStatus()} />);

    expect(html).toContain("Demo team");
    expect(html).toContain("Running");
    expect(html).toContain("Waiting");
    expect(html).toContain("Done");
    expect(html).toContain("Failed");
    expect(html).toContain("Blocked");
    expect(html).toContain("Retrying");
    expect(html).toContain("checking exposure");
    expect(html).toContain("missing data");
  });

  it("shows empty state while waiting for events", () => {
    const html = renderToStaticMarkup(<SwarmStatusCard status={makeStatus({ agents: [] })} />);

    expect(html).toContain(
      "The team is spinning up — first updates in a few seconds…",
    );
  });

  it("renders honest indeterminate progress while totals are unknown", () => {
    const html = renderToStaticMarkup(
      <SwarmStatusCard
        status={makeStatus({ agents: [], currentLayer: 0, totalLayers: 0 })}
      />,
    );

    expect(html).not.toContain("0/1");
    expect(html).not.toContain("Round 1 of 1");
    expect(html).not.toContain('value="0" max="1"');
    expect(html).toContain('data-layer-state="indeterminate"');
    expect(html).toContain(
      "animate-[pulse-slide_2s_ease-in-out_infinite]",
    );
    expect(html.match(/animate-pulse/g)).toHaveLength(2);
    expect(html).toMatch(
      /<progress class="sr-only" aria-label="[^"]+"><\/progress>/,
    );
  });

  it("keeps determinate counts when real totals are available", () => {
    const html = renderToStaticMarkup(<SwarmStatusCard status={makeStatus()} />);

    expect(html).toContain("3/6 agents");
    expect(html).toContain("Round 1 of 2");
    expect(html).toContain('data-layer-state="determinate"');
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuemin="0"');
    expect(html).toContain('aria-valuetext="Round 1 of 2"');
    expect(html).toContain("grid h-1.5 min-w-0 gap-1");
    expect(html).not.toContain("grid h-2 min-w-0 gap-1");
    expect(html).not.toContain(
      "animate-[pulse-slide_2s_ease-in-out_infinite]",
    );
  });

  it("renders a static terminal empty state without active-run copy", () => {
    const html = renderToStaticMarkup(
      <SwarmStatusCard
        status={makeStatus({
          agents: [],
          status: "completed",
          currentLayer: 0,
          totalLayers: 0,
        })}
      />,
    );

    expect(html).toContain("Completed — details unavailable");
    expect(html).not.toContain("Assembling team");
    expect(html).not.toContain("Preparing layers");
    expect(html).not.toContain("The team is spinning up");
    expect(html).not.toContain("animate-pulse");
    expect(html).not.toContain("pulse-slide");
    expect(html).not.toContain("<progress");
  });

  it("uses translated preset names and humanizes custom preset ids", () => {
    const translated = renderToStaticMarkup(
      <SwarmStatusCard
        status={makeStatus({ preset: "value_investing_committee" })}
      />,
    );
    const custom = renderToStaticMarkup(
      <SwarmStatusCard status={makeStatus({ preset: "custom_alpha_team" })} />,
    );

    expect(translated).toContain("Value Investing Committee");
    expect(translated).not.toContain("value_investing_committee");
    expect(custom).toContain("Custom alpha team");
  });

  it("builds a card model from swarm.started payload", () => {
    const status = buildSwarmStatusFromStarted({
      run_id: "r-start",
      preset: "research_team",
      status: "running",
      agents: [{ id: "analyst", role: "Analyst" }],
      tasks: [{ id: "t1", agent_id: "analyst", status: "pending" }],
    });

    expect(status?.runId).toBe("r-start");
    expect(status?.agents[0]).toMatchObject({
      agentId: "analyst",
      taskId: "t1",
      role: "Analyst",
      status: "waiting",
    });
  });

  it("updates tool and completion state from swarm events", () => {
    const initial = buildSwarmStatusFromStarted({
      run_id: "r-events",
      preset: "research_team",
      status: "running",
      agents: [{ id: "analyst", role: "Analyst" }],
      tasks: [{ id: "t1", agent_id: "analyst", status: "pending" }],
    })!;

    const started = applySwarmEvent(initial, {
      type: "task_started",
      agent_id: "analyst",
      task_id: "t1",
      data: {},
      timestamp: "2026-06-07T12:00:00Z",
    });
    const called = applySwarmEvent(started, {
      type: "tool_call",
      agent_id: "analyst",
      task_id: "t1",
      data: { tool: "read_file", iteration: 0 },
      timestamp: "2026-06-07T12:00:01Z",
    });
    const done = applySwarmEvent(called, {
      type: "task_completed",
      task_id: "t1",
      data: { iterations: 3, summary: "analysis complete" },
      timestamp: "2026-06-07T12:00:05Z",
    });

    expect(done.agents[0]).toMatchObject({
      status: "done",
      tool: "read_file",
      iterations: 3,
      lastText: "analysis complete",
    });
  });

  it("builds fallback status from run_swarm tool result preview", () => {
    const status = buildSwarmStatusFromToolResultPreview('{"status":"completed","run_id":"r-final","preset":"demo"}');

    expect(status).toMatchObject({
      runId: "r-final",
      preset: "demo",
      status: "completed",
    });
  });
});
