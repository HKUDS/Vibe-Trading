import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
      saveConnectionEndpoint: vi.fn(),
      checkConnection: vi.fn(),
    },
  };
});

const mocked = api as unknown as {
  getConnections: ReturnType<typeof vi.fn>;
  getConnectionAccounts: ReturnType<typeof vi.fn>;
  selectConnectionAccount: ReturnType<typeof vi.fn>;
  saveConnectionEndpoint: ReturnType<typeof vi.fn>;
  checkConnection: ReturnType<typeof vi.fn>;
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

  it("keeps the original remote connection behavior while selecting an account", async () => {
    let finishAccounts!: (value: unknown) => void;
    mocked.getConnectionAccounts.mockImplementation(() => new Promise((resolve) => { finishAccounts = resolve; }));
    mocked.checkConnection.mockResolvedValue({ status: "ok", report: { status: "ok" } });
    const onChanged = renderCenter(robinhood(""));
    const test = await screen.findByRole("button", { name: i18n.t("portfolio.connections.test") });
    fireEvent.click(test);
    expect(await screen.findByRole("status")).toHaveTextContent("Robinhood");
    fireEvent.click(screen.getByRole("button", { name: i18n.t("portfolio.connections.accountLoad") }));
    expect(test).toBeEnabled();
    finishAccounts({ accounts: [{ account_ref: "5QR12345", label: "Main", deactivated: false }] });
    const select = await screen.findByLabelText(i18n.t("portfolio.connections.accountPicker"));
    fireEvent.change(select, { target: { value: "5QR12345" } });
    mocked.getConnections.mockResolvedValue({ status: "ok", connections: [robinhood("5QR12345")], profiles: [] });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("portfolio.connections.accountSave") }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.getByRole("status")).toHaveTextContent("Robinhood");
  });
});

function ibkr(): LocalConnection {
  return {
    ...robinhood(""),
    id: "ibkr-paper",
    profile_id: "ibkr-paper-local",
    label: "IBKR Paper",
    connector: "ibkr",
    environment: "paper",
    transport: "local_tws",
    account_selection_required: false,
    effective_endpoint: { host: "127.0.0.1", port: 7497 },
  };
}

describe("ConnectionCenter IBKR address", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.saveConnectionEndpoint.mockResolvedValue({ status: "ok" });
    mocked.checkConnection.mockResolvedValue({ status: "ok", report: { status: "ok" } });
  });

  it("saves the edited address before testing, without a separate save button", async () => {
    const connection = ibkr();
    const onChanged = renderCenter(connection);
    expect(await screen.findByLabelText("Host")).toHaveValue("127.0.0.1");
    expect(screen.getByLabelText("Port")).toHaveValue("7497");
    expect(screen.queryByRole("button", { name: /Save address|保存地址/ })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Host"), { target: { value: "host.docker.internal" } });
    fireEvent.change(screen.getByLabelText("Port"), { target: { value: "4002" } });
    expect(mocked.saveConnectionEndpoint).not.toHaveBeenCalled();
    mocked.getConnections.mockResolvedValue({ status: "ok", connections: [{ ...connection, effective_endpoint: { host: "host.docker.internal", port: 4002 } }], profiles: [] });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("portfolio.connections.test") }));

    await waitFor(() => expect(mocked.saveConnectionEndpoint).toHaveBeenCalledWith("ibkr-paper", { host: "host.docker.internal", port: 4002 }));
    await waitFor(() => expect(mocked.checkConnection).toHaveBeenCalledWith("ibkr-paper"));
    expect(mocked.saveConnectionEndpoint.mock.invocationCallOrder[0]).toBeLessThan(mocked.checkConnection.mock.invocationCallOrder[0]);
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent(i18n.t("portfolio.connections.testOk", { label: "IBKR Paper" }));
  });

  it.each(["", "0", "65536", "1.5"])("disables testing invalid port %s", async (port) => {
    renderCenter(ibkr());
    fireEvent.change(await screen.findByLabelText("Port"), { target: { value: port } });
    expect(screen.getByLabelText("Port")).toHaveValue(port);
    expect(screen.getByRole("button", { name: i18n.t("portfolio.connections.test") })).toBeDisabled();
    expect(mocked.checkConnection).not.toHaveBeenCalled();
  });

  it("keeps the draft and skips testing when saving fails", async () => {
    mocked.saveConnectionEndpoint.mockRejectedValue(new Error("address rejected"));
    await act(async () => { renderCenter(ibkr()); });
    fireEvent.change(await screen.findByLabelText("Host"), { target: { value: "gateway.local" } });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("portfolio.connections.test") }));
    expect(await screen.findByRole("alert")).toHaveTextContent("address rejected");
    expect(screen.getByLabelText("Host")).toHaveValue("gateway.local");
    expect(mocked.checkConnection).not.toHaveBeenCalled();
  });

  it("waits for persistence before testing and prevents duplicate clicks", async () => {
    let finishSave!: () => void;
    mocked.saveConnectionEndpoint.mockImplementation(() => new Promise<void>((resolve) => { finishSave = resolve; }));
    renderCenter(ibkr());
    const test = await screen.findByRole("button", { name: i18n.t("portfolio.connections.test") });
    fireEvent.click(test);
    expect(test).toBeDisabled();
    fireEvent.click(test);
    expect(mocked.saveConnectionEndpoint).toHaveBeenCalledTimes(1);
    expect(mocked.checkConnection).not.toHaveBeenCalled();
    finishSave();
    await waitFor(() => expect(mocked.checkConnection).toHaveBeenCalledTimes(1));
  });

  it("keeps the saved address when the subsequent connection test fails", async () => {
    const connection = ibkr();
    renderCenter(connection);
    fireEvent.change(await screen.findByLabelText("Port"), { target: { value: "4002" } });
    mocked.getConnections.mockResolvedValue({ status: "ok", connections: [{ ...connection, effective_endpoint: { host: "127.0.0.1", port: 4002 } }], profiles: [] });
    mocked.checkConnection.mockResolvedValue({ status: "ok", report: { status: "error", error: "gateway unavailable" } });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("portfolio.connections.test") }));
    expect(await screen.findByRole("status")).toHaveTextContent("gateway unavailable");
    expect(mocked.saveConnectionEndpoint).toHaveBeenCalledWith("ibkr-paper", { host: "127.0.0.1", port: 4002 });
    expect(screen.getByLabelText("Port")).toHaveValue("4002");
  });

  it("tests remote MCP connections without saving a socket address", async () => {
    renderCenter({ ...ibkr(), transport: "remote_mcp" });
    fireEvent.click(await screen.findByRole("button", { name: i18n.t("portfolio.connections.test") }));
    await waitFor(() => expect(mocked.checkConnection).toHaveBeenCalledWith("ibkr-paper"));
    expect(screen.queryByLabelText("Host")).not.toBeInTheDocument();
    expect(mocked.saveConnectionEndpoint).not.toHaveBeenCalled();
  });
});

describe("Futu socket configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.saveConnectionEndpoint.mockResolvedValue({ status: "ok" });
    mocked.checkConnection.mockResolvedValue({ status: "ok", report: { status: "ok" } });
  });

  it.each(["paper", "live"] as const)("shows original Futu %s defaults and saves before testing", async (environment) => {
    const connection: LocalConnection = {
      ...ibkr(), id: `futu-${environment}`, connector: "futu", environment,
      profile_id: environment === "paper" ? "futu-paper-sdk" : "futu-live-sdk-readonly",
      label: "Futu", transport: "broker_sdk", effective_endpoint: { host: "127.0.0.1", port: 11111 },
    };
    renderCenter(connection);
    expect(await screen.findByLabelText("Host")).toHaveValue("127.0.0.1");
    const port = screen.getByRole("textbox", { name: "Port" });
    expect(port).toHaveValue("11111");
    expect(port).toHaveAttribute("inputmode", "numeric");
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    fireEvent.wheel(port, { deltaY: -100 });
    expect(port).toHaveValue("11111");
    fireEvent.change(screen.getByLabelText("Host"), { target: { value: "host.docker.internal" } });
    fireEvent.change(port, { target: { value: "11112" } });
    mocked.getConnections.mockResolvedValue({ status: "ok", connections: [{ ...connection, effective_endpoint: { host: "host.docker.internal", port: 11112 } }], profiles: [] });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("portfolio.connections.test") }));
    await waitFor(() => expect(mocked.checkConnection).toHaveBeenCalledWith(connection.id));
    expect(mocked.saveConnectionEndpoint).toHaveBeenCalledWith(connection.id, { host: "host.docker.internal", port: 11112 });
    expect(mocked.saveConnectionEndpoint.mock.invocationCallOrder[0]).toBeLessThan(mocked.checkConnection.mock.invocationCallOrder[0]);
  });
});
