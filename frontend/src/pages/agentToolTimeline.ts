import {
  deriveActivityVerb,
  type ActivityState,
  type AgentActivity,
  type StoredAgentMessage,
} from "@/stores/agent";

export interface ToolTimelineEntry {
  id?: string;
  call_id?: string;
  tool: string;
  arguments?: Record<string, string>;
  status?: "running" | "ok" | "error";
  preview?: string;
  elapsed_ms?: number;
  timestamp?: number;
}

interface ToolTimelineOptions {
  fallbackTimestamp?: number;
  idPrefix?: string;
  attemptId?: string;
  state?: ActivityState;
  /** Attempt wall-clock start (ms). When known it beats the first-tool guess. */
  startedAt?: number;
  endedAt?: number;
  activity?: AgentActivity;
}

/** Convert one attempt's consolidated tool records into its durable activity row. */
export function buildToolTimelineMessages(
  entries: readonly ToolTimelineEntry[],
  options: ToolTimelineOptions = {},
): StoredAgentMessage[] {
  const fallbackTimestamp = options.fallbackTimestamp ?? Date.now();
  const idPrefix = options.idPrefix ?? "";
  const steps = entries.map((entry, index) => ({
    id: entry.id || entry.call_id || `${entry.tool}#${index + 1}`,
    tool: entry.tool,
    arguments: entry.arguments ?? {},
    status: entry.status || "ok",
    preview: entry.preview,
    elapsed_ms: entry.elapsed_ms,
    timestamp: (
      typeof entry.timestamp === "number" && Number.isFinite(entry.timestamp)
        ? entry.timestamp
        : fallbackTimestamp + index
    ),
  }));
  // The first tool call is only a lower bound on when the attempt started: the
  // model thinks before it reaches for a tool, and a pure-text turn has no
  // tools at all. Prefer the attempt's recorded start when the caller has it.
  const inferredStart = steps.length > 0
    ? Math.min(...steps.map((step) => step.timestamp))
    : fallbackTimestamp;
  const startedAt = (
    typeof options.startedAt === "number" && Number.isFinite(options.startedAt)
      ? Math.min(options.startedAt, inferredStart)
      : inferredStart
  );
  const inferredEnd = Math.max(
    fallbackTimestamp,
    startedAt + steps.reduce((sum, step) => sum + (step.elapsed_ms ?? 0), 0),
  );
  const activity: AgentActivity = options.activity ?? {
    attemptId: options.attemptId || `${idPrefix}attempt`,
    state: options.state ?? "done",
    verb: deriveActivityVerb(steps[steps.length - 1]?.tool),
    steps,
    startedAt,
    endedAt: options.endedAt ?? inferredEnd,
  };

  return [{
    id: `${idPrefix}activity_${activity.attemptId}`,
    type: "thinking",
    content: "",
    meta: { activity },
    timestamp: activity.startedAt,
  }];
}
