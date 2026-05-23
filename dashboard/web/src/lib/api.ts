const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export interface EquityPoint {
  time: string;
  equity: number;
  drawdown: number;
}

export interface StrategyRow {
  strategy_id: string;
  symbol: string;
  gate: string;
  sharpe: number | null;
}

export interface GateResult {
  overall_pass: boolean;
  checks: Record<string, boolean>;
  red_flags: string[];
}

export interface BacktestMetrics {
  total_return: number;
  annual_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  trade_count: number;
  [key: string]: number;
}

export interface StrategyDetail {
  strategy_id: string;
  symbol: string;
  pipeline_stage: string;
  gate: GateResult;
  backtest: {
    in_sample: { metrics: BacktestMetrics; source_run: string };
    out_of_sample?: { metrics: BacktestMetrics; source_run: string };
  };
  generated_at: string;
  [key: string]: unknown;
}

export interface FactorEntry {
  factor: string;
  ic_mean: number;
  ic_std: number;
  ir: number;
  verdict: string;
}

export interface FactorManifest {
  symbol: string;
  factors: FactorEntry[];
  cross_regime_ic: Record<string, Record<string, number>> | null;
  stability: Record<string, number> | null;
  generated_at: string;
}

export interface TestnetStatus {
  strategy_id: string;
  symbol: string;
  status: string;
  pnl: number | null;
  generated_at: string;
  [key: string]: unknown;
}

export const api = {
  strategies: (): Promise<StrategyRow[]> => get("/strategies"),
  strategy: (id: string): Promise<StrategyDetail> => get(`/strategies/${id}`),
  equity: (id: string, run?: string): Promise<EquityPoint[]> =>
    get(`/strategies/${id}/equity${run ? `?run=${run}` : ""}`),
  trades: (id: string, run?: string): Promise<Record<string, unknown>[]> =>
    get(`/strategies/${id}/trades${run ? `?run=${run}` : ""}`),
  factorAnalysis: (): Promise<FactorManifest[]> => get("/factor-analysis"),
  regime: (symbol: string): Promise<Record<string, unknown>> => get(`/regime?symbol=${symbol}`),
  selection: (): Promise<Record<string, unknown>> => get("/selection"),
  pipeline: (): Promise<{ strategy_id: string; symbol: string; pipeline_stage: string; generated_at: string }[]> =>
    get("/pipeline"),
  testnet: (): Promise<TestnetStatus[]> => get("/testnet"),
  testnetDetail: (id: string): Promise<TestnetStatus> => get(`/testnet/${id}`),
  promote: (id: string, body: { override_reason?: string }) =>
    fetch(`${BASE}/strategies/${id}/promote`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  demote: (id: string) =>
    fetch(`${BASE}/strategies/${id}/promote`, { method: "DELETE" }),
};
