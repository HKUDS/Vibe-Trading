export type JournalOutcome = "Win" | "Loss" | "Break Even";
export type JournalDirection = "Long" | "Short";
export type RuleComplianceClassification = "Strong Discipline" | "Controlled" | "Inconsistent" | "High-Risk Behaviour";

export interface JournalEntry {
  id?: string;
  pair?: string;
  direction?: JournalDirection;
  entry?: number;
  exit?: number;
  stopLoss?: number;
  takeProfit?: number;
  riskPercentage?: number;
  outcome?: JournalOutcome;
  session?: string;
  date?: string;
  setup?: string;
  emotion?: string;
  ruleViolations?: string[];
  notes?: string;
}

export interface JournalComplianceInput {
  followedSetupRules: boolean;
  respectedRiskLimit: boolean;
  waitedForConfirmation: boolean;
  avoidedRevengeTrading: boolean;
  avoidedOvertrading: boolean;
  followedSessionPlan: boolean;
  recordedPostTradeReview: boolean;
  entries?: JournalEntry[];
}

const RULE_LABELS: Record<keyof Omit<JournalComplianceInput, "entries">, string> = {
  followedSetupRules: "Followed setup rules",
  respectedRiskLimit: "Respected risk limit",
  waitedForConfirmation: "Waited for confirmation",
  avoidedRevengeTrading: "Avoided revenge trading",
  avoidedOvertrading: "Avoided overtrading",
  followedSessionPlan: "Followed session plan",
  recordedPostTradeReview: "Recorded post-trade review",
};

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && !Number.isNaN(value);
}

function assertValidRisk(entry: JournalEntry) {
  if (entry.riskPercentage == null) return;
  if (!finite(entry.riskPercentage) || entry.riskPercentage < 0) throw new Error("Risk percentage must be a finite non-negative number");
}

export function calculateJournalWinRate(entries: JournalEntry[]): number {
  const decided = entries.filter((entry) => {
    assertValidRisk(entry);
    return entry.outcome === "Win" || entry.outcome === "Loss";
  });
  if (decided.length === 0) return 0;
  return decided.filter((entry) => entry.outcome === "Win").length / decided.length;
}

export function calculateAverageRisk(entries: JournalEntry[]): number {
  const risks = entries.map((entry) => {
    assertValidRisk(entry);
    return entry.riskPercentage;
  }).filter(finite);
  if (risks.length === 0) return 0;
  return risks.reduce((sum, value) => sum + value, 0) / risks.length;
}

export function groupEntriesByPair(entries: JournalEntry[]): Record<string, JournalEntry[]> {
  return groupEntries(entries, (entry) => entry.pair?.trim().toUpperCase() || "Unspecified pair");
}

export function groupEntriesBySession(entries: JournalEntry[]): Record<string, JournalEntry[]> {
  return groupEntries(entries, (entry) => entry.session?.trim() || "Unspecified session");
}

export function groupEntriesByWeekday(entries: JournalEntry[]): Record<string, JournalEntry[]> {
  return groupEntries(entries, (entry) => {
    if (!entry.date) return "Unspecified weekday";
    const date = new Date(`${entry.date}T00:00:00`);
    if (!Number.isFinite(date.getTime())) return "Unspecified weekday";
    return new Intl.DateTimeFormat("en-US", { weekday: "long" }).format(date);
  });
}

function groupEntries(entries: JournalEntry[], keyFor: (entry: JournalEntry) => string): Record<string, JournalEntry[]> {
  return entries.reduce<Record<string, JournalEntry[]>>((groups, entry) => {
    assertValidRisk(entry);
    const key = keyFor(entry);
    groups[key] = [...(groups[key] || []), entry];
    return groups;
  }, {});
}

export function identifyFrequentRuleViolations(entries: JournalEntry[]): Array<{ rule: string; count: number }> {
  const counts = new Map<string, number>();
  for (const entry of entries) {
    assertValidRisk(entry);
    for (const rule of entry.ruleViolations || []) {
      const key = rule.trim();
      if (!key) continue;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return [...counts.entries()].map(([rule, count]) => ({ rule, count })).sort((a, b) => b.count - a.count || a.rule.localeCompare(b.rule));
}

export function summarizeJournalEntries(entries: JournalEntry[]) {
  const wins = entries.filter((entry) => {
    assertValidRisk(entry);
    return entry.outcome === "Win";
  }).length;
  const losses = entries.filter((entry) => entry.outcome === "Loss").length;
  const breakEven = entries.filter((entry) => entry.outcome === "Break Even").length;
  return {
    totalEntries: entries.length,
    wins,
    losses,
    breakEven,
    winRate: calculateJournalWinRate(entries),
    averageRisk: calculateAverageRisk(entries),
    frequentRuleViolations: identifyFrequentRuleViolations(entries),
  };
}

export function calculateJournalCompliance(input: JournalComplianceInput) {
  const keys = Object.keys(RULE_LABELS) as Array<keyof typeof RULE_LABELS>;
  const passed = keys.filter((key) => input[key]).length;
  const compliancePercentage = keys.length === 0 ? 0 : (passed / keys.length) * 100;
  const violatedRules = keys.filter((key) => !input[key]).map((key) => RULE_LABELS[key]);
  const frequentViolations = identifyFrequentRuleViolations(input.entries || []);
  const classification: RuleComplianceClassification = compliancePercentage >= 86
    ? "Strong Discipline"
    : compliancePercentage >= 65
      ? "Controlled"
      : compliancePercentage >= 40
        ? "Inconsistent"
        : "High-Risk Behaviour";
  const improvementFocus = violatedRules[0] || frequentViolations[0]?.rule || "Maintain documented review discipline";
  return { compliancePercentage, violatedRules, improvementFocus, classification };
}
