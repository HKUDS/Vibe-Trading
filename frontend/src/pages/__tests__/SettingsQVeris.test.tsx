import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { QVerisSettings } from "@/components/settings/QVerisSettings";
import { Settings } from "../Settings";

const apiMock = vi.hoisted(() => ({
  getLLMSettings: vi.fn(),
  getDataSourceSettings: vi.fn(),
  getChannelStatus: vi.fn(),
  startChannels: vi.fn(),
  stopChannels: vi.fn(),
  updateLLMSettings: vi.fn(),
  updateDataSourceSettings: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: apiMock,
    isAuthRequiredError: vi.fn(() => false),
  };
});

vi.mock("@/lib/apiAuth", () => ({
  authHeaders: vi.fn(() => ({ Authorization: "Bearer local-test-key" })),
  getApiAuthKey: vi.fn(() => "local-test-key"),
  setApiAuthKey: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  },
}));

function llmSettings() {
  return {
    provider: "openrouter",
    model_name: "deepseek/deepseek-v3.2",
    base_url: "https://openrouter.ai/api/v1",
    api_key_env: "OPENROUTER_API_KEY",
    api_key_configured: false,
    api_key_required: true,
    temperature: 0.1,
    timeout_seconds: 120,
    max_retries: 2,
    reasoning_effort: "",
    sse_timeout_seconds: 300,
    env_path: "agent/.env",
    providers: [
      {
        name: "openrouter",
        label: "OpenRouter",
        api_key_env: "OPENROUTER_API_KEY",
        base_url_env: "OPENROUTER_BASE_URL",
        default_model: "deepseek/deepseek-v3.2",
        default_base_url: "https://openrouter.ai/api/v1",
        api_key_required: true,
        auth_type: "api_key",
      },
    ],
  };
}

function dataSourceSettings() {
  return {
    tushare_token_configured: false,
    baostock_supported: true,
    baostock_installed: true,
    baostock_message: "BaoStock available",
    env_path: "agent/.env",
  };
}

function channelStatus() {
  return {
    running: false,
    inbound_queue: 0,
    outbound_queue: 0,
    session_count: 0,
    channels: {},
  };
}

function qverisConfig(overrides = {}) {
  return {
    enabled: true,
    base_url: "https://qveris.ai/api/v1",
    api_key_masked: "sk-...8TI",
    mode: "paid",
    budget_credits_per_session: 50,
    configured: true,
    signup_url: "https://qveris.ai/?ref=from-api",
    invite_code: "INVITE-FROM-API",
    ...overrides,
  };
}

function qverisStatus(overrides = {}) {
  return {
    enabled: true,
    ok: true,
    error: null,
    remaining_credits: 123.45,
    recent: [
      {
        ts: "2026-07-07T01:02:03Z",
        tool_id: "sec_filings",
        cost: 1.25,
        charge_outcome: "charged",
      },
    ],
    signup_url: "https://qveris.ai/?ref=status",
    invite_code: "INVITE-FROM-STATUS",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockQVerisFetch(config = qverisConfig(), status = qverisStatus()) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/qveris/config" && init?.method === "PUT") {
      const payload = JSON.parse(String(init.body || "{}"));
      return jsonResponse({ ...config, ...payload, api_key_masked: payload.api_key ? "sk-...NEW" : config.api_key_masked });
    }
    if (path === "/qveris/config") return jsonResponse(config);
    if (path === "/qveris/status") return jsonResponse(status);
    return jsonResponse({ detail: `Unexpected path: ${path}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Settings QVeris card", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    window.localStorage.clear();
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    apiMock.getDataSourceSettings.mockResolvedValue(dataSourceSettings());
    apiMock.getChannelStatus.mockResolvedValue(channelStatus());
    apiMock.startChannels.mockResolvedValue(channelStatus());
    apiMock.stopChannels.mockResolvedValue(channelStatus());
  });

  afterEach(() => {
    cleanup();
    delete window.vibeDesktop;
    vi.unstubAllGlobals();
  });

  it("renders inside Settings and shows loaded config, balance, and recent usage", async () => {
    mockQVerisFetch();

    render(<Settings />);

    expect(await screen.findByText("QVeris Tool Marketplace")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("https://qveris.ai/api/v1")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("sk-...8TI")).toBeInTheDocument();
    expect(screen.getByText("123.45")).toBeInTheDocument();
    expect(screen.getByText("sec_filings")).toBeInTheDocument();
  });

  it("sends the configured PUT payload when saving with a new API key", async () => {
    const fetchMock = mockQVerisFetch(qverisConfig({ enabled: false, mode: "free" }), qverisStatus({ recent: [] }));
    render(<QVerisSettings />);

    // The base-URL input shows its default value before the config GET resolves,
    // so wait for the save button to leave its loading-disabled state instead.
    await waitFor(() => expect(screen.getByRole("button", { name: "Save QVeris settings" })).toBeEnabled());
    fireEvent.click(screen.getByLabelText("Enable paid QVeris route"));
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://example.test/qveris" } });
    fireEvent.change(screen.getByPlaceholderText("sk-...8TI"), { target: { value: "sk-new-key" } });
    fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "paid" } });
    fireEvent.change(screen.getByDisplayValue("50"), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Save QVeris settings" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/qveris/config", expect.objectContaining({ method: "PUT" })));
    const putCall = fetchMock.mock.calls.find(([path, init]) => String(path) === "/qveris/config" && init?.method === "PUT");
    expect(JSON.parse(String(putCall?.[1]?.body))).toEqual({
      enabled: true,
      base_url: "https://example.test/qveris",
      mode: "paid",
      budget_credits_per_session: 80,
      api_key: "sk-new-key",
    });
  });

  it("does not overwrite the saved API key when the key field is left blank", async () => {
    const fetchMock = mockQVerisFetch();
    render(<QVerisSettings />);

    // The base-URL input shows its default value before the config GET resolves,
    // so wait for the save button to leave its loading-disabled state instead.
    await waitFor(() => expect(screen.getByRole("button", { name: "Save QVeris settings" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save QVeris settings" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/qveris/config", expect.objectContaining({ method: "PUT" })));
    const putCall = fetchMock.mock.calls.find(([path, init]) => String(path) === "/qveris/config" && init?.method === "PUT");
    expect(JSON.parse(String(putCall?.[1]?.body))).not.toHaveProperty("api_key");
  });

  it("stores a desktop API key through safe storage and restarts the backend", async () => {
    const setCredential = vi.fn().mockResolvedValue({
      available: true,
      configured: ["QVERIS_API_KEY"],
      migrated: [],
    });
    const restartBackend = vi.fn().mockResolvedValue(true);
    window.vibeDesktop = {
      isDesktop: true,
      getCredentialStatus: vi.fn(),
      setCredential,
      restartBackend,
    };
    const fetchMock = mockQVerisFetch();
    render(<QVerisSettings />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save QVeris settings" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByPlaceholderText("sk-...8TI"), {
      target: { value: "sk-desktop-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save QVeris settings" }));

    await waitFor(() =>
      expect(setCredential).toHaveBeenCalledWith("QVERIS_API_KEY", "sk-desktop-key"),
    );
    const putCall = fetchMock.mock.calls.find(
      ([path, init]) => String(path) === "/qveris/config" && init?.method === "PUT",
    );
    expect(JSON.parse(String(putCall?.[1]?.body))).not.toHaveProperty("api_key");
    expect(restartBackend).toHaveBeenCalledTimes(1);
  });

  it("uses the signup href from the config response and renders the empty usage state", async () => {
    mockQVerisFetch(qverisConfig({ signup_url: "https://qveris.ai/?ref=config-response" }), qverisStatus({ recent: [] }));
    render(<QVerisSettings />);

    const signup = await screen.findByRole("link", { name: "Open signup" });
    expect(signup).toHaveAttribute("href", "https://qveris.ai/?ref=config-response");
    expect(screen.getByText("INVITE-FROM-API")).toBeInTheDocument();
    expect(screen.getByText("No recent usage")).toBeInTheDocument();
  });

  it("renders QVeris copy in English and Chinese through i18n", async () => {
    mockQVerisFetch(undefined, qverisStatus({ recent: [] }));
    const { unmount } = render(<QVerisSettings />);
    expect(await screen.findByText("QVeris Tool Marketplace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save QVeris settings" })).toBeInTheDocument();
    unmount();

    await i18n.changeLanguage("zh-CN");
    mockQVerisFetch(undefined, qverisStatus({ recent: [] }));
    render(<QVerisSettings />);
    expect(await screen.findByText("QVeris 工具市场")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存 QVeris 设置" })).toBeInTheDocument();
  });
});
