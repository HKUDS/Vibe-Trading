import { describe, expect, it } from "vitest";
import { calculateAverageRisk, calculateJournalCompliance, calculateJournalWinRate, groupEntriesByPair, groupEntriesBySession, groupEntriesByWeekday, identifyFrequentRuleViolations, summarizeJournalEntries, type JournalEntry } from "../journal";

const base: JournalEntry = { pair: "EUR/USD", direction: "Long", riskPercentage: 1, outcome: "Win", session: "London", date: "2026-07-13" };

describe("journal utilities", () => {
  it("handles an empty journal", () => {
    expect(summarizeJournalEntries([])).toMatchObject({ totalEntries: 0, wins: 0, losses: 0, winRate: 0, averageRisk: 0 });
  });

  it("summarizes a single winning trade", () => {
    expect(summarizeJournalEntries([base]).winRate).toBe(1);
  });

  it("summarizes a single losing trade", () => {
    expect(summarizeJournalEntries([{ ...base, outcome: "Loss" }]).winRate).toBe(0);
  });

  it("summarizes mixed outcomes", () => {
    const result = summarizeJournalEntries([base, { ...base, outcome: "Loss", riskPercentage: 2 }, { ...base, outcome: "Break Even" }]);
    expect(result.wins).toBe(1);
    expect(result.losses).toBe(1);
    expect(result.breakEven).toBe(1);
    expect(result.averageRisk).toBeCloseTo(1.3333);
  });

  it("handles missing optional fields", () => {
    expect(groupEntriesByPair([{ outcome: "Win" }])["Unspecified pair"]).toHaveLength(1);
    expect(groupEntriesBySession([{ outcome: "Loss" }])["Unspecified session"]).toHaveLength(1);
  });

  it("groups multiple pairs", () => {
    const grouped = groupEntriesByPair([base, { ...base, pair: "GBP/JPY" }]);
    expect(Object.keys(grouped)).toEqual(["EUR/USD", "GBP/JPY"]);
  });

  it("groups multiple sessions", () => {
    const grouped = groupEntriesBySession([base, { ...base, session: "New York" }]);
    expect(grouped.London).toHaveLength(1);
    expect(grouped["New York"]).toHaveLength(1);
  });

  it("groups by weekday", () => {
    expect(groupEntriesByWeekday([base]).Monday).toHaveLength(1);
  });

  it("calculates compliance percentage", () => {
    const result = calculateJournalCompliance({ followedSetupRules: true, respectedRiskLimit: true, waitedForConfirmation: true, avoidedRevengeTrading: false, avoidedOvertrading: true, followedSessionPlan: true, recordedPostTradeReview: false });
    expect(result.compliancePercentage).toBeCloseTo((5 / 7) * 100);
    expect(result.classification).toBe("Controlled");
  });

  it("identifies repeated violations", () => {
    const result = identifyFrequentRuleViolations([{ ...base, ruleViolations: ["Early exit", "Overtrading"] }, { ...base, ruleViolations: ["Early exit"] }]);
    expect(result[0]).toEqual({ rule: "Early exit", count: 2 });
  });

  it("rejects invalid risk values", () => {
    expect(() => calculateAverageRisk([{ ...base, riskPercentage: -1 }])).toThrow();
    expect(() => calculateJournalWinRate([{ ...base, riskPercentage: Number.NaN }])).toThrow();
  });

  it("protects against NaN and Infinity", () => {
    expect(() => summarizeJournalEntries([{ ...base, riskPercentage: Number.POSITIVE_INFINITY }])).toThrow();
  });
});
