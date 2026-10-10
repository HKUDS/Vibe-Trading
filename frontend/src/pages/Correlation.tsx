import i18n from '@/i18n';
import { useEffect, useRef, useState } from "react";
import { BarChart3 } from "lucide-react";
import { CorrelationMatrix } from "@/components/charts/CorrelationMatrix";
import { RegimeTimeline } from "@/components/charts/RegimeTimeline";
import { api, type CorrelationAnalysisResponse } from "@/lib/api";
import { useAnalysisState } from "@/hooks/useAnalysisState";

const WINDOWS = [30, 60, 90, 180, 365] as const;

export function Correlation() {
  const [draft, setDraft] = useAnalysisState("correlation", {
    codes: "000001.SZ,600519.SH,000858.SZ,601318.SH", days: 90,
    method: "pearson" as "pearson" | "spearman", showRegime: false,
    result: null as CorrelationAnalysisResponse | null, resultQuery: "", computedAt: "",
  });
  const { codes, days, method, showRegime, result, resultQuery, computedAt } = draft;
  const setCodes = (codes: string) => setDraft((d) => ({ ...d, codes }));
  const setDays = (days: number) => setDraft((d) => ({ ...d, days }));
  const setMethod = (method: "pearson" | "spearman") => setDraft((d) => ({ ...d, method }));
  const setShowRegime = (showRegime: boolean) => setDraft((d) => ({ ...d, showRegime }));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const labels = result?.correlation?.labels ?? [];
  const matrix = result?.correlation?.matrix ?? [];
  const regime = result?.regime ?? null;
  const requestGeneration = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const parsedCodes = codes.split(/[,;\s，；]+/).map((code) => code.trim().toUpperCase()).filter(Boolean);
  const uniqueCodes = new Set(parsedCodes.map((code) => code.replace(/\.US$/, "")));
  const inputValid = parsedCodes.length >= 2 && parsedCodes.length <= 20 && uniqueCodes.size === parsedCodes.length;
  const query = JSON.stringify({ codes: parsedCodes.join(","), days, method, showRegime });
  const fresh = resultQuery === query;
  useEffect(() => () => { requestGeneration.current += 1; controller.current?.abort(); }, []);

  const invalidateResult = () => {
    requestGeneration.current += 1;
    controller.current?.abort();
    setError(null);
    setLoading(false);
  };

  const compute = async () => {
    if (!inputValid) return;
    controller.current?.abort();
    const pending = new AbortController();
    controller.current = pending;
    const generation = ++requestGeneration.current;
    setError(null);
    setLoading(true);
    try {
      const response = await api.getCorrelationAnalysis(parsedCodes.join(","), days, method, showRegime, pending.signal);
      if (requestGeneration.current === generation) {
        setDraft((d) => ({ ...d, result: response, resultQuery: query, computedAt: new Date().toISOString() }));
      }
    } catch (e) {
      if (!pending.signal.aborted && requestGeneration.current === generation) {
        setError(e instanceof Error ? e.message : i18n.t("correlation.failedToCompute"));
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BarChart3 className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold">{i18n.t("correlation.title")}</h1>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-4 border rounded-lg p-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="correlation-codes" className="text-sm font-medium">{i18n.t("correlation.assetCodes")}</label>
          <input
            id="correlation-codes"
            type="text"
            value={codes}
            onChange={(e) => {
              invalidateResult();
              setCodes(e.target.value);
            }}
            placeholder="000001.SZ,600519.SH,000858.SZ"
            className="w-full px-3 py-2 rounded-md border bg-background text-sm"
          />
          <p className="text-xs text-muted-foreground">
            {i18n.t("correlation.assetCodesHint")}
          </p>
        </div>

        <div className="flex flex-wrap gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">{i18n.t("analysis.windowObservations")}</label>
            <div className="flex gap-1.5">
              {WINDOWS.map((w) => (
                <button
                  key={w}
                  onClick={() => {
                    invalidateResult();
                    setDays(w);
                  }}
                  className={`px-3 py-1.5 rounded text-sm border transition-colors ${
                    days === w
                      ? "bg-primary text-primary-foreground"
                      : "border-muted-foreground/30 hover:border-primary"
                  }`}
                >
                  {w}d
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">{i18n.t("correlation.method")}</label>
            <div className="flex gap-1.5">
              {(["pearson", "spearman"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    invalidateResult();
                    setMethod(m);
                  }}
                  className={`px-3 py-1.5 rounded text-sm border transition-colors capitalize ${
                    method === m
                      ? "bg-primary text-primary-foreground"
                      : "border-muted-foreground/30 hover:border-primary"
                  }`}
                >
                  {i18n.t(`correlation.method_${m}`)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
            <input
              type="checkbox"
              checked={showRegime}
              onChange={(e) => {
                invalidateResult();
                setShowRegime(e.target.checked);
              }}
              className="h-4 w-4"
            />
            {i18n.t("correlation.regimeTimeline")}
          </label>
          {showRegime && (
            <p className="text-xs text-muted-foreground">
              {i18n.t("correlation.regimeTimelineHint")}
            </p>
          )}
        </div>

        <button
          onClick={compute}
          disabled={loading || !inputValid}
          className="self-start px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {loading ? i18n.t("correlation.loading") : i18n.t("correlation.compute")}
        </button>
        {!inputValid && <p role="alert" className="text-sm text-warning">{i18n.t("analysis.assetsValidation")}</p>}
      </div>

      {/* Error */}
      {error && (
        <div className="text-sm text-danger border border-danger/30 rounded p-3 bg-danger/5">
          {error}
        </div>
      )}

      {result && <div className="space-y-2 rounded-lg border bg-card p-3 text-sm" role="status">
        <p>{fresh ? i18n.t("analysis.updated") : i18n.t("analysis.previousResult")} · {i18n.t("analysis.lastComputed", { time: new Date(computedAt).toLocaleTimeString() })}</p>
        <p className="text-muted-foreground">{i18n.t("analysis.coverage", { count: result.coverage.observations, start: result.coverage.first_date ?? "–", end: result.coverage.last_date ?? "–" })}</p>
        <p className="text-xs">{i18n.t("analysis.usedAssets", { assets: labels.join(", ") || "–" })}</p>
        {result.coverage.missing.length > 0 && <p className="text-warning">{i18n.t("analysis.missingAssets", { assets: result.coverage.missing.join(", ") })}</p>}
        {result.coverage.missing.map((code) => <p key={code} className="text-xs text-muted-foreground">{code}: {result.coverage.diagnostics[code]?.attempts.map((a) => `${a.source}: ${i18n.t(`analysis.${a.reason}`)}`).join("; ")}</p>)}
        {Object.entries(result.errors).map(([section, message]) => <p role="alert" key={section} className="text-danger">{i18n.t(section === "regime" ? "correlation.regimeTimeline" : "correlation.title")}: {message}</p>)}
        {regime && <p className="text-xs text-muted-foreground">{i18n.t("analysis.regimeMethod")}</p>}
      </div>}

      {/* Regime timeline (above the matrix when enabled) */}
      {regime && <RegimeTimeline data={regime} height={260} />}

      {/* Chart */}
      {labels.length > 0 && <CorrelationMatrix labels={labels} matrix={matrix} height={520} />}
    </div>
  );
}
