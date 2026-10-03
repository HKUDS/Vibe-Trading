import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Loader2, Pencil, Plus, Save, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, ApiError, type ChannelAdapterStatus, type ScheduledRun } from "@/lib/api";
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

function isWeekdayCadence(weekdays: number[]): boolean {
  return (
    weekdays.length === 5 &&
    weekdays.every((day, index) => day === index + 1)
  );
}

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function maskDeliveryTarget(target: string): string {
  if (target.length <= 2) return "•".repeat(target.length);
  if (target.length <= 6) {
    return `${target.slice(0, 1)}${"•".repeat(target.length - 2)}${target.slice(-1)}`;
  }
  const prefixLength = target.startsWith("-100") ? 4 : 3;
  return `${target.slice(0, prefixLength)}••••${target.slice(-2)}`;
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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [channelStatus, setChannelStatus] = useState<Record<string, ChannelAdapterStatus>>({});
  const [channelLoadError, setChannelLoadError] = useState(false);

  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<ComposerMode>("time");
  const [time, setTime] = useState("09:00");
  const [days, setDays] = useState<DaysChoice>("weekdays");
  const [advanced, setAdvanced] = useState("");
  const [timezone, setTimezone] = useState(() => browserTimezone());
  // Delivery is opt-in: an empty channel is what every monitor had before, and
  // it means the briefing stays in the app.
  const [deliveryChannel, setDeliveryChannel] = useState("");
  const [deliveryTarget, setDeliveryTarget] = useState("");
  const [deliveryTargetRef, setDeliveryTargetRef] = useState<string | null>(null);
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

  useEffect(() => {
    let cancelled = false;
    void api.getChannelStatus()
      .then((status) => {
        if (cancelled) return;
        setChannelStatus(status.channels ?? {});
        setChannelLoadError(false);
      })
      .catch(() => {
        if (cancelled) return;
        setChannelStatus({});
        setChannelLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  function resetComposer() {
    setEditingId(null);
    setPrompt("");
    setMode("time");
    setTime("09:00");
    setDays("weekdays");
    setAdvanced("");
    setTimezone(browserTimezone());
    setDeliveryChannel("");
    setDeliveryTarget("");
    setDeliveryTargetRef(null);
    setComposerError(null);
  }

  function beginEdit(run: ScheduledRun) {
    const cadence = describeCadence(run.schedule);
    setPendingDelete(null);
    setEditingId(run.id);
    setPrompt(run.prompt);
    setTimezone(displayZone(run));
    setDeliveryChannel(run.delivery_channel ?? "");
    setDeliveryTarget(run.delivery_target ?? "");
    setDeliveryTargetRef(run.delivery_target_ref);
    setComposerError(null);

    if (cadence.kind === "daily") {
      setMode("time");
      setDays("every");
      setTime(formatWallTime(cadence.hour, cadence.minute));
      setAdvanced("");
    } else if (cadence.kind === "weekly" && isWeekdayCadence(cadence.weekdays)) {
      setMode("time");
      setDays("weekdays");
      setTime(formatWallTime(cadence.hour, cadence.minute));
      setAdvanced("");
    } else {
      setMode("advanced");
      setAdvanced(run.schedule);
    }

  }

  async function handleSubmit(event: React.FormEvent) {
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
      const channel = deliveryChannel.trim();
      const target = deliveryTarget.trim();
      if (channel && !target) {
        setComposerError(t("scheduled.deliveryTargetRequired"));
        return;
      }
      const payload = {
        prompt: prompt.trim(),
        schedule,
        timezone,
        delivery_channel: channel || null,
        delivery_target: channel ? target : null,
        delivery_target_ref: channel ? deliveryTargetRef : null,
      };
      if (editingId) {
        await api.updateScheduledRun(editingId, payload);
      } else {
        await api.createScheduledRun(payload);
      }
      resetComposer();
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
      if (editingId === id) resetComposer();
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

  function verdictCell(run: ScheduledRun): ReactNode {
    const verdict = run.last_verdict;
    if (verdict === null) {
      return (
        <p className={hintClass} data-testid={`verdict-empty-${run.id}`}>
          {t("scheduled.verdictEmpty")}
        </p>
      );
    }
    // A monitor built from an ad-hoc prompt never produces a verdict section,
    // and that is its correct permanent state: render nothing, not a warning.
    if (verdict.parse === "no_verdict_section") {
      return null;
    }
    if (verdict.parse === "contract_violation") {
      // Never show a wrong verdict: the malformed run reads as unreadable, and
      // the prior good one is still visible through `previous` next release.
      return (
        <p className={hintClass} data-testid={`verdict-unreadable-${run.id}`}>
          {t("scheduled.verdictUnreadable")}
        </p>
      );
    }
    const when = formatInZone(verdict.recorded_at, displayZone(run), locale);
    if (verdict.items.length === 0) {
      return (
        <p className={hintClass} data-testid={`verdict-nocalls-${run.id}`}>
          {t("scheduled.verdictNoCalls")} · {t("scheduled.verdictRecorded", { when })}
        </p>
      );
    }
    const delta =
      verdict.previous && verdict.previous.outcome !== verdict.outcome
        ? t("scheduled.verdictDelta", { was: verdict.previous.outcome, now: verdict.outcome })
        : null;
    return (
      <p className="break-words text-xs text-muted-foreground" data-testid={`verdict-line-${run.id}`}>
        <span className="font-medium text-foreground">
          {verdict.items.map((item) => `${item.symbol} ${item.state}`).join(" · ")}
        </span>
        {" · "}
        {delta ? <span>{delta} · </span> : null}
        {t("scheduled.verdictRecorded", { when })}
      </p>
    );
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
      case "expired":
        return { label: t("scheduled.statusExpired", { defaultValue: "Expired" }), tone: "neutral" };
      default:
        return { label: t("scheduled.statusPending"), tone: "neutral" };
    }
  }

  const configuredDeliveryChannels = Object.values(channelStatus)
    .filter((channel) => channel.configured && channel.enabled && channel.available)
    .sort((a, b) => a.display_name.localeCompare(b.display_name));

  const selectedChannel = deliveryChannel ? channelStatus[deliveryChannel] : undefined;
  const selectedChannelIsAvailable = configuredDeliveryChannels.some(
    (channel) => channel.name === deliveryChannel,
  );
  const targetLabel =
    selectedChannel?.delivery_target_label ||
    (selectedChannel?.delivery_target_kind
      ? t(`scheduled.deliveryTargetKind_${selectedChannel.delivery_target_kind}`, {
          defaultValue: t("scheduled.deliveryTargetLabel"),
        })
      : t("scheduled.deliveryTargetLabel"));
  const targetPlaceholder =
    selectedChannel?.delivery_target_placeholder || t("scheduled.deliveryTargetPlaceholder");
  const targetInputType =
    selectedChannel?.delivery_target_input_type === "email" ? "email" : "text";
  const targetSuggestions = selectedChannel?.delivery_target_suggestions ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <header className="flex items-center gap-3">
        <CalendarClock className="h-6 w-6 text-primary" aria-hidden />
        <div>
          <h1 className="text-xl font-semibold">{t("scheduled.title")}</h1>
          <p className={hintClass}>{t("scheduled.subtitle")}</p>
        </div>
      </header>

      <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border bg-card p-4">
        {editingId && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-2">
            <p className="text-sm">{t("scheduled.editingHint")}</p>
            <button
              type="button"
              onClick={resetComposer}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
              {t("scheduled.cancelEdit")}
            </button>
          </div>
        )}
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

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="scheduled-delivery-channel" className={labelClass}>
              {t("scheduled.deliveryChannelLabel")}
            </label>
            <select
              id="scheduled-delivery-channel"
              value={deliveryChannel}
              onChange={(e) => {
                const nextChannel = e.target.value;
                if (nextChannel !== deliveryChannel) {
                  setDeliveryTarget("");
                  setDeliveryTargetRef(null);
                }
                setDeliveryChannel(nextChannel);
              }}
              className={fieldClass}
            >
              <option value="">{t("scheduled.deliveryInApp")}</option>
              {deliveryChannel && !selectedChannelIsAvailable && (
                <option value={deliveryChannel}>
                  {t("scheduled.deliveryChannelUnavailable", {
                    channel: selectedChannel?.display_name || deliveryChannel,
                  })}
                </option>
              )}
              {configuredDeliveryChannels.map((channel) => (
                <option key={channel.name} value={channel.name}>
                  {channel.display_name}
                </option>
              ))}
            </select>
            {channelLoadError ? (
              <p className="text-xs text-danger">{t("scheduled.deliveryChannelsLoadFailed")}</p>
            ) : configuredDeliveryChannels.length === 0 && !deliveryChannel ? (
              <p className={hintClass}>{t("scheduled.deliveryNoChannels")}</p>
            ) : (
              <p className={hintClass}>{t("scheduled.deliveryHint")}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <label htmlFor="scheduled-delivery-target" className={labelClass}>
              {targetLabel}
            </label>
            <input
              id="scheduled-delivery-target"
              type={targetInputType}
              disabled={!deliveryChannel}
              value={deliveryTarget}
              onChange={(e) => {
                setDeliveryTarget(e.target.value);
                setDeliveryTargetRef(null);
              }}
              placeholder={
                deliveryChannel
                  ? targetPlaceholder
                  : t("scheduled.deliveryTargetDisabled")
              }
              className={fieldClass}
            />
            {deliveryChannel && targetSuggestions.length > 0 && (
              <select
                aria-label={t("scheduled.deliveryKnownTargetLabel")}
                value=""
                onChange={(e) => {
                  if (!e.target.value) return;
                  setDeliveryTarget(e.target.value);
                  setDeliveryTargetRef(null);
                }}
                className={fieldClass}
              >
                <option value="">{t("scheduled.deliveryKnownTargetPlaceholder")}</option>
                {targetSuggestions.map((suggestion) => {
                  const label = suggestion.kind
                    ? t(`scheduled.deliverySuggestionKind_${suggestion.kind}`, {
                        defaultValue: suggestion.label || suggestion.target,
                      })
                    : suggestion.label || suggestion.target;
                  return (
                    <option
                      key={`${suggestion.kind || "target"}:${suggestion.target}`}
                      value={suggestion.target}
                    >
                      {label} · {maskDeliveryTarget(suggestion.target)}
                    </option>
                  );
                })}
              </select>
            )}
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
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : editingId ? (
              <Save className="h-4 w-4" aria-hidden />
            ) : (
              <Plus className="h-4 w-4" aria-hidden />
            )}
            {editingId ? t("scheduled.saveChanges") : t("scheduled.create")}
          </button>
          {editingId && (
            <button
              type="button"
              disabled={saving}
              onClick={resetComposer}
              className="rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted disabled:opacity-60"
            >
              {t("scheduled.cancelEdit")}
            </button>
          )}
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
                      {run.title && <span className="font-semibold">{run.title}</span>}
                      <span className="font-medium">{cadenceLabel(run)}</span>
                      <span className={hintClass}>{zone}</span>
                      <StatusPill label={status.label} tone={status.tone} />
                    </div>
                    <p className="line-clamp-2 break-words text-sm text-muted-foreground">{run.prompt}</p>
                    <p className={hintClass}>
                      {run.status === "expired"
                        ? t("scheduled.noFurtherRuns", { defaultValue: "No further runs" })
                        : t("scheduled.nextRun", {
                            when: formatInZone(run.next_run_at, zone, locale),
                          })}
                    </p>
                    {run.end_at && (
                      <p className={hintClass}>
                        {t("scheduled.endsAt", {
                          defaultValue: "Ends {{when}}",
                          when: formatInZone(run.end_at, zone, locale),
                        })}
                      </p>
                    )}
                    {run.last_error && (
                      <p className="break-words text-xs text-danger">
                        {t("scheduled.lastError", { error: run.last_error })}
                      </p>
                    )}
                    {run.delivery_channel && (
                      <>
                        <p className={hintClass}>
                          {t("scheduled.deliverySummary", {
                            channel:
                              channelStatus[run.delivery_channel]?.display_name ||
                              run.delivery_channel,
                            target:
                              run.delivery_target_label ||
                              run.delivery_target ||
                              t("scheduled.deliveryUnknownTarget"),
                          })}
                        </p>
                        <p
                          className={
                            run.delivery_status === "failed"
                              ? "break-words text-xs text-danger"
                              : hintClass
                          }
                        >
                          {t(`scheduled.delivery_${run.delivery_status}`, {
                            channel:
                              channelStatus[run.delivery_channel]?.display_name ||
                              run.delivery_channel,
                            defaultValue: t("scheduled.delivery_none", {
                              channel:
                                channelStatus[run.delivery_channel]?.display_name ||
                                run.delivery_channel,
                            }),
                          })}
                          {run.delivery_status === "failed" && run.delivery_error
                            ? ` — ${run.delivery_error}`
                            : ""}
                        </p>
                      </>
                    )}
                    {verdictCell(run)}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => beginEdit(run)}
                      disabled={run.status === "running"}
                      aria-label={t("scheduled.editAria", { prompt: run.prompt })}
                      title={
                        run.status === "running"
                          ? t("scheduled.editRunningDisabled")
                          : undefined
                      }
                      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                      {t("scheduled.edit")}
                    </button>
                    {pendingDelete === run.id ? (
                      <>
                        {/* Cancel first so an accidental double-click disarms instead of destroying. */}
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
                      </>
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
                  </div>
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
