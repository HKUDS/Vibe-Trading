import type {
  EvidenceClosureSummary,
  PolicyDecisionsResponse,
  ResearchClaimsResponse,
  RunCard,
} from "@/lib/api";

export const phase6EvidenceSummaryFixture: EvidenceClosureSummary = {
  schema_version: "1.2.1",
  passed: true,
  degraded: false,
  verified_from: ["artifact", "scorecard", "card"],
  missing_refs: [],
  dangling_refs: [],
  inconsistent_ids: [],
  outbox_pending: [],
  degraded_reasons: [],
};

export const phase6PolicyDecisionsFixture: PolicyDecisionsResponse = {
  schema_version: "1.2.1",
  run_id: "run_phase6_ui",
  decision_ids: ["pd_phase6_denied"],
  decisions: [
    {
      decision_id: "pd_phase6_denied",
      tool_name: "fake_shell",
      action: "deny",
      status: "shadow_denied",
      mode: "warn",
      surface: "remote_api",
      risk_level: "R5_SHELL",
      reason_codes: ["R5_REMOTE_API_DENIED"],
      evidence_refs: ["art_policy_phase6"],
      trace_event_id: "trace_phase6",
      ledger_event_hash: "ledger_phase6",
    },
  ],
};

export const phase6ClaimSetFixture: ResearchClaimsResponse = {
  schema_version: "1.2.1",
  run_id: "run_phase6_ui",
  artifact_ref: "art_claims_phase6",
  claim_ids: ["claim_tradable_phase6"],
  claim_set: {
    schema_version: "1.2.1",
    claim_set_id: "claim_set_phase6",
    run_id: "run_phase6_ui",
    extractor_version: "deterministic-v1.2.1",
    generated_by: "research_card.claim_extractor",
    artifact_ref: "art_claims_phase6",
    claims: [
      {
        schema_version: "1.2.1",
        claim_id: "claim_tradable_phase6",
        claim_type: "tradable",
        claim_text: "Research card claim text is redacted upstream.",
        source: "research_card",
        source_ref: "research_card.structured_claims[0]",
        confidence: 0.9,
        requires_gate: true,
        evidence_refs: ["claim_tradable_phase6"],
        created_at: "2026-07-07T00:00:00Z",
      },
    ],
  },
};

export const phase6RunCardFixture: RunCard = {
  schema_version: "1.2.1",
  run_id: "run_phase6_ui",
  conclusion_level: "not_reliable",
  evidence_closure_summary: phase6EvidenceSummaryFixture,
  policy_decision_ids: ["pd_phase6_denied"],
  claim_set_ref: "art_claims_phase6",
  methodology_fact_ref: "art_facts_phase6",
  scorecard_ref: "art_scorecard_phase6",
  claim_ids: ["claim_tradable_phase6"],
  hard_failures: ["tradable_claim_without_cost_model"],
  triggered_rules: [
    {
      schema_version: "1.2.1",
      rule_id: "tradable_claim_without_cost_model",
      reason_code: "SC_COST_MODEL_REQUIRED",
      action: "hard_fail",
      explanation: "Tradable claim requires an explicit cost model.",
      evidence_refs: ["claim_tradable_phase6", "has_cost_model"],
      conclusion_cap: "not_reliable",
    },
  ],
};
