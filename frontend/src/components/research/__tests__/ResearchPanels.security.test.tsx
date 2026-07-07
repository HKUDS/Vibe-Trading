import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClaimAuditPanel } from "../ClaimAuditPanel";
import { EvidenceClosurePanel } from "../EvidenceClosurePanel";
import { PolicyDecisionsPanel } from "../PolicyDecisionsPanel";
import { QuantScorecardPanel } from "../QuantScorecardPanel";
import { researchPayloadToMarkdown } from "../redaction";
import type { EvidenceClosureSummary, PolicyDecisionsResponse, ResearchClaimsResponse, RunCard } from "@/lib/api";

const RAW_SENTINEL = "PHASE10_RAW_SECRET_SENTINEL";
const BEARER_SENTINEL = `Bearer ${RAW_SENTINEL.repeat(2)}`;
const ENV_SENTINEL = `OPENAI_API_KEY=${RAW_SENTINEL}`;
const BROKER_SENTINEL = `broker_password=${RAW_SENTINEL}`;

function textContent(): string {
  return document.body.textContent || "";
}

describe("Phase 10.1 research panel security", () => {
  it("redacts secret-like keys in all research panels", () => {
    const evidence: EvidenceClosureSummary = {
      passed: false,
      missing_refs: [`api_key=${RAW_SENTINEL}`],
      verified_from: [],
    };
    const policies: PolicyDecisionsResponse = {
      schema_version: "1.2.1",
      run_id: "run_security",
      decision_ids: [`token=${RAW_SENTINEL}`],
      decisions: [
        {
          decision_id: "pd_security",
          tool_name: "fake_shell",
          action: "deny",
          status: "shadow_denied",
          mode: "warn",
          surface: "remote_api",
          risk_level: "R5_SHELL",
          reason_codes: [`credential=${RAW_SENTINEL}`],
          evidence_refs: [],
        },
      ],
    };
    const claims: ResearchClaimsResponse = {
      schema_version: "1.2.1",
      run_id: "run_security",
      claim_ids: [`password=${RAW_SENTINEL}`],
      claim_set: {
        claim_set_id: "claims_security",
        run_id: "run_security",
        claims: [
          {
            claim_id: "claim_security",
            claim_type: "tradable",
            claim_text: `secret=${RAW_SENTINEL}`,
            evidence_refs: [`api_key=${RAW_SENTINEL}`],
          },
        ],
      },
    };
    const card: RunCard = {
      run_id: "run_security",
      hard_failures: [`token=${RAW_SENTINEL}`],
      triggered_rules: [
        {
          rule_id: `secret=${RAW_SENTINEL}`,
          reason_code: "SECURITY",
          action: "hard_fail",
          explanation: "blocked",
          evidence_refs: [`password=${RAW_SENTINEL}`],
        },
      ],
    };

    render(
      <>
        <EvidenceClosurePanel summary={evidence} />
        <PolicyDecisionsPanel policyDecisions={policies} />
        <ClaimAuditPanel claimsResponse={claims} />
        <QuantScorecardPanel card={card} />
      </>,
    );

    expect(textContent()).not.toContain(RAW_SENTINEL);
    expect(screen.getAllByText("[REDACTED]").length).toBeGreaterThanOrEqual(4);
  });

  it("redacts bearer token values", () => {
    render(
      <ClaimAuditPanel
        claimsResponse={{
          schema_version: "1.2.1",
          run_id: "run_bearer",
          claim_ids: [],
          claim_set: {
            claim_set_id: "claims_bearer",
            run_id: "run_bearer",
            claims: [{ claim_id: "claim_bearer", claim_type: "alpha", claim_text: BEARER_SENTINEL }],
          },
        }}
      />,
    );

    expect(textContent()).not.toContain(RAW_SENTINEL);
    expect(screen.getByText("[REDACTED]")).toBeInTheDocument();
  });

  it("redacts env-style secrets", () => {
    render(
      <PolicyDecisionsPanel
        decisionIds={[ENV_SENTINEL]}
      />,
    );

    expect(textContent()).not.toContain(RAW_SENTINEL);
    expect(screen.getByText("[REDACTED]")).toBeInTheDocument();
  });

  it("redacts broker credential-looking values", () => {
    render(
      <QuantScorecardPanel
        card={{
          run_id: "run_broker",
          hard_failures: [BROKER_SENTINEL],
          triggered_rules: [],
        }}
      />,
    );

    expect(textContent()).not.toContain(RAW_SENTINEL);
    expect(screen.getByText("[REDACTED]")).toBeInTheDocument();
  });

  it("exported Markdown is redacted", () => {
    const markdown = researchPayloadToMarkdown({
      title: "Security Export",
      token: RAW_SENTINEL,
      nested: { authorization: `Bearer ${RAW_SENTINEL.repeat(2)}` },
      visible: "ok",
    });

    expect(markdown).toContain("visible: ok");
    expect(markdown).not.toContain(RAW_SENTINEL);
    expect(markdown).toContain("[REDACTED]");
  });

  it("malicious script renders as text and does not execute", () => {
    Reflect.deleteProperty(window, "__phase10ScriptRan");

    render(
      <ClaimAuditPanel
        claimsResponse={{
          schema_version: "1.2.1",
          run_id: "run_script",
          claim_ids: [],
          claim_set: {
            claim_set_id: "claims_script",
            run_id: "run_script",
            claims: [
              {
                claim_id: "claim_script",
                claim_type: "alpha",
                claim_text: "<script>window.__phase10ScriptRan = true</script>",
              },
            ],
          },
        }}
      />,
    );

    expect(screen.getByText("<script>window.__phase10ScriptRan = true</script>")).toBeInTheDocument();
    expect((window as unknown as { __phase10ScriptRan?: boolean }).__phase10ScriptRan).toBeUndefined();
    expect(document.querySelector("script")).toBeNull();
  });

  it("no raw sentinel appears in DOM", () => {
    render(<EvidenceClosurePanel summary={{ passed: false, missing_refs: [`secret=${RAW_SENTINEL}`] }} />);

    expect(document.body.innerHTML).not.toContain(RAW_SENTINEL);
  });

  it("no raw sentinel appears in export text", () => {
    const markdown = researchPayloadToMarkdown({ credential: RAW_SENTINEL });

    expect(markdown).not.toContain(RAW_SENTINEL);
  });
});
