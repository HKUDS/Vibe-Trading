import { useEffect, useState, useCallback } from "react";
import {
  api,
  type TestnetStatus,
  type LiveBlock,
  type VsBacktestBlock,
  type KillswitchBlock,
  type TestnetAlert,
  type AlertSeverity,
  type LiveStatus,
} from "../lib/api";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtPct = (v: number | null) =>
  v === null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const fmtRatio = (v: number | null) =>
  v === null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(3)}`;
const fmtCurrency = (v: number | null) =>
  v === null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: 2 });

const STATUS_STYLE: Record<LiveStatus, string> = {
  running: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  paused:  "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  stopped: "bg-muted text-muted-foreground",
};

const STATUS_DOT: Record<LiveStatus, string> = {
  running: "bg-emerald-500 animate-pulse",
  paused:  "bg-amber-400",
  stopped: "bg-gray-400",
};

const ALERT_STYLE: Record<AlertSeverity, string> = {
  info:     "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300",
  warning:  "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300",
  critical: "border-red-400 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300",
};

const ALERT_ICON: Record<AlertSeverity, string> = {
  info: "ℹ",
  warning: "⚠",
  critical: "🔴",
};

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border p-3 text-center">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live metrics row
// ---------------------------------------------------------------------------

function LiveMetrics({ live }: { live: LiveBlock }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard label="淨值" value={fmtCurrency(live.equity)} />
      <StatCard label="Sharpe (live)" value={fmtRatio(live.sharpe)} />
      <StatCard label="Max DD" value={fmtPct(live.max_drawdown)} />
      <StatCard label="成交筆數" value={String(live.trades)} sub={`持倉 ${live.open_positions}`} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// vs Backtest panel
// ---------------------------------------------------------------------------

function VsBacktestPanel({ vs }: { vs: VsBacktestBlock }) {
  const sharpeOk =
    vs.sharpe_ratio !== null ? vs.sharpe_ratio >= 0.8 : null;

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="py-2 pr-4 text-left">指標</th>
              <th className="py-2 pr-4 text-right">Live</th>
              <th className="py-2 pr-4 text-right">Backtest</th>
              <th className="py-2 text-right">Live / BT 比</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            <tr>
              <td className="py-2 pr-4 text-muted-foreground">Sharpe</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtRatio(vs.live_sharpe)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtRatio(vs.backtest_sharpe)}</td>
              <td className={cn(
                "py-2 text-right tabular-nums font-medium",
                sharpeOk === true ? "text-emerald-600 dark:text-emerald-400"
                : sharpeOk === false ? "text-red-500 dark:text-red-400"
                : "",
              )}>
                {vs.sharpe_ratio !== null ? vs.sharpe_ratio.toFixed(2) : "—"}
              </td>
            </tr>
            <tr>
              <td className="py-2 pr-4 text-muted-foreground">Slippage</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtPct(vs.live_slippage)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmtPct(vs.assumed_slippage)}</td>
              <td className="py-2 text-right tabular-nums text-muted-foreground">—</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 text-muted-foreground">未成交訂單</td>
              <td className="py-2 pr-4 text-right tabular-nums" colSpan={3}>{vs.unfilled_orders}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {sharpeOk === false && (
        <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          ⚠ Live Sharpe 顯著低於 backtest（比值 &lt; 0.8）— 策略可能在實盤表現降級
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Kill switch panel
// ---------------------------------------------------------------------------

function KillSwitchPanel({ ks }: { ks: KillswitchBlock }) {
  return (
    <div className="space-y-2">
      {ks.triggered && (
        <div className="rounded-lg border border-red-400 bg-red-50 dark:bg-red-950/30 dark:border-red-700 px-4 py-3">
          <div className="text-sm font-semibold text-red-700 dark:text-red-400">
            🔴 Kill Switch 已觸發
          </div>
          {ks.reason && (
            <div className="text-xs text-red-600 dark:text-red-400 mt-1">
              原因：{ks.reason}
            </div>
          )}
          {ks.triggered_at && (
            <div className="text-xs text-muted-foreground mt-0.5">
              時間：{new Date(ks.triggered_at).toLocaleString("zh-TW")}
            </div>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground mb-1">暫停閾值 (DD)</div>
          <div className="font-semibold text-amber-600">{fmtPct(ks.pause_drawdown)}</div>
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground mb-1">終止閾值 (DD)</div>
          <div className="font-semibold text-red-600">{fmtPct(ks.terminate_drawdown)}</div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Alerts list
// ---------------------------------------------------------------------------

function AlertsList({ alerts }: { alerts: TestnetAlert[] }) {
  if (alerts.length === 0) {
    return <p className="text-sm text-muted-foreground">無警報</p>;
  }
  const sorted = [...alerts].sort((a, b) => {
    const order = { critical: 0, warning: 1, info: 2 };
    return order[a.severity] - order[b.severity];
  });
  return (
    <ul className="space-y-2">
      {sorted.map((a, i) => (
        <li
          key={i}
          className={cn("rounded-md border px-3 py-2 text-sm flex items-start gap-2", ALERT_STYLE[a.severity])}
        >
          <span className="mt-0.5">{ALERT_ICON[a.severity]}</span>
          <div className="flex-1">
            <span>{a.message}</span>
            <span className="ml-2 text-xs opacity-60">
              {new Date(a.timestamp).toLocaleString("zh-TW")}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Single testnet card
// ---------------------------------------------------------------------------

function TestnetCard({ status }: { status: TestnetStatus }) {
  const { live, vs_backtest, killswitch, alerts } = status;
  const updatedAgo = Math.round(
    (Date.now() - new Date(live.updated_at).getTime()) / 1000
  );

  return (
    <div className="rounded-xl border shadow-sm space-y-0">
      {/* Card header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
            STATUS_STYLE[live.status],
          )}
        >
          <span className={cn("h-2 w-2 rounded-full", STATUS_DOT[live.status])} />
          {live.status.toUpperCase()}
        </span>
        <span className="font-mono font-semibold">{status.strategy_id}</span>
        <span className="text-sm text-muted-foreground">{status.symbol}</span>
        <span className="ml-auto text-xs text-muted-foreground">
          更新於 {updatedAgo}s 前
        </span>
      </div>

      <div className="p-5 space-y-5">
        {/* Kill switch alert (if triggered, show at top) */}
        {killswitch.triggered && (
          <div className="rounded-lg border border-red-400 bg-red-50 dark:bg-red-950/30 dark:border-red-700 px-4 py-3">
            <div className="text-sm font-semibold text-red-700 dark:text-red-400">
              🔴 Kill Switch 已觸發 — {killswitch.reason ?? "超過回撤閾值"}
            </div>
          </div>
        )}

        {/* Live metrics */}
        <LiveMetrics live={live} />

        {/* vs Backtest */}
        {vs_backtest ? (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">Live vs Backtest</div>
            <VsBacktestPanel vs={vs_backtest} />
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">vs Backtest 資料尚未產生</p>
        )}

        {/* Kill switch thresholds */}
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-2">Kill Switch</div>
          <KillSwitchPanel ks={killswitch} />
        </div>

        {/* Alerts */}
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-2">
            警報 {alerts.length > 0 && `(${alerts.length})`}
          </div>
          <AlertsList alerts={alerts} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Testnet page
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 15_000;

export default function Testnet() {
  const [statuses, setStatuses] = useState<TestnetStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  const fetchData = useCallback(() => {
    api
      .testnet()
      .then((data) => {
        setStatuses(data);
        setLastFetch(new Date());
        setError(null);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  // Initial fetch + polling
  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchData]);

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Testnet 監控</h1>
        <div className="flex items-center gap-3">
          {lastFetch && (
            <span className="text-xs text-muted-foreground">
              {lastFetch.toLocaleTimeString("zh-TW")} 更新
            </span>
          )}
          <button
            onClick={fetchData}
            className="rounded-md border px-3 py-1.5 text-xs hover:bg-muted transition-colors"
          >
            重新整理
          </button>
        </div>
      </div>

      {loading && (
        <div className="text-sm text-muted-foreground animate-pulse">載入 testnet 狀態…</div>
      )}

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          載入失敗：{error}
        </div>
      )}

      {!loading && !error && statuses.length === 0 && (
        /* Waiting state — no promoted strategies yet */
        <div className="rounded-xl border border-dashed p-12 text-center space-y-3">
          <div className="text-4xl">⏳</div>
          <div className="text-base font-medium text-muted-foreground">
            尚無 Testnet 運行資料
          </div>
          <div className="text-sm text-muted-foreground max-w-sm mx-auto">
            先在策略頁面 Promote 策略到 Testnet，
            v1.5 trader 啟動後資料會出現在這裡。
          </div>
          <div className="text-xs text-muted-foreground">
            每 {POLL_INTERVAL_MS / 1000}s 自動重新整理
          </div>
        </div>
      )}

      {statuses.map((s) => (
        <TestnetCard key={s.testnet_id} status={s} />
      ))}
    </div>
  );
}
