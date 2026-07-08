import { alphaGenesisDecisionBadge, type AlphaGenesisDecision } from "../alphaGenesisSecurity";

describe("Alpha Genesis decision badge truthfulness", () => {
  it.each<AlphaGenesisDecision>([
    "reject",
    "research_only",
    "candidate_zoo",
    "paper_candidate",
    "forward_track",
  ])("never presents %s as live or production ready", (decision) => {
    const badge = alphaGenesisDecisionBadge(decision);

    expect(badge.label).not.toMatch(/live ready|production ready/i);
    expect(badge.researchOnly).toBe(true);
    expect(badge.liveReady).toBe(false);
    expect(badge.productionReady).toBe(false);
  });
});
