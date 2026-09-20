import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Settings } from "../Settings";

const apiMock = vi.hoisted(() => ({
  getLLMSettings: vi.fn(),
  getDataSourceSettings: vi.fn(),
  getChannelStatus: vi.fn(),
  getChannelsConfigSchema: vi.fn(),
  getChannelsConfig: vi.fn(),
  updateChannelConfig: vi.fn(),
  testChannelConfig: vi.fn(),
  toggleChannelConfig: vi.fn(),
  listLLMModels: vi.fn(),
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
  getApiAuthKey: vi.fn(() => ""),
  setApiAuthKey: vi.fn(),
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

function channelStatus(overrides = {}) {
  return {
    running: false,
    inbound_queue: 0,
    outbound_queue: 0,
    session_count: 0,
    channels: {
      websocket: {
        name: "websocket",
        display_name: "WebSocket",
        configured: true,
        enabled: true,
        available: true,
        loaded: true,
        running: false,
        error: "",
        install_hint: "",
      },
      telegram: {
        name: "telegram",
        display_name: "Telegram",
        configured: true,
        enabled: false,
        available: false,
        loaded: false,
        running: false,
        error: "ModuleNotFoundError",
        install_hint: "pip install 'vibe-trading-ai[telegram]'",
      },
    },
    ...overrides,
  };
}

function channelsConfigSchema() {
  return {
    channels: [
      {
        name: "dingtalk",
        display_name: "DingTalk",
        available: true,
        enabled: false,
        install_hint: "",
        fields: [
          { key: "enabled", type: "boolean", secret: false, required: false, description: "Run this channel" },
          { key: "client_id", type: "string", secret: false, required: true, description: "Client ID (AppKey)" },
          { key: "client_secret", type: "string", secret: true, required: true, description: "Client Secret (AppSecret)" },
        ],
      },
      {
        name: "telegram",
        display_name: "Telegram",
        available: false,
        enabled: false,
        install_hint: "pip install 'vibe-trading-ai[telegram]'",
        fields: [
          { key: "enabled", type: "boolean", secret: false, required: false, description: "Run this channel" },
        ],
      },
    ],
  };
}

function channelsConfig() {
  return {
    channels: {
      dingtalk: { enabled: false, client_id: "", client_secret: "" },
      telegram: { enabled: false },
    },
  };
}

describe("Settings IM channels panel", () => {
  beforeEach(() => {
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    apiMock.getDataSourceSettings.mockResolvedValue(dataSourceSettings());
    apiMock.getChannelStatus.mockResolvedValue(channelStatus());
    apiMock.getChannelsConfigSchema.mockResolvedValue(channelsConfigSchema());
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig());
    apiMock.updateChannelConfig.mockResolvedValue({
      name: "dingtalk",
      enabled: false,
      config: { enabled: false, client_id: "dingid123", client_secret: "****t123" },
      applied: false,
      status: null,
    });
    apiMock.testChannelConfig.mockResolvedValue({
      name: "dingtalk",
      ok: false,
      reason: "invalid_credentials",
      detail: "HTTP 400: InvalidParameter",
    });
    apiMock.toggleChannelConfig.mockResolvedValue({
      name: "telegram",
      enabled: true,
      config: { enabled: true },
      applied: true,
      status: { enabled: true, running: false },
    });
    apiMock.listLLMModels.mockResolvedValue({
      provider: "openrouter",
      models: ["deepseek/deepseek-v3.2"],
      source: "default",
      warning_code: "api_key_required",
    });
    apiMock.startChannels.mockResolvedValue(channelStatus({ running: true }));
    apiMock.stopChannels.mockResolvedValue(channelStatus());
  });

  it("renders channel runtime status and refreshes it", async () => {
    render(<Settings />);

    expect(await screen.findByText("IM Channels")).toBeInTheDocument();
    expect(screen.getByText("websocket")).toBeInTheDocument();
    expect(screen.getByText("telegram")).toBeInTheDocument();
    expect(screen.getByText("pip install 'vibe-trading-ai[telegram]'")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(apiMock.getChannelStatus).toHaveBeenCalledTimes(2));
  });

  it("starts channels from the settings control surface", async () => {
    render(<Settings />);
    await screen.findByText("IM Channels");

    fireEvent.click(screen.getByRole("button", { name: "Start channels" }));

    await waitFor(() => expect(apiMock.startChannels).toHaveBeenCalledTimes(1));
  });

  it("still renders LLM and data source settings when channel status fails", async () => {
    apiMock.getChannelStatus.mockRejectedValue(
      new Error('Expected JSON from /channels/status, got text/html: <!doctype html>'),
    );

    render(<Settings />);

    expect(await screen.findByText("LLM Settings")).toBeInTheDocument();
    expect(screen.getByText("Data Source Settings")).toBeInTheDocument();
    expect(screen.getByText("IM Channels")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start channels" })).toBeDisabled();
  });

  it("renders SDK-managed provider authentication without editable transport fields", async () => {
    apiMock.getLLMSettings.mockResolvedValue({
      ...llmSettings(),
      provider: "copilot",
      model_name: "claude-sonnet-5",
      base_url: "https://api.githubcopilot.com",
      api_key_env: "COPILOT_GITHUB_TOKEN",
      api_key_required: false,
      providers: [
        {
          name: "copilot",
          label: "GitHub Copilot SDK",
          api_key_env: "COPILOT_GITHUB_TOKEN",
          base_url_env: "COPILOT_BASE_URL",
          default_model: "claude-sonnet-5",
          default_base_url: "https://api.githubcopilot.com",
          api_key_required: false,
          auth_type: "gh_cli",
          login_command: "gh auth login",
        },
      ],
    });

    render(<Settings />);

    expect(
      await screen.findByDisplayValue("https://api.githubcopilot.com"),
    ).toBeDisabled();
    const authStatus = screen.getByText(
      "This provider manages authentication. Run: gh auth login",
    );
    expect(authStatus.closest("label")?.querySelector("input")).toBeDisabled();
  });

  it("translates stable model-discovery warning codes in the frontend", async () => {
    render(<Settings />);
    await screen.findByText("LLM Settings");

    fireEvent.click(screen.getByRole("button", { name: "Load models" }));

    expect(await screen.findByText(
      "Enter or save this provider's API key to load its available models.",
    )).toBeInTheDocument();
  });

  it("saves DingTalk credentials from the channel config form", async () => {
    render(<Settings />);

    expect(await screen.findByText("Channel configuration")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));

    fireEvent.change(screen.getByLabelText("client_id"), { target: { value: "dingid123" } });
    fireEvent.change(screen.getByLabelText("client_secret"), { target: { value: "dingsecret123" } });
    fireEvent.click(screen.getByRole("button", { name: "Save credentials" }));

    await waitFor(() => expect(apiMock.updateChannelConfig).toHaveBeenCalledWith("dingtalk", {
      client_id: "dingid123",
      client_secret: "dingsecret123",
    }));
  });

  it("keeps the stored secret when the secret field is left empty", async () => {
    render(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: "Configure" }));
    fireEvent.change(screen.getByLabelText("client_id"), { target: { value: "dingid123" } });
    fireEvent.click(screen.getByRole("button", { name: "Save credentials" }));

    await waitFor(() => expect(apiMock.updateChannelConfig).toHaveBeenCalledWith("dingtalk", {
      client_id: "dingid123",
    }));
  });

  it("shows the honest failure reason from a DingTalk connection test", async () => {
    render(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: "Configure" }));
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    await waitFor(() => expect(apiMock.testChannelConfig).toHaveBeenCalledWith("dingtalk"));
    expect(await screen.findByText(/DingTalk rejected these credentials/)).toBeInTheDocument();
  });

  it("toggles a channel without touching its credentials", async () => {
    render(<Settings />);

    expect(await screen.findByText("Channel configuration")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Telegram Enabled" }));

    await waitFor(() => expect(apiMock.toggleChannelConfig).toHaveBeenCalledWith("telegram", true));
  });
});
