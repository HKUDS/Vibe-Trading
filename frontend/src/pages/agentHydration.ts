import type { MessageItem, ThreadDisplayItem, ThreadPage } from "@/lib/api";

export const THREAD_PAGE_LIMIT = 500;

export async function readThread(
  getPage: (after: number, limit: number) => Promise<ThreadPage>,
): Promise<Pick<ThreadPage, "items" | "cursor">> {
  const items: ThreadDisplayItem[] = [];
  let after = 0;
  for (;;) {
    const page = await getPage(after, THREAD_PAGE_LIMIT);
    items.push(...page.items);
    const last = page.items[page.items.length - 1];
    if (!page.has_more || !last) return { items, cursor: page.cursor };
    after = last.seq;
  }
}

/** Return only rows from before the durable thread log existed. */
export function rowsBeforeThread(
  rows: readonly MessageItem[],
  threadTurns: ReadonlySet<string>,
): MessageItem[] {
  if (threadTurns.size === 0) return [...rows];
  const turnOf: Array<string | undefined> = new Array(rows.length);
  let nextReplyTurn: string | undefined;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index];
    if (row.role === "assistant") {
      nextReplyTurn = row.linked_attempt_id || undefined;
      turnOf[index] = nextReplyTurn;
    } else {
      const delivered = row.metadata?.delivered_to_attempt_id;
      turnOf[index] = typeof delivered === "string" && delivered ? delivered : nextReplyTurn;
    }
  }
  return rows.filter((_, index) => {
    const turn = turnOf[index];
    return turn !== undefined && !threadTurns.has(turn);
  });
}
