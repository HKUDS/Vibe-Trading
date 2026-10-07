import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScheduledResearchProposalCard } from "../ScheduledResearchProposalCard";
import type { ScheduledResearchProposal } from "@/lib/api";
import i18n from "@/i18n";

function proposal(format?: "html" | "pdf" | null): ScheduledResearchProposal {
  return {
    type: "scheduled_research.proposal", proposal_id: "proposal", operation: "create",
    status: "pending", expires_at: 2000000,
    job: {
      id: "job", title: "Research", state: "active", source: { kind: "prompt" },
      schedule: { expression: "60000", timezone: null, next_run_at: null, end_at: null },
      delivery: { channel: "email", target_ref: "research", target_label: "Research inbox", status: "none", format },
    },
  };
}

describe("scheduled proposal email format confirmation", () => {
  it.each([
    ["html", "scheduled.deliveryFormatHtml"],
    ["pdf", "scheduled.deliveryFormatPdf"],
    [undefined, "scheduled.deliveryFormatDefault"],
    [null, "scheduled.deliveryFormatDefault"],
  ] as const)("shows %s before confirmation", (format, key) => {
    render(<ScheduledResearchProposalCard proposal={proposal(format)} />);
    expect(screen.getByText(i18n.t(key))).toBeInTheDocument();
    expect(screen.getByText("Research inbox")).toBeInTheDocument();
  });
});
