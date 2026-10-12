import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { SourcePrioritySettings } from "@/components/settings/SourcePrioritySettings";
import { toast } from "sonner";

const apiMock = vi.hoisted(() => ({
  getDataSourceSettings: vi.fn(),
  updateDataSourceSettings: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: apiMock,
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  },
}));

const A_SHARE_DEFAULT = ["tencent", "mootdx", "eastmoney", "baostock", "akshare", "tushare", "local"];
const CRYPTO_DEFAULT = ["okx", "binance", "ccxt", "yfinance", "local"];
const FOREX_DEFAULT = ["mt5", "akshare", "yfinance", "local"];

function sourceOrders(overrides: Record<string, string[]> = {}) {
  const base: Array<[string, string[]]> = [
    ["a_share", A_SHARE_DEFAULT],
    ["crypto", CRYPTO_DEFAULT],
    ["forex", FOREX_DEFAULT],
  ];
  return base.map(([market, order]) => ({
    market,
    env_var: `MARKET_DATA_ORDER_${market.toUpperCase()}`,
    default_order: order,
    effective_order: overrides[market] ?? order,
    override: overrides[market] ?? null,
    override_invalid: false,
  }));
}

function dataSourceSettings(overrides: Record<string, string[]> = {}) {
  return {
    tushare_token_configured: true,
    baostock_supported: true,
    baostock_installed: true,
    baostock_message: "BaoStock available",
    env_path: "agent/.env",
    source_orders: sourceOrders(overrides),
  };
}

describe("SourcePrioritySettings", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    window.localStorage.clear();
    apiMock.getDataSourceSettings.mockReset();
    apiMock.updateDataSourceSettings.mockReset();
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
    apiMock.getDataSourceSettings.mockResolvedValue(dataSourceSettings());
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the default order for the first market with boundary-disabled reordering", async () => {
    render(<SourcePrioritySettings />);

    expect(await screen.findByText("Data Source Priority")).toBeInTheDocument();
    // a_share is the first market: its default head renders as a row.
    expect(screen.getByText("tencent")).toBeInTheDocument();
    expect(screen.getByText("tushare")).toBeInTheDocument();
    // First row cannot move up, last row cannot move down.
    expect(screen.getByRole("button", { name: "Move up: tencent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move down: local" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move up: tushare" })).toBeEnabled();
    // Default badge — nothing customized yet.
    expect(screen.getByText("Default")).toBeInTheDocument();
    // Adjustment-caliber caveat is surfaced next to the setting (see PR review).
    expect(screen.getByText(/returned adjustment\/provenance/)).toBeInTheDocument();
  });

  it("sends all markets on save: reordered draft as order, default-equal as null", async () => {
    render(<SourcePrioritySettings />);

    await screen.findByText("tencent");
    // Move tushare up one slot (akshare <-> tushare swap).
    fireEvent.click(screen.getByRole("button", { name: "Move up: tushare" }));
    // The active market now shows a Custom badge.
    expect(screen.getByText("Custom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMock.updateDataSourceSettings).toHaveBeenCalledTimes(1));
    expect(apiMock.updateDataSourceSettings).toHaveBeenCalledWith({
      source_orders: [
        {
          market: "a_share",
          order: ["tencent", "mootdx", "eastmoney", "baostock", "tushare", "akshare", "local"],
        },
        { market: "crypto", order: null },
        { market: "forex", order: null },
      ],
    });
  });

  it("reset restores the default order and saves null (clearing saved residue)", async () => {
    // An override is already in effect from a previous save.
    apiMock.getDataSourceSettings.mockResolvedValue(
      dataSourceSettings({
        a_share: ["tushare", "tencent", "mootdx", "eastmoney", "baostock", "akshare", "local"],
      }),
    );
    render(<SourcePrioritySettings />);

    await screen.findByText("tushare");
    expect(screen.getByText("Custom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(screen.getByText("Default")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMock.updateDataSourceSettings).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateDataSourceSettings.mock.calls[0][0];
    expect(payload.source_orders.find((e: { market: string }) => e.market === "a_share").order).toBeNull();
  });

  it("switches markets via the selector and edits that market's order", async () => {
    render(<SourcePrioritySettings />);

    await screen.findByText("tencent");
    fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
    expect(screen.getByText("okx")).toBeInTheDocument();
    expect(screen.queryByText("tencent")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Move up: yfinance" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMock.updateDataSourceSettings).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateDataSourceSettings.mock.calls[0][0];
    expect(payload.source_orders.find((e: { market: string }) => e.market === "crypto").order).toEqual([
      "okx", "binance", "yfinance", "ccxt", "local",
    ]);
  });

  it("shows an error toast and message when the save is rejected", async () => {
    apiMock.updateDataSourceSettings.mockRejectedValue(
      new Error("Invalid source order for crypto: must be a permutation of the default chain"),
    );
    render(<SourcePrioritySettings />);

    await screen.findByText("tencent");
    fireEvent.click(screen.getByRole("button", { name: "Move up: tushare" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0][0]).toContain("permutation");
    expect(
      await screen.findByText(/must be a permutation of the default chain/),
    ).toBeInTheDocument();
  });

  it("warns when a persisted override is invalid", async () => {
    const settings = dataSourceSettings();
    settings.source_orders = settings.source_orders.map((entry) =>
      entry.market === "a_share"
        ? { ...entry, effective_order: A_SHARE_DEFAULT, override: ["tushare"], override_invalid: true }
        : entry,
    );
    apiMock.getDataSourceSettings.mockResolvedValue(settings);

    render(<SourcePrioritySettings />);

    expect(
      await screen.findByText(/MARKET_DATA_ORDER_A_SHARE is invalid/),
    ).toBeInTheDocument();
  });
});
