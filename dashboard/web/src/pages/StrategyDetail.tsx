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
  type GateBlock,
  type RedFlagCode,
  type FactorManifest,
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
// RedFlagBanner
// ---------------------------------------------------------------------------

const RED_FLAG_LABELS: Record<RedFlagCode, { short: string; detail: string }> = {
  oos_sharpe_far_below_is:   { short: "OOS Sharpe << IS",  detail: "樣本外表現遠差於樣本內，過擬合嫌疑高" },
  underperforms_hodl:        { short: "輸給 HODL",          detail: "策略報酬低於買入持有，不值得持倉" },
  too_few_trades:            { short: "交易數太少",          detail: "統計意義不足，結果不可靠" },
  alpha_is_fee_illusion:     { short: "Alpha = 費用幻覺",   detail: "扣除交易費後策略無超額收益" },
  overfit_suspect:           { short: "疑似過擬合",          detail: "Walk-forward 或 Monte Carlo 結果惡化" },
  regime_conditional:        { short: "Regime 限定",         detail: "策略只在特定市場環境有效" },
};

function RedFlagBanner({ gate }: { gate: GateBlock }) {
  const flags = gate.red_flags;
  if (flags.length === 0) return null;
  return (
    <div className="rounded-lg border border-red-400 bg-red-50 dark:bg-red-950/30 dark:border-red-700 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-red-700 dark:text-red-400">⚠ 紅旗警示</span>
        {gate.fatal_fail && (
          <span className="rounded px-1.5 py-0.5 text-xs font-bold bg-red-600 text-white">
            FATAL — 硬擋，無法 override
          </span>
        )}
      </div>
      <ul className="space-y-1">
        {flags.map((f) => {
          const info = RED_FLAG_LABELS[f];
          return (
            <li key={f} className="flex items-start gap-2 text-sm text-red-700 dark:text-red-300">
              <span className="mt-0.5 text-red-500">✗</span>
              <span>
                <span className="font-medium">{info.short}</span>
                <span className="text-red-600/70 dark:text-red-400/70"> — {info.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GateChecklist
// ---------------------------------------------------------------------------

function GateChecklist({ gate }: { gate: GateBlock }) {
  const { thresholds, overall_pass, fatal_fail } = gate;
  return (
    <div className="space-y-3">
      {/* Summary badge */}
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "rounded-full px-3 py-1 text-sm font-bold",
            fatal_fail
              ? "bg-red-600 text-white"
              : overall_pass
              ? "bg-emerald-500 text-white"
              : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
          )}
        >
          {fatal_fail ? "FATAL FAIL" : overall_pass ? "GO ✓" : "NO-GO"}
        </span>
        <span className="text-xs text-muted-foreground">
          {thresholds.filter((t) => t.passed).length}/{thresholds.length} 門檻通過
        </span>
      </div>

      {/* Threshold rows */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="py-2 pr-4 text-left">門檻</th>
              <th className="py-2 pr-4 text-right">要求</th>
              <th className="py-2 pr-4 text-right">實際</th>
              <th className="py-2 pr-2 text-center">結果</th>
              <th className="py-2 text-center">致命</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {thresholds.map((t) => (
              <tr
                key={t.name}
                className={cn(
                  !t.passed && t.fatal && "bg-red-50/70 dark:bg-red-950/30",
                  !t.passed && !t.fatal && "bg-orange-50/40 dark:bg-orange-950/10",
                )}
              >
                <td className="py-2 pr-4 font-medium">{t.name}</td>
                <td className="py-2 pr-4 text-right tabular-nums text-muted-foreground">
                  {t.threshold}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {t.actual !== null ? t.actual : "—"}
                </td>
                <td className="py-2 pr-2 text-center">
                  {t.passed ? (
                    <span className="text-emerald-500 font-bold">✓</span>
                  ) : (
                    <span className="text-red-500 font-bold">✗</span>
                  )}
                </td>
                <td className="py-2 text-center">
                  {t.fatal ? (
                    <span className="text-xs font-bold text-red-600 dark:text-red-400">硬擋</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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
  const [factorManifest, setFactorManifest] = useState<FactorManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api.strategy(id),
      api.equity(id).catch(() => [] as EquityPoint[]),
      api.trades(id).catch(() => [] as Record<string, unknown>[]),
      api.factorAnalysis().catch(() => [] as FactorManifest[]),
    ])
      .then(([m, eq, tr, factors]) => {
        setManifest(m);
        setEquity(eq);
        setTrades(tr);
        const fm = (factors as FactorManifest[]).find((f) => f.symbol === m.symbol) ?? null;
        setFactorManifest(fm);
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

      {/* Red flag banner — always shown when flags exist */}
      {manifest.gate && <RedFlagBanner gate={manifest.gate} />}

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

      {/* Gate checklist — Tier 1 */}
      {manifest.gate && (
        <Panel title="GO/NO-GO 門檻 Checklist">
          <GateChecklist gate={manifest.gate} />
        </Panel>
      )}

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

      {/* ── Tier 2: audit panels (default collapsed) ── */}

      <Panel title="策略 YAML（Tier 2）" defaultOpen={false}>
        {manifest.spec.spec_yaml ? (
          <pre className="overflow-x-auto rounded bg-muted p-3 text-xs font-mono whitespace-pre-wrap break-words">
            {manifest.spec.spec_yaml}
          </pre>
        ) : (
          <p className="text-sm text-muted-foreground">無 YAML</p>
        )}
      </Panel>

      {factorManifest && (
        <Panel title={`因子 IC/IR — ${factorManifest.symbol}（Tier 2）`} defaultOpen={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 pr-4 text-left">因子</th>
                  <th className="py-2 pr-4 text-right">IR</th>
                  {factorManifest.horizons_h.map((h) => (
                    <th key={h} className="py-2 pr-3 text-right">IC {h}h</th>
                  ))}
                  <th className="py-2 text-center">Verdict</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {factorManifest.factors.map((f) => (
                  <tr key={f.name} className={f.verdict === "reject" ? "opacity-50" : ""}>
                    <td className="py-2 pr-4 font-mono text-xs">{f.name}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{f.ir.toFixed(3)}</td>
                    {factorManifest.horizons_h.map((h) => (
                      <td key={h} className="py-2 pr-3 text-right tabular-nums text-xs">
                        {f.ic_by_horizon[h] !== undefined
                          ? f.ic_by_horizon[h].toFixed(3)
                          : "—"}
                      </td>
                    ))}
                    <td className="py-2 text-center">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-medium",
                          f.verdict === "single_use"
                            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                            : f.verdict === "ensemble_only"
                            ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {f.verdict}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {manifest.diagnosis && (
        <Panel title="診斷報告（Tier 2）" defaultOpen={false}>
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">建議行動：</span>
              <span
                className={cn(
                  "rounded px-2 py-0.5 text-xs font-semibold",
                  manifest.diagnosis.recommended_action === "proceed"
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                    : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
                )}
              >
                {manifest.diagnosis.recommended_action}
              </span>
            </div>
            {manifest.diagnosis.findings.length > 0 && (
              <ul className="space-y-1">
                {manifest.diagnosis.findings.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="mt-1 text-muted-foreground">•</span>
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Panel>
      )}

      {manifest.reproducibility && (
        <Panel title="可重現戳記（Tier 2）" defaultOpen={false}>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            {(
              [
                ["Git commit",   manifest.reproducibility.git_commit],
                ["Config hash",  manifest.reproducibility.config_hash],
                ["Engine",       manifest.reproducibility.engine],
                ["Data source",  manifest.reproducibility.data_source],
                ["Seed",         manifest.reproducibility.seed !== null ? String(manifest.reproducibility.seed) : null],
              ] as [string, string | null][]
            ).map(([label, val]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="font-mono text-xs break-all">{val ?? "—"}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      )}

      {/* ── Tier 3: deep links (noise) ── */}

      <div className="rounded-lg border border-dashed p-4 space-y-3">
        <div className="text-xs font-medium text-muted-foreground">Tier 3 — 深層連結</div>
        <div className="flex flex-wrap gap-3 text-sm">
          <a
            href="/factors"
            onClick={(e) => { e.preventDefault(); navigate("/factors"); }}
            className="text-primary underline underline-offset-2 hover:opacity-70"
          >
            → 因子分析完整報告
          </a>
        </div>
        {manifest.generation?.rationale && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">
              策略生成理由（LLM 散文 — 非決策依據）
            </summary>
            <p className="mt-2 rounded bg-muted p-3 text-xs text-muted-foreground whitespace-pre-wrap">
              {manifest.generation.rationale}
            </p>
          </details>
        )}
      </div>
    </div>
  );
}
