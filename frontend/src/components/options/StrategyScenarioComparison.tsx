import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type {
  OptionsPayoffRequest,
  OptionsStrategyCompareRequest,
  OptionsStrategyCompareResponse,
} from "@/lib/options";
import { OptionsScenarioMatrix } from "@/components/charts/OptionsScenarioMatrix";

const COMPARE_SPOT_LIMIT = 201;
const comparisonKey = (index: number) => `strategy-${index}`;

export function StrategyScenarioComparison({ request }: { request: OptionsPayoffRequest }) {
  if (!request.alternatives?.length) return null;
  return <ComparisonPairs request={request} />;
}

function ComparisonPairs({ request }: { request: OptionsPayoffRequest }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [baselineIndex, setBaselineIndex] = useState(0);
  const [targetIndex, setTargetIndex] = useState(1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<OptionsStrategyCompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const strategies = useMemo(() => [
    { name: (request.label ?? t("options.comparison.current")).trim(), legs: request.legs },
    ...(request.alternatives ?? []).map((item) => ({ name: item.label.trim(), legs: item.legs })),
  ], [request, t]);

  const baseline = Math.min(baselineIndex, strategies.length - 1);
  let target = Math.min(targetIndex, strategies.length - 1);
  if (target === baseline) target = baseline === 0 ? 1 : 0;
  const requestedSpotPoints = request.spot_points ?? 121;
  const gridCapped = requestedSpotPoints > COMPARE_SPOT_LIMIT;

  const compareRequest = useMemo<OptionsStrategyCompareRequest>(() => {
    const order = [baseline, target].sort((a, b) => a - b);
    return {
      strategies: order.map((index) => ({
        name: comparisonKey(index),
        legs: strategies[index].legs,
      })),
      baseline_index: order.indexOf(baseline),
      entry_spot: request.entry_spot,
      expiry_days: request.expiry_days,
      risk_free_rate: request.risk_free_rate,
      volatility: request.volatility,
      multiplier: request.multiplier,
      commission_rate: request.commission_rate,
      spot_min: request.spot_min,
      spot_max: request.spot_max,
      spot_points: Math.min(requestedSpotPoints, COMPARE_SPOT_LIMIT),
      scenario_iv_values: request.scenario_iv_values,
    };
  }, [baseline, request, strategies, target, requestedSpotPoints]);
  const signature = JSON.stringify(compareRequest);
  const currentSignature = useRef(signature);
  currentSignature.current = signature;

  useEffect(() => {
    if (!open) return;
    const gen = ++generation.current;
    const controller = new AbortController();
    setResult(null);
    setError(null);
    setLoading(true);
    api.compareOptionsStrategies(compareRequest, controller.signal)
      .then((response) => {
        if (generation.current === gen && currentSignature.current === signature) setResult(response);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && generation.current === gen) {
          setError(reason instanceof Error ? reason.message : t("options.errorGeneric"));
        }
      })
      .finally(() => {
        if (generation.current === gen) setLoading(false);
      });
    return () => {
      generation.current += 1;
      controller.abort();
    };
    // The completed request snapshot owns the fetch; its JSON identity is sufficient.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, signature, retry]);

  const baselineName = strategies[baseline].name;
  const targetName = strategies[target].name;
  const grid = result?.scenario_grid;
  const rawGrid = grid?.pnl[comparisonKey(target)];
  const deltaGrid = grid?.delta_to_baseline[comparisonKey(target)];

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <button
        type="button"
        aria-expanded={open}
        className="text-sm font-semibold"
        onClick={() => setOpen((value) => !value)}
      >
        {t("options.scenario.title")}
      </button>
      {open && (
        <div className="mt-3">
          <p className="text-xs text-muted-foreground">{t("options.comparison.scenarioBasis")}</p>
          {gridCapped && <p className="mt-1 text-xs text-muted-foreground">{t("options.comparison.gridCapped", { count: COMPARE_SPOT_LIMIT })}</p>}
          <div className="my-3 flex flex-wrap gap-3 text-sm">
            <label className="flex items-center gap-2">
              {t("options.comparison.baseline")}
              <select
                aria-label={t("options.comparison.baseline")}
                className="rounded border bg-background px-2 py-1"
                value={baseline}
                onChange={(event) => setBaselineIndex(Number(event.target.value))}
              >
                {strategies.map((strategy, index) => <option key={`${strategy.name}-${index}`} value={index}>{strategy.name}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2">
              {t("options.comparison.alternative")}
              <select
                aria-label={t("options.comparison.alternative")}
                className="rounded border bg-background px-2 py-1"
                value={target}
                onChange={(event) => setTargetIndex(Number(event.target.value))}
              >
                {strategies.map((strategy, index) => <option key={`${strategy.name}-${index}`} value={index}>{strategy.name}</option>)}
              </select>
            </label>
          </div>
          {loading && <p role="status" className="text-sm text-muted-foreground">{t("analysis.updating")}</p>}
          {error && (
            <div role="alert" className="flex items-center gap-3 text-sm text-danger">
              {error}
              <button type="button" onClick={() => setRetry((value) => value + 1)}>{t("connection.retry")}</button>
            </div>
          )}
          {result && grid && rawGrid && deltaGrid && (
            <div className="grid gap-4 xl:grid-cols-2">
              <div data-testid="scenario-raw">
                <h3 className="mb-2 text-sm font-medium">{t("options.scenario.pnl")}: {targetName}</h3>
                <OptionsScenarioMatrix grid={{ iv_values: grid.iv_values, spot: grid.spot, pnl: rawGrid }} />
              </div>
              <div data-testid="scenario-delta">
                <h3 className="mb-2 text-sm font-medium">{t("options.comparison.deltaGrid")}: {targetName} − {baselineName}</h3>
                <OptionsScenarioMatrix grid={{ iv_values: grid.iv_values, spot: grid.spot, pnl: deltaGrid }} />
              </div>
            </div>
          )}
          {result && result.limitations.length > 0 && (
            <ul className="mt-3 list-disc ps-5 text-xs text-muted-foreground">
              {result.limitations.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
