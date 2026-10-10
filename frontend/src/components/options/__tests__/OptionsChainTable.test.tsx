import { render, screen, waitFor } from "@testing-library/react";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
import { api } from "@/lib/api";
import { OptionsChainTable } from "../OptionsChainTable";
import type { OptionsChainResponse, OptionsContractRow } from "@/lib/options";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { getOptionsChain: vi.fn() } }));

function chain(strikes: number[], atm: number | null): OptionsChainResponse {
  return {
    ok: true, market: "us", source: "yahoo", data: {
      ticker: "AAPL", expiration: 1750000000, expirations: [1750000000],
      underlying_price: atm === null ? null : 337.4, atm_strike: atm,
      calls_count: strikes.length, puts_count: 0, puts: [],
      calls: strikes.map((strike) => ({ contract_symbol: `call-${strike}`, strike,
        last_price: null, bid: null, ask: null, volume: null, open_interest: null,
        implied_volatility: null, in_the_money: false, expiration: 1750000000,
      } satisfies OptionsContractRow)),
    },
  };
}

beforeEach(() => clearAnalysisState("options-chain"));
afterEach(() => vi.clearAllMocks());

it("marks the source-derived ATM strike instead of the simulator's default 100", async () => {
  vi.mocked(api.getOptionsChain).mockResolvedValue(chain([100, 330, 337, 340], 337));
  render(<OptionsChainTable />);
  const badge = await screen.findByText("options.chain.atm");
  expect(badge.closest("td")).toHaveTextContent("337");
});

it.each([
  ["missing quote", chain([100, 330, 337, 340], null)],
  ["ATM outside the displayed row cap", chain([100, 110, 120], 337)],
])("does not invent an ATM badge when %s", async (_name, response) => {
  vi.mocked(api.getOptionsChain).mockResolvedValue(response);
  render(<OptionsChainTable />);
  await waitFor(() => expect(screen.getByText("100")).toBeInTheDocument());
  expect(screen.queryByText("options.chain.atm")).not.toBeInTheDocument();
});
