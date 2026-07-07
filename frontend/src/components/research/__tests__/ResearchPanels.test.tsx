import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceClosurePanel } from "../EvidenceClosurePanel";
import { ClaimAuditPanel } from "../ClaimAuditPanel";
import { PolicyDecisionsPanel } from "../PolicyDecisionsPanel";
import { QuantScorecardPanel } from "../QuantScorecardPanel";
import {
  phase6ClaimSetFixture,
  phase6EvidenceSummaryFixture,
  phase6PolicyDecisionsFixture,
  phase6RunCardFixture,
} from "../fixtures";

describe("Phase 6 research panels", () => {
  it("shows visible evidence closure pass/degraded state", () => {
    render(<EvidenceClosurePanel summary={phase6EvidenceSummaryFixture} />);

    expect(screen.getByText("Evidence Closure")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("artifact")).toBeInTheDocument();
    expect(screen.getByText("scorecard")).toBeInTheDocument();
  });

  it("keeps policy decision ids visible for API/UI/card matching", () => {
    render(<PolicyDecisionsPanel policyDecisions={phase6PolicyDecisionsFixture} />);

    expect(screen.getByText("Policy Decisions")).toBeInTheDocument();
    expect(screen.getByText("pd_phase6_denied")).toBeInTheDocument();
    expect(screen.getByText("shadow_denied")).toBeInTheDocument();
  });

  it("shows claim audit claim ids and redacts secret-looking values", () => {
    render(<ClaimAuditPanel claimsResponse={phase6ClaimSetFixture} />);

    expect(screen.getByText("Claim Audit")).toBeInTheDocument();
    expect(screen.getAllByText("claim_tradable_phase6").length).toBeGreaterThan(0);
    expect(screen.getByText("tradable")).toBeInTheDocument();
    expect(screen.queryByText(/sk-live-should-not-render/i)).not.toBeInTheDocument();
    expect(screen.getByText("[REDACTED]")).toBeInTheDocument();
  });

  it("keeps hard failures and triggered rule evidence refs visible", () => {
    render(<QuantScorecardPanel card={phase6RunCardFixture} />);

    expect(screen.getByText("Scorecard Triggered Rules")).toBeInTheDocument();
    expect(screen.getAllByText("tradable_claim_without_cost_model").length).toBeGreaterThan(0);
    expect(screen.getByText("SC_COST_MODEL_REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("claim_tradable_phase6")).toBeInTheDocument();
  });

  it("fixture decision ids and hard failures match across panels", () => {
    const cardDecisionIds = phase6RunCardFixture.policy_decision_ids;
    const apiDecisionIds = phase6PolicyDecisionsFixture.decision_ids;
    const cardHardFailures = phase6RunCardFixture.hard_failures;
    const rulePanel = render(<QuantScorecardPanel card={phase6RunCardFixture} />);

    expect(cardDecisionIds).toEqual(apiDecisionIds);
    expect(cardHardFailures).toEqual(["tradable_claim_without_cost_model"]);
    const hardFailureList = rulePanel.container.querySelector("[data-testid='hard-failures']");
    expect(hardFailureList).not.toBeNull();
    expect(within(hardFailureList as HTMLElement).getByText("tradable_claim_without_cost_model")).toBeInTheDocument();
  });
});
