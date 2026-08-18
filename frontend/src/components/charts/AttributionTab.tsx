import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import i18n from "@/i18n";
import { Activity, AlertTriangle, BarChart3, Loader2, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type {
  AttributionBenchmarkInfo,
  AttributionBrinson,
  AttributionFactor,
  AttributionResponse,
  RunData,
} from "@/lib/api";
import { AttributionCumulativeChart } from "./AttributionCumulativeChart";
import { AttributionWaterfallChart } from "./AttributionWaterfallChart";
import { RollingBetaAlphaChart } from "./RollingBetaAlphaChart";

type AttrState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: AttributionResponse };

function fmtPct(v: number, digits = 2): string {
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtSignedPct(v: number, digits = 2): string {
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function signedTone(v: number): "positive" | "negative" | "neutral" {
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "neutral";
}

function signedNumberClass(value: number): string {
  if (value === 0) return "text-muted-foreground";
  return value > 0 ? "text-success" : "text-danger";
}

function benchmarkCaption(benchmark: AttributionBenchmarkInfo | null): string {
  if (!benchmark) return i18n.t("runDetail.attrNoBenchmark");
  const label = i18n.t("runDetail.attrBenchmark");
  if (benchmark.mode === "auto_equal_weight") {
    const auto = i18n.t("runDetail.attrAutoEqualWeight");
    return benchmark.ticker ? `${label}: ${benchmark.ticker} · ${auto}` : `${label}: ${auto}`;
  }
  if (benchmark.ticker) return `${label}: ${benchmark.ticker}`;
  return i18n.t("runDetail.attrNoBenchmark");
}

function modeCaption(mode: AttributionBrinson["mode"]): string {
  if (mode === "asset_class") return i18n.t("runDetail.attrModeAssetClass");
  if (mode === "invested_cash") return i18n.t("runDetail.attrModeInvestedCash");
  return i18n.t("runDetail.attrModeSymbol");
}

function AttrStat({ label, value, sub, tone = "neutral" }: {
  label: string;
  value: string;
  sub?: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn(
        "mt-1 truncate text-sm font-medium tabular-nums",
        tone === "positive" && "text-success",
        tone === "negative" && "text-danger",
      )}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

function AttrPanel({ title, icon: Icon, children }: {
  title: string;
  icon: typeof BarChart3;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Icon className="h-4 w-4 text-muted-foreground" />
        {title}
      </div>
      {children}
    </section>
  );
}

function BrinsonTable({ brinson }: { brinson: AttributionBrinson }) {
  const sectors = brinson.sectors;
  const weightTotal = (pick: "portfolio_weight" | "benchmark_weight") =>
    sectors.reduce((sum, s) => sum + s[pick], 0);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground [&_th]:font-medium">
            <th className="py-2 ps-4 pr-4">{i18n.t("runDetail.attrSector")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrPortfolioWeight")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrBenchmarkWeight")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrPortfolioReturn")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrBenchmarkReturn")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrAllocation")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrSelection")}</th>
            <th className="py-2 pr-4 text-right">{i18n.t("runDetail.attrInteraction")}</th>
            <th className="py-2 text-right">{i18n.t("runDetail.attrTotal")}</th>
          </tr>
        </thead>
        <tbody>
          {sectors.map((s) => (
            <tr key={s.sector} className="border-b last:border-0 hover:bg-muted/40">
              <td className="py-2 ps-4 pr-4 font-mono text-xs">{s.sector}</td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtPct(s.portfolio_weight)}</td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtPct(s.benchmark_weight)}</td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtSignedPct(s.portfolio_return)}</td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtSignedPct(s.benchmark_return)}</td>
              <td className={cn("py-2 pr-4 text-right font-mono tabular-nums", signedNumberClass(s.allocation))}>{fmtSignedPct(s.allocation)}</td>
              <td className={cn("py-2 pr-4 text-right font-mono tabular-nums", signedNumberClass(s.selection))}>{fmtSignedPct(s.selection)}</td>
              <td className={cn("py-2 pr-4 text-right font-mono tabular-nums", signedNumberClass(s.interaction))}>{fmtSignedPct(s.interaction)}</td>
              <td className={cn("py-2 text-right font-mono tabular-nums", signedNumberClass(s.total))}>{fmtSignedPct(s.total)}</td>
            </tr>
          ))}
          <tr className="border-t bg-muted/40 font-semibold">
            <td className="py-2 ps-4 pr-4">{i18n.t("runDetail.attrTotal")}</td>
            <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtPct(weightTotal("portfolio_weight"))}</td>
            <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtPct(weightTotal("benchmark_weight"))}</td>
            <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtSignedPct(brinson.portfolio_return)}</td>
            <td className="py-2 pr-4 text-right font-mono tabular-nums">{fmtSignedPct(brinson.benchmark_return)}</td>
            <td className={cn("py-2 pr-4 text-right font-mono tabular-nums", signedNumberClass(brinson.allocation))}>{fmtSignedPct(brinson.allocation)}</td>
            <td className={cn("py-2 pr-4 text-right font-mono tabular-nums", signedNumberClass(brinson.selection))}>{fmtSignedPct(brinson.selection)}</td>
            <td className={cn("py-2 pr-4 text-right font-mono tabular-nums", signedNumberClass(brinson.interaction))}>{fmtSignedPct(brinson.interaction)}</td>
            <td className={cn("py-2 text-right font-mono tabular-nums", signedNumberClass(brinson.active_return))}>{fmtSignedPct(brinson.active_return)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function FactorStatCards({ factor, metrics }: { factor: AttributionFactor | null; metrics: RunData["metrics"] }) {
  const informationRatio = metrics?.information_ratio;
  const trackingError = metrics?.tracking_error;
  const hasFactor = factor !== null;
  if (!hasFactor && informationRatio === undefined && trackingError === undefined) return null;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {hasFactor && (
        <>
          <AttrStat
            label={i18n.t("runDetail.attrAlpha")}
            value={fmtSignedPct(factor.alpha_annualized)}
            sub={i18n.t("runDetail.attrTStat", { value: factor.alpha_t_stat.toFixed(2) })}
            tone={signedTone(factor.alpha_annualized)}
          />
          <AttrStat label={i18n.t("runDetail.attrBeta")} value={factor.beta.toFixed(2)} />
          <AttrStat label={i18n.t("runDetail.attrRSquared")} value={factor.r_squared.toFixed(2)} />
        </>
      )}
      {informationRatio !== undefined && (
        <AttrStat
          label={i18n.t("runDetail.attrInformationRatio")}
          value={`${informationRatio > 0 ? "+" : ""}${informationRatio.toFixed(2)}`}
          tone={signedTone(informationRatio)}
        />
      )}
      {trackingError !== undefined && (
        <AttrStat label={i18n.t("runDetail.attrTrackingError")} value={fmtPct(trackingError)} />
      )}
    </div>
  );
}

export function AttributionTab({ runId, run }: { runId: string; run: RunData }) {
  const [state, setState] = useState<AttrState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    api.getRunAttribution(runId)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (state.status === "loading") {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {i18n.t("runDetail.attrLoading")}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-danger">
        <AlertTriangle className="h-4 w-4" aria-hidden="true" />
        <span>{i18n.t("runDetail.attrError")}</span>
        <span className="text-muted-foreground">{state.message}</span>
      </div>
    );
  }

  const { data } = state;
  const factor = data.factor;
  const brinson = data.brinson;

  if (!data.exists || (!factor && !brinson)) {
    return <div className="p-8 text-muted-foreground text-sm">{i18n.t("runDetail.attrNoData")}</div>;
  }

  return (
    <div className="p-4 space-y-4">
      <FactorStatCards factor={factor} metrics={run.metrics} />

      {brinson ? (
        <>
          <AttrPanel title={i18n.t("runDetail.attrBrinsonTitle")} icon={BarChart3}>
            <BrinsonTable brinson={brinson} />
            <p className="mt-2 text-xs text-muted-foreground">{modeCaption(brinson.mode)}</p>
            {data.notes.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {data.notes.map((note, index) => <li key={index}>{note}</li>)}
              </ul>
            )}
          </AttrPanel>
          <AttrPanel title={i18n.t("runDetail.attrWaterfallTitle")} icon={BarChart3}>
            <AttributionWaterfallChart brinson={brinson} height={300} />
          </AttrPanel>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">{i18n.t("runDetail.attrNoBrinson")}</p>
      )}

      {factor ? (
        <>
          {factor.rolling && factor.rolling.length > 0 && (
            <AttrPanel title={i18n.t("runDetail.attrRollingTitle")} icon={Activity}>
              <p className="mb-2 text-xs text-muted-foreground">
                {i18n.t("runDetail.attrRollingWindow", { count: factor.rolling_window })}
              </p>
              <RollingBetaAlphaChart data={factor.rolling} height={280} />
            </AttrPanel>
          )}
          {factor.cumulative.length > 0 && (
            <AttrPanel title={i18n.t("runDetail.attrCumulativeTitle")} icon={TrendingUp}>
              <AttributionCumulativeChart data={factor.cumulative} height={300} />
            </AttrPanel>
          )}
        </>
      ) : (
        <p className="text-xs text-muted-foreground">{i18n.t("runDetail.attrNoFactor")}</p>
      )}

      <p className="text-xs text-muted-foreground">{benchmarkCaption(data.benchmark)}</p>
    </div>
  );
}
