/** Maps metric keys to i18n translation keys */
export const METRIC_I18N_KEYS: Record<string, string> = {
  total_return: "metricTotalReturn",
  annual_return: "metricAnnualReturn",
  sharpe: "metricSharpe",
  max_drawdown: "metricMaxDrawdown",
  win_rate: "metricWinRate",
  trade_count: "metricTradeCount",
  final_value: "metricFinalValue",
  calmar: "metricCalmar",
  sortino: "metricSortino",
  profit_loss_ratio: "metricProfitLossRatio",
  max_consecutive_loss: "metricMaxConsecutiveLoss",
  avg_holding_days: "metricAvgHoldingDays",
  benchmark_return: "metricBenchmarkReturn",
  excess_return: "metricExcessReturn",
  information_ratio: "metricIR",
};

/** Resolve metric label using i18n translations object */
export function getMetricLabel(k: string, t: Record<string, string>): string {
  const i18nKey = METRIC_I18N_KEYS[k];
  return i18nKey ? (t[i18nKey] || k) : k;
}

const PCT_KEYS = ["total_return", "annual_return", "win_rate", "max_drawdown", "benchmark_return", "excess_return"];
const RATIO_KEYS = ["sharpe", "calmar", "sortino", "profit_loss_ratio", "information_ratio"];
const INT_KEYS = ["trade_count", "max_consecutive_loss"];
const NEUTRAL_KEYS = new Set([
  "trade_count", "avg_holding_days", "final_value",
  "win_rate", "max_consecutive_loss", "benchmark_return",
]);

export function formatMetricVal(k: string, v: number): string {
  if (PCT_KEYS.includes(k)) {
    const sign = v > 0 ? "+" : "";
    return `${sign}${(v * 100).toFixed(2)}%`;
  }
  if (RATIO_KEYS.includes(k)) {
    const sign = v > 0 ? "+" : "";
    return `${sign}${v.toFixed(2)}`;
  }
  if (INT_KEYS.includes(k)) return String(Math.round(v));
  if (k === "final_value") return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (k === "avg_holding_days") return v.toFixed(1);
  return v.toFixed(4);
}

export function metricSentiment(k: string, v: number): "positive" | "neutral" | "negative" {
  if (NEUTRAL_KEYS.has(k)) return "neutral";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "neutral";
}

export const DISPLAY_ORDER = [
  "total_return", "annual_return", "sharpe", "max_drawdown", "win_rate", "trade_count",
  "calmar", "sortino", "profit_loss_ratio", "max_consecutive_loss",
  "benchmark_return", "excess_return", "information_ratio", "final_value", "avg_holding_days",
];

export function formatTimestamp(ts: number): string {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export function abbreviateNum(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (abs >= 1e4) return (v / 1e3).toFixed(0) + "K";
  return v.toLocaleString();
}
