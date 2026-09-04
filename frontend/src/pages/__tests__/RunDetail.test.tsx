import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { RunDetail } from "../RunDetail";
import type { RunData } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getRun: vi.fn(),
  getRunCode: vi.fn(),
  getRunFactor: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/FactorResearchPanel", () => ({
  FactorResearchPanel: () => <div data-testid="factor-panel" />,
}));
vi.mock("@/components/charts/CandlestickChart", () => ({
  CandlestickChart: () => <div data-testid="candlestick-chart" />,
}));
vi.mock("@/components/charts/EquityChart", () => ({
  EquityChart: () => <div data-testid="equity-chart" />,
}));
vi.mock("@/components/charts/StrategyResearchDashboard", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/charts/StrategyResearchDashboard")>();
  return {
    ...actual,
    StrategyResearchDashboard: ({ run }: { run: RunData }) => <div data-testid="strategy-dashboard">{run.run_id}</div>,
  };
});

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
    apiMock.getRunFactor.mockReset();
  });

  it("presents a readable strategy title instead of promoting the run id", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "20260811_110751_32_d951c8",
      prompt: "回测 000001.SZ 在 2024 年的 20/50 日均线交叉策略。",
      chart_symbols: ["000001.SZ"],
      run_card: {
        backtest: { codes: ["000001.SZ"], start_date: "2024-01-01", end_date: "2024-12-31", engine: "daily" },
        data_sources: ["tencent"],
      },
    });
    apiMock.getRunCode.mockResolvedValueOnce({});

    renderRunDetail("/runs/20260811_110751_32_d951c8?view=dashboard");

    // The strategy name is report chrome derived from the prompt, so it follows
    // the UI language, not the prompt's. A Chinese prompt under an English UI
    // must not leak a Chinese title into an otherwise English report.
    expect(
      await screen.findByRole("heading", { name: "000001.SZ · 20/50-day moving-average crossover" })
    ).toBeInTheDocument();
    expect(screen.getByText("RUN 20260811_110751_32_d951c8")).toHaveClass("text-[10px]");
  });

  it("renders the derived strategy name in the active UI language", async () => {
    const i18n = (await import("@/i18n")).default;
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "zh-run",
      prompt: "回测 000001.SZ 在 2024 年的 20/50 日均线交叉策略。",
      chart_symbols: ["000001.SZ"],
    });
    apiMock.getRunCode.mockResolvedValueOnce({});
    const previous = i18n.language;
    await act(async () => {
      await i18n.changeLanguage("zh-CN");
    });
    try {
      renderRunDetail("/runs/zh-run?view=dashboard");
      expect(
        await screen.findByRole("heading", { name: "000001.SZ · 20/50 日均线交叉策略" })
      ).toBeInTheDocument();
    } finally {
      await act(async () => {
        await i18n.changeLanguage(previous);
      });
    }
  });

  it("opens the research dashboard when requested by the terminal report URL", async () => {
    apiMock.getRun.mockResolvedValue({ status: "success", run_id: "terminal-run", prompt: "MA strategy" });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/terminal-run?view=dashboard");

    expect(await screen.findByTestId("strategy-dashboard")).toHaveTextContent("terminal-run");
    expect(screen.getByRole("tab", { name: /dashboard/i })).toHaveAttribute("aria-selected", "true");
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

  it("collapses an expanded prompt when navigating to another run", async () => {
    const firstPrompt = "First run prompt\n".repeat(8).trim();
    const secondPrompt = "Second run prompt\n".repeat(8).trim();
    apiMock.getRun.mockImplementation((runId: string) => Promise.resolve({
      status: "success",
      run_id: runId,
      prompt: runId === "first" ? firstPrompt : secondPrompt,
    }));
    apiMock.getRunCode.mockResolvedValue({});

    const router = renderRunDetail("/runs/first");
    const expandButton = await screen.findByRole("button", { name: "Show full prompt" });
    const firstPromptElement = expandButton.previousElementSibling;
    expect(firstPromptElement).toHaveTextContent("First run prompt");
    expect(firstPromptElement).toHaveClass("line-clamp-3");
    expect(expandButton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(expandButton);
    expect(firstPromptElement).not.toHaveClass("line-clamp-3");
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    await act(async () => {
      await router.navigate("/runs/second");
    });

    const secondExpandButton = await screen.findByRole("button", { name: "Show full prompt" });
    const secondPromptElement = secondExpandButton.previousElementSibling;
    expect(secondPromptElement).toHaveTextContent("Second run prompt");
    expect(secondPromptElement).toHaveClass("line-clamp-3");
    expect(secondExpandButton).toHaveAttribute("aria-expanded", "false");
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
    expect(screen.getByRole("heading", { level: 1, name: "Portfolio · Accessible run" })).toHaveClass("text-xl", "font-semibold");
    expect(screen.getByText("RUN accessible")).toHaveClass("font-mono", "text-[10px]");
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

  it("renders the Factor Research tab from has_factor_artifacts and lazy-loads the report", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "factor-run",
      prompt: "Factor run",
      has_factor_artifacts: true,
    });
    apiMock.getRunCode.mockResolvedValue({});
    apiMock.getRunFactor.mockResolvedValue({
      exists: true,
      factors: [{
        name: "momentum_20d",
        path: "artifacts/factor_momentum_20d",
        ic_series: [{ date: "2024-01-02", ic: 0.03 }],
        ic_stats: { ic_mean: 0.03, ic_std: 0.02, ir: 1.5, ic_positive_ratio: 0.6, ic_count: 1 },
        group_equity: [{ date: "2024-01-02", Group_1: 1, Group_2: 1.01 }],
        n_groups: 2,
        long_short_spread: 0.01,
        group_final_equity: { Group_1: 1, Group_2: 1.01 },
      }],
      ic_correlation: null,
    });

    renderRunDetail("/runs/factor-run");

    await screen.findByText("Factor run");
    // The factor report is fetched lazily on tab open, never with the main run payload.
    expect(apiMock.getRunFactor).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: "Factor Research" }));

    expect(await screen.findByTestId("factor-panel")).toBeInTheDocument();
    expect(apiMock.getRunFactor).toHaveBeenCalledWith("factor-run");
  });

  it("hides the Factor Research tab when the run has no factor artifacts", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "no-factor-run",
      prompt: "No factor run",
      trade_log: [],
    });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/no-factor-run");

    await screen.findByText("No factor run");
    expect(screen.queryByRole("tab", { name: "Factor Research" })).not.toBeInTheDocument();
    expect(apiMock.getRunFactor).not.toHaveBeenCalled();
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
        summary: { target_change_count: 1, turnover_total: 0.35, turnover_mean: 0.35, turnover_max: 0.35, largest_rebalance_date: "2026-02-02", rebalance_executed_fills: 4, rebalance_realized_turnover: 0.2 },
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
    // execution evidence is shown separately from the requested count (#1275)
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("20.0%")).toBeInTheDocument();
  });

  it("renders the requested count from legacy rebalance_count for old artifacts", async () => {
    apiMock.getRun.mockResolvedValue({
      status: "success",
      run_id: "legacy-run",
      prompt: "Legacy run",
      rebalance_notes: {
        rebalances: [],
        summary: { rebalance_count: 7, turnover_total: 0.1, turnover_mean: 0.1, turnover_max: 0.1, largest_rebalance_date: "2026-02-02" },
      },
    });
    apiMock.getRunCode.mockResolvedValue({});

    renderRunDetail("/runs/legacy-run");

    await screen.findByText("Legacy run");
    fireEvent.click(screen.getByRole("tab", { name: "Portfolio Studio" }));
    await screen.findByText("Rebalance Notes");

    // old artifacts carry only rebalance_count; the fallback keeps them readable
    expect(screen.getByText("7")).toBeInTheDocument();
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
