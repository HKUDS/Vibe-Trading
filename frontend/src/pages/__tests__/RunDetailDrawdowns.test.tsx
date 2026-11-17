import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { RunDetail } from "../RunDetail";

const apiMock = vi.hoisted(() => ({
  getRun: vi.fn(),
  getRunCode: vi.fn(),
  getRunFactor: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/FactorResearchPanel", () => ({
  FactorResearchPanel: () => <div />,
}));
vi.mock("@/components/charts/CandlestickChart", () => ({
  CandlestickChart: () => <div />,
}));
vi.mock("@/components/charts/EquityChart", () => ({
  EquityChart: () => <div />,
}));
vi.mock("@/components/charts/StrategyResearchDashboard", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/charts/StrategyResearchDashboard")>();
  return { ...actual, StrategyResearchDashboard: () => <div /> };
});

function episodeReport() {
  const recovered = {
    peak: "2026-01-02",
    trough: "2026-01-03",
    recovery: "2026-01-05",
    depth: -0.5,
    duration_bars: 3,
  };
  const ongoing = {
    peak: "2026-01-06",
    trough: "2026-01-07",
    recovery: null,
    depth: -0.25,
    duration_bars: 1,
  };
  return {
    available: true,
    reason: null,
    basis: "constant_weight_model",
    duration_unit: "bars",
    recovery_rtol: 1e-12,
    total: 2,
    limit: 5,
    items: [recovered, ongoing],
    current: ongoing,
  };
}

async function openStudio(episodes?: unknown, maxDrawdown = -0.5) {
  apiMock.getRun.mockResolvedValue({
    status: "success",
    run_id: "risk-run",
    prompt: "Drawdown report",
    risk_xray: {
      inputs: { symbols: ["AAA"], weights: { AAA: 1 } },
      drawdown: { max_drawdown: maxDrawdown, ...(episodes ? { episodes } : {}) },
    },
  });
  apiMock.getRunCode.mockResolvedValue({});
  const router = createMemoryRouter(
    [{ path: "/runs/:runId", element: <RunDetail /> }],
    { initialEntries: ["/runs/risk-run"] },
  );
  render(<RouterProvider router={router} />);
  await screen.findByText("Drawdown report");
  fireEvent.click(screen.getByRole("tab", { name: "Portfolio Studio" }));
  await screen.findByText("Risk X-Ray");
}

describe("Risk X-Ray drawdown periods in Portfolio Studio", () => {
  beforeEach(() => {
    apiMock.getRun.mockReset();
    apiMock.getRunCode.mockReset();
    apiMock.getRunFactor.mockReset();
  });

  it("renders observed recovery, depth and bar duration from the persisted report", async () => {
    await openStudio(episodeReport());

    const table = await screen.findByRole("table", { name: "Drawdown periods" });
    expect(within(table).getByRole("columnheader", { name: "Observed bars" })).toBeInTheDocument();
    expect(within(table).getByText("2026-01-05")).toBeInTheDocument();
    expect(within(table).getByText("Not recovered")).toBeInTheDocument();
    expect(within(table).getByText("-50.00%")).toBeInTheDocument();
    expect(within(table).getByText("-25.00%")).toBeInTheDocument();
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1].lastElementChild).toHaveTextContent("3");
    expect(rows[2].lastElementChild).toHaveTextContent("1");
    expect(screen.getByText(/not calendar days/i)).toBeInTheDocument();
  });

  it("distinguishes an observed empty set from unavailable history", async () => {
    await openStudio({ ...episodeReport(), total: 0, items: [], current: null }, 0);

    expect(await screen.findByText("No drawdown periods observed in this window.")).toBeInTheDocument();
    expect(screen.queryByText(/Drawdown periods unavailable/)).not.toBeInTheDocument();
  });

  it("does not label missing return observations as no drawdowns", async () => {
    await openStudio({
      ...episodeReport(),
      available: false,
      reason: "missing_return_observations",
      total: null,
      items: [],
      current: null,
    });

    expect(await screen.findByText(/Drawdown periods unavailable: return observations are missing/i)).toBeInTheDocument();
    expect(screen.queryByText("No drawdown periods observed in this window.")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Drawdown periods" })).not.toBeInTheDocument();
  });

  it("keeps the window-end drawdown visible when it is outside the deepest five", async () => {
    const report = episodeReport();
    const items = Array.from({ length: 5 }, (_, index) => ({
      ...report.items[0],
      peak: `2026-01-${String(2 + index * 3).padStart(2, "0")}`,
      trough: `2026-01-${String(3 + index * 3).padStart(2, "0")}`,
      recovery: `2026-01-${String(4 + index * 3).padStart(2, "0")}`,
      depth: -0.6 + index * 0.05,
    }));
    await openStudio({
      ...report,
      total: 6,
      items,
      current: { peak: "2026-03-01", trough: "2026-03-04", recovery: null, depth: -0.01, duration_bars: 3 },
    }, -0.6);

    expect(await screen.findByText("Window-end drawdown: -1.00%; observed bars: 3")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Drawdown periods" });
    expect(within(table).queryByText("2026-03-01")).not.toBeInTheDocument();
  });

  it("preserves the legacy artifact view when episode data is absent", async () => {
    await openStudio();

    expect(screen.getByText("-50.0%")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Drawdown periods" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Drawdown periods unavailable/)).not.toBeInTheDocument();
  });
});
