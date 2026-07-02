import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("Settings IM channels panel", () => {
  beforeEach(() => {
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    apiMock.getDataSourceSettings.mockResolvedValue(dataSourceSettings());
    apiMock.getChannelStatus.mockResolvedValue(channelStatus());
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
});
