import { act, fireEvent, render, screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { SurfaceDiagnosticsResponse } from "@/lib/surfaceDiagnostics";
import { VolatilitySurfaceGrid } from "../VolatilitySurfaceGrid";

vi.mock("@/lib/api", () => ({
  api: { computeVolatilitySurface: vi.fn(), diagnoseVolatilitySurface: vi.fn() },
}));

const finding = {
  kind: "butterfly_convexity" as const,
  time_to_expiry: 1,
  strikes: [80, 100, 130],
  value: -3,
  lower_bound: 0,
  upper_bound: null,
  tolerance: 1e-7,
};
const report: SurfaceDiagnosticsResponse = {
  basis: "european_bsm_calls" as const,
  scope: "observed_strikes_per_expiry" as const,
  parameters: { spot: 100, risk_free_rate: 0.05, dividend_yield: 0.02, relative_price_tolerance: 1e-9 },
  checked: { vertical_spreads: 2, butterflies: 1 },
  slices: [{ time_to_expiry: 1, observations: 3, status: "checked" as const, reason: null, tolerance: 1e-7, vertical_spreads: 2, butterflies: 1 }],
  total_findings: 1,
  limit: 20,
  findings: [finding],
};

beforeEach(() => vi.clearAllMocks());

it("diagnoses original observations with explicit model rates, independently of the output grid", async () => {
  vi.mocked(api.diagnoseVolatilitySurface).mockResolvedValue(report);
  render(<VolatilitySurfaceGrid />);
  fireEvent.change(screen.getByLabelText("Risk-free rate (%)"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("Dividend yield (%)"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Grid strikes"), { target: { value: "500" } });
  fireEvent.change(screen.getByLabelText("Grid expiries (days)"), { target: { value: "5" } });

  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));

  expect(await screen.findByRole("table", { name: "Model-price violations: 1" })).toBeInTheDocument();
  expect(screen.getByText("Butterfly convexity")).toBeInTheDocument();
  expect(screen.getByText("-3")).toBeInTheDocument();
  const [request, signal] = vi.mocked(api.diagnoseVolatilitySurface).mock.calls[0];
  expect(request.spot).toBe(100);
  expect(request.risk_free_rate).toBe(0.05);
  expect(request.dividend_yield).toBe(0.02);
  expect(request.observations).toHaveLength(6);
  expect(request.observations[0]).toEqual({ strike: 90, time_to_expiry: 30 / 365, implied_volatility: 0.24 });
  expect(request).not.toHaveProperty("strikes");
  expect(request).not.toHaveProperty("expiries");
  expect(signal).toBeInstanceOf(AbortSignal);
  expect(api.computeVolatilitySurface).not.toHaveBeenCalled();
});

it("distinguishes zero coverage from zero violations", async () => {
  vi.mocked(api.diagnoseVolatilitySurface).mockResolvedValue({
    ...report,
    checked: { vertical_spreads: 0, butterflies: 0 },
    total_findings: 0,
    findings: [],
    slices: [
      { ...report.slices[0], status: "unavailable", reason: "model_price_out_of_range", tolerance: null, vertical_spreads: 0, butterflies: 0 },
      { ...report.slices[0], time_to_expiry: 2, observations: 1, status: "insufficient_points", reason: null, tolerance: null, vertical_spreads: 0, butterflies: 0 },
    ],
  });
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));

  expect(await screen.findByText("No checks could be performed.")).toBeInTheDocument();
  expect(screen.getByText("Model price unavailable")).toBeInTheDocument();
  expect(screen.getByText("Too few strikes")).toBeInTheDocument();
  expect(screen.getByText(/Coverage is incomplete/)).toBeInTheDocument();
  expect(screen.queryByText(/No violations found in the checks performed/)).not.toBeInTheDocument();
});

it("does not turn a clean checked slice into an arbitrage-free certificate", async () => {
  vi.mocked(api.diagnoseVolatilitySurface).mockResolvedValue({ ...report, total_findings: 0, findings: [] });
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));

  expect(await screen.findByText("No violations found in the checks performed. This is not a full-surface validation.")).toBeInTheDocument();
  expect(screen.getByText(/not executable quotes or an arbitrage-free certificate/)).toBeInTheDocument();
});

it("reports the displayed finding count separately from all performed checks", async () => {
  vi.mocked(api.diagnoseVolatilitySurface).mockResolvedValue({
    ...report,
    checked: { vertical_spreads: 40, butterflies: 39 },
    slices: [{ ...report.slices[0], observations: 41, vertical_spreads: 40, butterflies: 39 }],
    total_findings: 59,
    findings: Array.from({ length: 20 }, (_, index) => ({ ...finding, strikes: [80 + index, 100 + index, 130 + index] })),
  });
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));

  expect(await screen.findByText("Showing the first 20 of 59 findings, not a severity ranking.")).toBeInTheDocument();
  expect(screen.getByText("Vertical spread checks: 40. Butterfly checks: 39. Expiry slices: 1.")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Model-price violations: 59" }).querySelectorAll("tbody tr")).toHaveLength(20);
});

it.each(["Spot", "Strike 1", "Expiry (days) 1", "IV (%) 1", "Risk-free rate (%)", "Dividend yield (%)"])("invalidates pending diagnostics when %s changes", async (label) => {
  let resolve!: (value: typeof report) => void;
  vi.mocked(api.diagnoseVolatilitySurface).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));
  const signal = vi.mocked(api.diagnoseVolatilitySurface).mock.calls[0][1]!;

  fireEvent.change(screen.getByLabelText(label), { target: { value: "25" } });

  expect(signal.aborted).toBe(true);
  expect(screen.queryByRole("button", { name: "Checking observed slices…" })).not.toBeInTheDocument();
  await act(async () => resolve(report));
  expect(screen.queryByRole("table", { name: "Model-price violations: 1" })).not.toBeInTheDocument();
});

it("ignores an older response after a replacement check finishes", async () => {
  let resolveOld!: (value: typeof report) => void;
  vi.mocked(api.diagnoseVolatilitySurface)
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValueOnce({ ...report, total_findings: 0, findings: [] });
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));
  fireEvent.click(screen.getByRole("button", { name: "Checking observed slices…" }));

  expect(await screen.findByText(/No violations found in the checks performed/)).toBeInTheDocument();
  await act(async () => resolveOld(report));

  expect(screen.queryByRole("table", { name: "Model-price violations: 1" })).not.toBeInTheDocument();
});

it("removes completed diagnostics when the observations change", async () => {
  vi.mocked(api.diagnoseVolatilitySurface).mockResolvedValue(report);
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));
  await screen.findByRole("table", { name: "Model-price violations: 1" });

  fireEvent.change(screen.getByLabelText("IV (%) 1"), { target: { value: "80" } });

  expect(screen.queryByRole("table", { name: "Model-price violations: 1" })).not.toBeInTheDocument();
});

it("rejects an empty model rate rather than interpreting it as zero", async () => {
  render(<VolatilitySurfaceGrid />);
  fireEvent.change(screen.getByLabelText("Risk-free rate (%)"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Enter valid observations and finite rates; rates may be negative.");
  expect(api.diagnoseVolatilitySurface).not.toHaveBeenCalled();
});

it("aborts pending diagnostics when the options view unmounts", async () => {
  let resolve!: (value: SurfaceDiagnosticsResponse) => void;
  vi.mocked(api.diagnoseVolatilitySurface).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const view = render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));
  const signal = vi.mocked(api.diagnoseVolatilitySurface).mock.calls[0][1]!;

  view.unmount();

  expect(signal.aborted).toBe(true);
  await act(async () => resolve(report));
});

it("shows request failures without a clean coverage claim", async () => {
  vi.mocked(api.diagnoseVolatilitySurface).mockRejectedValue(new Error("diagnostic transport unavailable"));
  render(<VolatilitySurfaceGrid />);
  fireEvent.click(screen.getByRole("button", { name: "Check observed slices" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("diagnostic transport unavailable");
  expect(screen.queryByText(/No violations found in the checks performed/)).not.toBeInTheDocument();
});
