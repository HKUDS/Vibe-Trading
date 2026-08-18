export interface PositionsPanel {
  dates: string[];
  symbols: string[];
  weightByDate: Map<string, Record<string, number>>;
}

export type AssetClass =
  | "a_share"
  | "us_equity"
  | "hk_equity"
  | "ca_equity"
  | "kr_equity"
  | "india_equity"
  | "crypto"
  | "futures"
  | "forex"
  | "other";

export interface GroupWeight {
  group: string;
  weight: number;
}

export const CASH_SYMBOL = "__cash__";

const DATE_COLUMNS = new Set(["timestamp", "date", "time"]);

/**
 * True when a positions.csv column key is a date/time column rather than a
 * symbol weight column. Shared by the parser and the RunDetail `hasPositions`
 * gate so both treat timestamp/date/time identically.
 */
export function isDateColumn(key: string): boolean {
  return DATE_COLUMNS.has(key.toLowerCase());
}

const EQUITY_SUFFIX_MAP: Record<string, AssetClass> = {
  SH: "a_share",
  SZ: "a_share",
  BJ: "a_share",
  HK: "hk_equity",
  US: "us_equity",
  TO: "ca_equity",
  V: "ca_equity",
  KS: "kr_equity",
  KQ: "kr_equity",
  NS: "india_equity",
  BO: "india_equity",
};

const CRYPTO_QUOTE_SUFFIXES = new Set(["USDT", "USDC", "USD"]);

const FUTURES_EXCHANGE_SUFFIXES = new Set([
  "CFFEX", "SHFE", "DCE", "ZCE", "CZCE", "INE", "GFEX",
  "CBOT", "CME", "NYMEX", "COMEX", "ICE",
  "EUREX", "LME", "SGX", "TOCOM", "MCX",
]);

function parseWeightCell(raw: string | undefined): number {
  if (raw === undefined || raw === null || raw === "") return 0;
  const value = Number(raw);
  return Number.isFinite(value) ? value : 0;
}

export function parsePositionsPanel(rows: Array<Record<string, string>>): PositionsPanel {
  const dates: string[] = [];
  const symbols: string[] = [];
  const seenSymbols = new Set<string>();
  const weightByDate = new Map<string, Record<string, number>>();

  for (const row of rows) {
    let date = "";
    for (const [key, value] of Object.entries(row)) {
      if (isDateColumn(key)) {
        date = value ?? "";
        break;
      }
    }
    if (!date) continue;
    if (!weightByDate.has(date)) dates.push(date);
    const weights: Record<string, number> = weightByDate.get(date) ?? {};
    for (const [key, raw] of Object.entries(row)) {
      if (isDateColumn(key)) continue;
      if (!seenSymbols.has(key)) {
        seenSymbols.add(key);
        symbols.push(key);
      }
      weights[key] = parseWeightCell(raw);
    }
    weightByDate.set(date, weights);
  }

  return { dates, symbols, weightByDate };
}

/**
 * Last date that holds any position. Presence is decided by finite GROSS
 * exposure (`sum(|weight|)`), never the signed sum: a market-neutral book
 * (+50% / -50%) nets to zero while fully invested, so a signed test would
 * render the whole tab as empty.
 */
export function latestHoldingDate(panel: PositionsPanel): string | null {
  let latest: string | null = null;
  for (const date of panel.dates) {
    const weights = panel.weightByDate.get(date);
    if (!weights) continue;
    const gross = Object.values(weights).reduce(
      (acc, w) => acc + Math.abs(Number.isFinite(w) ? w : 0),
      0,
    );
    if (gross > 0.001) latest = date;
  }
  return latest;
}

/**
 * Heuristic asset-class classification mirroring the backend symbol rules.
 * Order matters: exchange suffixes first, then crypto quote pairs, then
 * forex shapes, then futures exchange suffixes, then bare alpha tickers.
 */
export function classifyAssetClass(symbol: string): AssetClass {
  const trimmed = symbol.trim();
  if (!trimmed) return "other";
  const upper = trimmed.toUpperCase();

  const dot = upper.lastIndexOf(".");
  if (dot >= 0) {
    const suffix = upper.slice(dot + 1);
    const equity = EQUITY_SUFFIX_MAP[suffix];
    if (equity) return equity;
    if (suffix === "FX") return "forex";
    if (FUTURES_EXCHANGE_SUFFIXES.has(suffix)) return "futures";
  }

  if (upper.endsWith("-PERP")) return "crypto";
  const hyphen = upper.lastIndexOf("-");
  if (hyphen >= 0 && CRYPTO_QUOTE_SUFFIXES.has(upper.slice(hyphen + 1))) return "crypto";
  const slash = upper.lastIndexOf("/");
  if (slash >= 0 && CRYPTO_QUOTE_SUFFIXES.has(upper.slice(slash + 1))) return "crypto";

  if (/^[A-Z]{6}$/.test(upper)) return "forex";
  if (/^[A-Z]{1,5}$/.test(upper)) return "us_equity";

  return "other";
}

/**
 * Groups weights, sorted descending. When more than 12 groups exist, the
 * bottom groups are merged into a single "other" bucket so at most 12
 * entries (11 named + other) remain.
 */
export function aggregateWeights(
  weights: Record<string, number>,
  grouping: (symbol: string) => string,
): GroupWeight[] {
  const totals = new Map<string, number>();
  for (const [symbol, weight] of Object.entries(weights)) {
    if (!Number.isFinite(weight) || weight === 0) continue;
    const group = grouping(symbol);
    totals.set(group, (totals.get(group) ?? 0) + weight);
  }

  const sorted: GroupWeight[] = [...totals.entries()]
    .map(([group, weight]) => ({ group, weight }))
    .sort((a, b) => b.weight - a.weight);

  const MAX_GROUPS = 12;
  if (sorted.length <= MAX_GROUPS) return sorted;

  const kept = sorted.slice(0, MAX_GROUPS - 1);
  const rest = sorted.slice(MAX_GROUPS - 1);
  const otherWeight = rest.reduce((acc, item) => acc + item.weight, 0);
  const merged = [...kept, { group: "other", weight: otherWeight }];
  merged.sort((a, b) => b.weight - a.weight);
  return merged;
}

/**
 * Adds a `__cash__` pseudo-symbol for the uncommitted remainder on the same
 * GROSS basis the pie slices use (`|weight|`): `cash = 1 - sum(|weight|)`,
 * added only when it exceeds 0.5% of NAV.
 *
 * The artifact contract is `weight = direction × margin_value / equity`
 * (engine normalises `sum(|weight|) <= 1`), so the signed sum is NOT a valid
 * cash basis: a +50% / -50% market-neutral book would otherwise show 100%
 * gross positions plus 100% invented cash. When the book is fully committed
 * or levered (`sum(|weight|) >= 1`) no residual exists and the slice is
 * omitted rather than fabricated.
 */
export function withCashSlice(weights: Record<string, number>): Record<string, number> {
  const gross = Object.values(weights).reduce(
    (acc, w) => acc + Math.abs(Number.isFinite(w) ? w : 0),
    0,
  );
  const cash = 1 - gross;
  if (cash <= 0.005) return { ...weights };
  return { ...weights, [CASH_SYMBOL]: cash };
}

/**
 * Even-stride downsample that always keeps the first and last date.
 */
export function downsampleDates(dates: string[], maxPoints = 500): string[] {
  if (dates.length <= maxPoints || maxPoints < 2) return [...dates];
  const step = (dates.length - 1) / (maxPoints - 1);
  const picked: string[] = [];
  const seen = new Set<number>();
  for (let i = 0; i < maxPoints; i += 1) {
    const index = Math.round(i * step);
    if (!seen.has(index)) {
      seen.add(index);
      picked.push(dates[index]);
    }
  }
  if (picked[picked.length - 1] !== dates[dates.length - 1]) {
    picked.push(dates[dates.length - 1]);
  }
  return picked;
}
