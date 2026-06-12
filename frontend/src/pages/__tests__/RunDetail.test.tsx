import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RunDetail } from "../RunDetail";
import type { RunData } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getRun: vi.fn(),
  getRunCode: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));

vi.mock("@/components/charts/CandlestickChart", () => ({
  CandlestickChart: ({ data }: { data: Array<{ code?: string; time: string }> }) => (
    <div data-testid={`chart-${data[0]?.code || data[0]?.time}`}>{data[0]?.code || data[0]?.time}</div>
  ),
}));

vi.mock("@/components/charts/EquityChart", () => ({
  EquityChart: () => <div data-testid="equity-chart" />,
}));

function renderRunDetail() {
  return render(
    <MemoryRouter initialEntries={["/runs/run-1"]}>
      <Routes>
        <Route path="/runs/:runId" element={<RunDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

function makeRun(symbol: string, overrides: Partial<RunData> = {}): RunData {
  return {
    run_id: "run-1",
    status: "success",
    chart_symbols: ["AAA", "BBB", "CCC"],
    price_series: {
      [symbol]: [
        { time: "2024-01-02", code: symbol, open: 1, high: 2, low: 0.5, close: 1.5, volume: 100 },
      ],
    },
    indicator_series: {},
    trade_markers: [{ time: "2024-01-02", code: symbol, side: "BUY", price: 1.5 }],
    equity_curve: [{ time: "2024-01-02", equity: 1000, drawdown: 0 }],
    ...overrides,
  };
}

describe("RunDetail chart loading", () => {
  beforeEach(() => {
    apiMock.getRun.mockReset();
    apiMock.getRunCode.mockReset();
    apiMock.getRunCode.mockResolvedValue({});
    apiMock.getRun.mockImplementation((_runId: string, params?: { chart_symbol?: string }) => {
      return Promise.resolve(makeRun(params?.chart_symbol || "AAA"));
    });
  });

  it("loads an added chart symbol without replacing existing charts", async () => {
    renderRunDetail();

    expect(await screen.findByTestId("chart-AAA")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "BBB" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByTestId("chart-BBB")).toBeInTheDocument();
    expect(screen.getByTestId("chart-AAA")).toBeInTheDocument();
    expect(apiMock.getRun).toHaveBeenCalledWith("run-1", { chart_symbol: "BBB" });
  });

  it("progressively loads all symbols and reports progress", async () => {
    renderRunDetail();

    expect(await screen.findByTestId("chart-AAA")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load all" }));

    expect(await screen.findByTestId("chart-CCC")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("3 / 3 (100%)")).toBeInTheDocument());
    expect(apiMock.getRun).toHaveBeenCalledWith("run-1", { chart_symbol: "BBB" });
    expect(apiMock.getRun).toHaveBeenCalledWith("run-1", { chart_symbol: "CCC" });
  });
});
