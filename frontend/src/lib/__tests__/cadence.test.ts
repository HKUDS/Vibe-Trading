import { describe, expect, it } from "vitest";
import {
  describeCadence,
  formatIntervalMs,
  formatWallTime,
  formatWeekdays,
} from "@/lib/cadence";

describe("describeCadence", () => {
  it("classifies interval-ms schedules", () => {
    expect(describeCadence("60000")).toEqual({ kind: "interval", ms: 60000 });
  });

  it("classifies a fixed daily time", () => {
    expect(describeCadence("0 9 * * *")).toEqual({ kind: "daily", hour: 9, minute: 0 });
  });

  it("classifies weekday ranges and lists in local terms", () => {
    expect(describeCadence("30 23 * * 1-5")).toEqual({
      kind: "weekly",
      weekdays: [1, 2, 3, 4, 5],
      hour: 23,
      minute: 30,
    });
    expect(describeCadence("0 9 * * 1,3-4")).toEqual({
      kind: "weekly",
      weekdays: [1, 3, 4],
      hour: 9,
      minute: 0,
    });
  });

  it("falls back to the raw expression for anything else", () => {
    expect(describeCadence("*/5 * * * *")).toEqual({ kind: "cron", expression: "*/5 * * * *" });
    expect(describeCadence("0 9 1 * *")).toEqual({ kind: "cron", expression: "0 9 1 * *" });
    expect(describeCadence("0 9 * * 5-1")).toEqual({ kind: "cron", expression: "0 9 * * 5-1" });
  });
});

describe("formatIntervalMs", () => {
  it("prefers the largest whole unit", () => {
    expect(formatIntervalMs(3_600_000)).toBe("1h");
    expect(formatIntervalMs(300_000)).toBe("5m");
    expect(formatIntervalMs(5_000)).toBe("5s");
    expect(formatIntervalMs(1_500)).toBe("1500ms");
  });
});

describe("formatWallTime", () => {
  it("zero-pads to HH:MM", () => {
    expect(formatWallTime(9, 5)).toBe("09:05");
    expect(formatWallTime(23, 30)).toBe("23:30");
  });
});

describe("formatWeekdays", () => {
  it("collapses a contiguous span", () => {
    expect(formatWeekdays([1, 2, 3, 4, 5], "en")).toBe("Mon–Fri");
  });

  it("lists non-contiguous days", () => {
    expect(formatWeekdays([1, 3, 5], "en")).toBe("Mon, Wed, Fri");
    expect(formatWeekdays([0, 6], "en")).toBe("Sun, Sat");
  });
});
