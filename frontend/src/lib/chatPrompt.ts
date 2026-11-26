import { extractUploadedAttachments, prependUploadedAttachments, type UploadedAttachment } from "@/lib/attachments";

// Match the interactive and goal request schemas in sessions_routes.py.
export const MAX_MESSAGE_CHARS = 100_000;
export const MAX_GOAL_CHARS = 5_000;

export function isPersistedMessageId(messageId: string): boolean {
  return /^[a-f0-9]{12}$/i.test(messageId);
}

export const SWARM_PROMPT_PREFIX =
  "[Swarm Team Mode] Use the swarm tool to assemble the best specialist team for this task. Auto-select the most appropriate preset.\n\n";
export const GOAL_KICKOFF_PREFIX = [
  "Start working on this research goal now.",
  "Keep it research-only, use available tools when evidence is needed, add concrete evidence to the goal ledger, and keep going until the goal is complete, blocked, waiting for user input, or budget-limited.",
  "",
  "Goal: ",
].join("\n");
export const GOAL_CONTINUE_PREFIX = [
  "Continue the active research goal.",
  "Use real available tools as needed, add evidence to the goal ledger, and only stop when the goal is complete, blocked, waiting for user input, or budget-limited.",
  "",
  "Goal: ",
].join("\n");

export function buildChatPrompt(prompt: string, attachments: UploadedAttachment[], swarm: boolean): string {
  return prependUploadedAttachments(swarm ? `${SWARM_PROMPT_PREFIX}${prompt}` : prompt, attachments);
}

/** Replace visible prompt text while retaining transport wrappers and hidden goal details. */
export function replacePromptText(rawPrompt: string, editedPrompt: string): string {
  const extracted = extractUploadedAttachments(rawPrompt);
  let body = extracted.content;
  let prefix = rawPrompt.slice(0, rawPrompt.length - body.length);

  if (body.startsWith(SWARM_PROMPT_PREFIX)) {
    prefix += SWARM_PROMPT_PREFIX;
    body = body.slice(SWARM_PROMPT_PREFIX.length);
  }

  let suffix = "";
  if (body.startsWith(GOAL_KICKOFF_PREFIX)) {
    prefix += GOAL_KICKOFF_PREFIX;
  } else if (body.startsWith(GOAL_CONTINUE_PREFIX)) {
    prefix += GOAL_CONTINUE_PREFIX;
    body = body.slice(GOAL_CONTINUE_PREFIX.length);
    const detailsStart = [
      body.indexOf("\nOpen criteria:"),
      body.indexOf("\nAll criteria appear covered;"),
    ].filter((index) => index >= 0);
    if (detailsStart.length > 0) {
      const boundary = Math.min(...detailsStart);
      suffix = body.slice(boundary);
    }
  }

  return `${prefix}${editedPrompt}${suffix}`;
}

/** Python validates Unicode code points; JS string.length counts UTF-16 units. */
export function promptExceedsLimit(prompt: string, limit: number): boolean {
  let count = 0;
  for (const _character of prompt) {
    if (++count > limit) return true;
  }
  return false;
}
