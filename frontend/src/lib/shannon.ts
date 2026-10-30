import { request } from "./api";

export interface ShannonHolding { code: string; weight?: number }
export interface ShannonSnapshot { date?: string; holdings: ShannonHolding[] }
export interface ShannonHoldingResult {
  ts_code: string; name?: string; industry?: string; normalized_weight?: number;
  exposures?: Record<string, number | null>;
}
export interface ShannonMeta {
  as_of?: string; actual_factor_date?: string; risk_as_of?: string; actual_as_of?: string;
  requested_holding_count?: number; included_holding_count?: number; excluded_holding_count?: number;
  risk_window_days?: number; specific_risk_method?: string;
  factor_coverage?: Record<string, { ratio: number }>;
}
export interface ShannonDiagnosis {
  status: string; requested_date: string; weight_assumption: "equal" | "custom";
  data: {
    exposures?: { portfolio?: Record<string, number | null> };
    holdings?: ShannonHoldingResult[]; missing?: unknown[];
    risk_attribution?: { total_risk?: number | null; top_stock_contributions?: Record<string, number | null> };
  };
  meta?: ShannonMeta; warnings?: unknown[];
}
export interface ShannonCatalog {
  data?: { universes?: { id: string; ready: boolean; current_as_of: string }[] };
}

const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(`/api/shannon/${path}`, { method: "POST", body: JSON.stringify(body), signal });
export const shannon = {
  status: (signal?: AbortSignal) => request<{ configured: boolean }>("/api/shannon/status", { signal }),
  catalog: (signal?: AbortSignal) => request<ShannonCatalog>("/api/shannon/catalog", { signal }),
  diagnosis: (body: ShannonSnapshot, signal?: AbortSignal) => post<ShannonDiagnosis>("diagnosis", body, signal),
};

/** Explicit percent weights; never silently normalize partial allocations or cash. */
export function parseHoldings(text: string): ShannonHolding[] | null {
  const lines = text.trim().split(/\r?\n/);
  if (!text.trim() || lines.length > 2000) return null;
  const holdings: ShannonHolding[] = [];
  for (const line of lines) {
    const fields = line.trim().split(/[,，\s]+/);
    if (fields.length > 2 || !/^\d{6}\.(SH|SZ|BJ)$/i.test(fields[0])) return null;
    const code = fields[0].toUpperCase();
    if (/^(000\d{3}\.SH|399\d{3}\.SZ|899\d{3}\.BJ)$/.test(code)) return null;
    if (fields[1] && !/^\d+(\.\d+)?%?$/.test(fields[1])) return null;
    const weight = fields[1] ? Number(fields[1].replace("%", "")) / 100 : undefined;
    if (weight !== undefined && (!Number.isFinite(weight) || weight <= 0 || weight > 1)) return null;
    holdings.push({ code, ...(weight === undefined ? {} : { weight }) });
  }
  if (new Set(holdings.map(h => h.code)).size !== holdings.length) return null;
  const supplied = holdings.filter(h => h.weight !== undefined).length;
  if (supplied && (supplied !== holdings.length || Math.abs(holdings.reduce((s, h) => s + (h.weight ?? 0), 0) - 1) > 1e-6)) return null;
  return holdings;
}

export const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
export const percent = (n: number | null | undefined, signed = false) => finite(n) ? `${signed && n > 0 ? "+" : ""}${(n * 100).toFixed(2)}%` : "—";
export const styleLabels: Record<string, [string, string]> = {
  BETA: ["市场贝塔", "Market beta"], VALUE: ["价值", "Value"], GROWTH: ["成长", "Growth"],
  QUALITY: ["质量", "Quality"], MOMENTUM_12M: ["动量12月", "12M momentum"], MOMENTUM_6M: ["动量6月", "6M momentum"],
  VOLATILITY: ["波动率", "Volatility"], LIQUIDITY: ["流动性", "Liquidity"], SIZE: ["市值", "Size"], LEVERAGE: ["杠杆", "Leverage"],
};
