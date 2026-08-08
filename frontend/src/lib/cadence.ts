// Structured description of a scheduled-run cadence.
//
// The backend stores the schedule exactly as authored: an interval-ms string,
// or a 5-field cron expression evaluated on the wall clock of the job's IANA
// timezone (UTC when the job has none). Because the stored cron is already
// local time, describing it is a lossless read — no UTC conversion happens
// here, which is what keeps the description correct on both sides of a DST
// transition (#953).

export type CadenceDescription =
  | { kind: "interval"; ms: number }
  | { kind: "daily"; hour: number; minute: number }
  | { kind: "weekly"; weekdays: number[]; hour: number; minute: number }
  | { kind: "cron"; expression: string };

const INTERVAL_RE = /^[1-9][0-9]*$/;
const SIMPLE_VALUE_RE = /^[0-9]+$/;

function parseDowField(field: string): number[] | null {
  // Cron day-of-week convention: Sunday == 0. Accepts N, N-M, and comma
  // lists of both — the exact grammar the backend validates.
  const days = new Set<number>();
  for (const atom of field.split(",")) {
    const match = /^([0-9]+)(?:-([0-9]+))?$/.exec(atom);
    if (!match) return null;
    const start = Number(match[1]);
    const end = match[2] !== undefined ? Number(match[2]) : start;
    if (start > end || end > 6) return null;
    for (let d = start; d <= end; d++) days.add(d);
  }
  return Array.from(days).sort((a, b) => a - b);
}

export function describeCadence(schedule: string): CadenceDescription {
  const spec = schedule.trim();
  if (INTERVAL_RE.test(spec)) {
    return { kind: "interval", ms: Number(spec) };
  }
  const fields = spec.split(/\s+/);
  if (fields.length === 5) {
    const [minute, hour, dom, month, dow] = fields;
    const fixedTime = SIMPLE_VALUE_RE.test(minute) && SIMPLE_VALUE_RE.test(hour);
    if (fixedTime && dom === "*" && month === "*") {
      if (dow === "*") {
        return { kind: "daily", hour: Number(hour), minute: Number(minute) };
      }
      const weekdays = parseDowField(dow);
      if (weekdays) {
        return { kind: "weekly", weekdays, hour: Number(hour), minute: Number(minute) };
      }
    }
  }
  return { kind: "cron", expression: spec };
}

export function formatIntervalMs(ms: number): string {
  if (ms % 3_600_000 === 0) return `${ms / 3_600_000}h`;
  if (ms % 60_000 === 0) return `${ms / 60_000}m`;
  if (ms % 1_000 === 0) return `${ms / 1_000}s`;
  return `${ms}ms`;
}

export function formatWallTime(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

// 2021-08-01 was a Sunday, so day offsets map cron's Sunday==0 convention
// onto real dates for locale-aware weekday names.
const CRON_SUNDAY_UTC_MS = Date.UTC(2021, 7, 1);

export function formatWeekdays(weekdays: number[], locale: string): string {
  const names = new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" });
  const label = (d: number) => names.format(new Date(CRON_SUNDAY_UTC_MS + d * 86_400_000));
  // Collapse a contiguous span into "Mon–Fri"; anything else stays a list.
  const contiguous =
    weekdays.length > 2 &&
    weekdays.every((d, i) => i === 0 || d === weekdays[i - 1] + 1);
  if (contiguous) {
    return `${label(weekdays[0])}–${label(weekdays[weekdays.length - 1])}`;
  }
  return weekdays.map(label).join(", ");
}
