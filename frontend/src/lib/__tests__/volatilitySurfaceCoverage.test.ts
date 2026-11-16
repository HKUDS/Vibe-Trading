import { buildVolatilitySurfaceRequest, volatilitySurfaceIssue } from "../options";

const quotes = [
  { id: 1, strike: "90", expiryDays: "30", ivPct: "24" },
  { id: 2, strike: "110", expiryDays: "30", ivPct: "30" },
  { id: 3, strike: "90", expiryDays: "60", ivPct: "26" },
  { id: 4, strike: "110", expiryDays: "60", ivPct: "34" },
  { id: 5, strike: "100", expiryDays: "90", ivPct: "28" },
  { id: 6, strike: "110", expiryDays: "90", ivPct: "36" },
];

it.each(["30", "45", "60", "30,45"])("allows the valid %s-day grid without consulting an unrelated 90-day slice", (days) => {
  const request = buildVolatilitySurfaceRequest("100", quotes, "90", days)!;
  expect(volatilitySurfaceIssue(request)).toBeNull();
});

it.each(["75", "90", "30,75", ""])("still rejects a %s-day grid that needs the uncovered 90-day slice", (days) => {
  const request = buildVolatilitySurfaceRequest("100", quotes, "90", days)!;
  expect(volatilitySurfaceIssue(request)?.key).toBe("strikeOutOfRange");
});

it.each([["45", "strikeOutOfRange"], ["75", null]])(
  "uses lower neighbors without consulting older unrelated slices (%s days)", (days, expected) => {
    const earlyNarrowQuotes = quotes.map((quote) => ({
      ...quote,
      strike: quote.id === 1 ? "100" : quote.id === 5 ? "90" : quote.strike,
    }));
    const request = buildVolatilitySurfaceRequest("100", earlyNarrowQuotes, "90", days)!;
    expect(volatilitySurfaceIssue(request)?.key ?? null).toBe(expected);
  },
);
