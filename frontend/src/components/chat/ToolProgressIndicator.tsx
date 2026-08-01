import { memo, useEffect, useMemo, useRef, type JSX } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { ProgressBar } from "@/components/chat/ProgressBar";
import { localizeToolName } from "@/lib/tools";
import type { ToolCallEntry } from "@/types/agent";

/* ---------- ETA tracking (per-tool) ---------- */
interface EtaSample {
  stage: string;
  current: number;
  suppressed: boolean;
}

function calculateEta(tc: ToolCallEntry, previous?: EtaSample): number | null {
  const progress = tc.progress;
  if (
    !progress
    || typeof progress.current !== "number"
    || typeof progress.total !== "number"
    || progress.total <= 0
  ) {
    return null;
  }

  const stage = progress.stage || "";
  if (previous && progress.current < previous.current) return null;
  if (previous?.suppressed && previous.stage === stage) return null;
  if (!previous || previous.stage !== stage) return null;
  if (progress.current < 3 || progress.current < progress.total * 0.1) return null;
  if (tc.elapsed_s == null || tc.elapsed_s <= 0) return null;

  const eta = (tc.elapsed_s / progress.current) * (progress.total - progress.current);
  if (!isFinite(eta) || eta < 0) return null;
  return Math.round(eta);
}

function formatStepElapsed(seconds: number): string {
  if (seconds < 0.05) return "<0.1s";
  if (seconds < 1) return `${seconds.toFixed(1)}s`;
  const wholeSeconds = Math.floor(seconds);
  if (wholeSeconds < 60) return `${wholeSeconds}s`;
  return `${Math.floor(wholeSeconds / 60)}m ${wholeSeconds % 60}s`;
}

/* ---------- Argument summary ----------
 * The step label alone ("Browse the factor zoo") is identical for every call
 * of the same tool; the argument summary is what tells seven such steps
 * apart. Prefer the arguments users phrase requests in (names, symbols,
 * queries) over incidental ones.
 */
const DETAIL_ARG_KEYS = [
  "name", "skill", "skill_name", "factor", "factor_id", "alpha_id",
  "symbol", "symbols", "code", "query", "q", "keyword", "action",
  "path", "file", "filename", "url", "source", "id",
];

function truncateDetail(value: string, max = 42): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function detailFor(entry: ToolCallEntry): string {
  const args = entry.arguments ?? {};
  for (const key of DETAIL_ARG_KEYS) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return truncateDetail(value.trim());
  }
  const fallback = Object.values(args).find(
    (value) => typeof value === "string" && value.trim() && value.trim().length <= 60,
  );
  return fallback ? truncateDetail(fallback.trim()) : "";
}

function entryElapsedSeconds(entry: ToolCallEntry): number | undefined {
  if (entry.elapsed_s != null) return entry.elapsed_s;
  if (entry.elapsed_ms != null) return entry.elapsed_ms / 1000;
  return undefined;
}

/* ---------- Determinate progress ring ---------- */
interface RingProps {
  current: number;
  total: number;
}

function ProgressRing({ current, total }: RingProps): JSX.Element {
  // h-3 w-3 = 12px; viewBox 24, r=10, circumference = 2*PI*10 ≈ 62.83
  const pct = Math.min(1, Math.max(0, current / total));
  const c = 2 * Math.PI * 10;
  const dash = c * pct;
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3 w-3 text-primary shrink-0"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="3"
      />
      <circle
        cx="12"
        cy="12"
        r="10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${c - dash}`}
        transform="rotate(-90 12 12)"
        style={{ transition: "stroke-dasharray 200ms ease" }}
      />
    </svg>
  );
}

/* ---------- Single row: one tool call, or a run of successful same-tool calls ---------- */
interface RowProps {
  entries: ToolCallEntry[];
  eta: number | null;
}

function ToolRow({ entries, eta }: RowProps): JSX.Element {
  const { t } = useTranslation();
  const entry = entries[entries.length - 1];
  const progress = entries.length === 1 ? entry.progress : undefined;
  const hasDeterminate = !!(progress && typeof progress.current === "number" && typeof progress.total === "number" && progress.total > 0);
  const stage = progress?.stage || "";
  const message = progress?.message || "";

  let elapsedSeconds: number | undefined;
  for (const item of entries) {
    const value = entryElapsedSeconds(item);
    if (value != null) elapsedSeconds = (elapsedSeconds ?? 0) + value;
  }

  const icon = entry.status === "error"
    ? <XCircle className="h-3 w-3 text-danger shrink-0" />
    : entry.status === "ok"
      ? <CheckCircle2 className="h-3 w-3 text-success shrink-0" />
      : hasDeterminate
        ? <ProgressRing current={progress!.current!} total={progress!.total!} />
        : <Loader2 className="h-3 w-3 animate-spin text-primary shrink-0" />;

  const localized = localizeToolName(entry.tool);
  const details = [...new Set(entries.map(detailFor).filter(Boolean))];
  const detailText = details.slice(0, 3).join(", ") + (details.length > 3 ? ` +${details.length - 3}` : "");

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-x-2 gap-y-0.5 text-xs min-w-0">
      {/* Primary row */}
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <span className="text-foreground shrink-0">
          {localized}
          {entries.length > 1 && (
            <span className="text-muted-foreground"> ×{entries.length}</span>
          )}
        </span>
        {detailText && (
          <span className="min-w-0 truncate text-muted-foreground/80">{detailText}</span>
        )}
        {elapsedSeconds != null && (
          <span
            aria-hidden="true"
            className="ml-auto sm:ml-0 tabular-nums text-[10px] text-muted-foreground/70 shrink-0"
          >
            {formatStepElapsed(elapsedSeconds)}
          </span>
        )}
      </div>
      {/* Secondary row: stage + progress bar (+ ETA) */}
      {(progress && (hasDeterminate || stage)) && (
        <div className="flex items-center gap-2 min-w-0 sm:flex-1">
          {stage && (
            <span className="text-foreground text-xs shrink-0 truncate max-w-[40%]">{stage}</span>
          )}
          {hasDeterminate && (
            <ProgressBar
              current={progress!.current!}
              total={progress!.total!}
              height="xs"
              showCount
              ariaLabel={stage || localized}
              className="text-muted-foreground"
            />
          )}
          {eta != null && (
            <span
              aria-hidden="true"
              className="text-[10px] text-muted-foreground/70 tabular-nums shrink-0"
            >
              {t("toolProgress.etaSeconds" as never, { seconds: eta })}
            </span>
          )}
        </div>
      )}
      {/* Tertiary row: message */}
      {message && (
        <div className="text-[10px] text-muted-foreground/60 truncate min-w-0 sm:basis-full">
          {message}
        </div>
      )}
    </div>
  );
}

/* ---------- Public component ---------- */
export interface ToolProgressIndicatorProps {
  /** Full step list from the durable activity object. */
  toolCalls: ToolCallEntry[];
}

/**
 * Expanded activity step rows.
 *
 * ActivityLine owns status, disclosure and announcements; this component is
 * deliberately only the shared row renderer so the chat has one status surface.
 *
 * Rows read chronologically top-to-bottom (the running call is naturally the
 * newest, at the bottom); consecutive successful calls of the same tool
 * coalesce into one "×N" row so repeated lookups don't become a wall of
 * identical lines. Errors and the running call always keep their own row.
 */
export const ToolProgressIndicator = memo(function ToolProgressIndicator({
  toolCalls,
}: ToolProgressIndicatorProps): JSX.Element | null {
  const etaSamplesRef = useRef<Map<string, EtaSample>>(new Map());

  const { rows, running } = useMemo(() => {
    const rows: ToolCallEntry[][] = [];
    const running: ToolCallEntry[] = [];

    for (const entry of toolCalls) {
      if (entry.status === "running") running.push(entry);
      const lastGroup = rows[rows.length - 1];
      if (
        entry.status === "ok"
        && lastGroup
        && lastGroup[0].status === "ok"
        && lastGroup[0].tool === entry.tool
      ) {
        lastGroup.push(entry);
      } else {
        rows.push([entry]);
      }
    }
    return { rows, running };
  }, [toolCalls]);

  const etaById = useMemo(() => {
    const eta = new Map<string, number | null>();
    for (const entry of running) {
      eta.set(entry.id, calculateEta(entry, etaSamplesRef.current.get(entry.id)));
    }
    return eta;
  }, [running]);

  useEffect(() => {
    const previousSamples = etaSamplesRef.current;
    const nextSamples = new Map<string, EtaSample>();

    for (const entry of running) {
      const progress = entry.progress;
      if (!progress || typeof progress.current !== "number") continue;

      const stage = progress.stage || "";
      const previous = previousSamples.get(entry.id);
      const sameStage = previous?.stage === stage;
      nextSamples.set(entry.id, {
        stage,
        current: progress.current,
        suppressed: Boolean(
          sameStage
          && (previous?.suppressed || progress.current < previous.current),
        ),
      });
    }

    etaSamplesRef.current = nextSamples;
  }, [running]);

  if (toolCalls.length === 0) return null;

  return (
    <div className="min-w-0 space-y-1 border-s border-border/40 ps-3">
      {rows.map((entries) => (
        <ToolRow
          key={entries[0].id}
          entries={entries}
          eta={etaById.get(entries[entries.length - 1].id) ?? null}
        />
      ))}
    </div>
  );
});
