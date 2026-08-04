import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { RunDetail } from "../RunDetail";
import type { RunData } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getRun: vi.fn(),
  getRunCode: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/CandlestickChart", () => ({
  CandlestickChart: () => <div data-testid="candlestick-chart" />,
}));
vi.mock("@/components/charts/EquityChart", () => ({
  EquityChart: () => <div data-testid="equity-chart" />,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function renderRunDetail(path = "/runs/old") {
  const router = createMemoryRouter(
    [{ path: "/runs/:runId", element: <RunDetail /> }],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("RunDetail page", () => {
  beforeEach(() => {
    apiMock.getRun.mockReset();
    apiMock.getRunCode.mockReset();
  });

  it("does not let an older route load replace the current run or code", async () => {
    const oldRun = deferred<RunData>();
    const oldCode = deferred<Record<string, string>>();
    const newRun = deferred<RunData>();
    const newCode = deferred<Record<string, string>>();

    apiMock.getRun.mockImplementation((runId: string) => runId === "old" ? oldRun.promise : newRun.promise);
    apiMock.getRunCode.mockImplementation((runId: string) => runId === "old" ? oldCode.promise : newCode.promise);

    const router = renderRunDetail();
    await act(async () => { await router.navigate("/runs/new"); });

    await act(async () => {
      newRun.resolve({ status: "success", run_id: "new", prompt: "New run" });
      newCode.resolve({ "new.py": "NEW_CODE" });
      await Promise.all([newRun.promise, newCode.promise]);
    });
    expect(await screen.findByText("New run")).toBeInTheDocument();

    await act(async () => {
      oldRun.resolve({ status: "success", run_id: "old", prompt: "Old run" });
      oldCode.resolve({ "old.py": "OLD_CODE" });
      await Promise.all([oldRun.promise, oldCode.promise]);
    });

    expect(screen.getByText("New run")).toBeInTheDocument();
    expect(screen.queryByText("Old run")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    expect(await screen.findByText("NEW_CODE")).toBeInTheDocument();
    expect(screen.queryByText("OLD_CODE")).not.toBeInTheDocument();
  });

  it("ignores a chart response that finishes after the route changes", async () => {
    const oldChart = deferred<RunData>();
    apiMock.getRun.mockImplementation((runId: string, params: Record<string, string>) => {
      if (runId === "old" && params.chart_payload === "summary") {
        return Promise.resolve({ status: "success", run_id: "old", prompt: "Old run", chart_symbols: ["OLD"] });
      }
      if (runId === "old" && params.chart_symbol === "OLD") return oldChart.promise;
      return Promise.resolve({ status: "success", run_id: "new", prompt: "New run" });
    });
    apiMock.getRunCode.mockResolvedValue({});

    const router = renderRunDetail();
    expect(await screen.findByText("Old run")).toBeInTheDocument();
    await waitFor(() => {
      expect(apiMock.getRun).toHaveBeenCalledWith("old", { chart_symbol: "OLD" });
    });

    await act(async () => { await router.navigate("/runs/new"); });
    expect(await screen.findByText("New run")).toBeInTheDocument();

    await act(async () => {
      oldChart.resolve({
        status: "success",
        run_id: "old",
        chart_symbols: ["OLD"],
        trade_log: [{ note: "OLD TRADE" }],
      });
      await oldChart.promise;
    });

    expect(screen.getByText("New run")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "OLD" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Trades" }));
    expect(screen.queryByText("OLD TRADE")).not.toBeInTheDocument();
  });

  it("exposes run status and tab state while keeping the trades table scrollable", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "accessible",
      prompt: "Accessible run",
      trade_log: [{
        time: "2026-07-29",
        code: "AAPL",
        side: "BUY",
        price: "200",
        qty: "2",
        reason: "signal",
      }],
    });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/accessible");

    await screen.findByText("Accessible run");
    expect(screen.getByText("Completed")).toHaveClass("sr-only");
    expect(screen.getByRole("heading", { level: 1, name: "accessible" })).toHaveClass("text-2xl", "font-semibold");
    expect(screen.getByRole("tablist")).toBeInTheDocument();

    const chartTab = screen.getByRole("tab", { name: "Chart" });
    const tradesTab = screen.getByRole("tab", { name: "Trades" });
    expect(chartTab).toHaveAttribute("aria-selected", "true");
    expect(chartTab).toHaveClass("font-medium");
    expect(tradesTab).toHaveAttribute("aria-selected", "false");

    fireEvent.click(tradesTab);

    expect(tradesTab).toHaveAttribute("aria-selected", "true");
    expect(tradesTab).toHaveClass("font-medium");
    const table = screen.getByRole("table");
    expect(table.parentElement).toHaveClass("overflow-x-auto", "rounded-xl", "border");
    expect(screen.getByRole("columnheader", { name: "Time" })).toHaveClass("ps-4");
  });

  it("pads and scroll-wraps run-card key/value and artifact tables", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "card",
      prompt: "Run card",
      run_card: {
        backtest: { engine: "vectorized" },
        artifacts: [{ path: "artifacts/result.json", size_bytes: 42, sha256: "abc123" }],
      } as NonNullable<RunData["run_card"]>,
    });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/card");

    await screen.findByText("Run card");
    fireEvent.click(screen.getByRole("tab", { name: "Run Card" }));

    const keyCell = await screen.findByText("engine");
    expect(keyCell).toHaveClass("ps-4");
    expect(keyCell.closest("table")?.parentElement).toHaveClass("overflow-x-auto");
    expect(screen.getByRole("columnheader", { name: "Path" })).toHaveClass("ps-4");
    expect(screen.getByText("artifacts/result.json")).toHaveClass("ps-4");
  });
});

  it("renders the Portfolio Studio tab from risk_xray and rebalance_notes payloads", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "studio-run",
      prompt: "Studio run",
      risk_xray: {
        inputs: { symbols: ["AAPL", "MSFT"], weights: { AAPL: 0.6, MSFT: 0.4 }, aligned_days: 60 },
        concentration: { hhi: 0.52, effective_n: 1.9 },
        volatility: { annualized_vol: 0.22 },
        drawdown: { max_drawdown: -0.11 },
      },
      rebalance_notes: {
        rebalances: [
          { date: "2026-02-02", turnover: 0.35, entries: [{ code: "NVDA", to: 0.6 }], exits: [], top_moves: [] },
        ],
        summary: { rebalance_count: 1, turnover_total: 0.35, turnover_mean: 0.35, turnover_max: 0.35, largest_rebalance_date: "2026-02-02" },
      },
    });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/studio-run");

    await screen.findByText("Studio run");
    fireEvent.click(screen.getByRole("tab", { name: "Portfolio Studio" }));

    expect(await screen.findByText("Risk X-Ray")).toBeInTheDocument();
    expect(screen.getByText("0.520")).toBeInTheDocument();
    expect(screen.getByText("22.0%")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("Rebalance Notes")).toBeInTheDocument();
    // the date shows up twice: once in the rebalances table, once in the summary card
    expect(screen.getAllByText("2026-02-02")).toHaveLength(2);
    // 35.0% shows up three times: the table row plus the mean and max summary cards
    expect(screen.getAllByText("35.0%")).toHaveLength(3);
  });

  it("hides the Portfolio Studio tab when the payloads are absent", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "plain-run",
      prompt: "Plain run",
      trade_log: [],
    });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/plain-run");

    await screen.findByText("Plain run");
    expect(screen.queryByRole("tab", { name: "Portfolio Studio" })).not.toBeInTheDocument();
  });
