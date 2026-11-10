import { act, fireEvent, render, screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { VolatilitySurfaceResponse } from "@/lib/options";
import { VolatilitySurfaceGrid } from "../VolatilitySurfaceGrid";

vi.mock("@/lib/api", () => ({ api: { computeVolatilitySurface: vi.fn() } }));

const response: VolatilitySurfaceResponse = {
  strikes: [90, 100, 110],
  expiries: [0.1],
  interpolation: {
    strike: "linear_iv_log_moneyness",
    expiry: "linear_total_variance",
    extrapolation: "rejected",
  },
  points: [
    { strike: 90, time_to_expiry: 0.1, implied_volatility: 0.25, total_variance: 0.00625, source: "observed" },
    { strike: 100, time_to_expiry: 0.1, implied_volatility: 0.3, total_variance: 0.009, source: "interpolated" },
    { strike: 110, time_to_expiry: 0.1, implied_volatility: 0.35, total_variance: 0.01225, source: "observed" },
  ],
};

beforeEach(() => vi.clearAllMocks());

it("computes the editable grid through the backend and labels each point source", async () => {
  vi.mocked(api.computeVolatilitySurface).mockResolvedValue(response);
  render(<VolatilitySurfaceGrid />);

  fireEvent.click(screen.getByRole("button", { name: "Compute surface" }));

  expect(await screen.findByText("30.00%")).toBeInTheDocument();
  expect(screen.getAllByText("observed")).toHaveLength(2);
  expect(screen.getByText("interpolated")).toBeInTheDocument();
  const [request] = vi.mocked(api.computeVolatilitySurface).mock.calls[0];
  expect(request.spot).toBe(100);
  expect(request.strikes).toEqual([90, 100, 110]);
  expect(request.expiries).toHaveLength(5);
  expect(request.observations).toHaveLength(6);
  expect(request.observations[0]).toEqual({
    strike: 90,
    time_to_expiry: 30 / 365,
    implied_volatility: 0.24,
  });
});

it("shows backend validation failures without inventing a grid", async () => {
  vi.mocked(api.computeVolatilitySurface).mockRejectedValue(new Error("no extrapolation"));
  render(<VolatilitySurfaceGrid />);

  fireEvent.click(screen.getByRole("button", { name: "Compute surface" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("no extrapolation");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("clears pending state when a replacement submission fails client validation", async () => {
  vi.mocked(api.computeVolatilitySurface).mockImplementation(() => new Promise(() => {}));
  render(<VolatilitySurfaceGrid />);

  fireEvent.click(screen.getByRole("button", { name: "Compute surface" }));
  fireEvent.change(screen.getByLabelText("Spot"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Computing surface…" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Enter valid positive numbers");
  expect(screen.getByRole("button", { name: "Compute surface" })).toBeInTheDocument();
});

it("ignores an older response after a newer computation completes", async () => {
  let resolveOld!: (value: VolatilitySurfaceResponse) => void;
  let resolveNew!: (value: VolatilitySurfaceResponse) => void;
  vi.mocked(api.computeVolatilitySurface)
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
  render(<VolatilitySurfaceGrid />);
  const button = screen.getByRole("button", { name: "Compute surface" });
  fireEvent.click(button);
  fireEvent.click(button);

  const newer = { ...response, points: response.points.map((point) => ({ ...point })) };
  await act(async () => resolveNew(newer));
  expect(await screen.findByText("30.00%")).toBeInTheDocument();
  await act(async () => resolveOld({
    ...response,
    points: response.points.map((point) => ({ ...point, implied_volatility: 0.99 })),
  }));
  expect(screen.queryByText("99.00%")).not.toBeInTheDocument();
  expect(screen.getByText("30.00%")).toBeInTheDocument();
});

it("rejects duplicate quotes with a day-based message before sending", async () => {
  render(<VolatilitySurfaceGrid />);
  fireEvent.change(screen.getByLabelText("Strike 2"), { target: { value: "90" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute surface" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Duplicate quote for strike 90 at 30 days");
  expect(api.computeVolatilitySurface).not.toHaveBeenCalled();
});

it("rejects grid expiries outside quote coverage with a day-based range", async () => {
  render(<VolatilitySurfaceGrid />);
  fireEvent.change(screen.getByLabelText("Grid expiries (days)"), { target: { value: "15, 30, 60, 90" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute surface" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Grid expiry 15 days is outside the quoted range 30 to 90 days");
  expect(api.computeVolatilitySurface).not.toHaveBeenCalled();
});

it("rejects grid strikes outside quote coverage with the relevant expiry in days", async () => {
  render(<VolatilitySurfaceGrid />);
  fireEvent.change(screen.getByLabelText("Grid strikes"), { target: { value: "80, 90, 100, 110" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute surface" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Grid strike 80 is outside the quoted range 90 to 110 at 30 days");
  expect(api.computeVolatilitySurface).not.toHaveBeenCalled();
});

it("labels spot as validation-only because it does not change interpolated IV", () => {
  render(<VolatilitySurfaceGrid />);
  expect(screen.getByText("Validation only; spot cancels out of IV interpolation.")).toBeInTheDocument();
});
