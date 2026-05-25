import { useEffect, useState } from "react";
import { api, type FactorManifest, type FactorEntry, type FactorVerdict, type FactorStability } from "../lib/api";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Verdict chip
// ---------------------------------------------------------------------------

const VERDICT_STYLE: Record<FactorVerdict, string> = {
  single_use:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  ensemble_only: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  reject:        "bg-muted text-muted-foreground line-through",
};

const VERDICT_LABEL: Record<FactorVerdict, string> = {
  single_use:    "單獨可用",
  ensemble_only: "組合限定",
  reject:        "拒絕",
};

function VerdictChip({ verdict }: { verdict: FactorVerdict }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", VERDICT_STYLE[verdict])}>
      {VERDICT_LABEL[verdict]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Stability chip
// ---------------------------------------------------------------------------

const STABILITY_STYLE: Record<FactorStability, string> = {
  regime_stable: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  conditional:   "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
};

const STABILITY_LABEL: Record<FactorStability, string> = {
  regime_stable: "Regime 穩定",
  conditional:   "條件性",
};

function StabilityChip({ stability }: { stability: FactorStability | null }) {
  if (!stability) return <span className="text-muted-foreground text-xs">—</span>;
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", STABILITY_STYLE[stability])}>
      {STABILITY_LABEL[stability]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// IC value cell — color-code by magnitude
// ---------------------------------------------------------------------------

function IcCell({ v }: { v: number | null | undefined }) {
  if (v === undefined || v === null) return <span className="text-muted-foreground">—</span>;
  return (
    <span
      className={cn(
        "tabular-nums",
        Math.abs(v) >= 0.10 ? "font-semibold text-emerald-600 dark:text-emerald-400"
        : Math.abs(v) >= 0.05 ? "text-amber-600 dark:text-amber-400"
        : "text-muted-foreground",
      )}
    >
      {v >= 0 ? "+" : ""}{v.toFixed(3)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// IC/IR table
// ---------------------------------------------------------------------------

function FactorTable({ manifest }: { manifest: FactorManifest }) {
  const { factors, horizons_h } = manifest;

  return (
    <div className="space-y-4">
      {/* Main IC/IR table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="py-2 pr-4 text-left min-w-[160px]">因子</th>
              <th className="py-2 pr-4 text-right">IR</th>
              <th className="py-2 pr-4 text-right">樣本數</th>
              {horizons_h.map((h) => (
                <th key={h} className="py-2 pr-3 text-right">IC {h}h</th>
              ))}
              <th className="py-2 pr-4 text-center">穩定性</th>
              <th className="py-2 text-center">Verdict</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {factors.map((f) => (
              <tr
                key={f.name}
                className={cn(f.verdict === "reject" && "opacity-40")}
              >
                <td className="py-2 pr-4 font-mono text-xs font-medium">{f.name}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  <span className={cn(
                    f.ir >= 1.0 ? "font-semibold text-emerald-600 dark:text-emerald-400"
                    : f.ir >= 0.3 ? "text-amber-600 dark:text-amber-400"
                    : "text-muted-foreground",
                  )}>
                    {f.ir.toFixed(3)}
                  </span>
                </td>
                <td className="py-2 pr-4 text-right tabular-nums text-muted-foreground text-xs">
                  {f.sample_size}
                </td>
                {horizons_h.map((h) => (
                  <td key={h} className="py-2 pr-3 text-right">
                    <IcCell v={f.ic_by_horizon[h]} />
                  </td>
                ))}
                <td className="py-2 pr-4 text-center">
                  <StabilityChip stability={f.stability} />
                </td>
                <td className="py-2 text-center">
                  <VerdictChip verdict={f.verdict} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Cross-regime IC section */}
      <CrossRegimeSection factors={factors} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cross-regime IC section
// ---------------------------------------------------------------------------

function CrossRegimeSection({ factors }: { factors: FactorEntry[] }) {
  const withRegime = factors.filter((f) => f.cross_regime_ic !== null);
  const withoutRegime = factors.filter((f) => f.cross_regime_ic === null);

  // Collect all regimes
  const regimes = Array.from(
    new Set(withRegime.flatMap((f) => Object.keys(f.cross_regime_ic ?? {})))
  ).sort();

  return (
    <div className="space-y-3">
      <div className="text-sm font-semibold">Cross-Regime IC</div>

      {withoutRegime.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          ⚠ 未做 cross-regime 驗證：
          {withoutRegime.map((f) => f.name).join("、")}
        </div>
      )}

      {withRegime.length === 0 ? (
        <p className="text-sm text-muted-foreground">所有因子均未做 cross-regime 分析</p>
      ) : regimes.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-4 text-left min-w-[160px]">因子</th>
                {regimes.map((r) => (
                  <th key={r} className="py-2 pr-3 text-right capitalize">{r}</th>
                ))}
                <th className="py-2 text-center">穩定性</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {withRegime.map((f) => (
                <tr key={f.name}>
                  <td className="py-2 pr-4 font-mono text-xs font-medium">{f.name}</td>
                  {regimes.map((r) => (
                    <td key={r} className="py-2 pr-3 text-right">
                      <IcCell v={f.cross_regime_ic?.[r]} />
                    </td>
                  ))}
                  <td className="py-2 text-center">
                    <StabilityChip stability={f.stability} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FactorReport page
// ---------------------------------------------------------------------------

export default function FactorReport() {
  const [manifests, setManifests] = useState<FactorManifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSymbol, setActiveSymbol] = useState<string>("");

  useEffect(() => {
    api
      .factorAnalysis()
      .then((data) => {
        setManifests(data);
        if (data.length > 0) setActiveSymbol(data[0].symbol);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="p-6 text-sm text-muted-foreground animate-pulse">載入因子分析…</div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          無法載入因子分析：{error}
        </div>
      </div>
    );
  }

  if (manifests.length === 0) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-semibold mb-4">因子分析</h1>
        <p className="text-sm text-muted-foreground">
          無因子分析資料。請先執行 Stage 1 管線產生 factor manifest。
        </p>
      </div>
    );
  }

  const active = manifests.find((m) => m.symbol === activeSymbol) ?? manifests[0];

  return (
    <div className="p-6 space-y-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-2xl font-semibold">因子分析</h1>
        <span className="text-xs text-muted-foreground">
          {active.factors.length} 個因子 · {active.period_days} 天 · 生成於{" "}
          {new Date(active.generated_at).toLocaleString("zh-TW")}
        </span>
      </div>

      {/* Symbol tabs */}
      {manifests.length > 1 && (
        <div className="flex gap-2">
          {manifests.map((m) => (
            <button
              key={m.symbol}
              onClick={() => setActiveSymbol(m.symbol)}
              className={cn(
                "rounded-full px-3 py-1 text-sm font-medium transition-colors",
                activeSymbol === m.symbol
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              )}
            >
              {m.symbol}
            </button>
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground border rounded-md px-3 py-2">
        <span>IC 顏色：<span className="text-emerald-600 font-semibold">≥0.10 強</span> / <span className="text-amber-600">≥0.05 中</span> / 弱</span>
        <span>IR 顏色：<span className="text-emerald-600 font-semibold">≥1.0 強</span> / <span className="text-amber-600">≥0.3 中</span> / 弱</span>
        <span>Verdict：<VerdictChip verdict="single_use" /> <VerdictChip verdict="ensemble_only" /> <VerdictChip verdict="reject" /></span>
      </div>

      {/* Factor table + cross-regime */}
      <FactorTable manifest={active} />
    </div>
  );
}
