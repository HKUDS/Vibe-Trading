import type { MessageItem, RunPreview } from "@/lib/api";
import { hasStoredMetrics, runCardFields } from "@/lib/runCards";
import { buildToolTimelineMessages } from "@/pages/agentToolTimeline";
import type { AgentMessageMeta, StoredAgentMessage } from "@/stores/agent";

export interface LegacyTranscriptOptions {
  displayPrompt: (content: string) => { content: string; meta?: AgentMessageMeta };
  previews: ReadonlyMap<string, RunPreview | null>;
}

/** Project pre-thread messages into the one fallback transcript. */
export function buildLegacyTranscript(
  rows: readonly MessageItem[],
  options: LegacyTranscriptOptions,
): StoredAgentMessage[] {
  const messages: StoredAgentMessage[] = [];
  for (const message of rows) {
    const meta = message.metadata as Record<string, unknown> | undefined;
    const runId = typeof meta?.run_id === "string" ? meta.run_id : undefined;
    const metrics = meta?.metrics as Record<string, number> | undefined;
    const elapsedMs = typeof meta?.elapsed_ms === "number" ? meta.elapsed_ms : undefined;
    const timestamp = new Date(message.created_at).getTime();
    const startedAt = typeof meta?.started_at === "number" && meta.started_at > 0
      ? meta.started_at * 1000
      : elapsedMs != null ? timestamp - elapsedMs : undefined;
    const timeline = message.role === "assistant"
      ? buildToolTimelineMessages(message.tool_trail ?? [], {
          fallbackTimestamp: timestamp,
          idPrefix: `${message.message_id}_`,
          attemptId: message.linked_attempt_id || `${message.message_id}_attempt`,
          state: meta?.status === "failed" ? "failed" : meta?.status === "cancelled" ? "stopped" : "done",
          startedAt,
          endedAt: timestamp,
        })
      : [];
    messages.push(...timeline);
    const lastToolTimestamp = timeline.length > 0 ? timeline[timeline.length - 1].timestamp : timestamp - 1;
    const assistantTimestamp = Math.max(timestamp, lastToolTimestamp + 1);
    if (message.role === "user") {
      const prompt = options.displayPrompt(message.content);
      messages.push({ id: message.message_id, type: "user", content: prompt.content, meta: prompt.meta, timestamp });
      continue;
    }
    if (runId) {
      if (message.content && message.content !== "Strategy execution completed.") {
        messages.push({ id: `${message.message_id}_ans`, type: "answer", content: message.content, elapsed_ms: elapsedMs, timestamp: assistantTimestamp });
      }
      const card = hasStoredMetrics(metrics) ? { metrics } : runCardFields(options.previews.get(runId) ?? null);
      if (card) messages.push({ id: message.message_id, type: "run_complete", content: "", runId, ...card, timestamp: assistantTimestamp + 1 });
      continue;
    }
    messages.push({ id: message.message_id, type: "answer", content: message.content, elapsed_ms: elapsedMs, timestamp: assistantTimestamp });
  }
  return messages;
}
