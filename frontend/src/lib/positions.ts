// Parsing and aggregation helpers for the positions artifacts
// (artifacts/positions.csv and artifacts/target_positions.csv). Both are wide
// frames: one `timestamp` column plus one numeric column per symbol.

export interface PositionRow {
  time: string;
  weights: Record<string, number>;
}

export function parsePositionRows(rows?: Array<Record<string, unknown>> | null): PositionRow[] {
  if (!rows) return [];
  const out: PositionRow[] = [];
  for (const row of rows) {
    const time = String(row.timestamp ?? "");
    if (!time) continue;
    const weights: Record<string, number> = {};
    for (const [key, value] of Object.entries(row)) {
      if (key === "timestamp") continue;
      const n = typeof value === "number" ? value : Number(value);
      if (Number.isFinite(n) && n !== 0) weights[key] = n;
    }
    out.push({ time, weights });
  }
  return out;
}

/** Symbols to show as named series, ranked by latest-row absolute weight. */
export function topSymbols(rows: PositionRow[], limit = 8): string[] {
  const latest = rows[rows.length - 1]?.weights ?? {};
  return Object.entries(latest)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, limit)
    .map(([symbol]) => symbol);
}

export interface WeightPoint {
  time: string;
  [symbol: string]: number | string;
}

/** Rows reshaped for a stacked area chart: top symbols plus an Other bucket. */
export function toWeightSeries(rows: PositionRow[], symbols: string[]): WeightPoint[] {
  return rows.map((row) => {
    const point: WeightPoint = { time: row.time };
    let other = 0;
    for (const [symbol, weight] of Object.entries(row.weights)) {
      if (symbols.includes(symbol)) {
        point[symbol] = weight;
      } else {
        other += weight;
      }
    }
    for (const symbol of symbols) {
      if (point[symbol] === undefined) point[symbol] = 0;
    }
    if (other !== 0) point.Other = other;
    return point;
  });
}

export interface DriftRow {
  symbol: string;
  target: number;
  actual: number;
  drift: number;
}

/** Latest target weights vs latest actual weights, largest absolute drift first. */
export function computeDrift(targetRows: PositionRow[], actualRows: PositionRow[]): DriftRow[] {
  const target = targetRows[targetRows.length - 1]?.weights;
  const actual = actualRows[actualRows.length - 1]?.weights;
  if (!target || !actual) return [];
  const symbols = new Set([...Object.keys(target), ...Object.keys(actual)]);
  return [...symbols]
    .map((symbol) => {
      const t = target[symbol] ?? 0;
      const a = actual[symbol] ?? 0;
      return { symbol, target: t, actual: a, drift: a - t };
    })
    .sort((a, b) => Math.abs(b.drift) - Math.abs(a.drift));
}

export function exposureSummary(weights: Record<string, number>): { gross: number; net: number } {
  let gross = 0;
  let net = 0;
  for (const w of Object.values(weights)) {
    gross += Math.abs(w);
    net += w;
  }
  return { gross, net };
}
