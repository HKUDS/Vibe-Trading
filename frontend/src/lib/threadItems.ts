/**
 * The conversation as the server records it: thread items and the item events
 * derived from them (design §6.8).
 *
 * A {@link ThreadView} holds one session's items in the order they happened.
 * It is built from the thread endpoint and kept current by `item.*` events;
 * {@link buildTranscript} turns it into the chat rows the page renders, so a
 * reloaded turn and a live one go through the same code.
 */
import type {
  PendingInputView,
  ThreadDisplayItem,
  ThreadItemType,
  ThreadPage,
} from "@/lib/api";
import {
  deriveActivityVerb,
  type ActivityState,
  type AgentActivity,
  type AgentMessageMeta,
  type StoredAgentMessage,
} from "@/stores/agent";
import type { ToolCallEntry } from "@/types/agent";

/** Tool progress carried by `tool.progress` deltas. */
export type ThreadToolProgress = NonNullable<ToolCallEntry["progress"]>;

/** One item of the conversation, recorded or still in progress. */
export interface ThreadEntry {
  /** Render key; assigned when the entry first appears and never changed. */
  key: string;
  /** Set once the item is recorded in the thread. */
  seq?: number;
  /** The server's id for the item while it is in progress. */
  liveId?: string;
  turnId: string;
  type: ThreadItemType;
  /** `discarded`: the turn ended before the server recorded the item. */
  state: "live" | "recorded" | "discarded";
  item: Partial<ThreadDisplayItem> & { arguments?: Record<string, string>; blocked?: boolean };
  /** Text a discarded response had streamed before it was dropped. */
  text?: string;
  progress?: ThreadToolProgress;
  /** Seconds a running tool has taken so far (heartbeat). */
  elapsedS?: number;
  /** Client clock when the entry first appeared, ms. */
  receivedAt: number;
}

/** A message sent while a turn runs, waiting to join the conversation. */
export interface QueuedInput {
  inputId: string;
  content: string;
  /** Live id of its `item.started` event, when one was seen. */
  liveId?: string;
  status: "queued" | "delivering";
}

export interface ThreadView {
  /** The thread endpoint answered; the session renders from items. */
  loaded: boolean;
  /** Highest seq the view has every recorded item for; resumes the stream. */
  cursor: number;
  entries: ThreadEntry[];
  /** The response streaming now; its text lives in the store's streamingText. */
  liveAssistant: { liveId: string; turnId: string } | null;
  queued: QueuedInput[];
}

/** Per-turn facts that come from attempt events and the projected reply row, not from items. */
export interface TurnMeta {
  /** Run directory name of the turn. */
  runId?: string;
  /** Run card fields once the turn produced metrics or a shadow report. */
  card?: Pick<StoredAgentMessage, "metrics" | "equityCurve" | "shadowId"> | null;
  /** Reply text the server projected for the turn (`summary` / the stored reply row). */
  content?: string;
  /** Failure reason of a failed turn. */
  error?: string;
  /** Backend wall-clock start, ms. */
  startedAt?: number;
  /** The client stopped waiting for this turn (no events for too long). */
  timedOut?: boolean;
  /** When this page stopped following the turn (a stop or a timeout), ms. */
  localEndedAt?: number;
  /** The user asked the server to stop this turn. */
  stopRequested?: boolean;
}

export function emptyThreadView(): ThreadView {
  return { loaded: false, cursor: 0, entries: [], liveAssistant: null, queued: [] };
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

/** Plain text of message content, which may be a list of content parts. */
export function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => (
      part && typeof part === "object" && typeof (part as { text?: unknown }).text === "string"
        ? (part as { text: string }).text
        : ""
    ))
    .filter(Boolean)
    .join("\n");
}

function recordedEntry(item: ThreadDisplayItem, now: number, key?: string, liveId?: string): ThreadEntry {
  return {
    key: key ?? `seq:${item.seq}`,
    seq: item.seq,
    liveId,
    turnId: item.turn_id,
    type: item.type,
    state: "recorded",
    item,
    receivedAt: now,
  };
}

function withCursor(view: ThreadView, data: Record<string, unknown>): ThreadView {
  const cursor = asNumber(data.cursor);
  return cursor !== undefined && cursor > view.cursor ? { ...view, cursor } : view;
}

/** Insert a recorded entry at its seq position among the recorded entries. */
function insertBySeq(entries: ThreadEntry[], entry: ThreadEntry): ThreadEntry[] {
  const seq = entry.seq ?? Number.MAX_SAFE_INTEGER;
  const index = entries.findIndex((existing) => existing.seq !== undefined && existing.seq > seq);
  if (index < 0) return [...entries, entry];
  return [...entries.slice(0, index), entry, ...entries.slice(index)];
}

/** Record a completed item: in place of its live entry or an earlier copy, else by seq. */
function recordItem(view: ThreadView, item: ThreadDisplayItem, liveId: string | undefined, now: number): ThreadView {
  const bySeq = view.entries.findIndex((entry) => entry.seq === item.seq);
  if (bySeq >= 0) {
    const entries = [...view.entries];
    entries[bySeq] = { ...entries[bySeq], item, state: "recorded" };
    return { ...view, entries };
  }
  if (liveId) {
    const byLive = view.entries.findIndex((entry) => entry.liveId === liveId);
    if (byLive >= 0) {
      const entries = [...view.entries];
      entries[byLive] = { ...entries[byLive], seq: item.seq, item, state: "recorded" };
      return { ...view, entries };
    }
  }
  let next = view;
  if (liveId && view.liveAssistant?.liveId === liveId) {
    next = { ...next, liveAssistant: null };
  }
  if (item.type === "user") {
    // A queued message joined the conversation: it leaves the queue.
    const text = contentText(item.content);
    const queuedIndex = next.queued.findIndex((queued) => (
      (liveId !== undefined && queued.liveId === liveId)
    ));
    const fallbackIndex = queuedIndex >= 0
      ? queuedIndex
      : next.queued.findIndex((queued) => queued.content === text);
    if (fallbackIndex >= 0) {
      next = { ...next, queued: next.queued.filter((_, index) => index !== fallbackIndex) };
    }
  }
  const key = liveId ? `live:${liveId}` : undefined;
  return { ...next, entries: insertBySeq(next.entries, recordedEntry(item, now, key, liveId)) };
}

/**
 * Apply one SSE event to the view.
 *
 * Idempotent: an item already recorded is replaced in place, so a replayed or
 * duplicated event never adds a second row.
 *
 * @param view Current view.
 * @param eventType SSE event name (`item.started` / `item.delta` / `item.completed` / `run.*`).
 * @param data Event payload.
 * @param now Client clock, ms.
 * @param streamedText Text the live response had streamed, kept when it is discarded.
 * @returns The next view; the same object when nothing changed.
 */
export function applyThreadEvent(
  view: ThreadView,
  eventType: string,
  data: Record<string, unknown>,
  now: number,
  streamedText = "",
): ThreadView {
  const kind = asString(data.kind);
  const liveId = asString(data.live_id);
  const turnId = asString(data.turn_id) ?? "";
  const seq = asNumber(data.seq);
  const item = (data.item && typeof data.item === "object" ? data.item : {}) as Partial<ThreadDisplayItem> & {
    status?: string;
    input_id?: string;
    arguments?: Record<string, string>;
    blocked?: boolean;
  };

  if (eventType === "item.started") {
    if (seq !== undefined) {
      if (!item.type) return withCursor(view, data);
      return withCursor(recordItem(view, item as ThreadDisplayItem, undefined, now), data);
    }
    if (!liveId) return withCursor(view, data);
    if (item.type === "user" && item.status === "queued") {
      const inputId = asString(item.input_id);
      const content = contentText(item.content);
      const existing = view.queued.findIndex((queued) => queued.inputId === inputId);
      const queued = existing >= 0
        ? view.queued.map((entry, index) => index === existing ? { ...entry, liveId } : entry)
        : inputId
          ? [...view.queued, { inputId, content, liveId, status: "queued" as const }]
          : view.queued;
      return withCursor({ ...view, queued }, data);
    }
    if (item.type === "assistant") {
      return withCursor({ ...view, liveAssistant: { liveId, turnId } }, data);
    }
    if (item.type === "tool_result") {
      if (view.entries.some((entry) => entry.liveId === liveId)) return withCursor(view, data);
      const entry: ThreadEntry = {
        key: `live:${liveId}`,
        liveId,
        turnId,
        type: "tool_result",
        state: "live",
        item: {
          turn_id: turnId,
          type: "tool_result",
          tool_call_id: item.tool_call_id,
          name: item.name,
          arguments: item.arguments,
          blocked: item.blocked,
        },
        receivedAt: now,
      };
      return withCursor({ ...view, entries: [...view.entries, entry] }, data);
    }
    return withCursor(view, data);
  }

  if (eventType === "item.delta") {
    if (kind !== "tool.progress" || !liveId) return withCursor(view, data);
    const index = view.entries.findIndex((entry) => entry.liveId === liveId && entry.state === "live");
    if (index < 0) return withCursor(view, data);
    const raw = (data.progress && typeof data.progress === "object" ? data.progress : {}) as Record<string, unknown>;
    const entries = [...view.entries];
    const current = entries[index];
    if (data.heartbeat === true) {
      entries[index] = { ...current, elapsedS: asNumber(raw.elapsed_s) ?? current.elapsedS };
    } else {
      const progress: ThreadToolProgress = {};
      if (asString(raw.stage)) progress.stage = raw.stage as string;
      if (asString(raw.message)) progress.message = raw.message as string;
      if (asNumber(raw.current) !== undefined) progress.current = raw.current as number;
      if (asNumber(raw.total) !== undefined) progress.total = raw.total as number;
      entries[index] = { ...current, progress };
    }
    return withCursor({ ...view, entries }, data);
  }

  if (eventType === "item.completed") {
    if (kind === "item.discarded") {
      if (!liveId) return withCursor(view, data);
      if (view.liveAssistant?.liveId === liveId) {
        const entries = streamedText.trim()
          ? [...view.entries, {
              key: `live:${liveId}`,
              liveId,
              turnId,
              type: "assistant" as const,
              state: "discarded" as const,
              item: { turn_id: turnId, type: "assistant" as const },
              text: streamedText,
              receivedAt: now,
            }]
          : view.entries;
        return withCursor({ ...view, liveAssistant: null, entries }, data);
      }
      const queued = view.queued.filter((entry) => entry.liveId !== liveId);
      const entries = view.entries.map((entry) => (
        entry.liveId === liveId && entry.state === "live" ? { ...entry, state: "discarded" as const } : entry
      ));
      return withCursor({ ...view, queued, entries }, data);
    }
    if (seq === undefined || !item.type) return withCursor(view, data);
    return withCursor(recordItem(view, item as ThreadDisplayItem, liveId, now), data);
  }

  // run.* events: the turn boundaries are items too; only the cursor moves.
  return withCursor(view, data);
}

/** Keep the text a response streamed when the client itself gives up on it (stop, timeout). */
export function discardLiveAssistant(view: ThreadView, streamedText: string, now: number): ThreadView {
  const live = view.liveAssistant;
  if (!live) return view;
  return applyThreadEvent(
    view,
    "item.completed",
    { kind: "item.discarded", live_id: live.liveId, turn_id: live.turnId },
    now,
    streamedText,
  );
}

/**
 * Merge a full read of the thread into the view.
 *
 * Items the read covers come from it; entries the events added after it
 * (newer items, in-progress items, discarded text) are kept after them.
 */
export function mergeThreadPage(view: ThreadView, page: Pick<ThreadPage, "items" | "cursor">, now: number): ThreadView {
  const pageSeqs = new Set(page.items.map((item) => item.seq));
  const maxSeq = page.items.reduce((max, item) => Math.max(max, item.seq), 0);
  const existingBySeq = new Map(
    view.entries.filter((entry) => entry.seq !== undefined).map((entry) => [entry.seq as number, entry]),
  );
  const fromPage = page.items.map((item) => {
    const existing = existingBySeq.get(item.seq);
    return existing ? { ...existing, item, state: "recorded" as const } : recordedEntry(item, now);
  });
  const answeredCalls = new Set(
    page.items.filter((item) => item.type === "tool_result").map((item) => `${item.turn_id}:${item.tool_call_id}`),
  );
  const rest = view.entries.filter((entry) => {
    if (entry.seq !== undefined) return !pageSeqs.has(entry.seq) && entry.seq > maxSeq;
    // A call still running when the events reported it may be answered in the read.
    return !(entry.state === "live" && answeredCalls.has(`${entry.turnId}:${entry.item.tool_call_id}`));
  });
  const recordedUsers = new Set(
    page.items.filter((item) => item.type === "user").map((item) => contentText(item.content)),
  );
  return {
    ...view,
    loaded: true,
    cursor: Math.max(view.cursor, page.cursor),
    entries: [...fromPage, ...rest],
    // A queued message already in the read has joined the conversation.
    queued: view.queued.filter((queued) => !(queued.status === "delivering" && recordedUsers.has(queued.content))),
  };
}

/** Replace the queue with the server's list of waiting messages. */
export function withPendingInputs(view: ThreadView, pending: readonly PendingInputView[]): ThreadView {
  const liveIds = new Map(view.queued.map((queued) => [queued.inputId, queued.liveId]));
  return {
    ...view,
    queued: pending.map((input) => ({
      inputId: input.input_id,
      content: input.content,
      liveId: liveIds.get(input.input_id),
      status: input.status === "delivering" ? "delivering" : "queued",
    })),
  };
}

/** Add a message the server queued (idempotent by input id). */
export function addQueuedInput(view: ThreadView, input: { inputId: string; content: string }): ThreadView {
  if (view.queued.some((queued) => queued.inputId === input.inputId)) return view;
  return { ...view, queued: [...view.queued, { ...input, status: "queued" }] };
}

export function removeQueuedInput(view: ThreadView, inputId: string): ThreadView {
  if (!view.queued.some((queued) => queued.inputId === inputId)) return view;
  return { ...view, queued: view.queued.filter((queued) => queued.inputId !== inputId) };
}

const endedCache = new WeakMap<readonly ThreadEntry[], Map<string, string>>();

/** Terminal status of each turn the view holds a `turn_end` for. */
export function endedTurns(view: ThreadView): Map<string, string> {
  const cached = endedCache.get(view.entries);
  if (cached) return cached;
  const ended = new Map<string, string>();
  for (const entry of view.entries) {
    if (entry.type === "turn_end" && entry.state === "recorded") {
      ended.set(entry.turnId, String(entry.item.status || "completed"));
    }
  }
  endedCache.set(view.entries, ended);
  return ended;
}

/* ---------- Transcript ---------- */

export interface TranscriptOptions {
  /** Display form of a user message (strips prompt envelopes, finds attachments). */
  displayUser: (content: string) => { content: string; meta?: AgentMessageMeta };
  /** Preview shown on a tool call the turn ended before answering. */
  interruptedLabel: string;
  /** Fallback text of a failed turn whose reason is unknown. */
  failedLabel: string;
}

interface TurnBuild {
  turnId: string;
  entries: ThreadEntry[];
}

function splitTurns(entries: readonly ThreadEntry[]): TurnBuild[] {
  const turns: TurnBuild[] = [];
  const byId = new Map<string, TurnBuild>();
  for (const entry of entries) {
    let turn = byId.get(entry.turnId);
    if (!turn) {
      turn = { turnId: entry.turnId, entries: [] };
      byId.set(entry.turnId, turn);
      turns.push(turn);
    }
    turn.entries.push(entry);
  }
  return turns;
}

function entryTime(entry: ThreadEntry): number {
  return entry.state === "recorded" && typeof entry.item.ts === "number"
    ? entry.item.ts * 1000
    : entry.receivedAt;
}

const TOOL_PREVIEW_CHARS = 200;

/** Report links the server appends to a stored reply, added when the answer lacks them. */
function withReportLinks(answer: string, turn: TurnBuild): string {
  const links: string[] = [];
  for (const entry of turn.entries) {
    const artifact = entry.item.artifact;
    if (entry.type !== "tool_result" || entry.item.status !== "ok" || !artifact) continue;
    const url = artifact.download_url;
    if (!url || answer.includes(url)) continue;
    const name = String(artifact.filename || "report").replace(/[[\]]/g, "");
    links.push(`[${name}](${url})`);
  }
  const unique = [...new Set(links)];
  return unique.length > 0 ? `${answer}\n\n${unique.join("\n\n")}` : answer;
}

/**
 * Text a stopped turn streamed after its last recorded response.
 *
 * The stored reply of a stopped turn is everything the turn streamed, followed
 * by a stop notice as its last paragraph. Only when the recorded responses are
 * exactly its beginning is the rest known to be the cut-off text.
 */
function stoppedRemainder(turn: TurnBuild, reply: string | undefined): string {
  if (!reply) return "";
  const lastBreak = reply.lastIndexOf("\n\n");
  if (lastBreak < 0) return "";
  const streamed = reply.slice(0, lastBreak);
  const recorded = turn.entries
    .filter((entry) => entry.type === "assistant" && entry.state === "recorded")
    .map((entry) => contentText(entry.item.content))
    .join("");
  if (!streamed.startsWith(recorded)) return "";
  return streamed.slice(recorded.length).trim();
}

function footerState(status: string | undefined, meta: TurnMeta | undefined): ActivityState | null {
  if (status === "completed") return "done";
  if (status === "cancelled") return "stopped";
  if (status === "failed") return "failed";
  if (status === "interrupted") return "interrupted";
  if (status) return "failed";
  if (meta?.timedOut) return "timeout";
  return meta?.stopRequested ? "stopped" : null;
}

/**
 * Turn the view into chat rows, one turn after another, each in the order it
 * happened: the user's message, commentary, tool steps (consecutive calls
 * share one row), and at the end the turn's status line, final answer and run
 * card.
 *
 * @param view The session's thread view.
 * @param meta Per-turn facts keyed by turn id.
 * @param options Labels and the user-message formatter.
 * @returns Chat rows with non-decreasing timestamps.
 */
export function buildTranscript(
  view: ThreadView,
  meta: Readonly<Record<string, TurnMeta>>,
  options: TranscriptOptions,
): StoredAgentMessage[] {
  const rows: StoredAgentMessage[] = [];
  let lastTs = 0;
  const push = (row: StoredAgentMessage) => {
    lastTs = Math.max(row.timestamp, lastTs + 1);
    rows.push({ ...row, timestamp: lastTs, meta: { ...row.meta, fromThread: true } });
  };

  for (const turn of splitTurns(view.entries)) {
    const turnMeta = meta[turn.turnId];
    const end = turn.entries.find((entry) => entry.type === "turn_end" && entry.state === "recorded");
    const start = turn.entries.find((entry) => entry.type === "turn_start");
    const status = end ? String(end.item.status || "completed") : undefined;
    const ended = end !== undefined;
    const allSteps: ToolCallEntry[] = [];
    let block: ToolCallEntry[] = [];
    let blockIndex = 0;
    let finalEntry: ThreadEntry | undefined;
    let partialShown = false;

    const flush = () => {
      if (block.length === 0) return;
      const steps = block;
      block = [];
      blockIndex += 1;
      if (ended) {
        // A call the ended turn never answered did not finish.
        for (const step of steps) {
          if (step.status !== "running") continue;
          step.status = "error";
          step.preview = options.interruptedLabel;
        }
      }
      const running = steps.some((step) => step.status === "running");
      const startedAt = Math.min(...steps.map((step) => step.timestamp));
      const endedAt = Math.max(...steps.map((step) => step.timestamp + (step.elapsed_ms ?? 0)));
      const activity: AgentActivity = {
        attemptId: `${turn.turnId}:steps:${blockIndex}`,
        state: running ? "working" : "done",
        verb: deriveActivityVerb(steps[steps.length - 1]?.tool),
        steps,
        startedAt,
        endedAt: running ? undefined : endedAt,
      };
      push({
        id: `${turn.turnId}:steps:${blockIndex}`,
        type: "thinking",
        content: "",
        meta: { activity, turnId: turn.turnId },
        timestamp: startedAt,
      });
    };

    const findStep = (callId: string | undefined, name: string | undefined) => (
      (callId ? allSteps.find((step) => step.id === callId) : undefined)
      ?? [...allSteps].reverse().find((step) => step.tool === name && step.status === "running")
    );

    for (const entry of turn.entries) {
      const at = entryTime(entry);
      if (entry.type === "user" && entry.state === "recorded") {
        flush();
        const display = options.displayUser(contentText(entry.item.content));
        push({
          id: `${turn.turnId}:user:${entry.key}`,
          type: "user",
          content: display.content,
          meta: { ...display.meta, turnId: turn.turnId },
          timestamp: at,
        });
      } else if (entry.type === "assistant" && entry.state === "recorded") {
        const text = contentText(entry.item.content).trim();
        if (entry.item.phase === "final") {
          finalEntry = entry;
        } else if (text) {
          flush();
          push({
            id: `${turn.turnId}:commentary:${entry.key}`,
            type: "commentary",
            content: text,
            meta: { turnId: turn.turnId },
            timestamp: at,
          });
        }
        for (const [index, call] of (entry.item.tool_calls ?? []).entries()) {
          const step: ToolCallEntry = {
            id: call.id || `${entry.key}#${index}`,
            tool: call.name || "",
            arguments: call.arguments ?? {},
            status: "running",
            timestamp: at,
          };
          allSteps.push(step);
          block.push(step);
        }
      } else if (entry.type === "assistant" && entry.state === "discarded" && entry.text?.trim()) {
        // A response cut off by the end of its turn. A finished turn dropped
        // it on purpose; a stopped one shows what it had said.
        if (ended && status === "completed") continue;
        flush();
        partialShown = true;
        push({
          id: `${turn.turnId}:partial:${entry.key}`,
          type: "commentary",
          content: entry.text.trim(),
          meta: { turnId: turn.turnId, partial: true },
          timestamp: at,
        });
      } else if (entry.type === "tool_result") {
        const callId = entry.item.tool_call_id;
        let step = findStep(callId, entry.item.name);
        if (!step) {
          step = {
            id: callId || entry.key,
            tool: entry.item.name || "",
            arguments: entry.item.arguments ?? {},
            status: "running",
            timestamp: at,
          };
          allSteps.push(step);
          block.push(step);
        }
        if (entry.state === "recorded") {
          step.status = entry.item.status === "ok" ? "ok" : "error";
          const elapsed = asNumber(entry.item.elapsed_ms);
          if (elapsed !== undefined) step.elapsed_ms = Math.max(0, Math.round(elapsed));
          step.preview = contentText(entry.item.content).slice(0, TOOL_PREVIEW_CHARS);
          step.progress = undefined;
          step.elapsed_s = undefined;
        } else if (entry.state === "discarded") {
          step.status = "error";
          step.preview = options.interruptedLabel;
        } else {
          if (entry.item.arguments && Object.keys(step.arguments).length === 0) step.arguments = entry.item.arguments;
          step.progress = entry.progress;
          step.elapsed_s = entry.elapsedS;
        }
      } else if (entry.type === "compaction" && entry.state === "recorded") {
        flush();
        push({
          id: `${turn.turnId}:compaction:${entry.key}`,
          type: "notice",
          content: String(entry.item.summary || ""),
          meta: { turnId: turn.turnId, notice: "compaction" },
          timestamp: at,
        });
      }
    }

    flush();

    if (status === "cancelled" && !partialShown) {
      const remainder = stoppedRemainder(turn, turnMeta?.content);
      if (remainder) {
        push({
          id: `${turn.turnId}:partial:reply`,
          type: "commentary",
          content: remainder,
          meta: { turnId: turn.turnId, partial: true },
          timestamp: end ? entryTime(end) : lastTs,
        });
      }
    }

    const state = footerState(status, turnMeta);
    if (state) {
      const endedAt = end ? entryTime(end) : turnMeta?.localEndedAt ?? lastTs;
      const elapsed = asNumber(end?.item.elapsed_ms);
      const startedAt = turnMeta?.startedAt
        ?? (elapsed !== undefined ? endedAt - elapsed : undefined)
        ?? (start ? entryTime(start) : turn.entries[0] ? entryTime(turn.entries[0]) : endedAt);
      const activity: AgentActivity = {
        attemptId: turn.turnId,
        state,
        verb: deriveActivityVerb(allSteps[allSteps.length - 1]?.tool),
        steps: allSteps,
        startedAt,
        endedAt,
      };
      push({
        id: `${turn.turnId}:status`,
        type: "turn_status",
        content: "",
        meta: { activity, turnId: turn.turnId },
        timestamp: endedAt,
      });
    }

    if (status === "completed") {
      const answer = finalEntry
        ? contentText(finalEntry.item.content)
        : turnMeta?.content ?? "";
      if (answer.trim()) {
        push({
          id: `${turn.turnId}:answer`,
          type: "answer",
          content: finalEntry ? withReportLinks(answer, turn) : answer,
          elapsed_ms: asNumber(end?.item.elapsed_ms),
          meta: { turnId: turn.turnId },
          timestamp: finalEntry ? entryTime(finalEntry) : lastTs,
        });
      }
    } else if (status === "failed" || status === "interrupted") {
      if (finalEntry) {
        push({
          id: `${turn.turnId}:answer`,
          type: "answer",
          content: contentText(finalEntry.item.content),
          meta: { turnId: turn.turnId },
          timestamp: entryTime(finalEntry),
        });
      }
      if (status === "interrupted" && !finalEntry && turnMeta?.content?.trim()) {
        push({
          id: `${turn.turnId}:interrupted:reply`,
          type: "commentary",
          content: turnMeta.content.trim(),
          meta: { turnId: turn.turnId, partial: true },
          timestamp: end ? entryTime(end) : lastTs,
        });
      }
      if (status === "failed") {
        push({
          id: `${turn.turnId}:error`,
          type: "error",
          content: turnMeta?.error || turnMeta?.content || options.failedLabel,
          meta: { turnId: turn.turnId },
          timestamp: lastTs,
        });
      }
    }

    const card = turnMeta?.card;
    if (ended && card && (turnMeta?.runId || card.shadowId)) {
      push({
        id: `${turn.turnId}:run`,
        type: "run_complete",
        content: "",
        runId: turnMeta?.runId,
        metrics: card.metrics,
        equityCurve: card.equityCurve,
        shadowId: card.shadowId,
        meta: { turnId: turn.turnId },
        timestamp: lastTs,
      });
    }
  }
  // A turn this page stopped following before the server recorded any of it.
  const shown = new Set(view.entries.map((entry) => entry.turnId));
  for (const [turnId, turnMeta] of Object.entries(meta)) {
    const state = footerState(undefined, turnMeta);
    if (!state || shown.has(turnId)) continue;
    const endedAt = turnMeta.localEndedAt ?? lastTs;
    push({
      id: `${turnId}:status`,
      type: "turn_status",
      content: "",
      meta: {
        turnId,
        activity: {
          attemptId: turnId,
          state,
          verb: "working",
          steps: [],
          startedAt: turnMeta.startedAt ?? endedAt,
          endedAt,
        },
      },
      timestamp: endedAt,
    });
  }
  return rows;
}

/**
 * Reuse the previous row object wherever a rebuilt row is unchanged, so
 * memoized rows do not re-render (and re-parse their markdown) on every event.
 */
export function reuseRows(
  previous: readonly StoredAgentMessage[],
  next: StoredAgentMessage[],
): StoredAgentMessage[] {
  if (previous.length === 0) return next;
  const byId = new Map(previous.map((row) => [row.id, row]));
  return next.map((row) => {
    const old = byId.get(row.id);
    if (!old) return row;
    return JSON.stringify(old) === JSON.stringify(row) ? old : row;
  });
}
