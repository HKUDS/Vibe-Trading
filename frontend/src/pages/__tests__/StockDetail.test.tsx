import { createMemoryRouter, RouterProvider } from "react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StockDetail } from "../StockDetail";

const apiMock = vi.hoisted(() => ({
  getStockDetail: vi.fn(),
  getStockInfo: vi.fn(),
  getStockBars: vi.fn(),
  getStockReports: vi.fn(),
  getStockIndustry: vi.fn(),
  getStockNews: vi.fn(),
  getStockFundFlow: vi.fn(),
  getStockTechnicalIndicators: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/CandlestickChart", () => ({
  CandlestickChart: ({ intraday, onSubChange }: { intraday?: boolean; onSubChange?: (sub: string) => void }) => (
    <div data-testid="stock-chart" data-intraday={String(Boolean(intraday))}>
      <button type="button" onClick={() => onSubChange?.("fundflow")}>资金流</button>
    </div>
  ),
}));

describe("StockDetail", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    apiMock.getStockDetail.mockReset();
    apiMock.getStockInfo.mockReset();
    apiMock.getStockBars.mockReset();
    apiMock.getStockReports.mockReset();
    apiMock.getStockIndustry.mockReset();
    apiMock.getStockNews.mockReset();
    apiMock.getStockFundFlow.mockReset();
    apiMock.getStockTechnicalIndicators.mockReset();
    apiMock.getStockInfo.mockResolvedValue({ symbol: "600519.SH", market: "a_share", profile: { name: "Test Stock", price: 100, change_pct: 1 }, financials: {} });
    apiMock.getStockBars.mockResolvedValue({ symbol: "600519.SH", market: "a_share", period: "1m", bars: [{ time: "2026-08-17 09:31", open: 99, high: 101, low: 98, close: 100, volume: 10 }] });
    apiMock.getStockReports.mockResolvedValue({ symbol: "600519.SH", market: "a_share", reports: [] });
    apiMock.getStockIndustry.mockResolvedValue({ symbol: "600519.SH", market: "a_share", industry: "", boards: [] });
    apiMock.getStockNews.mockResolvedValue({ items: [], page: 1, page_size: 20, has_more: false });
    apiMock.getStockFundFlow.mockResolvedValue({ ok: true, period: "daily", buckets: [], data: {} });
    apiMock.getStockTechnicalIndicators.mockResolvedValue({ ok: true, symbol: "600519.SH", interval: "1d", indicators: {} });
    apiMock.getStockDetail.mockResolvedValue({
      symbol: "600519.SH",
      market: "a_share",
      period: "1m",
      profile: { name: "Test Stock", price: 100, change_pct: 1 },
      financials: {},
      bars: [{ time: "2026-08-17 09:31", open: 99, high: 101, low: 98, close: 100, volume: 10 }],
      reports: [],
      news: [],
      updated_at: "2026-08-17T01:31:00Z",
    });
  });

  it("loads today's intraday view by default", async () => {
    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByTestId("stock-chart")).toHaveAttribute("data-intraday", "true");
    expect(apiMock.getStockInfo).toHaveBeenCalledWith("600519.SH");
    expect(apiMock.getStockBars).toHaveBeenCalledWith("600519.SH", "1m");
    await waitFor(() => expect(apiMock.getStockReports).toHaveBeenCalledWith("600519.SH"));
    expect(apiMock.getStockIndustry).toHaveBeenCalledWith("600519.SH");
  });

  it("loads US detail through the same independent sections", async () => {
    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/AAPL.US"] },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByTestId("stock-chart")).toHaveAttribute("data-intraday", "true");
    expect(apiMock.getStockInfo).toHaveBeenCalledWith("AAPL.US");
    expect(apiMock.getStockBars).toHaveBeenCalledWith("AAPL.US", "1m");
    await waitFor(() => expect(apiMock.getStockReports).toHaveBeenCalledWith("AAPL.US"));
    expect(apiMock.getStockIndustry).toHaveBeenCalledWith("AAPL.US");
    expect(apiMock.getStockDetail).not.toHaveBeenCalled();
  });

  it("omits unavailable metrics and lets available metrics reflow", async () => {
    apiMock.getStockInfo.mockResolvedValueOnce({
      symbol: "600519.SH",
      market: "a_share",
      profile: { name: "Test Stock", price: 100, change_pct: 1, pe_ttm: 0, total_shares: null },
      financials: { eps: 1.25, capital_reserve_ps: 0, period: "2026-06-30" },
    });
    apiMock.getStockIndustry.mockResolvedValueOnce({
      symbol: "600519.SH",
      market: "a_share",
      industry: "Technology",
      boards: [],
    });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByText("EPS")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.queryByText("Dynamic P/E")).not.toBeInTheDocument();
    expect(screen.queryByText("Capital reserve per share")).not.toBeInTheDocument();
    expect(screen.queryByText("Total shares")).not.toBeInTheDocument();
  });

  it("renders related news returned by the news endpoint", async () => {
    apiMock.getStockNews.mockResolvedValueOnce({
      items: [{ title: "Latest stock news", source: "Newswire", time: "2026-08-17 10:00:00", url: "https://example.test/news" }],
      page: 1,
      page_size: 20,
      has_more: false,
    });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByText("Latest stock news")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Latest stock news - original" })).toHaveAttribute("href", "https://example.test/news");
  });

  it("refreshes reports and news independently", async () => {
    apiMock.getStockNews.mockResolvedValue({ items: [], page: 1, page_size: 20, has_more: false });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getStockNews).toHaveBeenCalledTimes(1));

    await waitFor(() => expect(apiMock.getStockReports).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId("refresh-reports"));

    await waitFor(() => {
      expect(apiMock.getStockReports).toHaveBeenCalledTimes(2);
      expect(apiMock.getStockNews).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByTestId("refresh-news"));

    await waitFor(() => {
      expect(apiMock.getStockReports).toHaveBeenCalledTimes(2);
      expect(apiMock.getStockNews).toHaveBeenCalledTimes(2);
    });
  });

  it("loads only K-line data when changing the period", async () => {
    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);
    await waitFor(() => {
      expect(apiMock.getStockNews).toHaveBeenCalledTimes(1);
      expect(apiMock.getStockReports).toHaveBeenCalledTimes(1);
      expect(apiMock.getStockIndustry).toHaveBeenCalledTimes(1);
    });
    apiMock.getStockInfo.mockClear();
    apiMock.getStockBars.mockClear();
    apiMock.getStockReports.mockClear();
    apiMock.getStockIndustry.mockClear();
    apiMock.getStockNews.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /15/ }));

    await waitFor(() => expect(apiMock.getStockBars).toHaveBeenCalledWith("600519.SH", "15m"));
    expect(apiMock.getStockInfo).not.toHaveBeenCalled();
    expect(apiMock.getStockReports).not.toHaveBeenCalled();
    expect(apiMock.getStockIndustry).not.toHaveBeenCalled();
    expect(apiMock.getStockNews).not.toHaveBeenCalled();
  });

  it("requests bars only once when the backend refresh is still in progress", async () => {
    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);
    await waitFor(() => expect(apiMock.getStockIndustry).toHaveBeenCalledTimes(1));
    apiMock.getStockBars.mockClear();
    apiMock.getStockBars
      .mockResolvedValueOnce({
        symbol: "600519.SH",
        market: "a_share",
        period: "15m",
        bars: [],
        cache_status: "refreshing",
      });

    fireEvent.click(screen.getByRole("button", { name: /15/ }));
    await waitFor(() => expect(apiMock.getStockBars).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(apiMock.getStockBars).toHaveBeenCalledTimes(1);
  });

  it("refreshes each page block through its own endpoint", async () => {
    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);
    await waitFor(() => {
      expect(apiMock.getStockNews).toHaveBeenCalledTimes(1);
      expect(apiMock.getStockReports).toHaveBeenCalledTimes(1);
      expect(apiMock.getStockIndustry).toHaveBeenCalledTimes(1);
    });
    apiMock.getStockInfo.mockClear();
    apiMock.getStockBars.mockClear();
    apiMock.getStockReports.mockClear();
    apiMock.getStockIndustry.mockClear();
    apiMock.getStockNews.mockClear();

    fireEvent.click(screen.getByTestId("refresh-profile"));
    await waitFor(() => expect(apiMock.getStockInfo).toHaveBeenCalledWith("600519.SH"));
    expect(apiMock.getStockBars).not.toHaveBeenCalled();
    expect(apiMock.getStockIndustry).not.toHaveBeenCalled();
    expect(apiMock.getStockReports).not.toHaveBeenCalled();
    expect(apiMock.getStockNews).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("refresh-industry"));
    await waitFor(() => expect(apiMock.getStockIndustry).toHaveBeenCalledWith("600519.SH"));
    expect(apiMock.getStockBars).not.toHaveBeenCalled();
    expect(apiMock.getStockReports).not.toHaveBeenCalled();
    expect(apiMock.getStockNews).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("refresh-bars"));
    await waitFor(() => expect(apiMock.getStockBars).toHaveBeenCalledWith("600519.SH", "1m"));
    expect(apiMock.getStockReports).not.toHaveBeenCalled();
    expect(apiMock.getStockNews).not.toHaveBeenCalled();
  });

  it("places the industry refresh button beside the associated boards label", async () => {
    apiMock.getStockIndustry.mockResolvedValueOnce({
      symbol: "600519.SH",
      market: "a_share",
      industry: "Consumer",
      boards: [{ board_code: "BK001", board_name: "白酒" }],
    });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);

    const boardsLabel = await screen.findByText("Associated boards");
    const boardsHeader = boardsLabel.parentElement;
    expect(boardsHeader).toContainElement(screen.getByTestId("refresh-industry"));
  });

  it("does not render industry news even when the API includes it", async () => {
    apiMock.getStockIndustry.mockResolvedValueOnce({
      symbol: "600519.SH",
      market: "a_share",
      industry: "Consumer",
      boards: [],
      industry_news: [{ title: "Removed industry news" }],
    });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByText("Consumer")).toBeInTheDocument();
    expect(screen.queryByText("Removed industry news")).not.toBeInTheDocument();
  });

  it("loads fund flow only when the fund-flow subchart is selected", async () => {
    apiMock.getStockFundFlow.mockResolvedValueOnce({
      ok: true,
      period: "min",
      buckets: ["main", "small", "medium", "large", "super_large"],
      data: {
        "600519.SH": {
          symbol: "600519.SH",
          rows: [{ timestamp: "2026-08-17", main: 120000000, super_large: 80000000, large: 40000000, medium: -10000000, small: -110000000 }],
        },
      },
    });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);

    expect(apiMock.getStockFundFlow).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "资金流" }));
    expect(await screen.findByTestId("stock-chart")).toBeInTheDocument();
    expect(apiMock.getStockFundFlow).toHaveBeenCalledWith("600519.SH", "min", 30);
  });

  it("falls back to daily rows when the minute flow endpoint is empty", async () => {
    apiMock.getStockFundFlow
      .mockResolvedValueOnce({ ok: true, period: "min", buckets: [], data: {} })
      .mockResolvedValueOnce({
        ok: true,
        period: "daily",
        buckets: ["main"],
        data: {
          "600519.SH": {
            symbol: "600519.SH",
            rows: [{ timestamp: "2026-08-17", main: 120, super_large: 80, large: 40, medium: -10, small: -110 }],
          },
        },
      });

    const router = createMemoryRouter(
      [{ path: "/stocks/:symbol", element: <StockDetail /> }],
      { initialEntries: ["/stocks/600519.SH"] },
    );

    render(<RouterProvider router={router} />);
    fireEvent.click(await screen.findByRole("button", { name: "资金流" }));

    await waitFor(() => expect(apiMock.getStockFundFlow).toHaveBeenNthCalledWith(2, "600519.SH", "daily", 30));
  });

});
