import { fireEvent, render, screen } from "@testing-library/react";
import { Runtime } from "../Runtime";
import type { LiveStatus } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getLiveStatus: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));

function makeStatus(overrides: Partial<LiveStatus> = {}): LiveStatus {
  return {
    global_halted: false,
    brokers: [
      {
        auth: {
          broker: "paper",
          oauth_token_present: true,
          is_live_broker: true,
        },
        runner: {
          broker: "paper",
          alive: true,
          last_tick: null,
          last_tick_age_seconds: 5,
        },
        mandate: {
          broker: "paper",
          account_ref: "acct-1",
          created_at: "2026-06-12T00:00:00Z",
          expires_at: "2999-01-01T00:00:00Z",
          expires_in_seconds: 3600,
          expired: false,
          limits: {
            max_order_notional_usd: 750,
            max_total_exposure_usd: 2000,
            max_leverage: 1,
            max_trades_per_day: 4,
            allowed_instruments: ["equity"],
            account_funding_usd: 10000,
          },
        },
        halted: false,
      },
      {
        auth: {
          broker: "sandbox",
          oauth_token_present: false,
          is_live_broker: true,
        },
        runner: {
          broker: "sandbox",
          alive: false,
          last_tick: null,
          last_tick_age_seconds: null,
        },
        mandate: null,
        halted: false,
      },
    ],
    ...overrides,
  };
}

describe("Runtime page", () => {
  beforeEach(() => {
    apiMock.getLiveStatus.mockReset();
  });

  it("renders broker auth, runner, mandate, and risk state from live status", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeStatus());

    render(<Runtime />);

    expect(await screen.findByText("Live / Paper Runtime Status")).toBeInTheDocument();
    expect(screen.getByText("Clear")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();
    expect(screen.getByText("auth present")).toBeInTheDocument();
    expect(screen.getByText("runner alive")).toBeInTheDocument();
    expect(screen.getByText("runtime active")).toBeInTheDocument();
    expect(screen.getByText("acct-1")).toBeInTheDocument();
    expect(screen.getByText(/\$750\/order/)).toBeInTheDocument();
    expect(screen.getByText("sandbox")).toBeInTheDocument();
    expect(screen.getByText("auth missing")).toBeInTheDocument();
    expect(screen.getByText("dormant")).toBeInTheDocument();
  });

  it("fails closed when live status is unavailable", async () => {
    apiMock.getLiveStatus.mockRejectedValue(new Error("backend offline"));

    render(<Runtime />);

    expect(await screen.findByText("Runtime status unavailable")).toBeInTheDocument();
    expect(screen.getByText("backend offline")).toBeInTheDocument();
    expect(screen.getByText(/Treat connector runtime as unavailable/)).toBeInTheDocument();
  });

  it("refreshes by reading live status again", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeStatus());

    render(<Runtime />);
    await screen.findByText("paper");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(apiMock.getLiveStatus).toHaveBeenCalledTimes(2);
  });
});
