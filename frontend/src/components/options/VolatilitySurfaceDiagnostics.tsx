import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { SurfaceObservationInput } from "@/lib/options";
import { buildSurfaceDiagnosticsRequest, type SurfaceDiagnosticsResponse } from "@/lib/surfaceDiagnostics";

const statusKeys = {
  checked: "options.surfaceDiagnostics.checked",
  insufficient_points: "options.surfaceDiagnostics.insufficient",
  unavailable: "options.surfaceDiagnostics.unavailable",
} as const;
const findingKeys = {
  vertical_spread_bounds: "options.surfaceDiagnostics.vertical",
  butterfly_convexity: "options.surfaceDiagnostics.convexity",
} as const;

function numberLabel(value: number): string {
  return value.toLocaleString(undefined, { maximumSignificantDigits: 8 });
}

interface Snapshot {
  key: string;
  loading: boolean;
  result: SurfaceDiagnosticsResponse | null;
  error: string | null;
}

export function VolatilitySurfaceDiagnostics({ spot, observations }: {
  spot: string;
  observations: SurfaceObservationInput[];
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const [ratePct, setRatePct] = useState("0");
  const [dividendPct, setDividendPct] = useState("0");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const generation = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const inputKey = JSON.stringify([spot, observations, ratePct, dividendPct]);

  useEffect(() => () => {
    generation.current += 1;
    controllerRef.current?.abort();
  }, [inputKey]);

  // Hide old output during the render that changes an input, before effect cleanup.
  const current = snapshot?.key === inputKey ? snapshot : null;
  const result = current?.result;

  const diagnose = async (event: FormEvent) => {
    event.preventDefault();
    const currentGeneration = ++generation.current;
    controllerRef.current?.abort();
    const request = buildSurfaceDiagnosticsRequest(spot, observations, ratePct, dividendPct);
    if (!request) {
      controllerRef.current = null;
      setSnapshot({ key: inputKey, loading: false, result: null, error: t("options.surfaceDiagnostics.invalid") });
      return;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setSnapshot({ key: inputKey, loading: true, result: null, error: null });
    try {
      const next = await api.diagnoseVolatilitySurface(request, controller.signal);
      if (generation.current === currentGeneration) {
        setSnapshot({ key: inputKey, loading: false, result: next, error: null });
      }
    } catch (cause) {
      if (generation.current === currentGeneration && !controller.signal.aborted) {
        setSnapshot({ key: inputKey, loading: false, result: null, error: cause instanceof Error ? cause.message : t("options.surfaceDiagnostics.invalid") });
      }
    }
  };

  const incomplete = result?.slices.some((slice) => slice.status !== "checked" || slice.observations < 3);
  const performed = result && result.checked.vertical_spreads + result.checked.butterflies;

  return (
    <section aria-labelledby={titleId} className="mt-4 border-t border-border/60 pt-4">
      <h3 id={titleId} className="text-sm font-semibold">{t("options.surfaceDiagnostics.title")}</h3>
      <p className="mt-1 text-xs text-muted-foreground">{t("options.surfaceDiagnostics.description")}</p>
      <p className="mt-1 text-xs text-muted-foreground">{t("options.surfaceDiagnostics.limits")}</p>
      <form onSubmit={diagnose} className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs">
          <span className="mb-1 block text-muted-foreground">{t("options.surfaceDiagnostics.rate")}</span>
          <input aria-label={t("options.surfaceDiagnostics.rate")} className="w-36 rounded-md border bg-background px-2 py-1.5" inputMode="decimal" value={ratePct} onChange={(event) => setRatePct(event.target.value)} />
        </label>
        <label className="text-xs">
          <span className="mb-1 block text-muted-foreground">{t("options.surfaceDiagnostics.dividend")}</span>
          <input aria-label={t("options.surfaceDiagnostics.dividend")} className="w-36 rounded-md border bg-background px-2 py-1.5" inputMode="decimal" value={dividendPct} onChange={(event) => setDividendPct(event.target.value)} />
        </label>
        <button type="submit" className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium">
          {current?.loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {current?.loading ? t("options.surfaceDiagnostics.running") : t("options.surfaceDiagnostics.run")}
        </button>
      </form>
      {current?.error && <p role="alert" className="mt-3 text-sm text-danger">{current.error}</p>}
      {result && (
        <div className="mt-3 space-y-3 text-xs">
          <p>{t("options.surfaceDiagnostics.coverage", { spreads: result.checked.vertical_spreads, butterflies: result.checked.butterflies, slices: result.slices.length })}</p>
          {incomplete && <p className="text-muted-foreground">{t("options.surfaceDiagnostics.incomplete")}</p>}
          {!performed && <p>{t("options.surfaceDiagnostics.zero")}</p>}
          {performed && result.total_findings === 0 ? <p>{t("options.surfaceDiagnostics.clean")}</p> : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left tabular-nums">
              <caption className="mb-2 text-left font-medium">{t("options.surfaceDiagnostics.sliceCoverage")}</caption>
              <thead><tr>
                <th className="p-2">{t("options.surface.expiryDays")}</th>
                <th className="p-2">{t("options.surfaceDiagnostics.observedCount")}</th>
                <th className="p-2">{t("options.surfaceDiagnostics.coverageStatus")}</th>
                <th className="p-2">{t("options.surfaceDiagnostics.sliceChecks")}</th>
              </tr></thead>
              <tbody>{result.slices.map((slice) => (
                <tr key={slice.time_to_expiry} className="border-t border-border/40">
                  <td className="p-2">{numberLabel(slice.time_to_expiry * 365)}</td>
                  <td className="p-2">{slice.observations}</td>
                  <td className="p-2">{t(statusKeys[slice.status])}</td>
                  <td className="p-2">{slice.vertical_spreads} / {slice.butterflies}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {result.total_findings > 0 && (
            <div className="overflow-x-auto">
              <p className="mb-2 text-muted-foreground">{t("options.surfaceDiagnostics.truncation", { shown: result.findings.length, total: result.total_findings })}</p>
              <table className="w-full min-w-[36rem] text-left tabular-nums">
                <caption className="mb-2 text-left font-medium">{t("options.surfaceDiagnostics.findingsCount", { total: result.total_findings })}</caption>
                <thead><tr>
                  <th className="p-2">{t("options.surfaceDiagnostics.checkType")}</th>
                  <th className="p-2">{t("options.surface.expiryDays")}</th>
                  <th className="p-2">{t("options.surface.strike")}</th>
                  <th className="p-2">{t("options.surfaceDiagnostics.residual")}</th>
                  <th className="p-2">{t("options.surfaceDiagnostics.bounds")}</th>
                  <th className="p-2">{t("options.surfaceDiagnostics.tolerance")}</th>
                </tr></thead>
                <tbody>{result.findings.map((finding) => (
                  <tr key={`${finding.kind}:${finding.time_to_expiry}:${finding.strikes.join(":")}`} className="border-t border-border/40">
                    <td className="p-2">{t(findingKeys[finding.kind])}</td>
                    <td className="p-2">{numberLabel(finding.time_to_expiry * 365)}</td>
                    <td className="p-2">{finding.strikes.map(numberLabel).join(", ")}</td>
                    <td className="p-2">{numberLabel(finding.value)}</td>
                    <td className="p-2">{finding.upper_bound === null ? `≥ ${numberLabel(finding.lower_bound)}` : `[${numberLabel(finding.lower_bound)}, ${numberLabel(finding.upper_bound)}]`}</td>
                    <td className="p-2">{numberLabel(finding.tolerance)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
