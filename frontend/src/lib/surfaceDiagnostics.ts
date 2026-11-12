import { buildVolatilitySurfaceRequest, type SurfaceObservationInput, type VolatilityObservation } from "@/lib/options";

export interface SurfaceDiagnosticsRequest {
  observations: VolatilityObservation[];
  spot: number;
  /** Continuously compounded annual fractions, not percent inputs. */
  risk_free_rate: number;
  dividend_yield: number;
}

interface SliceCoverage {
  time_to_expiry: number;
  observations: number;
  vertical_spreads: number;
  butterflies: number;
}

export type SurfaceDiagnosticSlice = SliceCoverage & (
  | { status: "checked"; reason: null; tolerance: number }
  | { status: "insufficient_points"; reason: null; tolerance: null }
  | { status: "unavailable"; reason: "model_price_out_of_range"; tolerance: null }
);

interface PriceResidual {
  time_to_expiry: number;
  strikes: number[];
  /** Price units, never a percentage. */
  value: number;
  lower_bound: number;
  tolerance: number;
}

export type SurfaceDiagnosticFinding = PriceResidual & (
  | { kind: "vertical_spread_bounds"; upper_bound: number }
  | { kind: "butterfly_convexity"; upper_bound: null }
);

export interface SurfaceDiagnosticsResponse {
  basis: "european_bsm_calls";
  scope: "observed_strikes_per_expiry";
  parameters: {
    spot: number;
    risk_free_rate: number;
    dividend_yield: number;
    relative_price_tolerance: number;
  };
  checked: { vertical_spreads: number; butterflies: number };
  slices: SurfaceDiagnosticSlice[];
  total_findings: number;
  limit: number;
  findings: SurfaceDiagnosticFinding[];
}

/** Normalize only observed points; the interpolation grid has no role here. */
export function buildSurfaceDiagnosticsRequest(
  spot: string,
  observations: SurfaceObservationInput[],
  ratePct: string,
  dividendPct: string,
): SurfaceDiagnosticsRequest | null {
  if (!ratePct.trim() || !dividendPct.trim() || observations.length > 400) return null;
  const rate = Number(ratePct);
  const dividend = Number(dividendPct);
  if (!Number.isFinite(rate) || !Number.isFinite(dividend)) return null;
  const base = buildVolatilitySurfaceRequest(spot, observations, "", "");
  if (!base || base.observations.some((point) => point.time_to_expiry <= 0)) return null;
  return {
    observations: base.observations,
    spot: base.spot,
    risk_free_rate: rate / 100,
    dividend_yield: dividend / 100,
  };
}
