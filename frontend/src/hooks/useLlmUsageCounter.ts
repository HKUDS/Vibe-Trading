/**
 * Live per-attempt LLM token counter, fed by the `run.usage` item delta.
 *
 * The backend emits one `run.usage` event per agent iteration carrying the
 * provider-reported usage DELTA plus `iter` and `attempt_id`
 * (emitted at agent/src/agent/loop.py; `turn_id` injected at
 * agent/src/session/service.py). useSSE dedups by Last-Event-ID, but a
 * reconnect replay can still deliver an already-applied iteration, so
 * accumulation is keyed idempotently on `(attemptId, iter)` and a new
 * attempt_id resets the running totals to zero.
 */

import { useCallback, useRef, useState } from "react";

/** Loose SSE payload accepted at the accumulation boundary (untrusted data). */
export type UsageDelta = Readonly<Record<string, unknown>>;

export interface LlmUsageTotals {
  input: number;
  output: number;
  calls: number;
}

export interface LlmUsageCounter extends LlmUsageTotals {
  record: (attemptId: string, iter: number, delta: UsageDelta) => void;
  reset: () => void;
}

const ZERO: LlmUsageTotals = { input: 0, output: 0, calls: 0 };

/** Missing / null / non-finite / negative provider fields count as 0 — never NaN. */
function toTokenCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

export function useLlmUsageCounter(): LlmUsageCounter {
  // The ref owns the truth so records batched before a re-render still
  // accumulate independently; state only mirrors it for rendering.
  const totalsRef = useRef<LlmUsageTotals>({ ...ZERO });
  const attemptRef = useRef<string | null>(null);
  const seenKeysRef = useRef<Set<string>>(new Set());
  const [totals, setTotals] = useState<LlmUsageTotals>(totalsRef.current);

  const commit = useCallback((): void => {
    setTotals({ ...totalsRef.current });
  }, []);

  const record = useCallback((attemptId: string, iter: number, delta: UsageDelta): void => {
    if (attemptRef.current !== attemptId) {
      attemptRef.current = attemptId;
      seenKeysRef.current.clear();
      totalsRef.current = { ...ZERO };
    }
    const key = `${attemptId}:${iter}`;
    if (seenKeysRef.current.has(key)) return;
    seenKeysRef.current.add(key);
    const prev = totalsRef.current;
    totalsRef.current = {
      input: prev.input + toTokenCount(delta.input_tokens),
      output: prev.output + toTokenCount(delta.output_tokens),
      calls: prev.calls + 1,
    };
    commit();
  }, [commit]);

  const reset = useCallback((): void => {
    attemptRef.current = null;
    seenKeysRef.current.clear();
    totalsRef.current = { ...ZERO };
    commit();
  }, [commit]);

  return { ...totals, record, reset };
}
