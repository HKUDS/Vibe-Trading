import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { api } from "@/lib/api";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
import type { OptionsChainResponse } from "@/lib/options";
import { OptionsChainTable } from "../OptionsChainTable";

vi.mock("@/lib/api", () => ({ api: { getOptionsChain: vi.fn() } }));

const chain: OptionsChainResponse = {
  ok: true, market: "us", source: "yahoo", data: {
    ticker: "AAPL", expiration: 1794528000, expirations: [1794528000],
    underlying_price: 100, atm_strike: 100, calls_count: 0, puts_count: 0,
    calls: [], puts: [],
  },
};

beforeEach(async () => {
  clearAnalysisState("options-chain");
  vi.resetAllMocks();
  await i18n.changeLanguage("en");
});

afterEach(async () => { await act(async () => { await i18n.changeLanguage("en"); }); });

it.each(["success", "failure"])("finishes a pending refresh after a language change (%s)", async (outcome) => {
  let complete!: (response: OptionsChainResponse) => void;
  vi.mocked(api.getOptionsChain).mockResolvedValueOnce(chain)
    .mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
  const view = render(<OptionsChainTable />);
  await screen.findByText(i18n.t("options.chain.noData"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("options.chain.load") }));
  await waitFor(() => expect(api.getOptionsChain).toHaveBeenCalledTimes(2));
  await act(async () => { await i18n.changeLanguage("zh-CN"); });
  await screen.findByRole("button", { name: "加载" });
  await act(async () => { complete(outcome === "success" ? chain : { ok: false, error: "offline" }); });
  expect(screen.queryByLabelText(i18n.t("options.chain.loading"))).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: i18n.t("options.chain.load") })).toBeEnabled();
  expect(api.getOptionsChain).toHaveBeenCalledTimes(2);
  if (outcome === "failure") expect(screen.getByText("offline")).toBeInTheDocument();
  view.unmount();
});


it("ignores a late response after unmount instead of overwriting a new chain", async () => {
  let complete!: (response: OptionsChainResponse) => void;
  vi.mocked(api.getOptionsChain)
    .mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }))
    .mockResolvedValueOnce({ ...chain, data: { ...chain.data!, ticker: "MSFT" } });
  const oldView = render(<OptionsChainTable />);
  await waitFor(() => expect(api.getOptionsChain).toHaveBeenCalledTimes(1));
  oldView.unmount();
  render(<OptionsChainTable />);
  await screen.findByText(/MSFT/);
  await act(async () => { complete(chain); });
  expect(screen.getByText(/MSFT/)).toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem("vibe-analysis-v1:options-chain")!).data.ticker).toBe("MSFT");
});
