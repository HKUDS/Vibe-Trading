import { prependUploadedAttachments, type UploadedAttachment } from "@/lib/attachments";

// Match the interactive and goal request schemas in sessions_routes.py.
export const MAX_MESSAGE_CHARS = 100_000;
export const MAX_GOAL_CHARS = 5_000;
export const SWARM_PROMPT_PREFIX =
  "[Swarm Team Mode] Use the swarm tool to assemble the best specialist team for this task. Auto-select the most appropriate preset.\n\n";

export function buildChatPrompt(prompt: string, attachments: UploadedAttachment[], swarm: boolean): string {
  return prependUploadedAttachments(swarm ? `${SWARM_PROMPT_PREFIX}${prompt}` : prompt, attachments);
}

/** Python validates Unicode code points; JS string.length counts UTF-16 units. */
export function promptExceedsLimit(prompt: string, limit: number): boolean {
  let count = 0;
  for (const _character of prompt) {
    if (++count > limit) return true;
  }
  return false;
}
