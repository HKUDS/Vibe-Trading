import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  bidAskSpreadPct,
  buildPayoffRequest,
  buildVolatilitySurfaceRequest,
  DEFAULT_SURFACE_EXPIRY_DAYS,
  DEFAULT_SURFACE_OBSERVATIONS,
  DEFAULT_SURFACE_STRIKES,
  buildPresetLegs,
  DEFAULT_PARAMS,
  downsampleIndices,
  expirationLabel,
  fractionToPct,
  getPreset,
  ivLabel,
  nearestStrikeIndex,
  niceStrikeStep,
  pctToFraction,
  parsePositiveGrid,
  roundToNiceStrike,
  volatilitySurfaceIssue,
  STRATEGY_PRESETS,
  type OptionLeg,
  type OptionsContractRow,
} from "../options";

it.each(["America/Los_Angeles", "America/New_York", "UTC", "Asia/Singapore"])("keeps the source expiration date in %s", (timeZone) => {
  // Use a fresh process so the assertion exercises real timezone conversion
  // even when CI and the test worker run in UTC.
  const script = `
    import { expirationLabel } from ${JSON.stringify(pathToFileURL(resolve("src/lib/options.ts")).href)};
    console.log(JSON.stringify([[2026, 0, 16], [2026, 6, 17]].map(([year, month, day]) => ({
      actual: expirationLabel(Date.UTC(year, month, day) / 1000),
      expected: new Date(year, month, day, 12).toLocaleDateString(undefined, {
        year: "numeric", month: "short", day: "numeric",
      }),
    }))));
  `;
  const rows = JSON.parse(execFileSync(process.execPath, ["--experimental-strip-types", "--input-type=module", "-e", script], {
    encoding: "utf8", env: { ...process.env, TZ: timeZone },
  })) as { actual: string; expected: string }[];
  for (const row of rows) expect(row.actual).toBe(row.expected);
});

describe("strategy preset catalog", () => {
  it("ships at least 10 presets with unique ids and options.presets.* name keys", () => {
    expect(STRATEGY_PRESETS.length).toBeGreaterThanOrEqual(10);
    const ids = STRATEGY_PRESETS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const preset of STRATEGY_PRESETS) {
      expect(preset.nameKey.startsWith("options.presets.")).toBe(true);
    }
  });

  it("long_call builds one long call at the rounded spot strike", () => {
    const legs = buildPresetLegs("long_call", 100)!;
    expect(legs).toHaveLength(1);
    expect(legs[0].option_type).toBe("call");
    expect(legs[0].qty).toBe(1);
    expect(legs[0].strike).toBe(100);
  });

  it("long_put builds one long put", () => {
    const legs = buildPresetLegs("long_put", 100)!;
    expect(legs).toHaveLength(1);
    expect(legs[0].option_type).toBe("put");
    expect(legs[0].qty).toBe(1);
  });

  it("long_straddle buys a call and a put at the same strike", () => {
    const legs = buildPresetLegs("long_straddle", 100)!;
    expect(legs).toHaveLength(2);
    const types = legs.map((l) => l.option_type).sort();
    expect(types).toEqual(["call", "put"]);
    expect(legs[0].strike).toBe(legs[1].strike);
    expect(legs.every((l) => l.qty === 1)).toBe(true);
  });

  it("bull_call_spread longs the lower strike and shorts the higher", () => {
    const legs = buildPresetLegs("bull_call_spread", 100)!;
    expect(legs).toHaveLength(2);
    expect(legs.every((l) => l.option_type === "call")).toBe(true);
    const long = legs.find((l) => l.qty === 1)!;
    const short = legs.find((l) => l.qty === -1)!;
    expect(long.strike).toBeLessThan(short.strike);
  });

  it("iron_condor has four legs, ordered strikes and net-zero quantity", () => {
    const legs = buildPresetLegs("iron_condor", 100)!;
    expect(legs).toHaveLength(4);
    const sorted = [...legs].sort((a, b) => a.strike - b.strike);
    expect(sorted.map((l) => l.strike)).toEqual([90, 95, 105, 110]);
    expect(sorted[0].option_type).toBe("put");
    expect(sorted[0].qty).toBe(1);
    expect(sorted[1].option_type).toBe("put");
    expect(sorted[1].qty).toBe(-1);
    expect(sorted[2].option_type).toBe("call");
    expect(sorted[2].qty).toBe(-1);
    expect(sorted[3].option_type).toBe("call");
    expect(sorted[3].qty).toBe(1);
    expect(legs.reduce((sum, l) => sum + l.qty, 0)).toBe(0);
  });

  it("call_butterfly is +1 / -2 / +1 with the body between the wings", () => {
    const legs = buildPresetLegs("call_butterfly", 100)!;
    expect(legs).toHaveLength(3);
    expect(legs.every((l) => l.option_type === "call")).toBe(true);
    const qtys = [...legs].sort((a, b) => a.strike - b.strike).map((l) => l.qty);
    expect(qtys).toEqual([1, -2, 1]);
    expect(legs.reduce((sum, l) => sum + l.qty, 0)).toBe(0);
  });

  it("ratio_call_spread longs 1 lower strike and shorts 2 higher strikes", () => {
    const legs = buildPresetLegs("ratio_call_spread", 100)!;
    expect(legs).toHaveLength(2);
    const long = legs.find((l) => l.qty === 1)!;
    const short = legs.find((l) => l.qty === -2)!;
    expect(long.strike).toBeLessThan(short.strike);
  });

  it("returns null for unknown presets and invalid spots", () => {
    expect(buildPresetLegs("nope", 100)).toBeNull();
    expect(buildPresetLegs("long_call", 0)).toBeNull();
    expect(buildPresetLegs("long_call", NaN)).toBeNull();
    expect(getPreset("nope")).toBeUndefined();
  });
});

describe("roundToNiceStrike", () => {
  it("rounds to the price-level step grid", () => {
    expect(roundToNiceStrike(100)).toBe(100);
    expect(roundToNiceStrike(227.35)).toBe(225);
    expect(roundToNiceStrike(52)).toBe(52.5);
    expect(roundToNiceStrike(21.4)).toBe(21);
    expect(roundToNiceStrike(3.1)).toBe(3);
  });

  it("never returns a non-positive strike", () => {
    expect(roundToNiceStrike(0.4)).toBeGreaterThan(0);
    expect(roundToNiceStrike(0)).toBe(0);
    expect(roundToNiceStrike(-5)).toBe(0);
    expect(roundToNiceStrike(NaN)).toBe(0);
  });

  it("uses coarser steps for higher prices", () => {
    expect(niceStrikeStep(250)).toBe(5);
    expect(niceStrikeStep(75)).toBe(2.5);
    expect(niceStrikeStep(30)).toBe(1);
    expect(niceStrikeStep(10)).toBe(0.5);
    expect(niceStrikeStep(2)).toBe(0.25);
  });
});

describe("buildPayoffRequest", () => {
  const validLegs: OptionLeg[] = [{ option_type: "call", strike: 100, qty: 1 }];

  it("converts percent inputs to fractions in the request body", () => {
    const req = buildPayoffRequest(validLegs, DEFAULT_PARAMS)!;
    expect(req.entry_spot).toBe(100);
    expect(req.expiry_days).toBe(30);
    expect(req.volatility).toBeCloseTo(0.3);
    expect(req.risk_free_rate).toBeCloseTo(0.05);
    expect(req.commission_rate).toBeCloseTo(0.001);
    expect(req.multiplier).toBe(100);
    expect(req.legs).toHaveLength(1);
  });

  it("omits premium when undefined and keeps it when set", () => {
    const without = buildPayoffRequest(validLegs, DEFAULT_PARAMS)!;
    expect("premium" in without.legs[0]).toBe(false);
    const withPrem = buildPayoffRequest(
      [{ option_type: "put", strike: 95, qty: -1, premium: 2.5 }],
      DEFAULT_PARAMS,
    )!;
    expect(withPrem.legs[0].premium).toBe(2.5);
  });

  it("rejects out-of-contract inputs", () => {
    expect(buildPayoffRequest([], DEFAULT_PARAMS)).toBeNull();
    expect(buildPayoffRequest([{ option_type: "call", strike: -1, qty: 1 }], DEFAULT_PARAMS)).toBeNull();
    expect(buildPayoffRequest([{ option_type: "call", strike: 100, qty: 0 }], DEFAULT_PARAMS)).toBeNull();
    expect(buildPayoffRequest([{ option_type: "call", strike: 100, qty: 1.5 }], DEFAULT_PARAMS)).toBeNull();
    expect(buildPayoffRequest(validLegs, { ...DEFAULT_PARAMS, entry_spot: 0 })).toBeNull();
    expect(buildPayoffRequest(validLegs, { ...DEFAULT_PARAMS, expiry_days: -1 })).toBeNull();
    expect(buildPayoffRequest(validLegs, { ...DEFAULT_PARAMS, volatility_pct: 0 })).toBeNull();
    expect(buildPayoffRequest(validLegs, { ...DEFAULT_PARAMS, multiplier: 0 })).toBeNull();
    expect(buildPayoffRequest(validLegs, { ...DEFAULT_PARAMS, commission_rate_pct: 100 })).toBeNull();
    expect(
      buildPayoffRequest([{ option_type: "call", strike: 100, qty: 1, premium: -2 }], DEFAULT_PARAMS),
    ).toBeNull();
  });
});

describe("percent conversion helpers", () => {
  it("round-trips percents and fractions", () => {
    expect(pctToFraction(30)).toBeCloseTo(0.3);
    expect(pctToFraction(0.1)).toBeCloseTo(0.001);
    expect(fractionToPct(0.05)).toBeCloseTo(5);
  });
});

describe("downsampleIndices", () => {
  it("returns the identity when the grid is already small enough", () => {
    expect(downsampleIndices(10, 61)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  });

  it("keeps first and last and stays monotonic on the 121 -> 61 case", () => {
    const idx = downsampleIndices(121, 61);
    expect(idx).toHaveLength(61);
    expect(idx[0]).toBe(0);
    expect(idx[idx.length - 1]).toBe(120);
    for (let i = 1; i < idx.length; i++) {
      expect(idx[i]).toBeGreaterThan(idx[i - 1]);
    }
  });

  it("handles degenerate inputs", () => {
    expect(downsampleIndices(0, 61)).toEqual([]);
    expect(downsampleIndices(5, 1)).toEqual([0, 1, 2, 3, 4]);
  });
});

describe("bidAskSpreadPct", () => {
  it("computes spread percent of mid", () => {
    expect(bidAskSpreadPct(1, 2)).toBeCloseTo(66.6667, 3);
    expect(bidAskSpreadPct(99, 101)).toBeCloseTo(2, 5);
  });

  it("returns null for missing or non-positive mid", () => {
    expect(bidAskSpreadPct(null, 2)).toBeNull();
    expect(bidAskSpreadPct(1, null)).toBeNull();
    expect(bidAskSpreadPct(-1, 1)).toBeNull();
    expect(bidAskSpreadPct(NaN, 1)).toBeNull();
  });
});

describe("nearestStrikeIndex", () => {
  const row = (strike: number): OptionsContractRow => ({
    contract_symbol: `X${strike}`,
    strike,
    last_price: null,
    bid: null,
    ask: null,
    volume: null,
    open_interest: null,
    implied_volatility: null,
    in_the_money: false,
    expiration: 0,
  });

  it("finds the strike closest to the reference spot", () => {
    const rows = [row(90), row(95), row(100), row(105)];
    expect(nearestStrikeIndex(rows, 101)).toBe(2);
    expect(nearestStrikeIndex(rows, 93)).toBe(1);
  });

  it("returns -1 for empty rows or invalid spot", () => {
    expect(nearestStrikeIndex([], 100)).toBe(-1);
    expect(nearestStrikeIndex([row(100)], NaN)).toBe(-1);
  });
});

describe("display formatters", () => {
  it("expirationLabel renders a non-empty locale date", () => {
    const label = expirationLabel(1755216000);
    expect(typeof label).toBe("string");
    expect(label.length).toBeGreaterThan(0);
  });

  it("ivLabel formats IV fractions as percents", () => {
    expect(ivLabel(0.3)).toBe("30%");
    expect(ivLabel(0.255)).toBe("25.5%");
  });
});

describe("preset strike geometry", () => {
  it.each([0.01, 0.4, 0.74, 0.75, 1, 2, 4.9, 5, 19.9, 20, 49, 50, 53, 100, 199, 200])(
    "preserves distinct strikes and symmetric wings at spot %s", (spot) => {
      for (const id of ["bull_call_spread", "bear_put_spread", "bull_put_spread", "bear_call_spread", "long_strangle", "ratio_call_spread"]) {
        const legs = buildPresetLegs(id, spot)!;
        expect(new Set(legs.map((leg) => leg.strike)).size, id).toBe(2);
      }
      const condor = buildPresetLegs("iron_condor", spot)!;
      expect(condor[0].strike).toBeGreaterThan(0);
      for (let i = 1; i < condor.length; i++) {
        expect(condor[i].strike).toBeGreaterThan(condor[i - 1].strike);
      }
      expect(condor[1].strike - condor[0].strike).toBeCloseTo(condor[3].strike - condor[2].strike, 10);
      for (const id of ["call_butterfly", "iron_butterfly"]) {
        const strikes = [...new Set(buildPresetLegs(id, spot)!.map((leg) => leg.strike))].sort((a, b) => a - b);
        expect(strikes, id).toHaveLength(3);
        expect(strikes[0]).toBeGreaterThan(0);
        expect(strikes[1] - strikes[0], id).toBeCloseTo(strikes[2] - strikes[1], 10);
      }
    },
  );
});

it("accepts 20 legs and rejects 21 before submitting a payoff request", () => {
  const legs: OptionLeg[] = Array.from({ length: 20 }, () => ({ option_type: "call", strike: 100, qty: 1 }));
  expect(buildPayoffRequest(legs, DEFAULT_PARAMS)?.legs).toHaveLength(20);
  expect(buildPayoffRequest([...legs, legs[0]], DEFAULT_PARAMS)).toBeNull();
});

describe("volatility surface request inputs", () => {
  it("converts days and percent IV to backend years and fractions", () => {
    const request = buildVolatilitySurfaceRequest(
      "100",
      DEFAULT_SURFACE_OBSERVATIONS,
      DEFAULT_SURFACE_STRIKES,
      DEFAULT_SURFACE_EXPIRY_DAYS,
    );

    expect(request).not.toBeNull();
    expect(request?.spot).toBe(100);
    expect(request?.strikes).toEqual([90, 100, 110]);
    expect(request?.expiries).toHaveLength(5);
    expect(request?.observations[0]).toEqual({
      strike: 90,
      time_to_expiry: 30 / 365,
      implied_volatility: 0.24,
    });
  });

  it("rejects malformed, non-positive, and blank values", () => {
    expect(parsePositiveGrid("90, 100, 110")).toEqual([90, 100, 110]);
    expect(parsePositiveGrid("90, 0")).toBeNull();
    expect(parsePositiveGrid("90,")).toBeNull();
    expect(buildVolatilitySurfaceRequest("0", DEFAULT_SURFACE_OBSERVATIONS, "90", "30")).toBeNull();
    expect(buildVolatilitySurfaceRequest("100", [], "90", "30")).toBeNull();
    expect(buildVolatilitySurfaceRequest("100", [{ id: 1, strike: "90", expiryDays: "30", ivPct: "" }], "90", "30")).toBeNull();
    expect(buildVolatilitySurfaceRequest("100", DEFAULT_SURFACE_OBSERVATIONS, "90, 0", "30")).toBeNull();
  });

  it("reports duplicate quotes in days before any backend call", () => {
    const request = buildVolatilitySurfaceRequest(
      "100",
      [...DEFAULT_SURFACE_OBSERVATIONS, { ...DEFAULT_SURFACE_OBSERVATIONS[0], id: 7 }],
      DEFAULT_SURFACE_STRIKES,
      DEFAULT_SURFACE_EXPIRY_DAYS,
    )!;
    expect(volatilitySurfaceIssue(request)).toEqual({
      key: "duplicateQuote",
      values: { strike: 90, days: 30 },
    });
  });

  it("reports grid expiries outside quote coverage in days", () => {
    const request = buildVolatilitySurfaceRequest(
      "100",
      DEFAULT_SURFACE_OBSERVATIONS,
      DEFAULT_SURFACE_STRIKES,
      "15, 30, 60, 90",
    )!;
    expect(volatilitySurfaceIssue(request)).toEqual({
      key: "expiryOutOfRange",
      values: { days: 15, minDays: 30, maxDays: 90 },
    });
  });

  it("checks strike coverage at every observed expiry rather than only globally", () => {
    const observations = DEFAULT_SURFACE_OBSERVATIONS.map((observation) => (
      observation.id === 3 ? { ...observation, strike: "100" } : { ...observation }
    ));
    const request = buildVolatilitySurfaceRequest(
      "100",
      observations,
      "90, 100, 110",
      DEFAULT_SURFACE_EXPIRY_DAYS,
    )!;
    expect(volatilitySurfaceIssue(request)).toEqual({
      key: "strikeOutOfRange",
      values: { strike: 90, minStrike: 100, maxStrike: 110, days: 60 },
    });
  });

  it("rejects quote, grid, and cross-product limits on the client", () => {
    const quotes = Array.from({ length: 401 }, (_, index) => ({
      id: index + 1,
      strike: String(90 + index),
      expiryDays: "30",
      ivPct: "25",
    }));
    const quoteRequest = buildVolatilitySurfaceRequest("100", quotes, "90", "30")!;
    expect(volatilitySurfaceIssue(quoteRequest)).toEqual({ key: "quoteLimit", values: { limit: 400 } });

    const gridRequest = buildVolatilitySurfaceRequest(
      "100",
      DEFAULT_SURFACE_OBSERVATIONS,
      Array.from({ length: 401 }, (_, index) => String(90 + index)).join(","),
      "30",
    )!;
    expect(volatilitySurfaceIssue(gridRequest)).toEqual({ key: "gridLimit", values: { limit: 400 } });

    const pointRequest = buildVolatilitySurfaceRequest(
      "100",
      DEFAULT_SURFACE_OBSERVATIONS,
      Array.from({ length: 21 }, (_, index) => String(90 + index)).join(","),
      Array.from({ length: 20 }, (_, index) => String(30 + index)).join(","),
    )!;
    expect(volatilitySurfaceIssue(pointRequest)).toEqual({ key: "pointLimit", values: { limit: 400 } });
  });
});


it("includes stock units and keeps pre-upgrade drafts options-only", () => {
  const legs = [{ option_type: "call" as const, strike: 110, qty: -1, premium: 2 }];
  expect(buildPayoffRequest(legs, { ...DEFAULT_PARAMS, underlying_qty: 1 })?.underlying_qty).toBe(1);
  const { underlying_qty: _, ...oldDraft } = DEFAULT_PARAMS;
  expect(buildPayoffRequest(legs, oldDraft)?.underlying_qty).toBe(0);
  expect(buildPayoffRequest(legs, { ...DEFAULT_PARAMS, underlying_qty: Number.NaN })).toBeNull();
});

it("passes exact expiry prices through without financial calculations", () => {
  const legs: OptionLeg[] = [{ option_type: "call", strike: 100, qty: 1 }];
  expect(buildPayoffRequest(legs, { ...DEFAULT_PARAMS, expiry_spots_text: "160, 180，0" })?.expiry_spot_values).toEqual([160, 180, 0]);
  expect(buildPayoffRequest(legs, DEFAULT_PARAMS)?.expiry_spot_values).toBeUndefined();
  for (const text of ["160,", "-1", "NaN", "Infinity", "bad"]) {
    expect(buildPayoffRequest(legs, { ...DEFAULT_PARAMS, expiry_spots_text: text })).toBeNull();
  }
});
