import type { ThreadDisplayItem, ThreadPage } from "@/lib/api";

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
