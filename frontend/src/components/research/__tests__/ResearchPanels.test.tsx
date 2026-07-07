import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClaimAuditPanel } from "../ClaimAuditPanel";
import { DataProvenancePanel } from "../DataProvenancePanel";
import { EvidenceClosurePanel } from "../EvidenceClosurePanel";
import { PITWarningsPanel } from "../PITWarningsPanel";
import { PolicyDecisionsPanel } from "../PolicyDecisionsPanel";
import { QuantScorecardPanel } from "../QuantScorecardPanel";
import { ResearchCardPanel } from "../ResearchCardPanel";
import {
  phase6ClaimSetFixture,
  phase6EvidenceSummaryFixture,
  phase6PolicyDecisionsFixture,
  phase6RunCardFixture,
} from "../fixtures";

describe("research reliability panels", () => {
  it("renders a missing card empty state", () => {
    render(<ResearchCardPanel card={null} />);

    expect(screen.getByText("No Research Card available")).toBeInTheDocument();
  });

  it("keeps hard failures visible", () => {
    render(
      <ResearchCardPanel
        card={{
          card_id: "card_1",
          schema_version: "1.0.0",
          title: "Study",
          conclusion_level: "not_reliable",
          hard_failures: [{ code: "PIT_FUTURE_DATA", severity: "hard_failure", message: "future data" }],
          warnings: [],
        }}
      />,
    );

    expect(screen.getByText("PIT_FUTURE_DATA")).toBeInTheDocument();
    expect(screen.getByText("not_reliable")).toBeInTheDocument();
  });

  it("renders benchmark cost OOS and trial count evidence", () => {
    render(
      <ResearchCardPanel
        card={{
          card_id: "card_2",
          schema_version: "1.0.0",
          title: "Study",
          conclusion_level: "research_candidate",
          benchmark: { primary: "CSI300" },
          cost_model: { commission_bps: 2, slippage_bps: 5 },
          oos_results: { fold_count: 4 },
          key_metrics: { trial_count: 12 },
          hard_failures: [],
          warnings: [],
        }}
      />,
    );

    expect(screen.getByText("CSI300")).toBeInTheDocument();
    expect(screen.getByText("commission_bps: 2")).toBeInTheDocument();
    expect(screen.getByText("fold_count: 4")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders score breakdown entries", () => {
    render(
      <QuantScorecardPanel
        scorecard={{
          scorecard_id: "sc_1",
          schema_version: "1.0.0",
          score: 0.5,
          conclusion_cap: "research_candidate",
          score_breakdown: { pit_clean: 1, oos_split: 0, cost_model: 0.5 },
          warnings: [],
          hard_failures: [],
        }}
      />,
    );

    expect(screen.getByText("pit_clean")).toBeInTheDocument();
    expect(screen.getByText("oos_split")).toBeInTheDocument();
    expect(screen.getByText("research_candidate")).toBeInTheDocument();
  });

  it("renders PIT warnings and failures", () => {
    render(
      <PITWarningsPanel
        warnings={[{ code: "DATA_AVAILABLE_AT_MISSING", severity: "warning", message: "missing available_at" }]}
        hardFailures={[{ code: "PIT_FUTURE_DATA", severity: "hard_failure", message: "future data" }]}
      />,
    );

    expect(screen.getByText("DATA_AVAILABLE_AT_MISSING")).toBeInTheDocument();
    expect(screen.getByText("PIT_FUTURE_DATA")).toBeInTheDocument();
  });

  it("renders policy warning and deny counts", () => {
    render(
      <PolicyDecisionsPanel
        decisions={[
          { decision_id: "pd_1", tool_name: "bash", action: "deny", rule_id: "P20" },
          { decision_id: "pd_2", tool_name: "web_search", action: "warn", rule_id: "P900" },
        ]}
      />,
    );

    expect(screen.getByText("Denied")).toBeInTheDocument();
    expect(screen.getByText("Warned")).toBeInTheDocument();
    expect(screen.getByText("P20")).toBeInTheDocument();
  });

  it("renders data source and fallback path", () => {
    render(
      <DataProvenancePanel
        dataSources={[
          {
            audit_id: "audit_1",
            source: "auto",
            selected_source: "local_cache",
            fallback_chain: ["local_cache", "vendor"],
          },
        ]}
      />,
    );

    expect(screen.getByText("local_cache")).toBeInTheDocument();
    expect(screen.getByText("local_cache -> vendor")).toBeInTheDocument();
  });
});

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
    const fixtureWithSyntheticSecret = JSON.parse(JSON.stringify(phase6ClaimSetFixture));
    fixtureWithSyntheticSecret.claim_set.claims[0].claim_text = "sk-live-should-not-render";

    render(<ClaimAuditPanel claimsResponse={fixtureWithSyntheticSecret} />);

    expect(screen.getByText("Claim Audit")).toBeInTheDocument();
    expect(screen.getAllByText("claim_tradable_phase6").length).toBeGreaterThan(0);
    expect(screen.getByText("tradable")).toBeInTheDocument();
    expect(screen.queryByText(/sk-live-should-not-render/i)).not.toBeInTheDocument();
    expect(screen.getByText("[REDACTED]")).toBeInTheDocument();
  });

  it("keeps hard failures and triggered rule evidence refs visible", () => {
    render(<QuantScorecardPanel card={phase6RunCardFixture} />);

    expect(screen.getByText("Quant Scorecard")).toBeInTheDocument();
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
