import { render, screen } from "@testing-library/react";
import { DataProvenancePanel } from "../DataProvenancePanel";
import { PITWarningsPanel } from "../PITWarningsPanel";
import { PolicyDecisionsPanel } from "../PolicyDecisionsPanel";
import { QuantScorecardPanel } from "../QuantScorecardPanel";
import { ResearchCardPanel } from "../ResearchCardPanel";

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

  it("redacts secret-like values before rendering research card evidence", () => {
    render(
      <ResearchCardPanel
        card={{
          card_id: "card_secret",
          schema_version: "1.0.0",
          title: "Secret Fixture",
          hypothesis: "Authorization: Bearer fixture-token",
          conclusion_level: "exploratory",
          cost_model: { api_key: "sk-test-123456", commission_bps: 2 },
          hard_failures: [{ code: "SECRET_FIXTURE", severity: "hard_failure", message: "AWS_SECRET_ACCESS_KEY=fixture" }],
          warnings: [],
        }}
      />,
    );

    expect(screen.queryByText(/fixture-token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-test-123456/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/AWS_SECRET_ACCESS_KEY=fixture/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("[REDACTED]").length).toBeGreaterThan(0);
  });

  it("redacts secret-like values in policy, PIT, scorecard, and data provenance panels", () => {
    render(
      <>
        <PolicyDecisionsPanel decisions={[{ decision_id: "pd_1", tool_name: "Authorization: Bearer fixture-token", action: "deny", rule_id: "AWS_SECRET_ACCESS_KEY=fixture" }]} />
        <PITWarningsPanel warnings={[{ code: "DATA_AVAILABLE_AT_MISSING", severity: "warning", message: "Authorization: Bearer fixture-token" }]} />
        <QuantScorecardPanel scorecard={{ conclusion_cap: "AWS_SECRET_ACCESS_KEY=fixture", score_breakdown: { "Authorization: Bearer fixture-token": 1 } }} />
        <DataProvenancePanel dataSources={[{ source: "AWS_SECRET_ACCESS_KEY=fixture", selected_source: "local_cache", fallback_chain: ["Authorization: Bearer fixture-token"] }]} />
      </>,
    );

    expect(screen.queryByText(/fixture-token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/AWS_SECRET_ACCESS_KEY=fixture/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("[REDACTED]").length).toBeGreaterThan(0);
  });

  it("renders malicious HTML fixtures as text instead of executable markup", () => {
    render(
      <PITWarningsPanel
        warnings={[{ code: "DATA_AVAILABLE_AT_MISSING", severity: "warning", message: "<script>window.__pwned = true</script>" }]}
      />,
    );

    expect(screen.getByText("<script>window.__pwned = true</script>")).toBeInTheDocument();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });
});
