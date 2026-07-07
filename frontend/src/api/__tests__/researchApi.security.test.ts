import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  hasRawSecretSentinel,
  normalizeEvidenceClosureReport,
  normalizeResearchClaimsResponse,
} from "@/lib/api";

const RAW_SENTINEL = "PHASE10_RAW_SECRET_SENTINEL";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("Phase 10.1 research API security", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("client treats evidence endpoints as GET-only", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ schema_version: "1.2.1", run_id: "run_api", passed: true, claim_ids: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.getEvidenceClosure("run_api");
    await api.getPolicyDecisions("run_api");
    await api.getResearchClaims("run_api");
    await api.getMethodologyFacts("run_api");

    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit | undefined;
      expect(init?.method ?? "GET").toBe("GET");
    }
  });

  it("parser tolerates legacy v1.1/v1.2 missing fields", () => {
    const normalized = normalizeEvidenceClosureReport({ run_id: "run_legacy", passed: true });

    expect(normalized.run_id).toBe("run_legacy");
    expect(normalized.passed).toBe(true);
    expect(normalized.degraded).toBe(false);
    expect(normalized.verified_from).toEqual([]);
    expect(normalized.missing_refs).toEqual([]);
  });

  it("parser does not require secret-like debug fields", () => {
    const normalized = normalizeResearchClaimsResponse({
      schema_version: "1.2",
      run_id: "run_claims",
      claim_set: {
        claim_set_id: "claim_set_legacy",
        run_id: "run_claims",
        claims: [],
      },
    });

    expect(normalized.claim_ids).toEqual([]);
    expect(normalized.claim_set?.claims).toEqual([]);
    expect("debug_api_key" in normalized).toBe(false);
  });

  it("response fixture contains no raw secret sentinel", () => {
    const fixture = normalizeResearchClaimsResponse({
      schema_version: "1.2.1",
      run_id: "run_fixture",
      claim_ids: ["claim_safe"],
      claim_set: {
        claim_set_id: "claims_fixture",
        run_id: "run_fixture",
        claims: [{ claim_id: "claim_safe", claim_type: "alpha", claim_text: "safe text" }],
      },
    });

    expect(hasRawSecretSentinel(fixture, RAW_SENTINEL)).toBe(false);
  });
});
