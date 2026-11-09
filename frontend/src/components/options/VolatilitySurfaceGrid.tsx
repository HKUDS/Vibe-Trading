import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import {
  buildVolatilitySurfaceRequest,
  DEFAULT_SURFACE_EXPIRY_DAYS,
  DEFAULT_SURFACE_OBSERVATIONS,
  DEFAULT_SURFACE_STRIKES,
  type SurfaceObservationInput,
  volatilitySurfaceIssue,
  type VolatilitySurfacePoint,
  type VolatilitySurfaceResponse,
} from "@/lib/options";
import { cn } from "@/lib/utils";

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function pointKey(point: Pick<VolatilitySurfacePoint, "strike" | "time_to_expiry">): string {
  return `${point.strike}:${point.time_to_expiry}`;
}

export function VolatilitySurfaceGrid() {
  const { t } = useTranslation();
  const [spot, setSpot] = useState("100");
  const [strikes, setStrikes] = useState(DEFAULT_SURFACE_STRIKES);
  const [expiryDays, setExpiryDays] = useState(DEFAULT_SURFACE_EXPIRY_DAYS);
  const [observations, setObservations] = useState<SurfaceObservationInput[]>(
    () => DEFAULT_SURFACE_OBSERVATIONS.map((observation) => ({ ...observation })),
  );
  const [result, setResult] = useState<VolatilitySurfaceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(DEFAULT_SURFACE_OBSERVATIONS.length + 1);
  const generation = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => {
    generation.current += 1;
    controllerRef.current?.abort();
  }, []);

  const updateObservation = (id: number, field: keyof Omit<SurfaceObservationInput, "id">, value: string) => {
    setObservations((current) => current.map((observation) => (
      observation.id === id ? { ...observation, [field]: value } : observation
    )));
  };

  const addObservation = () => {
    const id = nextId.current++;
    setObservations((current) => [...current, {
      id,
      strike: "100",
      expiryDays: "60",
      ivPct: "30",
    }]);
  };

  const compute = async (event: FormEvent) => {
    event.preventDefault();
    const currentGeneration = ++generation.current;
    controllerRef.current?.abort();
    const request = buildVolatilitySurfaceRequest(spot, observations, strikes, expiryDays);
    const issue = request ? volatilitySurfaceIssue(request) : null;
    if (!request || issue) {
      controllerRef.current = null;
      setLoading(false);
      setResult(null);
      setError(issue ? t(`options.surface.${issue.key}`, issue.values) : t("options.surface.invalid"));
      return;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const next = await api.computeVolatilitySurface(request, controller.signal);
      if (generation.current === currentGeneration) setResult(next);
    } catch (cause) {
      if (generation.current === currentGeneration && !controller.signal.aborted) {
        setResult(null);
        setError(cause instanceof Error ? cause.message : t("options.surface.invalid"));
      }
    } finally {
      if (generation.current === currentGeneration) setLoading(false);
    }
  };

  const points = new Map(result?.points.map((point) => [pointKey(point), point]) ?? []);
  const ivValues = result?.points.map((point) => point.implied_volatility) ?? [];
  const minIv = ivValues.length ? Math.min(...ivValues) : 0;
  const maxIv = ivValues.length ? Math.max(...ivValues) : 0;

  const cellStyle = (point: VolatilitySurfacePoint) => {
    const ratio = maxIv === minIv ? 0.5 : (point.implied_volatility - minIv) / (maxIv - minIv);
    return {
      backgroundColor: `rgba(37, 99, 235, ${0.10 + ratio * 0.72})`,
      color: ratio > 0.62 ? "#ffffff" : undefined,
    };
  };

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">{t("options.surface.title")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{t("options.surface.subtitle")}</p>
      </div>
      <form className="flex flex-col gap-3" onSubmit={compute}>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs">
            <span className="mb-1 block text-muted-foreground">{t("options.surface.spot")}</span>
            <input aria-label={t("options.surface.spot")} className="w-full rounded-md border bg-background px-2 py-1.5" inputMode="decimal" value={spot} onChange={(event) => setSpot(event.target.value)} />
            <span className="mt-1 block text-[10px] leading-4 text-muted-foreground">{t("options.surface.spotHint")}</span>
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-muted-foreground">{t("options.surface.gridStrikes")}</span>
            <input className="w-full rounded-md border bg-background px-2 py-1.5" value={strikes} onChange={(event) => setStrikes(event.target.value)} />
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-muted-foreground">{t("options.surface.gridExpiries")}</span>
            <input className="w-full rounded-md border bg-background px-2 py-1.5" value={expiryDays} onChange={(event) => setExpiryDays(event.target.value)} />
          </label>
        </div>

        <div className="flex flex-col gap-2">
          <div className="hidden grid-cols-[1fr_1fr_1fr_auto] gap-2 text-xs text-muted-foreground sm:grid">
            <span>{t("options.surface.strike")}</span>
            <span>{t("options.surface.expiryDays")}</span>
            <span>{t("options.surface.ivPct")}</span>
            <span className="sr-only">{t("options.surface.remove")}</span>
          </div>
          {observations.map((observation, index) => (
            <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2" key={observation.id}>
              <input aria-label={`${t("options.surface.strike")} ${index + 1}`} className="min-w-0 rounded-md border bg-background px-2 py-1.5 text-xs" inputMode="decimal" value={observation.strike} onChange={(event) => updateObservation(observation.id, "strike", event.target.value)} />
              <input aria-label={`${t("options.surface.expiryDays")} ${index + 1}`} className="min-w-0 rounded-md border bg-background px-2 py-1.5 text-xs" inputMode="decimal" value={observation.expiryDays} onChange={(event) => updateObservation(observation.id, "expiryDays", event.target.value)} />
              <input aria-label={`${t("options.surface.ivPct")} ${index + 1}`} className="min-w-0 rounded-md border bg-background px-2 py-1.5 text-xs" inputMode="decimal" value={observation.ivPct} onChange={(event) => updateObservation(observation.id, "ivPct", event.target.value)} />
              <button aria-label={`${t("options.surface.remove")} ${index + 1}`} className="rounded-md border px-2 text-muted-foreground hover:text-danger disabled:opacity-40" type="button" disabled={observations.length === 1} onClick={() => setObservations((current) => current.filter((item) => item.id !== observation.id))}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs" type="button" onClick={addObservation}>
            <Plus className="h-3.5 w-3.5" />{t("options.surface.addQuote")}
          </button>
          <button className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground" type="submit">
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {loading ? t("options.surface.computing") : t("options.surface.compute")}
          </button>
        </div>
      </form>

      {error && <div role="alert" className="mt-3 rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger">{error}</div>}
      {!result && !error && <p className="mt-3 text-xs text-muted-foreground">{t("options.surface.empty")}</p>}

      {result && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[32rem] border-separate border-spacing-1 text-center text-xs">
            <caption className="mb-2 text-left text-xs text-muted-foreground">{t("options.surface.caption")}</caption>
            <thead>
              <tr>
                <th className="p-2 text-left text-muted-foreground">{t("options.surface.expiryDays")}</th>
                {result.strikes.map((strike) => <th className="p-2 font-medium" key={strike}>{strike}</th>)}
              </tr>
            </thead>
            <tbody>
              {result.expiries.map((expiry) => (
                <tr key={expiry}>
                  <th className="p-2 text-left font-medium text-muted-foreground">{Math.round(expiry * 365)}</th>
                  {result.strikes.map((strike) => {
                    const point = points.get(`${strike}:${expiry}`);
                    if (!point) return <td key={strike}>N/A</td>;
                    return (
                      <td className={cn("rounded-md p-2 tabular-nums", point.source === "observed" && "ring-1 ring-inset ring-primary/40")} key={strike} style={cellStyle(point)}>
                        <div className="font-semibold">{formatPercent(point.implied_volatility)}</div>
                        <div className="mt-0.5 text-[10px] opacity-80">{t(`options.surface.${point.source}`)}</div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
