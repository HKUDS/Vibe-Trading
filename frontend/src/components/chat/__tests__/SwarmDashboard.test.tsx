// @vitest-environment node

import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../../i18n";
import { SwarmDashboard } from "../SwarmDashboard";
import type { SwarmAgentStatus } from "@/types/agent";

function makeAgents(): SwarmAgentStatus[] {
  return [
    {
      agentId: "macro",
      role: "Macro analyst",
      status: "running",
      tool: "read_file",
      elapsed_s: 12,
      iterations: 2,
      lastText: "Checking market regime",
    },
    {
      agentId: "risk",
      status: "done",
      elapsed_s: 65,
      iterations: 4,
      lastText: "Risk review complete",
    },
  ];
}

describe("SwarmDashboard", () => {
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
      },
      true,
      true,
    );
    await i18n.changeLanguage("en");
  });

  it("renders responsive wide rows and narrow cards without horizontal overflow", () => {
    const html = renderToStaticMarkup(
      <SwarmDashboard agents={makeAgents()} />,
    );

    expect(html).toContain('data-agent-layout="wide"');
    expect(html).toContain('data-agent-layout="narrow"');
    expect(html).toContain("hidden min-w-0 md:block");
    expect(html).toContain("space-y-2 md:hidden");
    expect(html).not.toContain("hidden min-w-0 sm:block");
    expect(html).not.toContain("space-y-2 sm:hidden");
    expect(html).toContain(
      "grid-cols-[minmax(0,1.25fr)_minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,0.55fr)_minmax(0,1.5fr)]",
    );
    expect(html).not.toContain("min-w-[620px]");
    expect(html).not.toContain("overflow-x-auto");
    expect(html).toContain("Checking market regime");
    expect(html).toContain("Risk review complete");
    expect(html).toContain('role="table"');
    expect(html.match(/role="columnheader"/g)).toHaveLength(5);
    expect(html.match(/role="cell"/g)).toHaveLength(10);
    expect(html).toContain("text-end");
    expect(html).not.toContain("text-right");
    expect(html).not.toContain("mt-3 hidden");
    expect(html).not.toContain("mt-3 space-y-2");
  });

  it("adds status-color transitions and a reduced-motion-safe row entrance", () => {
    const html = renderToStaticMarkup(
      <SwarmDashboard agents={makeAgents()} />,
    );

    expect(html).toContain("transition-colors duration-300");
    expect(html).toContain(
      "animate-[msg-enter_300ms_cubic-bezier(0.16,1,0.3,1)_both]",
    );
    expect(html).toContain("motion-reduce:animate-none");
  });

  it("renders audience-facing copy while an empty run starts", () => {
    const html = renderToStaticMarkup(<SwarmDashboard agents={[]} />);

    expect(html).toContain(
      "The team is spinning up — first updates in a few seconds…",
    );
    expect(html).not.toContain('data-agent-layout="wide"');
    expect(html).not.toContain('data-agent-layout="narrow"');
  });

  it("renders a static unavailable state when an empty run is terminal", () => {
    const html = renderToStaticMarkup(
      <SwarmDashboard
        agents={[]}
        emptyStatus="Completed"
        isActive={false}
      />,
    );

    expect(html).toContain("Completed — details unavailable");
    expect(html).not.toContain("The team is spinning up");
    expect(html).not.toContain("animate-pulse");
    expect(html).not.toContain("animate-spin");
  });

  it("stops stale running-agent spinners after the run terminates", () => {
    const html = renderToStaticMarkup(
      <SwarmDashboard agents={makeAgents()} isActive={false} />,
    );

    expect(html).not.toContain("animate-spin");
  });
});
