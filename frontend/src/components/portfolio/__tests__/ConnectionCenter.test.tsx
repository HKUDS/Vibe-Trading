import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionCenter } from "@/components/portfolio/ConnectionCenter";
import { api, type LocalConnection } from "@/lib/api";
import i18n from "@/i18n";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getConnections: vi.fn(),
      getConnectionAccounts: vi.fn(),
      selectConnectionAccount: vi.fn(),
    },
  };
});

const mocked = api as unknown as {
  getConnections: ReturnType<typeof vi.fn>;
  getConnectionAccounts: ReturnType<typeof vi.fn>;
  selectConnectionAccount: ReturnType<typeof vi.fn>;
};

function robinhood(accountRef: string): LocalConnection {
  return {
    id: "robinhood-live",
    profile_id: "robinhood-live-mcp-readonly",
    label: "Robinhood",
    account_ref: accountRef,
    account_selection_required: true,
    connector: "robinhood",
    environment: "live",
    transport: "remote_mcp",
    readonly: true,
    capabilities: ["account.read", "positions.read"],
    supports_reconnect: true,
    credential_fields: [],
    credential_status: {},
    credentials_configured: false,
    portfolio_compatibility: { level: "experimental", contract_version: 1, asset_scope: "stocks_etfs", note: "" },
  };
}

function renderCenter(connection: LocalConnection, onChanged = vi.fn().mockResolvedValue(undefined)) {
  mocked.getConnections.mockResolvedValue({
    status: "ok",
    connections: [connection],
    profiles: [],
    plugin_directory: "/tmp/connectors",
  });
  render(<ConnectionCenter open onClose={() => undefined} onChanged={onChanged} />);
  return onChanged;
}

describe("ConnectionCenter account selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getConnectionAccounts.mockResolvedValue({
      status: "ok",
      connection_id: "robinhood-live",
      account_ref: "",
      accounts: [
        { account_ref: "5QR12345", label: "Main ····2345", is_default: true, agentic_allowed: true, deactivated: false },
        { account_ref: "5QR55555", label: "Old ····5555", is_default: false, agentic_allowed: true, deactivated: true },
      ],
    });
    mocked.selectConnectionAccount.mockResolvedValue({ status: "ok", connection: robinhood("5QR12345") });
  });

  it("warns that an unscoped connection reads nothing", async () => {
    renderCenter(robinhood(""));

    expect(await screen.findByText(i18n.t("portfolio.connections.accountNone"))).toBeInTheDocument();
  });

  it("picks from the broker's list with nothing preselected and saves the choice", async () => {
    const onChanged = renderCenter(robinhood(""));

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("portfolio.connections.accountLoad") }));
    const select = await screen.findByLabelText(i18n.t("portfolio.connections.accountPicker"));
    const save = screen.getByRole("button", { name: i18n.t("portfolio.connections.accountSave") });

    expect(select).toHaveValue("");
    expect(save).toBeDisabled();
    const deactivated = within(select).getByRole("option", { name: /Old ····5555/ });
    expect(deactivated).toBeDisabled();

    fireEvent.change(select, { target: { value: "5QR12345" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(mocked.selectConnectionAccount).toHaveBeenCalledWith("robinhood-live", "5QR12345"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("shows the selected account by its last four digits", async () => {
    renderCenter(robinhood("5QR12345"));

    expect(
      await screen.findByText(i18n.t("portfolio.connections.accountCurrent", { last4: "2345" })),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("portfolio.connections.accountChange") })).toBeInTheDocument();
  });

  it("reports an account list the broker could not return", async () => {
    mocked.getConnectionAccounts.mockRejectedValue(new Error("token expired"));
    renderCenter(robinhood(""));

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("portfolio.connections.accountLoad") }));

    expect(await screen.findByRole("alert")).toHaveTextContent("token expired");
    expect(mocked.selectConnectionAccount).not.toHaveBeenCalled();
  });
});
