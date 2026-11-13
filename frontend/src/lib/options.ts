/**
 * Options Lab — API contract types, preset strategy catalog, and pure
 * display-only helpers.
 *
 * All numeric finance math (payoff curves, Black-Scholes pricing, Greeks,
 * scenario grids) is computed by the backend (`POST /options/payoff`).
 * The ONLY client-side math living here is display-only: strike rounding,
 * percent <-> fraction conversion of user input, grid downsampling, and
 * bid/ask spread width.
 */

// ---------------------------------------------------------------------------
// API contract — POST /options/payoff
// ---------------------------------------------------------------------------

export type OptionType = "call" | "put";

/** One option leg. `qty` is a signed integer: positive = long, negative = short. */
export interface OptionLeg {
  option_type: OptionType;
  strike: number;
  qty: number;
  /** Optional per-share premium; when omitted the backend prices via Black-Scholes. */
  premium?: number;
}

export interface PayoffAlternative { label: string; legs: OptionLeg[] }

export interface PayoffComparison {
  left_label: string;
  right_label: string;
  status: "ok" | "unavailable";
  reason?: string;
  metrics?: Record<string, {
    status?: "unavailable";
    reason?: string;
    left_decimal?: number;
    right_decimal?: number;
    relation?: "higher" | "lower" | "equal";
    difference_percentage_points?: number;
  }>;
}

export interface OptionsPayoffRequest {
  label?: string;
  alternatives?: PayoffAlternative[];
  legs: OptionLeg[];
  entry_spot: number;
  expiry_days: number;
  /** Annual fraction, default 0.05. */
  risk_free_rate?: number;
  /** Annualized IV fraction, default 0.3. */
  volatility?: number;
  /** Contract multiplier, default 1. */
  multiplier?: number;
  /** Signed stock units per multiplier; 1 covers one option contract. */
  underlying_qty?: number;
  price_as_of?: string;
  /** Fraction in [0, 1), default 0.001. */
  commission_rate?: number;
  spot_min?: number;
  spot_max?: number;
  /** Integer 21-501, default 121. */
  spot_points?: number;
  /** IV scenarios as annualized fractions (max 9). */
  scenario_iv_values?: number[];
  expiry_spot_values?: number[];
}

export interface BreakevenInterval {
  start: number;
  end: number | null;
}

export interface OptionsPayoffSummary {
  net_premium: number;
  entry_commission: number;
  entry_cost: number;
  entry_side: "debit" | "credit" | "flat";
  breakevens: number[];
  breakeven_intervals: BreakevenInterval[];
  max_profit: number | null;
  max_loss: number | null;
  profit_unbounded: boolean;
  loss_unbounded: boolean;
}

export interface OptionsGreeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
}

export interface ExpiryCurve {
  spot: number[];
  pnl: number[];
}

export interface ScenarioGrid {
  iv_values: number[];
  spot: number[];
  /** One row per iv_values entry, each row aligned with spot. */
  pnl: number[][];
}

export interface OptionsPayoffResponse {
  comparisons?: PayoffComparison[];
  status: "ok";
  inputs: Record<string, unknown>;
  summary: OptionsPayoffSummary;
  greeks: OptionsGreeks;
  expiry_scenarios?: Array<{ spot: number; pnl: number; return_fraction: number | null; return_percent: number | null }>;
  expiry_curve: ExpiryCurve;
  scenario_grid: ScenarioGrid;
  limitations: string[];
}

export interface VolatilityObservation {
  strike: number;
  /** Years. */
  time_to_expiry: number;
  /** Annualized IV as a fraction: 0.30 = 30%. */
  implied_volatility: number;
}

export interface VolatilitySurfaceRequest {
  observations: VolatilityObservation[];
  spot: number;
  strikes?: number[];
  expiries?: number[];
}

export interface VolatilitySurfacePoint extends VolatilityObservation {
  total_variance: number;
  source: "observed" | "interpolated";
}

export interface VolatilitySurfaceResponse {
  strikes: number[];
  expiries: number[];
  interpolation: {
    strike: "linear_iv_log_moneyness";
    expiry: "linear_total_variance";
    extrapolation: "rejected";
  };
  points: VolatilitySurfacePoint[];
}

// ---------------------------------------------------------------------------
// API contract — GET /options/chain
// ---------------------------------------------------------------------------

/** One contract row; any market field may be null (render "–"). */
export interface OptionsContractRow {
  contract_symbol: string;
  strike: number;
  last_price: number | null;
  bid: number | null;
  ask: number | null;
  volume: number | null;
  open_interest: number | null;
  implied_volatility: number | null;
  in_the_money: boolean;
  expiration: number;
}

export interface OptionsChainData {
  ticker: string;
  /** Source quote and nearest strike in the complete ladder, before row capping. */
  underlying_price?: number | null;
  atm_strike?: number | null;
  expiration: number;
  /** Epoch seconds. */
  expirations: number[];
  calls_count: number;
  puts_count: number;
  calls: OptionsContractRow[];
  puts: OptionsContractRow[];
}

export interface OptionsChainResponse {
  ok: boolean;
  market: string;
  source: string;
  data: OptionsChainData;
  /** Present on `{ok: false}` error envelopes (HTTP 400/502 throw as ApiError). */
  error?: string;
}

// ---------------------------------------------------------------------------
// UI parameter model (percent convention)
// ---------------------------------------------------------------------------

/**
 * Builder parameters as the USER types them. ONE convention, kept consistent
 * across the page: volatility, risk-free rate and commission rate are entered
 * as PERCENTS (30 means 30%) and converted to fractions only when the request
 * body is built.
 */
export interface OptionsLabParams {
  entry_spot: number;
  expiry_days: number;
  /** Percent: 30 = 30% annualized IV. Sent as 0.30. */
  volatility_pct: number;
  /** Percent: 5 = 5%. Sent as 0.05. */
  risk_free_rate_pct: number;
  /** Contract multiplier; 100 = standard US equity contract. */
  multiplier: number;
  underlying_qty?: number;
  /** Percent: 0.1 = 0.1%. Sent as 0.001. */
  commission_rate_pct: number;
  expiry_spots_text?: string;
}

export const DEFAULT_PARAMS: OptionsLabParams = {
  entry_spot: 100,
  expiry_days: 30,
  volatility_pct: 30,
  risk_free_rate_pct: 5,
  multiplier: 100,
  underlying_qty: 0,
  commission_rate_pct: 0.1,
};

export interface SurfaceObservationInput {
  id: number;
  strike: string;
  expiryDays: string;
  ivPct: string;
}

export interface VolatilitySurfaceIssue {
  key: "duplicateQuote" | "expiryOutOfRange" | "strikeOutOfRange" | "quoteLimit" | "gridLimit" | "pointLimit";
  values: Record<string, number>;
}

export const DEFAULT_SURFACE_OBSERVATIONS: SurfaceObservationInput[] = [
  { id: 1, strike: "90", expiryDays: "30", ivPct: "24" },
  { id: 2, strike: "110", expiryDays: "30", ivPct: "30" },
  { id: 3, strike: "90", expiryDays: "60", ivPct: "26" },
  { id: 4, strike: "110", expiryDays: "60", ivPct: "34" },
  { id: 5, strike: "90", expiryDays: "90", ivPct: "28" },
  { id: 6, strike: "110", expiryDays: "90", ivPct: "36" },
];

export const DEFAULT_SURFACE_STRIKES = "90, 100, 110";
export const DEFAULT_SURFACE_EXPIRY_DAYS = "30, 45, 60, 75, 90";

export function parsePositiveGrid(value: string): number[] | null {
  const items = value.split(",").map((item) => item.trim());
  if (items.some((item) => !item)) return null;
  const values = items.map(Number);
  return values.every((value) => Number.isFinite(value) && value > 0) ? values : null;
}

export function buildVolatilitySurfaceRequest(
  spot: string,
  observations: SurfaceObservationInput[],
  strikes: string,
  expiryDays: string,
): VolatilitySurfaceRequest | null {
  const spotValue = Number(spot);
  if (!Number.isFinite(spotValue) || spotValue <= 0 || observations.length === 0) return null;
  const parsedObservations: VolatilityObservation[] = [];
  for (const observation of observations) {
    if (!observation.strike.trim() || !observation.expiryDays.trim() || !observation.ivPct.trim()) return null;
    const strike = Number(observation.strike);
    const days = Number(observation.expiryDays);
    const ivPct = Number(observation.ivPct);
    if (!Number.isFinite(strike) || strike <= 0) return null;
    if (!Number.isFinite(days) || days <= 0) return null;
    if (!Number.isFinite(ivPct) || ivPct < 0) return null;
    parsedObservations.push({
      strike,
      time_to_expiry: days / 365,
      implied_volatility: pctToFraction(ivPct),
    });
  }
  const parsedStrikes = strikes.trim() ? parsePositiveGrid(strikes) : undefined;
  const parsedExpiries = expiryDays.trim() ? parsePositiveGrid(expiryDays) : undefined;
  if (parsedStrikes === null || parsedExpiries === null) return null;
  return {
    observations: parsedObservations,
    spot: spotValue,
    ...(parsedStrikes ? { strikes: parsedStrikes } : {}),
    ...(parsedExpiries ? { expiries: parsedExpiries.map((days) => days / 365) } : {}),
  };
}

export function volatilitySurfaceIssue(request: VolatilitySurfaceRequest): VolatilitySurfaceIssue | null {
  if (request.observations.length > 400) return { key: "quoteLimit", values: { limit: 400 } };
  if (!request.observations.length) return null;
  const strikes = request.strikes ?? [...new Set(request.observations.map((observation) => observation.strike))];
  const expiries = request.expiries ?? [...new Set(request.observations.map((observation) => observation.time_to_expiry))];
  if (strikes.length > 400 || expiries.length > 400) return { key: "gridLimit", values: { limit: 400 } };
  if (new Set(strikes).size * new Set(expiries).size > 400) return { key: "pointLimit", values: { limit: 400 } };

  const seen = new Set<string>();
  const ranges = new Map<number, { minStrike: number; maxStrike: number }>();
  for (const observation of request.observations) {
    const key = JSON.stringify([observation.time_to_expiry, observation.strike]);
    const days = Number((observation.time_to_expiry * 365).toPrecision(12));
    if (seen.has(key)) return { key: "duplicateQuote", values: { strike: observation.strike, days } };
    seen.add(key);
    const range = ranges.get(observation.time_to_expiry);
    if (range) {
      range.minStrike = Math.min(range.minStrike, observation.strike);
      range.maxStrike = Math.max(range.maxStrike, observation.strike);
    } else {
      ranges.set(observation.time_to_expiry, { minStrike: observation.strike, maxStrike: observation.strike });
    }
  }

  const observedExpiries = [...ranges.keys()].sort((a, b) => a - b);
  const minDays = Number((observedExpiries[0] * 365).toPrecision(12));
  const maxDays = Number((observedExpiries[observedExpiries.length - 1] * 365).toPrecision(12));
  const requiredExpiries = new Set<number>();
  for (const expiry of expiries) {
    if (expiry < observedExpiries[0] || expiry > observedExpiries[observedExpiries.length - 1]) {
      return {
        key: "expiryOutOfRange",
        values: { days: Number((expiry * 365).toPrecision(12)), minDays, maxDays },
      };
    }
    if (ranges.has(expiry)) {
      requiredExpiries.add(expiry);
    } else {
      // Match the engine's interpolation coverage: only the two neighboring
      // observed slices contribute to an intermediate expiry.
      const upperIndex = observedExpiries.findIndex((observed) => observed > expiry);
      requiredExpiries.add(observedExpiries[upperIndex - 1]);
      requiredExpiries.add(observedExpiries[upperIndex]);
    }
  }
  for (const expiry of observedExpiries) {
    if (!requiredExpiries.has(expiry)) continue;
    const range = ranges.get(expiry)!;
    for (const strike of [...strikes].sort((a, b) => a - b)) {
      if (strike < range.minStrike || strike > range.maxStrike) {
        return {
          key: "strikeOutOfRange",
          values: {
            strike,
            minStrike: range.minStrike,
            maxStrike: range.maxStrike,
            days: Number((expiry * 365).toPrecision(12)),
          },
        };
      }
    }
  }
  return null;
}

export function pctToFraction(pct: number): number {
  return pct / 100;
}

export function fractionToPct(fraction: number): number {
  return fraction * 100;
}

/** Matches the options payoff API leg limit. */
export const MAX_OPTION_LEGS = 20;

/**
 * Validate inputs against the backend contract and build the request body.
 * Returns null when any input is out of contract bounds (the page then skips
 * the debounced call). Display-only guard — the backend stays authoritative.
 */
export function buildPayoffRequest(
  legs: OptionLeg[],
  p: OptionsLabParams,
): OptionsPayoffRequest | null {
  if (!Number.isFinite(p.entry_spot) || p.entry_spot <= 0) return null;
  if (!Number.isFinite(p.expiry_days) || p.expiry_days < 0) return null;
  if (!Number.isFinite(p.volatility_pct) || p.volatility_pct <= 0) return null;
  if (!Number.isFinite(p.risk_free_rate_pct)) return null;
  if (!Number.isFinite(p.multiplier) || p.multiplier <= 0) return null;
  if (!Number.isFinite(p.underlying_qty ?? 0)) return null;
  if (!Number.isFinite(p.commission_rate_pct) || p.commission_rate_pct < 0 || p.commission_rate_pct >= 100) {
    return null;
  }
  if (legs.length === 0 || legs.length > MAX_OPTION_LEGS) return null;
  for (const leg of legs) {
    if (leg.option_type !== "call" && leg.option_type !== "put") return null;
    if (!Number.isFinite(leg.strike) || leg.strike <= 0) return null;
    if (!Number.isInteger(leg.qty) || leg.qty === 0) return null;
    if (leg.premium !== undefined && (!Number.isFinite(leg.premium) || leg.premium < 0)) return null;
  }
  const text = (p.expiry_spots_text ?? "").trim();
  const expirySpots = text ? text.split(/[,，]/).map((value) => value.trim()) : [];
  if (expirySpots.length > 501 || expirySpots.some((value) => value === "" || !Number.isFinite(Number(value)) || Number(value) < 0)) return null;
  return {
    ...(expirySpots.length ? { expiry_spot_values: expirySpots.map(Number) } : {}),
    legs: legs.map((l) => ({
      option_type: l.option_type,
      strike: l.strike,
      qty: l.qty,
      ...(l.premium !== undefined ? { premium: l.premium } : {}),
    })),
    entry_spot: p.entry_spot,
    expiry_days: p.expiry_days,
    risk_free_rate: pctToFraction(p.risk_free_rate_pct),
    volatility: pctToFraction(p.volatility_pct),
    multiplier: p.multiplier,
    underlying_qty: p.underlying_qty ?? 0,
    commission_rate: pctToFraction(p.commission_rate_pct),
  };
}

// ---------------------------------------------------------------------------
// Preset strategy catalog
// ---------------------------------------------------------------------------

export interface StrategyPreset {
  id: string;
  /** i18n key of the display name (options.presets.*). */
  nameKey: string;
  /** Generate legs parameterized by the underlying spot S. */
  buildLegs: (spot: number) => OptionLeg[];
}

/** Strike grid step by price level — keeps preset strikes on listed-like increments. */
export function niceStrikeStep(price: number): number {
  if (price >= 200) return 5;
  if (price >= 50) return 2.5;
  if (price >= 20) return 1;
  if (price >= 5) return 0.5;
  return 0.25;
}

/** Round a raw price to a "nice" listed-style strike. Returns 0 for non-positive input. */
export function roundToNiceStrike(price: number): number {
  if (!Number.isFinite(price) || price <= 0) return 0;
  const step = niceStrikeStep(price);
  const rounded = Math.max(step, Math.round(price / step) * step);
  return Number(rounded.toFixed(4));
}

function k(spot: number, offset: -2 | -1 | 0 | 1 | 2): number {
  // One grid for the whole strategy keeps distinct strikes and equal wings,
  // including across niceStrikeStep boundaries. Sub-dollar spots need a finer
  // grid so both lower wings remain positive without shifting the body up.
  const listedStep = niceStrikeStep(spot);
  const step = spot < 3 * listedStep
    ? 10 ** Math.floor(Math.log10(spot)) / 10
    : listedStep;
  const centerTicks = Math.round(spot / step);
  const wingTicks = Math.max(1, Math.round(spot * 0.05 / step));
  return Number(((centerTicks + offset * wingTicks) * step).toPrecision(12));
}

/**
 * Twelve canonical presets, parameterized by spot S. Strike ratios follow the
 * S x {0.9, 0.95, 1.0, 1.05, 1.1} approximately, using a shared grid with
 * at least one tick between neighboring levels. These are modeled strikes,
 * not a claim that the contracts are listed by an exchange.
 */
export const STRATEGY_PRESETS: StrategyPreset[] = [
  {
    id: "long_call",
    nameKey: "options.presets.longCall",
    buildLegs: (s) => [{ option_type: "call", strike: k(s, 0), qty: 1 }],
  },
  {
    id: "long_put",
    nameKey: "options.presets.longPut",
    buildLegs: (s) => [{ option_type: "put", strike: k(s, 0), qty: 1 }],
  },
  {
    id: "bull_call_spread",
    nameKey: "options.presets.bullCallSpread",
    buildLegs: (s) => [
      { option_type: "call", strike: k(s, -1), qty: 1 },
      { option_type: "call", strike: k(s, 1), qty: -1 },
    ],
  },
  {
    id: "bear_put_spread",
    nameKey: "options.presets.bearPutSpread",
    buildLegs: (s) => [
      { option_type: "put", strike: k(s, 1), qty: 1 },
      { option_type: "put", strike: k(s, -1), qty: -1 },
    ],
  },
  {
    id: "bull_put_spread",
    nameKey: "options.presets.bullPutSpread",
    buildLegs: (s) => [
      { option_type: "put", strike: k(s, 1), qty: -1 },
      { option_type: "put", strike: k(s, -1), qty: 1 },
    ],
  },
  {
    id: "bear_call_spread",
    nameKey: "options.presets.bearCallSpread",
    buildLegs: (s) => [
      { option_type: "call", strike: k(s, -1), qty: -1 },
      { option_type: "call", strike: k(s, 1), qty: 1 },
    ],
  },
  {
    id: "long_straddle",
    nameKey: "options.presets.longStraddle",
    buildLegs: (s) => [
      { option_type: "call", strike: k(s, 0), qty: 1 },
      { option_type: "put", strike: k(s, 0), qty: 1 },
    ],
  },
  {
    id: "long_strangle",
    nameKey: "options.presets.longStrangle",
    buildLegs: (s) => [
      { option_type: "call", strike: k(s, 1), qty: 1 },
      { option_type: "put", strike: k(s, -1), qty: 1 },
    ],
  },
  {
    id: "iron_condor",
    nameKey: "options.presets.ironCondor",
    buildLegs: (s) => [
      { option_type: "put", strike: k(s, -2), qty: 1 },
      { option_type: "put", strike: k(s, -1), qty: -1 },
      { option_type: "call", strike: k(s, 1), qty: -1 },
      { option_type: "call", strike: k(s, 2), qty: 1 },
    ],
  },
  {
    id: "iron_butterfly",
    nameKey: "options.presets.ironButterfly",
    buildLegs: (s) => [
      { option_type: "put", strike: k(s, 0), qty: -1 },
      { option_type: "call", strike: k(s, 0), qty: -1 },
      { option_type: "put", strike: k(s, -2), qty: 1 },
      { option_type: "call", strike: k(s, 2), qty: 1 },
    ],
  },
  {
    id: "call_butterfly",
    nameKey: "options.presets.callButterfly",
    buildLegs: (s) => [
      { option_type: "call", strike: k(s, -2), qty: 1 },
      { option_type: "call", strike: k(s, 0), qty: -2 },
      { option_type: "call", strike: k(s, 2), qty: 1 },
    ],
  },
  {
    id: "ratio_call_spread",
    nameKey: "options.presets.ratioCallSpread",
    buildLegs: (s) => [
      { option_type: "call", strike: k(s, 0), qty: 1 },
      { option_type: "call", strike: k(s, 2), qty: -2 },
    ],
  },
];

export function getPreset(id: string): StrategyPreset | undefined {
  return STRATEGY_PRESETS.find((p) => p.id === id);
}

export function buildPresetLegs(presetId: string, spot: number): OptionLeg[] | null {
  const preset = getPreset(presetId);
  if (!preset || !Number.isFinite(spot) || spot <= 0) return null;
  return preset.buildLegs(spot);
}

// ---------------------------------------------------------------------------
// Display-only helpers (chain table, heatmap downsampling)
// ---------------------------------------------------------------------------

/**
 * Even-stride index selection that ALWAYS keeps the first and last element.
 * Used to downsample the scenario spot grid for heatmap display.
 */
export function downsampleIndices(total: number, maxPoints: number): number[] {
  if (total <= 0) return [];
  if (total <= maxPoints || maxPoints < 2) {
    return Array.from({ length: total }, (_, i) => i);
  }
  const stride = (total - 1) / (maxPoints - 1);
  const indices: number[] = [];
  for (let i = 0; i < maxPoints; i++) {
    indices.push(Math.round(i * stride));
  }
  indices[indices.length - 1] = total - 1;
  return indices;
}

/** Bid/ask spread width as a percent of mid. Null when uncomputable. */
export function bidAskSpreadPct(bid: number | null, ask: number | null): number | null {
  if (bid === null || ask === null || !Number.isFinite(bid) || !Number.isFinite(ask)) return null;
  const mid = (bid + ask) / 2;
  if (mid <= 0) return null;
  return ((ask - bid) / mid) * 100;
}

/** Index of the row whose strike is nearest to the reference spot (-1 when empty). */
export function nearestStrikeIndex(rows: OptionsContractRow[], spot: number): number {
  if (rows.length === 0 || !Number.isFinite(spot)) return -1;
  let best = 0;
  let bestDist = Math.abs(rows[0].strike - spot);
  for (let i = 1; i < rows.length; i++) {
    const dist = Math.abs(rows[i].strike - spot);
    if (dist < bestDist) {
      best = i;
      bestDist = dist;
    }
  }
  return best;
}

/** Localized label for the UTC calendar date encoded by a chain expiration. */
export function expirationLabel(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Format an IV fraction (0.30) as a percent label ("30%"). */
export function ivLabel(iv: number): string {
  const pct = fractionToPct(iv);
  return `${Number(pct.toFixed(2)).toLocaleString()}%`;
}
