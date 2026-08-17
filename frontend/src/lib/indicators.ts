type N = number | null;

/** Cumulative volume-weighted average price for one trading session. */
export function calcIntradayAverage(
  data: Array<{ open: number; high: number; low: number; close: number; volume: number }>,
): number[] {
  let totalVolume = 0;
  let totalValue = 0;
  return data.map((bar) => {
    const volume = Number.isFinite(bar.volume) && bar.volume > 0 ? bar.volume : 0;
    const typicalPrice = (bar.open + bar.high + bar.low + bar.close) / 4;
    if (volume > 0 && Number.isFinite(typicalPrice)) {
      totalVolume += volume;
      totalValue += typicalPrice * volume;
    }
    return totalVolume > 0 ? totalValue / totalVolume : bar.close;
  });
}

export function calcMA(data: number[], period: number): N[] {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += data[j];
    return s / period;
  });
}

export function calcEMA(data: number[], period: number): N[] {
  const k = 2 / (period + 1);
  const out: N[] = [];
  let ema: number | null = null;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      out.push(null);
    } else if (ema === null) {
      let s = 0;
      for (let j = 0; j < period; j++) s += data[j];
      ema = s / period;
      out.push(ema);
    } else {
      ema = data[i] * k + ema * (1 - k);
      out.push(ema);
    }
  }
  return out;
}

export function calcBOLL(data: number[], period = 20, mult = 2) {
  const mid = calcMA(data, period);
  const upper: N[] = [];
  const lower: N[] = [];
  for (let i = 0; i < data.length; i++) {
    if (mid[i] === null) { upper.push(null); lower.push(null); continue; }
    let sq = 0;
    for (let j = i - period + 1; j <= i; j++) sq += (data[j] - mid[i]!) ** 2;
    const std = Math.sqrt(sq / period);
    upper.push(mid[i]! + mult * std);
    lower.push(mid[i]! - mult * std);
  }
  return { upper, mid, lower };
}

function calcMACDWithHistogramScale(data: number[], fast: number, slow: number, sig: number, histogramScale: number) {
  const ef = calcEMA(data, fast);
  const es = calcEMA(data, slow);
  const dif: N[] = data.map((_, i) =>
    ef[i] !== null && es[i] !== null ? ef[i]! - es[i]! : null
  );

  // Signal = EMA of non-null DIF values
  const valid: number[] = [];
  const idx: number[] = [];
  dif.forEach((v, i) => { if (v !== null) { valid.push(v); idx.push(i); } });
  const sigEma = calcEMA(valid, sig);

  const signal: N[] = new Array(data.length).fill(null);
  const hist: N[] = new Array(data.length).fill(null);
  idx.forEach((ii, j) => {
    if (sigEma[j] !== null) {
      signal[ii] = sigEma[j];
      hist[ii] = (dif[ii]! - sigEma[j]!) * histogramScale;
    }
  });
  return { dif, signal, histogram: hist };
}

export function calcMACD(data: number[], fast = 12, slow = 26, sig = 9) {
  return calcMACDWithHistogramScale(data, fast, slow, sig, 1);
}

/** MACD used by Chinese intraday charts: the histogram is 2 * (DIF - DEA). */
export function calcMACDFS(data: number[], fast = 12, slow = 26, sig = 9) {
  return calcMACDWithHistogramScale(data, fast, slow, sig, 2);
}

export function calcRSI(data: number[], period = 14): N[] {
  if (data.length < period + 1) return data.map(() => null);
  const out: N[] = new Array(data.length).fill(null);
  let avgG = 0, avgL = 0;
  for (let i = 1; i <= period; i++) {
    const c = data[i] - data[i - 1];
    if (c > 0) avgG += c; else avgL -= c;
  }
  avgG /= period;
  avgL /= period;
  out[period] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  for (let i = period + 1; i < data.length; i++) {
    const c = data[i] - data[i - 1];
    avgG = (avgG * (period - 1) + (c > 0 ? c : 0)) / period;
    avgL = (avgL * (period - 1) + (c < 0 ? -c : 0)) / period;
    out[i] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  }
  return out;
}

export function calcKDJ(highs: number[], lows: number[], closes: number[], period = 9) {
  const n = closes.length;
  const k: N[] = new Array(n).fill(null);
  const d: N[] = new Array(n).fill(null);
  const j: N[] = new Array(n).fill(null);
  if (n < period) return { k, d, j };

  let pk = 50, pd = 50;
  for (let i = period - 1; i < n; i++) {
    let hi = -Infinity, lo = Infinity;
    for (let p = i - period + 1; p <= i; p++) {
      if (highs[p] > hi) hi = highs[p];
      if (lows[p] < lo) lo = lows[p];
    }
    const rsv = hi === lo ? 50 : ((closes[i] - lo) / (hi - lo)) * 100;
    pk = (pk * 2 + rsv) / 3;
    pd = (pd * 2 + pk) / 3;
    k[i] = pk;
    d[i] = pd;
    j[i] = 3 * pk - 2 * pd;
  }
  return { k, d, j };
}
