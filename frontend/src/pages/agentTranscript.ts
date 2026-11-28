import type { StoredAgentMessage } from "@/stores/agent";

export type MsgGroup =
  | { kind: "single"; msg: StoredAgentMessage; msgIdx: number }
  | { kind: "timeline"; msgs: StoredAgentMessage[]; msgIdx: number };

export function groupMessages(messages: StoredAgentMessage[]): MsgGroup[] {
  const groups: MsgGroup[] = [];
  let timeline: StoredAgentMessage[] = [];
  let start = -1;
  const flush = () => {
    if (timeline.length === 0) return;
    groups.push({ kind: "timeline", msgs: [...timeline], msgIdx: start });
    timeline = [];
    start = -1;
  };
  for (const [msgIdx, message] of messages.entries()) {
    if (["thinking", "tool_call", "tool_result", "compact"].includes(message.type)) {
      if (start < 0) start = msgIdx;
      timeline.push(message);
    } else {
      flush();
      groups.push({ kind: "single", msg: message, msgIdx });
    }
  }
  flush();
  return groups;
}
