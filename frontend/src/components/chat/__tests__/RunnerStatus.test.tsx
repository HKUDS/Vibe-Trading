import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RunnerStatus } from "../RunnerStatus";
import type { LiveBrokerStatus, LiveStatus } from "@/lib/api";
import i18n from "@/i18n";

const apiMock = vi.hoisted(() => ({
  authorizeLive: vi.fn(),
  startLiveRunner: vi.fn(),
  stopLiveRunner: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: apiMock };
});

function broker(
  name: string,
  auth: Partial<LiveBrokerStatus["auth"]> = {},
): LiveBrokerStatus {
  return {
    auth: {
      broker: name,
      oauth_token_present: false,
      is_live_broker: false,
      ...auth,
    },
    mandate: null,
    runner: { broker: name, alive: false, last_tick: null },
    halted: false,
  };
}

function status(brokers: LiveBrokerStatus[]): LiveStatus {
  return { global_halted: false, brokers };
}

describe("RunnerStatus compact connector panel", () => {
  beforeEach(() => {
    apiMock.authorizeLive.mockResolvedValue({
      broker: "test",
      connector_profile: "test-live-sdk-readonly",
      oauth_token_present: false,
      instruction: "Configure this connector.",
      note: "Read-only.",
    });
  });

  it("shows relevant connectors and hides an unconfigured connector", async () => {
    const user = userEvent.setup();
    render(
      <RunnerStatus
        status={status([
          broker("alpaca", { configured: false, connection_state: "not_configured", transport: "broker_sdk" }),
          broker("longbridge", { configured: true, connection_state: "connected", transport: "broker_sdk" }),
          broker("binance", { configured: true, connection_state: "ready", transport: "broker_sdk" }),
          broker("futu", { configured: true, connection_state: null, transport: "broker_sdk" }),
          broker("okx", { configured: true, connection_state: "error", transport: "broker_sdk" }),
          broker("ibkr", { oauth_token_present: true, is_live_broker: true, transport: "remote_mcp" }),
        ])}
        onRefresh={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /connector runtime/i }));

    expect(screen.queryByText("alpaca", { exact: false })).not.toBeInTheDocument();
    expect(screen.getByText("longbridge", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("binance", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("futu", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("okx", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("ibkr", { exact: false })).toBeInTheDocument();
  });

  it.each([false, null])(
    "keeps connected and ready connectors visible when configured is %s",
    async (configured) => {
      const user = userEvent.setup();
      render(
        <RunnerStatus
          status={status([
            broker("connected-sdk", { configured, connection_state: "connected", transport: "broker_sdk" }),
            broker("ready-sdk", { configured, connection_state: "ready", transport: "broker_sdk" }),
          ])}
          onRefresh={vi.fn()}
        />,
      );

      await user.click(screen.getByRole("button", { name: /connector runtime/i }));

      expect(screen.getByText("connected-sdk", { exact: false })).toBeInTheDocument();
      expect(screen.getByText("ready-sdk", { exact: false })).toBeInTheDocument();
    },
  );

  it("bounds the expanded connector list and enables internal vertical scrolling", async () => {
    const user = userEvent.setup();
    render(
      <RunnerStatus
        status={status([
          broker("longbridge", { configured: true, connection_state: "connected", transport: "broker_sdk" }),
        ])}
        onRefresh={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /connector runtime/i }));

    const list = screen.getByRole("region", { name: i18n.t("runnerStatus.configuredProfiles") });
    expect(list).toHaveClass("max-h-[min(70vh,36rem)]", "overflow-y-auto");
  });

  it("hides the compact control when every connector is irrelevant", () => {
    const { container } = render(
      <RunnerStatus
        status={status([
          broker("alpaca", { configured: false, connection_state: "not_configured", transport: "broker_sdk" }),
          broker("binance", { configured: false, connection_state: null, transport: "broker_sdk" }),
        ])}
        onRefresh={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
