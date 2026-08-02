import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Loader2, Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, ApiError, type ScheduledRun } from "@/lib/api";
import {
  describeCadence,
  formatIntervalMs,
  formatWallTime,
  formatWeekdays,
} from "@/lib/cadence";

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

const POLL_MS = 15_000;

type DaysChoice = "every" | "weekdays";
type ComposerMode = "time" | "advanced";

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function timezoneOptions(): string[] {
  // Not yet in the project's TS lib target, hence the local type.
  const supported = (Intl as { supportedValuesOf?: (key: "timeZone") => string[] })
    .supportedValuesOf;
  const zones = typeof supported === "function" ? supported("timeZone") : [browserTimezone()];
  return zones.includes("UTC") ? zones : ["UTC", ...zones];
}

// Jobs created before timezone support have timezone=null and keep their
// original UTC semantics; render them as UTC without converting anything.
function displayZone(run: ScheduledRun): string {
  return run.timezone ?? "UTC";
}

function formatInZone(epochMs: number, zone: string, locale: string): string {
  const date = new Date(epochMs);
  if (Number.isNaN(date.getTime())) return "—";
  try {
    return new Intl.DateTimeFormat(locale, {
      timeZone: zone,
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  } catch {
    return date.toISOString();
  }
}

function StatusPill({ label, tone }: { label: string; tone: "success" | "danger" | "warning" | "neutral" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        tone === "success" && "bg-success/10 text-success",
        tone === "danger" && "bg-danger/10 text-danger",
        tone === "warning" && "bg-warning/10 text-warning",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}

export function Scheduled() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;

  const [runs, setRuns] = useState<ScheduledRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<ComposerMode>("time");
  const [time, setTime] = useState("09:00");
  const [days, setDays] = useState<DaysChoice>("weekdays");
  const [advanced, setAdvanced] = useState("");
  const [timezone, setTimezone] = useState(() => browserTimezone());
  const [saving, setSaving] = useState(false);
  const [composerError, setComposerError] = useState<string | null>(null);

  const zonesRef = useRef<string[] | null>(null);
  if (zonesRef.current === null) zonesRef.current = timezoneOptions();

  // Stale-response guard: each refresh aborts the previous request and only
  // the newest sequence number may write state, so a slow 15s poll can never
  // overwrite the list a create/delete just updated.
  const refreshSeq = useRef(0);
  const refreshController = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    refreshController.current?.abort();
    const controller = new AbortController();
    refreshController.current = controller;
    const seq = ++refreshSeq.current;
    try {
      const rows = await api.listScheduledRuns(controller.signal);
      if (seq !== refreshSeq.current) return;
      setRuns(rows);
      setListError(null);
    } catch (error) {
      if (seq !== refreshSeq.current || controller.signal.aborted) return;
      setListError(error instanceof ApiError ? error.message : String(error));
    } finally {
      if (seq === refreshSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => {
      refreshSeq.current++; // invalidate any in-flight response
      refreshController.current?.abort();
      clearInterval(timer);
    };
  }, [refresh]);

  // Auto-disarm an armed delete after a few seconds (blur is unreliable on
  // Safari/iOS, where buttons do not take focus on click).
  useEffect(() => {
    if (pendingDelete === null) return;
    const timer = setTimeout(() => setPendingDelete(null), 5_000);
    return () => clearTimeout(timer);
  }, [pendingDelete]);

  function composedSchedule(): string | null {
    if (mode === "advanced") {
      const spec = advanced.trim();
      return spec ? spec : null;
    }
    const match = /^(\d{1,2}):(\d{2})$/.exec(time);
    if (!match) return null;
    return `${Number(match[2])} ${Number(match[1])} * * ${days === "every" ? "*" : "1-5"}`;
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setComposerError(null);
    if (!prompt.trim()) {
      setComposerError(t("scheduled.promptRequired"));
      return;
    }
    const schedule = composedSchedule();
    if (schedule === null) {
      setComposerError(t("scheduled.invalidTime"));
      return;
    }
    setSaving(true);
    try {
      await api.createScheduledRun({ prompt: prompt.trim(), schedule, timezone });
      setPrompt("");
      await refresh();
    } catch (error) {
      setComposerError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirmedDelete(id: string) {
    setPendingDelete(null);
    try {
      await api.deleteScheduledRun(id);
      await refresh();
    } catch (error) {
      setListError(error instanceof ApiError ? error.message : String(error));
    }
  }

  function cadenceLabel(run: ScheduledRun): string {
    const cadence = describeCadence(run.schedule);
    switch (cadence.kind) {
      case "interval":
        return t("scheduled.cadenceEvery", { interval: formatIntervalMs(cadence.ms) });
      case "daily":
        return t("scheduled.cadenceDaily", { time: formatWallTime(cadence.hour, cadence.minute) });
      case "weekly":
        return t("scheduled.cadenceWeekly", {
          days: formatWeekdays(cadence.weekdays, locale),
          time: formatWallTime(cadence.hour, cadence.minute),
        });
      default:
        return cadence.expression;
    }
  }

  function statusLabel(run: ScheduledRun): { label: string; tone: "success" | "danger" | "warning" | "neutral" } {
    switch (run.status) {
      case "completed":
        return { label: t("scheduled.statusCompleted"), tone: "success" };
      case "failed":
        return { label: t("scheduled.statusFailed"), tone: "danger" };
      case "running":
        return { label: t("scheduled.statusRunning"), tone: "warning" };
      case "cancelled":
        return { label: t("scheduled.statusCancelled"), tone: "neutral" };
      default:
        return { label: t("scheduled.statusPending"), tone: "neutral" };
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <header className="flex items-center gap-3">
        <CalendarClock className="h-6 w-6 text-primary" aria-hidden />
        <div>
          <h1 className="text-xl font-semibold">{t("scheduled.title")}</h1>
          <p className={hintClass}>{t("scheduled.subtitle")}</p>
        </div>
      </header>

      <form onSubmit={handleCreate} className="space-y-4 rounded-lg border bg-card p-4">
        <div className="space-y-1.5">
          <label htmlFor="scheduled-prompt" className={labelClass}>
            {t("scheduled.promptLabel")}
          </label>
          <textarea
            id="scheduled-prompt"
            required
            rows={2}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={t("scheduled.promptPlaceholder")}
            className={fieldClass}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <label htmlFor="scheduled-mode" className={labelClass}>
              {t("scheduled.modeLabel")}
            </label>
            <select
              id="scheduled-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as ComposerMode)}
              className={fieldClass}
            >
              <option value="time">{t("scheduled.modeTime")}</option>
              <option value="advanced">{t("scheduled.modeAdvanced")}</option>
            </select>
          </div>

          {mode === "time" ? (
            <>
              <div className="space-y-1.5">
                <label htmlFor="scheduled-time" className={labelClass}>
                  {t("scheduled.timeLabel")}
                </label>
                <input
                  id="scheduled-time"
                  type="time"
                  required
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  className={fieldClass}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="scheduled-days" className={labelClass}>
                  {t("scheduled.daysLabel")}
                </label>
                <select
                  id="scheduled-days"
                  value={days}
                  onChange={(e) => setDays(e.target.value as DaysChoice)}
                  className={fieldClass}
                >
                  <option value="weekdays">{t("scheduled.daysWeekdays")}</option>
                  <option value="every">{t("scheduled.daysEveryDay")}</option>
                </select>
              </div>
            </>
          ) : (
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="scheduled-advanced" className={labelClass}>
                {t("scheduled.scheduleLabel")}
              </label>
              <input
                id="scheduled-advanced"
                required
                value={advanced}
                onChange={(e) => setAdvanced(e.target.value)}
                placeholder="30 23 * * 1-5"
                className={cn(fieldClass, "font-mono")}
              />
              <p className={hintClass}>{t("scheduled.advancedHint")}</p>
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="scheduled-timezone" className={labelClass}>
              {t("scheduled.timezoneLabel")}
            </label>
            <select
              id="scheduled-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className={fieldClass}
            >
              {zonesRef.current.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </div>
        </div>

        {composerError && (
          <p role="alert" className="text-sm text-danger">
            {composerError}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
            {t("scheduled.create")}
          </button>
          <p className={hintClass}>{t("scheduled.executorHint")}</p>
        </div>
      </form>

      <section aria-label={t("scheduled.listTitle")} className="rounded-lg border bg-card">
        {loading ? (
          <div className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t("scheduled.loading")}
          </div>
        ) : listError && runs.length === 0 ? (
          <div className="space-y-2 p-6 text-sm">
            <p className="text-danger">{listError}</p>
            <button
              type="button"
              onClick={() => void refresh()}
              className="rounded-md border px-3 py-1.5 text-sm transition hover:bg-muted"
            >
              {t("scheduled.retry")}
            </button>
          </div>
        ) : runs.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">{t("scheduled.empty")}</p>
        ) : (
          <>
          {listError && (
            <p role="alert" className="border-b px-4 py-2 text-xs text-danger">
              {listError}
            </p>
          )}
          <ul className="divide-y">
            {runs.map((run) => {
              const status = statusLabel(run);
              const zone = displayZone(run);
              return (
                <li key={run.id} className="flex flex-wrap items-start gap-3 p-4">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{cadenceLabel(run)}</span>
                      <span className={hintClass}>{zone}</span>
                      <StatusPill label={status.label} tone={status.tone} />
                    </div>
                    <p className="truncate text-sm text-muted-foreground">{run.prompt}</p>
                    <p className={hintClass}>
                      {t("scheduled.nextRun", {
                        when: formatInZone(run.next_run_at, zone, locale),
                      })}
                    </p>
                    {run.last_error && (
                      <p className="break-words text-xs text-danger">
                        {t("scheduled.lastError", { error: run.last_error })}
                      </p>
                    )}
                  </div>
                  {pendingDelete === run.id ? (
                    <div className="flex items-center gap-1.5">
                      {/* Cancel first so it inherits the Delete button's spot —
                          an accidental double-click disarms instead of destroying. */}
                      <button
                        type="button"
                        onClick={() => setPendingDelete(null)}
                        className="rounded-md border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:bg-muted"
                      >
                        {t("layout.cancel")}
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleConfirmedDelete(run.id)}
                        aria-label={t("scheduled.confirmDeleteAria", { prompt: run.prompt })}
                        className="inline-flex items-center gap-1.5 rounded-md border border-danger bg-danger/10 px-2.5 py-1.5 text-xs text-danger transition"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        {t("scheduled.confirmDelete")}
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setPendingDelete(run.id)}
                      aria-label={t("scheduled.deleteAria", { prompt: run.prompt })}
                      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:bg-muted"
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      {t("scheduled.delete")}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          </>
        )}
      </section>
    </div>
  );
}
