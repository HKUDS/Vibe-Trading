import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import type { SurfaceDiagnosticsRequest } from "../surfaceDiagnostics";

const body: SurfaceDiagnosticsRequest = {
  observations: [{ strike: 100, time_to_expiry: 1, implied_volatility: 0.2 }],
  spot: 100,
  risk_free_rate: 0.03,
  dividend_yield: 0.01,
};

beforeEach(() => {
  vi.stubGlobal("localStorage", {
    getItem: vi.fn((key) => key === "vibe_trading_api_auth_key" ? "surface-test-key" : "en"),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
});
afterEach(() => vi.unstubAllGlobals());

it("posts the original observations to the diagnostic endpoint through shared auth", async () => {
  const result = {
    basis: "european_bsm_calls", scope: "observed_strikes_per_expiry",
    parameters: { spot: 100, risk_free_rate: 0.03, dividend_yield: 0.01, relative_price_tolerance: 1e-9 },
    checked: { vertical_spreads: 0, butterflies: 0 },
    slices: [{ time_to_expiry: 1, observations: 1, status: "insufficient_points", reason: null, tolerance: null, vertical_spreads: 0, butterflies: 0 }],
    total_findings: 0, limit: 20, findings: [],
  };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(result), {
    headers: { "content-type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetch);

  await expect(api.diagnoseVolatilitySurface(body)).resolves.toEqual(result);

  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch).toHaveBeenCalledWith("/options/volatility-surface/diagnostics", expect.objectContaining({
    method: "POST", body: JSON.stringify(body),
    headers: expect.objectContaining({ Authorization: "Bearer surface-test-key" }),
  }));
});

it("forwards an already aborted caller signal instead of creating an active request", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetch = vi.fn((_path, options) => {
    expect(options.signal.aborted).toBe(true);
    return Promise.reject(new DOMException("aborted", "AbortError"));
  });
  vi.stubGlobal("fetch", fetch);

  await expect(api.diagnoseVolatilitySurface(body, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
});
