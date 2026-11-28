import type { ThreadDisplayItem, ThreadPage } from "@/lib/api";

/** Build canonical thread pages from concise historical-turn test data. */
export function threadFixture(rows: any[]): ThreadPage {
  const items: ThreadDisplayItem[] = [];
  let pending: any[] = [];
  const append = (turn_id: string, ts: number, data: any) => {
    items.push({ seq: items.length + 1, turn_id, ts, ...data });
  };
  for (const row of rows) {
    if (row.role === "user") { pending.push(row); continue; }
    const turn = row.linked_attempt_id || row.message_id;
    const meta = row.metadata || {};
    const end = Date.parse(row.created_at) / 1000;
    const start = meta.started_at || end - (meta.elapsed_ms || 0) / 1000;
    append(turn, start, { type: "turn_start", prompt: pending[0]?.content || "", provider: meta.provider, model: meta.model });
    for (const user of pending) append(turn, Date.parse(user.created_at) / 1000, { type: "user", content: user.content });
    pending = [];
    for (const [i, tool] of (row.tool_trail || []).entries()) {
      const id = tool.call_id || `call-${i}`;
      append(turn, tool.timestamp || start, { type: "assistant", tool_calls: [{ id, name: tool.tool, arguments: tool.arguments || {} }], phase: "commentary" });
      append(turn, tool.timestamp || start, { type: "tool_result", tool_call_id: id, name: tool.tool, content: tool.preview, status: tool.status, elapsed_ms: tool.elapsed_ms });
    }
    append(turn, end, { type: "assistant", content: row.content, phase: "final" });
    append(turn, end, { type: "turn_end", status: meta.status || "completed", summary: row.content, elapsed_ms: meta.elapsed_ms, display: meta });
  }
  for (const user of pending) append(user.linked_attempt_id || user.message_id, Date.parse(user.created_at) / 1000, { type: "user", content: user.content });
  return { items, cursor: items.length, has_more: false };
}
