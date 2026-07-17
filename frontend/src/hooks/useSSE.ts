/**
 * SSE Hook — auto-reconnect + exponential backoff + LRU dedup + Last-Event-ID resume.
 */

import { useCallback, useRef } from "react";
import { getApiAuthKey, withAuthTicket } from "@/lib/apiAuth";

type EventHandler = (data: Record<string, unknown>) => void;
type Handlers = Record<string, EventHandler>;

export type SSEStatus = "disconnected" | "connected" | "reconnecting";

interface SSEConfig {
  initialRetryMs?: number;
  maxRetryMs?: number;
  backoffFactor?: number;
  dedupeCapacity?: number;
}

const DEFAULTS: Required<SSEConfig> = {
  initialRetryMs: 1000,
  maxRetryMs: 30000,
  backoffFactor: 2,
  dedupeCapacity: 500,
};

export function useSSE(config?: SSEConfig) {
  const opts = { ...DEFAULTS, ...config };
  const sourceRef = useRef<EventSource | null>(null);
  const handlersRef = useRef<Handlers>({});
  const urlRef = useRef<string>("");
  const closedRef = useRef(true);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  const statusRef = useRef<SSEStatus>("disconnected");
  const onStatusChangeRef = useRef<((s: SSEStatus) => void) | null>(null);
  const generationRef = useRef(0);

  // LRU dedup set
  const seenIdsRef = useRef<Set<string>>(new Set());
  const seenOrderRef = useRef<string[]>([]);

  const trackEventId = useCallback((eventId: string): boolean => {
    if (!eventId) return false;
    const seen = seenIdsRef.current;
    const order = seenOrderRef.current;
    if (seen.has(eventId)) return true; // duplicate
    seen.add(eventId);
    order.push(eventId);
    if (order.length > opts.dedupeCapacity) {
      const oldest = order.shift()!;
      seen.delete(oldest);
    }
    return false;
  }, [opts.dedupeCapacity]);

  const setStatus = useCallback((s: SSEStatus) => {
    statusRef.current = s;
    onStatusChangeRef.current?.(s);
  }, []);

  const buildUrl = useCallback((baseUrl: string) => {
    const sep = baseUrl.includes("?") ? "&" : "?";
    if (lastEventIdRef.current) {
      return `${baseUrl}${sep}Last-Event-ID=${encodeURIComponent(lastEventIdRef.current)}`;
    }
    return baseUrl;
  }, []);

  const attach = useCallback((url: string, generation: number) => {
    if (closedRef.current || generation !== generationRef.current) return;

    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => {
      if (generation !== generationRef.current || sourceRef.current !== source) {
        return;
      }
      retryCountRef.current = 0;
      setStatus("connected");
    };

    // Only subscribe to event types the backend actually emits
    const knownTypes = [
      "text_delta", "reasoning_delta", "stream_reset", "thinking_done", "tool_call", "tool_result", "compact",
      "tool_heartbeat", "tool_progress", "llm_usage",
      "swarm.started", "swarm.event",
      "attempt.created", "attempt.started", "attempt.completed", "attempt.failed",
      "message.received", "session.created",
      "goal.created", "goal.evidence", "goal.updated",
      "mandate.proposal", "mandate.committed", "live.halted", "live.resumed", "live.action",
      "heartbeat", "done",
    ];

    const handleRaw = (eventType: string, raw: MessageEvent) => {
      if (generation !== generationRef.current || sourceRef.current !== source) {
        return;
      }
      if (raw.lastEventId) {
        lastEventIdRef.current = raw.lastEventId;
      }
      if (raw.lastEventId && trackEventId(raw.lastEventId)) return;

      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(raw.data);
      } catch {
        parsed = { raw: raw.data };
      }

      const handler = handlersRef.current[eventType] ?? handlersRef.current["message"];
      handler?.(parsed);
    };

    for (const eventType of knownTypes) {
      source.addEventListener(eventType, (e) => handleRaw(eventType, e as MessageEvent));
    }

    source.onerror = () => {
      if (
        closedRef.current ||
        generation !== generationRef.current ||
        sourceRef.current !== source
      ) {
        return;
      }
      source.close();
      sourceRef.current = null;
      scheduleReconnect(generation);
    };
  }, [trackEventId, setStatus]);

  const doConnect = useCallback((generation: number) => {
    if (closedRef.current || generation !== generationRef.current) return;

    const baseUrl = buildUrl(urlRef.current);

    // When an API key is stored we must first mint a single-use SSE ticket —
    // EventSource can't send an Authorization header. In loopback dev mode (no
    // key) the backend bypasses auth, so we connect synchronously and preserve
    // the original zero-round-trip behavior (and the synchronous test path).
    if (!getApiAuthKey()) {
      attach(baseUrl, generation);
      return;
    }
    withAuthTicket(baseUrl)
      .then((url) => attach(url, generation))
      .catch(() => {
        if (!closedRef.current && generation === generationRef.current) {
          scheduleReconnect(generation);
        }
      });
  }, [buildUrl, attach]);

  const scheduleReconnect = useCallback((generation: number) => {
    if (closedRef.current || generation !== generationRef.current) return;
    retryCountRef.current += 1;
    const delay = Math.min(
      opts.initialRetryMs * Math.pow(opts.backoffFactor, retryCountRef.current - 1),
      opts.maxRetryMs,
    );
    setStatus("reconnecting");
    handlersRef.current["reconnect"]?.({ attempt: retryCountRef.current, delayMs: delay });

    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      if (generation === generationRef.current) {
        doConnect(generation);
      }
    }, delay);
  }, [opts.initialRetryMs, opts.backoffFactor, opts.maxRetryMs, setStatus, doConnect]);

  const connect = useCallback((url: string, handlers: Handlers) => {
    const generation = ++generationRef.current;
    closedRef.current = true;
    sourceRef.current?.close();
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    urlRef.current = url;
    handlersRef.current = handlers;
    closedRef.current = false;
    retryCountRef.current = 0;
    lastEventIdRef.current = null;
    seenIdsRef.current.clear();
    seenOrderRef.current.length = 0;

    doConnect(generation);
  }, [doConnect]);

  const disconnect = useCallback(() => {
    generationRef.current += 1;
    closedRef.current = true;
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    sourceRef.current?.close();
    sourceRef.current = null;
    setStatus("disconnected");
  }, [setStatus]);

  const getStatus = useCallback(() => statusRef.current, []);

  const onStatusChange = useCallback((cb: (s: SSEStatus) => void) => {
    onStatusChangeRef.current = cb;
  }, []);

  return { connect, disconnect, getStatus, onStatusChange };
}
