import { Download, FileCheck2 } from "lucide-react";

import type { QuantScorecardSummary } from "./QuantScorecardPanel";
import type { DataSourceSummary } from "./DataProvenancePanel";
import type { PolicyDecisionSummary } from "./PolicyDecisionsPanel";
import type { StructuredIssue } from "./PITWarningsPanel";
import { redactResearchText } from "./redaction";

export interface ResearchCardSummary {
  card_id: string;
  schema_version?: string;
  title?: string;
  hypothesis?: string | null;
  data_sources?: DataSourceSummary[];
  policy_decisions?: PolicyDecisionSummary[];
  scorecard?: QuantScorecardSummary | null;
  key_metrics?: Record<string, unknown>;
  benchmark?: Record<string, unknown>;
  cost_model?: Record<string, unknown>;
  execution_assumptions?: Record<string, unknown>;
  oos_results?: Record<string, unknown>;
  warnings?: StructuredIssue[];
  hard_failures?: StructuredIssue[];
  conclusion_level?: string;
}

export function ResearchCardPanel({ card }: { card?: ResearchCardSummary | null }) {
  if (!card) {
    return (
      <section className="rounded-md border border-dashed bg-card p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
          <FileCheck2 className="h-4 w-4 text-muted-foreground" />
          Research Card
        </div>
        <p className="text-sm text-muted-foreground">No Research Card available</p>
      </section>
    );
  }

  const hardFailures = card.hard_failures || [];
  const warnings = card.warnings || [];
  const trialCount = card.key_metrics?.trial_count;

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <FileCheck2 className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-medium">{redactResearchText(card.title || "Research Card")}</h2>
        <span className="rounded-md bg-muted px-2 py-1 font-mono text-xs">
          {redactResearchText(card.conclusion_level || "exploratory")}
        </span>
        <button
          onClick={() => downloadMarkdown(card)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-muted"
          title="Export Markdown"
        >
          <Download className="h-3.5 w-3.5" />
          Export Markdown
        </button>
      </div>
      {card.hypothesis && <p className="mb-3 text-sm text-muted-foreground">{redactResearchText(card.hypothesis)}</p>}
      <div className="grid gap-2 sm:grid-cols-3">
        <ResearchStat label="Warnings" value={String(warnings.length)} />
        <ResearchStat label="Hard Failures" value={String(hardFailures.length)} tone={hardFailures.length ? "danger" : "normal"} />
        <ResearchStat label="Schema" value={card.schema_version || "unknown"} />
        <ResearchStat label="Benchmark" value={formatBenchmark(card.benchmark)} />
        <ResearchStat label="OOS" value={hasEvidence(card.oos_results) ? "Recorded" : "Not recorded"} />
        <ResearchStat label="Trial Count" value={formatEvidenceValue(trialCount)} />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <EvidenceBlock title="Cost Model" data={card.cost_model} />
        <EvidenceBlock title="Benchmark" data={card.benchmark} />
        <EvidenceBlock title="OOS" data={card.oos_results} />
      </div>
      {hardFailures.length > 0 && (
        <div className="mt-3 space-y-2">
          {hardFailures.map((failure) => (
            <div key={failure.code} className="rounded-md border border-red-500/25 bg-red-500/5 p-2 text-sm">
              <div className="font-mono text-xs font-medium text-danger">{redactResearchText(failure.code)}</div>
              {failure.message && <div className="mt-1 text-xs text-muted-foreground">{redactResearchText(failure.message)}</div>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function EvidenceBlock({ title, data }: { title: string; data?: Record<string, unknown> }) {
  const entries = Object.entries(data || {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
  return (
    <div className="rounded-md border p-2">
      <div className="mb-1 text-xs text-muted-foreground">{title}</div>
      {entries.length === 0 ? (
        <div className="text-xs text-muted-foreground">Not recorded</div>
      ) : (
        <div className="space-y-1">
          {entries.slice(0, 4).map(([key, value]) => (
            <div key={key} className="truncate font-mono text-xs">
              {redactResearchText(key)}: {formatEvidenceValue(value)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ResearchStat({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "danger" }) {
  return (
    <div className="rounded-md border p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 truncate text-sm font-medium ${tone === "danger" ? "text-danger" : ""}`}>{value}</div>
    </div>
  );
}

function formatBenchmark(value?: Record<string, unknown>): string {
  if (!value || Object.keys(value).length === 0) {
    return "Not recorded";
  }
  return formatEvidenceValue(value.primary ?? Object.values(value)[0]);
}

function hasEvidence(value?: Record<string, unknown>): boolean {
  return Boolean(value && Object.keys(value).length > 0);
}

function formatEvidenceValue(value: unknown): string {
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "unknown";
  }
  if (typeof value === "string") {
    return redactResearchText(value || "Not recorded");
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    return value.map(formatEvidenceValue).join(", ");
  }
  if (value && typeof value === "object") {
    return redactResearchText(JSON.stringify(value));
  }
  return redactResearchText("Not recorded");
}

function downloadMarkdown(card: ResearchCardSummary) {
  const lines = [
    `# Research Card: ${card.title || card.card_id}`,
    "",
    `- Card ID: \`${card.card_id}\``,
    `- Schema Version: \`${card.schema_version || "unknown"}\``,
    `- Conclusion: \`${card.conclusion_level || "exploratory"}\``,
    "",
    "## Evidence",
    `- Benchmark: ${formatBenchmark(card.benchmark)}`,
    `- Trial Count: ${formatEvidenceValue(card.key_metrics?.trial_count)}`,
    ...formatEvidenceLines("Cost Model", card.cost_model),
    ...formatEvidenceLines("OOS", card.oos_results),
    "",
    "## Warnings",
    ...((card.warnings || []).map((warning) => `- \`${warning.code}\`: ${warning.message || ""}`)),
    "",
    "## Hard Failures",
    ...((card.hard_failures || []).map((failure) => `- \`${failure.code}\`: ${failure.message || ""}`)),
    "",
  ];
  const blob = new Blob([lines.map(redactResearchText).join("\n")], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${card.card_id}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function formatEvidenceLines(title: string, data?: Record<string, unknown>): string[] {
  const entries = Object.entries(data || {});
  if (entries.length === 0) {
    return [`- ${title}: Not recorded`];
  }
  return entries.map(([key, value]) => `- ${title} ${key}: ${formatEvidenceValue(value)}`);
}
