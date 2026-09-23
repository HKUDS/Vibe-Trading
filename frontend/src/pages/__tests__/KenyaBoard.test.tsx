import { fireEvent, render, screen, within } from "@testing-library/react";
import { KenyaBoard } from "../KenyaBoard";
import type { KenyaBoardResponse, KenyaBoardRow } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getKenyaBoard: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/KenyaBoardTreemap", () => ({
  KenyaBoardTreemap: ({ rows }: { rows: KenyaBoardRow[] }) => (
    <div data-testid="treemap">{rows.filter((r) => r.traded).length}</div>
  ),
}));

function row(over: Partial<KenyaBoardRow>): KenyaBoardRow {
  return {
    code: "SCOM",
    name: "Safaricom Plc Ord 0.05",
    isin: "KE1000001402",
    sector: "Telecommunication",
    close: 36.6,
    prev: 36.3,
    change: 0.3,
    change_pct: 0.8264,
    high: 36.8,
    low: 36.35,
    volume: 7_340_000,
    turnover: 268_644_000,
    hi52: 39.5,
    lo52: 25.8,
    traded: true,
    ...over,
  };
}

const BOARD: KenyaBoardResponse = {
  as_of: "2026-09-22",
  source: "nse_ke",
  source_url: "https://www.nse.co.ke/wp-content/uploads/22-SEP-26.pdf",
  breadth: { listed: 3, traded: 2, advancers: 1, decliners: 1, unchanged: 0 },
  rows: [
    row({}),
    row({
      code: "KUKZ", name: "Kakuzi Plc Ord.5.00", isin: "KE0000000281", sector: "Agricultural",
      close: 433, prev: 436.5, change: -3.5, change_pct: -0.8018, volume: 443, turnover: 191_819,
    }),
    row({
      code: "KPLC-P4", name: "Kenya Power & Lighting Ltd 4% Pref 20.00", isin: "KE0000000356",
      sector: "Energy & Petroleum", close: 5.26, prev: 5.26, change: null, change_pct: null,
      volume: 0, turnover: 0, traded: false,
    }),
  ],
};

describe("KenyaBoard page", () => {
  beforeEach(() => {
    apiMock.getKenyaBoard.mockReset();
    apiMock.getKenyaBoard.mockResolvedValue(BOARD);
  });

  it("renders the session, breadth and traded counters", async () => {
    render(<KenyaBoard />);
    expect(await screen.findByText("Close of 2026-09-22")).toBeInTheDocument();
    expect(apiMock.getKenyaBoard).toHaveBeenCalledWith(undefined);
    expect(screen.getByTestId("treemap")).toHaveTextContent("2");

    const table = screen.getByRole("table");
    expect(within(table).getByText("SCOM")).toBeInTheDocument();
    expect(within(table).getByText("KUKZ")).toBeInTheDocument();
    // Untraded counters are hidden until "Traded only" is cleared.
    expect(within(table).queryByText("KPLC-P4")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Traded only" }));
    expect(within(table).getByText("KPLC-P4")).toBeInTheDocument();
    expect(within(table).getByText("not traded")).toBeInTheDocument();
  });

  it("filters by code or name", async () => {
    render(<KenyaBoard />);
    await screen.findByText("Close of 2026-09-22");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search code or name" }), {
      target: { value: "kakuzi" },
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("KUKZ")).toBeInTheDocument();
    expect(within(table).queryByText("SCOM")).not.toBeInTheDocument();
  });

  it("shows the error and retries", async () => {
    apiMock.getKenyaBoard.mockRejectedValueOnce(new Error("No readable NSE price list"));
    render(<KenyaBoard />);
    expect(await screen.findByText("No readable NSE price list")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Close of 2026-09-22")).toBeInTheDocument();
  });
});
