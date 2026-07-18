import { act, fireEvent, render, screen } from "@testing-library/react";
import { Runtime } from "../Runtime";
import type { LiveBrokerStatus, LiveStatus } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getLiveStatus: vi.fn(),
  verifyConnector: vi.fn(),
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

function makeLongbridgeStatus(
  authOverrides: Partial<LiveBrokerStatus["auth"]> = {},
): LiveStatus {
  return makeStatus({
    brokers: [
      {
        auth: {
          broker: "longbridge",
          oauth_token_present: false,
          is_live_broker: false,
          profile_id: "longbridge-live-sdk-readonly",
          transport: "broker_sdk",
          configured: true,
          sdk_installed: true,
          readonly: true,
          capabilities: ["account.read", "positions.read", "orders.read", "quotes.read", "history.read"],
          ...authOverrides,
        },
        runner: {
          broker: "longbridge",
          alive: false,
          last_tick: null,
          last_tick_age_seconds: null,
        },
        mandate: null,
        halted: false,
      },
    ],
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("Runtime page", () => {
  beforeEach(() => {
    apiMock.getLiveStatus.mockReset();
    apiMock.verifyConnector.mockReset();
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

  it("keeps the newest live status when an older request resolves later", async () => {
    const first = deferred<LiveStatus>();
    const second = deferred<LiveStatus>();
    apiMock.getLiveStatus
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    render(<Runtime />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await act(async () => {
      second.resolve(makeStatus({ global_halted: true, brokers: [] }));
      await second.promise;
    });
    expect(await screen.findByText("Halted")).toBeInTheDocument();

    await act(async () => {
      first.resolve(makeStatus());
      await first.promise;
    });

    expect(screen.getByText("Halted")).toBeInTheDocument();
    expect(screen.queryByText("paper")).not.toBeInTheDocument();
  });

  it("aborts an in-flight status request on unmount", () => {
    const pending = deferred<LiveStatus>();
    apiMock.getLiveStatus.mockReturnValue(pending.promise);

    const { unmount } = render(<Runtime />);
    const signal = apiMock.getLiveStatus.mock.calls[0][0] as AbortSignal;

    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(false);

    unmount();

    expect(signal.aborted).toBe(true);
  });

  it("renders sub-minute mandate expiry as seconds", async () => {
    const baseStatus = makeStatus();
    const expiresAt = new Date(Date.now() + 45_000).toISOString();
    apiMock.getLiveStatus.mockResolvedValue(makeStatus({
      brokers: [
        {
          ...baseStatus.brokers[0],
          mandate: {
            ...baseStatus.brokers[0].mandate!,
            expires_at: expiresAt,
          },
        },
      ],
    }));

    render(<Runtime />);

    expect(await screen.findByText("45s")).toBeInTheDocument();
  });

  it("shows exact missing Longbridge variable names without rendering secret inputs", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      configured: false,
      connection_state: "not_configured",
      error_code: "credentials_missing",
    }));

    render(<Runtime />);

    expect(await screen.findByText("Not configured")).toBeInTheDocument();
    expect(screen.getByText("LONGBRIDGE_APP_KEY")).toBeInTheDocument();
    expect(screen.getByText("LONGBRIDGE_APP_SECRET")).toBeInTheDocument();
    expect(screen.getByText("LONGBRIDGE_ACCESS_TOKEN")).toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("renders a verify action when Longbridge is ready", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "ready",
    }));

    render(<Runtime />);

    expect(await screen.findByText("Ready to verify")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verify connection" })).toBeEnabled();
  });

  it.each([
    {
      name: "ready",
      auth: { connection_state: "ready" },
      stateLabel: "Ready to verify",
    },
    {
      name: "error",
      auth: { connection_state: "error", error_code: "authentication_failed" },
      stateLabel: "Connection failed",
    },
    {
      name: "missing connection state",
      auth: { connection_state: undefined, configured: true },
      stateLabel: "Status unavailable",
    },
  ])("does not advertise read-only access when the SDK state is $name", async ({ auth, stateLabel }) => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus(auth));

    render(<Runtime />);

    expect(await screen.findByText(stateLabel)).toBeInTheDocument();
    expect(screen.queryByText("Connected · Read-only")).not.toBeInTheDocument();
    expect(screen.queryByText(/read-only profile/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/· read-only$/)).not.toBeInTheDocument();
    expect(screen.getByText("Account, positions, open orders, quotes, history · access unknown")).toBeInTheDocument();
  });

  it.each([undefined, true])(
    "keeps an SDK response without connection state neutral when configured is %s",
    async (configured) => {
      apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
        connection_state: undefined,
        configured,
      }));

      render(<Runtime />);

      expect(await screen.findByText("Status unavailable")).toBeInTheDocument();
      expect(screen.queryByText("Ready to verify")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Verify connection" })).not.toBeInTheDocument();
    },
  );

  it.each([true, false, null])(
    "renders connected Longbridge as read-only when configured is %s",
    async (configured) => {
      apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
        connection_state: "connected",
        configured,
        credential_source: "runtime_file",
        environment_identity: "config_declared",
      }));

      render(<Runtime />);

      expect(await screen.findByText("Connected · Read-only")).toBeInTheDocument();
      expect(screen.getByText("Authorized").parentElement?.parentElement).toHaveTextContent("1");
      expect(screen.getByText("Credential source")).toBeInTheDocument();
      expect(screen.getByText("runtime_file")).toBeInTheDocument();
      expect(screen.getByText("Config-declared")).toBeInTheDocument();
      expect(screen.getByText("SDK")).toBeInTheDocument();
      expect(screen.getByText("Account, positions, open orders, quotes, history · read-only")).toBeInTheDocument();
    },
  );

  it("keeps connected access neutral when read-only metadata is absent", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "connected",
      environment_identity: undefined,
      readonly: undefined,
      capabilities: undefined,
    }));

    render(<Runtime />);

    expect(await screen.findByText("Connected · Access unknown")).toBeInTheDocument();
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
    expect(screen.queryByText("Connected · Read-only")).not.toBeInTheDocument();
    expect(screen.queryByText("Config-declared")).not.toBeInTheDocument();
    expect(screen.queryByText("Account, positions, open orders, quotes, history · read-only")).not.toBeInTheDocument();
  });

  it.each([
    {
      name: "readonly metadata is missing",
      auth: { readonly: undefined },
    },
    {
      name: "the profile ID is missing",
      auth: { profile_id: undefined },
    },
    {
      name: "capability metadata is missing",
      auth: { capabilities: undefined },
    },
    {
      name: "the capability list is empty",
      auth: { capabilities: [] },
    },
    {
      name: "a write capability is present despite a readonly profile",
      auth: { readonly: true, capabilities: ["account.read", "orders.place"] },
    },
    {
      name: "a capability merely contains a read segment",
      auth: { readonly: true, capabilities: ["account.read", "orders.read.place"] },
    },
    {
      name: "the profile is not declared readonly",
      auth: { profile_id: "longbridge-live-trade", readonly: true },
    },
  ])("fails closed when $name", async ({ auth }) => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "connected",
      ...auth,
    }));

    render(<Runtime />);

    expect(await screen.findByText("Connected · Access unknown")).toBeInTheDocument();
    expect(screen.queryByText("Connected · Read-only")).not.toBeInTheDocument();
    expect(screen.queryByText(/read-only profile/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/· read-only$/)).not.toBeInTheDocument();
  });

  it("shows access unknown in the capability summary when capabilities are missing", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "connected",
      readonly: true,
      capabilities: undefined,
    }));

    render(<Runtime />);

    expect(await screen.findByText("Connected · Access unknown")).toBeInTheDocument();
    expect(screen.getByText("access unknown")).toBeInTheDocument();
  });

  it("shows access unknown without write names when all capabilities are write capabilities", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "connected",
      readonly: true,
      capabilities: ["orders.place"],
    }));

    render(<Runtime />);

    expect(await screen.findByText("Connected · Access unknown")).toBeInTheDocument();
    expect(screen.getByText("access unknown")).toBeInTheDocument();
    expect(screen.queryByText(/orders\.place/)).not.toBeInTheDocument();
  });

  it("does not advertise write capabilities in the capability summary", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "connected",
      readonly: true,
      capabilities: ["account.read", "orders.place"],
    }));

    render(<Runtime />);

    expect(await screen.findByText("Connected · Access unknown")).toBeInTheDocument();
    expect(screen.getByText("Account · access unknown")).toBeInTheDocument();
    expect(screen.queryByText(/orders\.place/)).not.toBeInTheDocument();
  });

  it("renders failed Longbridge diagnostics without displaying backend detail", async () => {
    apiMock.getLiveStatus.mockResolvedValue(makeLongbridgeStatus({
      connection_state: "error",
      error_code: "authentication_failed",
      error: "raw diagnostic must stay hidden",
    }));

    render(<Runtime />);

    expect(await screen.findByText("Connection failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(screen.getByText("authentication_failed")).toBeInTheDocument();
    expect(screen.getByText("Authentication failed. Check the configured credentials.")).toBeInTheDocument();
    expect(screen.queryByText("raw diagnostic must stay hidden")).not.toBeInTheDocument();
  });

  it("verifies once, disables the action while pending, then refreshes status", async () => {
    const verification = deferred<Record<string, unknown>>();
    apiMock.getLiveStatus
      .mockResolvedValueOnce(makeLongbridgeStatus({ connection_state: "ready" }))
      .mockResolvedValueOnce(makeLongbridgeStatus({ connection_state: "connected" }));
    apiMock.verifyConnector.mockReturnValueOnce(verification.promise);

    render(<Runtime />);

    const verifyButton = await screen.findByRole("button", { name: "Verify connection" });
    fireEvent.click(verifyButton);

    expect(apiMock.verifyConnector).toHaveBeenCalledTimes(1);
    expect(apiMock.verifyConnector).toHaveBeenCalledWith("longbridge-live-sdk-readonly");
    expect(verifyButton).toBeDisabled();
    fireEvent.click(verifyButton);
    expect(apiMock.verifyConnector).toHaveBeenCalledTimes(1);

    await act(async () => {
      verification.resolve({ connection_state: "connected" });
      await verification.promise;
    });

    expect(apiMock.getLiveStatus).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Connected · Read-only")).toBeInTheDocument();
  });

  it("retains IBKR and Robinhood OAuth status cards without SDK verify actions", async () => {
    const baseStatus = makeStatus();
    apiMock.getLiveStatus.mockResolvedValue(makeStatus({
      brokers: [
        {
          ...baseStatus.brokers[0],
          auth: {
            broker: "ibkr",
            oauth_token_present: true,
            is_live_broker: true,
            transport: "remote_mcp",
          },
        },
        {
          ...baseStatus.brokers[1],
          auth: {
            broker: "robinhood",
            oauth_token_present: false,
            is_live_broker: true,
            transport: "remote_mcp",
          },
        },
      ],
    }));

    render(<Runtime />);

    expect(await screen.findByText("ibkr")).toBeInTheDocument();
    expect(screen.getByText("robinhood")).toBeInTheDocument();
    expect(screen.getAllByText("Authorization")).toHaveLength(2);
    expect(screen.getAllByText("OAuth token")).toHaveLength(2);
    expect(screen.getByText("auth present")).toBeInTheDocument();
    expect(screen.getByText("auth missing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify connection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(apiMock.verifyConnector).not.toHaveBeenCalled();
  });
});
