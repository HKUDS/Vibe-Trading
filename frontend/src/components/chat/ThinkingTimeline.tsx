import { memo, useMemo } from "react";
import { ActivityLine } from "@/components/chat/ActivityLine";
import {
  deriveActivityVerb,
  type AgentActivity,
  type StoredAgentMessage,
} from "@/stores/agent";
import type { ToolCallEntry } from "@/types/agent";

interface Props {
  messages: StoredAgentMessage[];
  isLatest?: boolean;
  onContinue?: (activity: AgentActivity) => void;
  onReattach?: (activity: AgentActivity) => void;
}

function rebuildLegacyActivity(
  messages: StoredAgentMessage[],
  isLatest: boolean,
): AgentActivity {
  const steps: ToolCallEntry[] = [];

  for (const message of messages) {
    if (message.type === "tool_call") {
      steps.push({
        id: message.id,
        tool: message.tool || "",
        arguments: message.args ?? {},
        status: message.status === "running" ? "running" : "ok",
        timestamp: message.timestamp,
      });
      continue;
    }
    if (message.type !== "tool_result") continue;
    const existing = [...steps].reverse().find((step) => (
      step.tool === message.tool && step.status === "running"
    )) ?? [...steps].reverse().find((step) => step.tool === message.tool);
    if (existing) {
      existing.status = message.status === "error" ? "error" : "ok";
      existing.elapsed_ms = message.elapsed_ms;
      existing.preview = message.content;
    }
  }

  const startedAt = messages[0]?.timestamp ?? Date.now();
  const isRunning = isLatest || steps.some((step) => step.status === "running");
  return {
    attemptId: messages[0]?.id || `legacy-${startedAt}`,
    state: isRunning ? (steps.length > 0 ? "working" : "thinking") : "done",
    verb: deriveActivityVerb(steps[steps.length - 1]?.tool),
    steps,
    startedAt,
    endedAt: isRunning
      ? undefined
      : startedAt + steps.reduce((sum, step) => sum + (step.elapsed_ms ?? 0), 0),
  };
}

/**
 * Compatibility adapter for transcript groups.
 *
 * New turns carry one durable activity object; older tool_call/tool_result
 * groups are reconstructed once and handed to the same ActivityLine renderer.
 */
export const ThinkingTimeline = memo(function ThinkingTimeline({
  messages,
  isLatest = false,
  onContinue,
  onReattach,
}: Props) {
  const activity = useMemo(
    () => messages.find((message) => message.meta?.activity)?.meta?.activity
      ?? rebuildLegacyActivity(messages, isLatest),
    [isLatest, messages],
  );

  return (
    <ActivityLine
      activity={activity}
      onContinue={onContinue ? () => onContinue(activity) : undefined}
      onReattach={onReattach ? () => onReattach(activity) : undefined}
    />
  );
});
