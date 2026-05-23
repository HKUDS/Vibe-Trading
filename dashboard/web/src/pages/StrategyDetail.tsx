import { useEffect, useState, type ReactNode } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  api,
  type StrategyManifest,
  type EquityPoint,
  type BacktestMetrics,
  type CostStressLevel,
  type RegimeMetrics,
  type RecommendedAction,
} from "../lib/api";
import { EquityChart } from "../components/charts/EquityChart";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtPct = (v: number | null) =>
  v === null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const fmtRatio = (v: number | null) =>
  v === null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
const fmtInt = (v: number | null) => (v === null ? "—" : String(Math.round(v)));

function MetricRow({
  label,
  is,
  oos,
}: {
  label: string;
  is: ReactNode;
  oos: ReactNode;
}) {
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-4 text-xs text-muted-foreground w-36">{label}</td>
      <td className="py-2 pr-6 text-sm tabular-nums font-medium">{is}</td>
      <td className="py-2 text-sm tabular-nums font-medium">{oos}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Collapsible panel
// ---------------------------------------------------------------------------

function Panel({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-left hover:bg-muted/30 transition-colors"
      >
        {title}
        <span className="text-muted-foreground text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EvidenceChain
// ---------------------------------------------------------------------------

const ACTION_LABEL: Record<RecommendedAction, string> = {
  proceed: "繼續",
  back_to_stage_2: "回 Stage 2",
  back_to_stage_4: "回 Stage 4",
};

interface StageNode {
  label: string;
  done: boolean;
  warning?: string;
}

function EvidenceChain({ manifest }: { manifest: StrategyManifest }) {
  const diagAction = manifest.diagnosis?.recommended_action;
  const nodes: StageNode[] = [
    {
      label: "因子分析",
      done: true, // factors always present if manifest exists
    },
    {
      label: "策略生成",
      done: manifest.generation !== null,
      warning:
        diagAction === "back_to_stage_2" ? ACTION_LABEL.back_to_stage_2 : undefined,
    },
    {
      label: "回測 + 診斷",
      done: manifest.backtest !== null,
    },
    {
      label: "優化",
      done: manifest.optimization !== null,
      warning:
        diagAction === "back_to_stage_4" ? ACTION_LABEL.back_to_stage_4 : undefined,
    },
    {
      label: "Gate 評估",
      done: manifest.gate !== null,
    },
  ];

  return (
    <div className="flex items-center gap-0 flex-wrap">
      {nodes.map((node, i) => (
        <div key={i} className="flex items-center">
          <div
            className={cn(
              "flex flex-col items-center px-3 py-2 rounded-md text-xs font-medium min-w-[80px] text-center",
              node.warning
                ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border border-amber-400"
                : node.done
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                : "bg-muted text-muted-foreground",
            )}
          >
            <span>{node.label}</span>
            {node.warning && (
              <span className="mt-0.5 text-[10px] font-bold">⚠ {node.warning}</span>
            )}
            {!node.done && <span className="mt-0.5 text-[10px]">未完成</span>}
          </div>
          {i < nodes.length - 1 && (
            <span className="mx-1 text-muted-foreground">→</span>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OOS vs IS panel
// ---------------------------------------------------------------------------

function OosVsIsPanel({
  is,
  oos,
}: {
  is: BacktestMetrics;
  oos: BacktestMetrics | null;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground border-b">
            <th className="pr-4 py-2 text-left w-36">指標</th>
            <th className="pr-6 py-2 text-left">IS (樣本內)</th>
            <th className="py-2 text-left">OOS (樣本外)</th>
          </tr>
        </thead>
        <tbody>
          <MetricRow
            label="Sharpe"
            is={fmtRatio(is.sharpe)}
            oos={fmtRatio(oos?.sharpe ?? null)}
          />
          <MetricRow
            label="Max Drawdown"
            is={fmtPct(is.max_drawdown)}
            oos={fmtPct(oos?.max_drawdown ?? null)}
          />
          <MetricRow
            label="Total Return"
            is={fmtPct(is.total_return)}
            oos={fmtPct(oos?.total_return ?? null)}
          />
          <MetricRow
            label="Trades"
            is={fmtInt(is.trades)}
            oos={fmtInt(oos?.trades ?? null)}
          />
          <MetricRow
            label="Win Rate"
            is={fmtPct(is.win_rate)}
            oos={fmtPct(oos?.win_rate ?? null)}
          />
          <MetricRow
            label="Profit Factor"
            is={fmtRatio(is.profit_factor)}
            oos={fmtRatio(oos?.profit_factor ?? null)}
          />
        </tbody>
      </table>
      {oos === null && (
        <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">
          ⚠ 無 OOS 資料 — 尚未跑樣本外回測
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Benchmark panel
// ---------------------------------------------------------------------------

function BenchmarkPanel({ manifest }: { manifest: StrategyManifest }) {
  const bm = manifest.backtest?.benchmark;
  if (!bm) {
    return <p className="text-sm text-muted-foreground">無 benchmark 資料</p>;
  }
  const beat = bm.beats_hodl;
  return (
    <div className="grid grid-cols-3 gap-4">
      {[
        { label: "策略報酬", value: fmtPct(bm.strategy_return) },
        { label: "HODL 報酬", value: fmtPct(bm.hodl_return) },
        {
          label: "超額報酬",
          value: fmtPct(bm.excess_return),
          highlight: beat === null ? undefined : beat ? "positive" : "negative",
        },
      ].map(({ label, value, highlight }) => (
        <div key={label} className="rounded-md border p-3 text-center">
          <div className="text-xs text-muted-foreground mb-1">{label}</div>
          <div
            className={cn(
              "text-lg font-semibold tabular-nums",
              highlight === "positive" && "text-emerald-600 dark:text-emerald-400",
              highlight === "negative" && "text-red-500 dark:text-red-400",
            )}
          >
            {value}
          </div>
        </div>
      ))}
      {beat === false && (
        <div className="col-span-3 rounded-md bg-red-50 border border-red-300 px-3 py-2 text-xs text-red-700 dark:bg-red-950/30 dark:border-red-800 dark:text-red-400">
          策略報酬輸給 HODL — 考慮捨棄
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cost stress panel
// ---------------------------------------------------------------------------

function CostStressPanel({ levels }: { levels: CostStressLevel[] }) {
  if (levels.length === 0) {
    return <p className="text-sm text-muted-foreground">無成本壓力資料</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 pr-4 text-left">情境</th>
            <th className="py-2 pr-4 text-right">費率倍數</th>
            <th className="py-2 pr-4 text-right">Sharpe</th>
            <th className="py-2 pr-4 text-right">Total Return</th>
            <th className="py-2 text-right">Profit Factor</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {levels.map((lv) => (
            <tr
              key={lv.label}
              className={cn(
                lv.sharpe !== null && lv.sharpe < 0 && "bg-red-50/50 dark:bg-red-950/20",
              )}
            >
              <td className="py-2 pr-4 font-medium">{lv.label}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-muted-foreground">
                {lv.fee_multiplier}×
              </td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtRatio(lv.sharpe)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtPct(lv.total_return)}</td>
              <td className="py-2 text-right tabular-nums">{fmtRatio(lv.profit_factor)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Regime table panel
// ---------------------------------------------------------------------------

function RegimeTablePanel({ rows }: { rows: RegimeMetrics[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">無 regime 分析資料</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 pr-4 text-left">Regime</th>
            <th className="py-2 pr-4 text-right">Sharpe</th>
            <th className="py-2 pr-4 text-right">Max DD</th>
            <th className="py-2 pr-4 text-right">Total Return</th>
            <th className="py-2 text-right">Trades</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.regime + r.source_run}>
              <td className="py-2 pr-4 font-medium capitalize">{r.regime}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtRatio(r.sharpe)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtPct(r.max_drawdown)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtPct(r.total_return)}</td>
              <td className="py-2 text-right tabular-nums">{fmtInt(r.trades)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trade table panel (成交明細)
// ---------------------------------------------------------------------------

function TradeTablePanel({ trades }: { trades: Record<string, unknown>[] }) {
  if (trades.length === 0) {
    return <p className="text-sm text-muted-foreground">無成交明細</p>;
  }
  const cols = Object.keys(trades[0]);
  const SHOW = 100;
  const shown = trades.slice(0, SHOW);

  return (
    <div>
      <div className="overflow-x-auto max-h-72 overflow-y-auto rounded border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b text-muted-foreground">
              {cols.map((c) => (
                <th key={c} className="px-3 py-2 text-left font-medium whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {shown.map((row, i) => (
              <tr key={i} className="hover:bg-muted/30">
                {cols.map((c) => (
                  <td key={c} className="px-3 py-1.5 whitespace-nowrap tabular-nums">
                    {String(row[c] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {trades.length > SHOW && (
        <p className="mt-2 text-xs text-muted-foreground">
          顯示前 {SHOW} / 共 {trades.length} 筆
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StrategyDetail page
// ---------------------------------------------------------------------------

export default function StrategyDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [manifest, setManifest] = useState<StrategyManifest | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [trades, setTrades] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api.strategy(id),
      api.equity(id).catch(() => [] as EquityPoint[]),
      api.trades(id).catch(() => [] as Record<string, unknown>[]),
    ])
      .then(([m, eq, tr]) => {
        setManifest(m);
        setEquity(eq);
        setTrades(tr);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, [id]);

  if (loading) {
    return (
      <div className="p-6 text-sm text-muted-foreground animate-pulse">載入策略…</div>
    );
  }

  if (error || !manifest) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          {error ?? "找不到策略"}
        </div>
      </div>
    );
  }

  const bt = manifest.backtest;

  return (
    <div className="p-6 space-y-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button
          onClick={() => navigate("/")}
          className="mt-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          ← 回比較表
        </button>
        <div className="flex-1">
          <div className="flex items-baseline gap-3">
            <h1 className="text-2xl font-semibold font-mono">{manifest.strategy_id}</h1>
            <span className="text-sm text-muted-foreground">{manifest.symbol}</span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            Stage {manifest.pipeline_stage} · 生成於{" "}
            {new Date(manifest.generated_at).toLocaleString("zh-TW")}
          </div>
        </div>
      </div>

      {/* Evidence chain */}
      <div className="rounded-lg border p-4">
        <div className="text-xs font-medium text-muted-foreground mb-3">證據鏈</div>
        <EvidenceChain manifest={manifest} />
        {manifest.diagnosis?.summary && (
          <p className="mt-3 text-xs text-muted-foreground border-t pt-3">
            診斷摘要：{manifest.diagnosis.summary}
          </p>
        )}
      </div>

      {/* Tier 1 panels */}

      {bt && (
        <Panel title="OOS vs IS 比較">
          <OosVsIsPanel is={bt.in_sample} oos={bt.oos} />
        </Panel>
      )}

      <Panel title="淨值曲線 + Benchmark">
        <div className="space-y-4">
          <EquityChart data={equity} height={280} />
          <BenchmarkPanel manifest={manifest} />
        </div>
      </Panel>

      {bt?.cost_stress && bt.cost_stress.levels.length > 0 && (
        <Panel title="成本壓力測試">
          <CostStressPanel levels={bt.cost_stress.levels} />
        </Panel>
      )}

      {bt && bt.by_regime.length > 0 && (
        <Panel title="Regime 分析">
          <RegimeTablePanel rows={bt.by_regime} />
        </Panel>
      )}

      <Panel title="成交明細">
        <TradeTablePanel trades={trades} />
      </Panel>
    </div>
  );
}
