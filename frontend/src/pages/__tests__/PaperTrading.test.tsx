import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PaperTrading } from "../PaperTrading";
import { paperApi } from "@/lib/api";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ paperApi: { list: vi.fn(), create: vi.fn(), advance: vi.fn(), history: vi.fn() } }));
const account = { id: "paper-1", label: "Example", market: "us", currency: "USD", start_on: "2026-10-20", last_date: null, revision: 7, account_state: { cash: 1000, positions: [] }, last_result: null } as const;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(paperApi.list).mockResolvedValue([{ ...account }]);
  vi.mocked(paperApi.history).mockResolvedValue([]);
});

test("sends the loaded revision and shows an in-band failure without claiming a saved ledger", async () => {
  vi.mocked(paperApi.advance).mockResolvedValue({ account: { ...account }, committed: false, result: { code: "PAPER_DATA_NOT_READY", message: "Await daily data" } });
  render(<PaperTrading />);
  await screen.findByRole("option", { name: "Example · USD" });
  fireEvent.change(screen.getByLabelText("paper.accounts"), { target: { value: "paper-1" } });
  fireEvent.change(await screen.findByLabelText("paper.date"), { target: { value: "2026-10-20" } });
  fireEvent.click(screen.getByRole("button", { name: "paper.advance" }));
  await waitFor(() => expect(paperApi.advance).toHaveBeenCalledWith("paper-1", { expected_revision: 7, to_date: "2026-10-20", orders: [] }));
  expect(await screen.findByRole("alert")).toHaveTextContent("PAPER_DATA_NOT_READY");
  expect(screen.getByRole("status")).toHaveTextContent("paper.notSaved");
  expect(screen.queryByText("paper.saved")).not.toBeInTheDocument();
});

test("preserves configurable initial ledger and next-session selection", async () => {
  vi.mocked(paperApi.create).mockResolvedValue({ ...account });
  render(<PaperTrading />);
  fireEvent.change(screen.getByLabelText("paper.label"), { target: { value: "My simulated account" } });
  fireEvent.change(screen.getByLabelText("paper.start"), { target: { value: "next_session" } });
  fireEvent.change(screen.getByLabelText(/paper.cash/), { target: { value: "2500" } });
  fireEvent.click(screen.getByRole("button", { name: "paper.addPosition" }));
  fireEvent.change(screen.getByLabelText("paper.symbol"), { target: { value: "AAPL.US" } });
  fireEvent.change(screen.getByLabelText("paper.quantity"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("paper.cost"), { target: { value: "100" } });
  fireEvent.click(screen.getByRole("button", { name: "paper.create" }));
  await waitFor(() => expect(paperApi.create).toHaveBeenCalledWith({ label: "My simulated account", market: "us", start: "next_session", account_state: { cash: 2500, positions: [{ symbol: "AAPL.US", qty: 5, avg_cost: 100 }] } }));
});
