import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { ApiError } from "@/lib/api";
import { ChannelSettings } from "@/components/settings/ChannelSettings";
import { toast } from "sonner";

const apiMock = vi.hoisted(() => ({
  getChannelStatus: vi.fn(),
  getChannelsConfig: vi.fn(),
  startChannels: vi.fn(),
  stopChannels: vi.fn(),
  putChannelConfig: vi.fn(),
  testChannel: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: apiMock,
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  },
}));

function channelStatus(overrides = {}) {
  return {
    running: false,
    inbound_queue: 0,
    outbound_queue: 0,
    session_count: 0,
    channels: {
      dingtalk: {
        name: "dingtalk",
        display_name: "DingTalk",
        configured: true,
        enabled: false,
        available: true,
        loaded: true,
        running: false,
        error: "",
        install_hint: "",
      },
    },
    ...overrides,
  };
}

function dingtalkEntry(overrides: Record<string, unknown> = {}) {
  return {
    display_name: "DingTalk",
    available: true,
    loaded: true,
    install_hint: "",
    error: "",
    supports_test: true,
    sdk_available: true,
    fields: [
      { key: "client_id", type: "text", secret: false, required: true, help_key: "settings.channels.fields.dingtalk.client_id" },
      { key: "client_secret", type: "password", secret: true, required: true, help_key: "settings.channels.fields.dingtalk.client_secret" },
      { key: "allow_from", type: "list", secret: false, required: false, help_key: "settings.channels.fields.dingtalk.allow_from" },
      { key: "group_user_isolation", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.dingtalk.group_user_isolation" },
    ],
    values: {
      enabled: false,
      client_id: "ding_appkey",
      allow_from: ["user-1"],
      group_user_isolation: false,
    },
    secrets: { client_secret: { set: true, masked: "****abcd" } },
    ...overrides,
  };
}

function qqEntry(overrides: Record<string, unknown> = {}) {
  return {
    display_name: "QQ",
    available: true,
    loaded: true,
    install_hint: "",
    error: "",
    supports_test: true,
    sdk_available: true,
    fields: [
      { key: "app_id", type: "text", secret: false, required: true, help_key: "settings.channels.fields.qq.app_id" },
      { key: "secret", type: "password", secret: true, required: true, help_key: "settings.channels.fields.qq.secret" },
      { key: "allow_from", type: "list", secret: false, required: false, help_key: "settings.channels.fields.qq.allow_from" },
      { key: "msg_format", type: "text", secret: false, required: false, help_key: "settings.channels.fields.qq.msg_format" },
      { key: "ack_message", type: "text", secret: false, required: false, help_key: "settings.channels.fields.qq.ack_message" },
      { key: "media_dir", type: "text", secret: false, required: false, help_key: "settings.channels.fields.qq.media_dir" },
      { key: "download_chunk_size", type: "text", secret: false, required: false, help_key: "settings.channels.fields.qq.download_chunk_size" },
      { key: "download_max_bytes", type: "text", secret: false, required: false, help_key: "settings.channels.fields.qq.download_max_bytes" },
    ],
    values: {
      enabled: false,
      app_id: "102000001",
      allow_from: [],
      msg_format: "markdown",
      ack_message: "",
      media_dir: "",
      download_chunk_size: 262144,
      download_max_bytes: 209715200,
    },
    secrets: { secret: { set: true, masked: "****9f2c" } },
    ...overrides,
  };
}

function channelsConfig(overrides: Record<string, unknown> = {}) {
  return {
    config_path: "~/.vibe-trading/agent.json",
    writable: true,
    runtime_running: false,
    channels: { dingtalk: dingtalkEntry() },
    ...overrides,
  };
}

/** Render the card with the DingTalk config panel expanded. */
async function renderExpanded() {
  render(<ChannelSettings />);
  await screen.findByText("IM Channels");
  fireEvent.click(await screen.findByRole("button", { name: "Configure DingTalk" }));
  expect(await screen.findByDisplayValue("ding_appkey")).toBeInTheDocument();
}

/** Render the card with both the DingTalk and QQ config panels available. */
function bothChannelsConfig() {
  return channelsConfig({
    channels: { dingtalk: dingtalkEntry(), qq: qqEntry() },
  });
}

/** Render the card with the QQ config panel expanded. */
async function renderQqExpanded() {
  apiMock.getChannelsConfig.mockResolvedValue(bothChannelsConfig());
  render(<ChannelSettings />);
  await screen.findByText("IM Channels");
  fireEvent.click(await screen.findByRole("button", { name: "Configure QQ" }));
  expect(await screen.findByDisplayValue("102000001")).toBeInTheDocument();
}

describe("ChannelSettings config panel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    window.localStorage.clear();
    apiMock.getChannelStatus.mockReset();
    apiMock.getChannelsConfig.mockReset();
    apiMock.putChannelConfig.mockReset();
    apiMock.testChannel.mockReset();
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
    apiMock.getChannelStatus.mockResolvedValue(channelStatus());
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig());
    apiMock.putChannelConfig.mockResolvedValue({
      channel: dingtalkEntry({ values: { enabled: true, client_id: "ding_appkey" } }),
      applied: "hot_swapped",
    });
    apiMock.testChannel.mockResolvedValue({
      ok: true,
      code: "ok",
      sdk_available: true,
      tested_saved_config: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the status row and reveals a generic form from the field metadata", async () => {
    await renderExpanded();

    expect(screen.getByText("DingTalk")).toBeInTheDocument();
    expect(screen.getByText("Client ID (AppKey)")).toBeInTheDocument();
    expect(screen.getByText("Client Secret (AppSecret)")).toBeInTheDocument();
    expect(screen.getByText("Allowed senders")).toBeInTheDocument();
    expect(screen.getByText("Per-user group sessions")).toBeInTheDocument();
    // List values render as removable chips.
    expect(screen.getByText("user-1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove user-1" })).toBeInTheDocument();
    // Hot-apply copy sits next to Save.
    expect(screen.getByText("Saving applies immediately — no restart needed.")).toBeInTheDocument();
  });

  it("shows only the masked secret placeholder and never renders a secret value", async () => {
    // A contract-violating response that smuggles the raw secret into `values`
    // still must not reach the DOM: rendering is driven by `fields`, not by
    // whatever keys `values` happens to carry.
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({
      channels: {
        dingtalk: dingtalkEntry({
          values: {
            enabled: false,
            client_id: "ding_appkey",
            allow_from: [],
            group_user_isolation: false,
            client_secret: "leaked-secret-value",
          },
        }),
      },
    }));
    await renderExpanded();

    const secretInput = screen.getByPlaceholderText("Keep current (****abcd)");
    expect(secretInput).toHaveAttribute("type", "password");
    expect(secretInput).toHaveValue("");
    expect(document.body.textContent).not.toContain("leaked-secret-value");
    expect(document.body.textContent).not.toContain("****abcd9");
  });

  it("tests the saved configuration with an empty body when the form is pristine", async () => {
    apiMock.testChannel.mockResolvedValue({
      ok: true,
      code: "ok",
      sdk_available: true,
      tested_saved_config: true,
    });
    await renderExpanded();

    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    await waitFor(() => expect(apiMock.testChannel).toHaveBeenCalledTimes(1));
    expect(apiMock.testChannel).toHaveBeenCalledWith("dingtalk", undefined);
    expect(await screen.findByText("Tested the saved configuration.")).toBeInTheDocument();
  });

  it("tests unsaved credentials straight from the form", async () => {
    await renderExpanded();

    fireEvent.change(screen.getByPlaceholderText("Keep current (****abcd)"), {
      target: { value: "typed-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    await waitFor(() => expect(apiMock.testChannel).toHaveBeenCalledTimes(1));
    const [name, body] = apiMock.testChannel.mock.calls[0] as [string, { config?: Record<string, unknown> }];
    expect(name).toBe("dingtalk");
    expect(body.config).toMatchObject({ client_secret: "typed-secret", client_id: "ding_appkey" });
    // The typed secret must only travel in the request, never be echoed.
    expect(document.body.textContent).not.toContain("typed-secret");
    expect(await screen.findByText("Tested the values currently in the form (not saved yet).")).toBeInTheDocument();
  });

  it("enables the channel with a PUT and refreshes status + config", async () => {
    await renderExpanded();
    expect(apiMock.getChannelsConfig).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("checkbox", { name: "Enable channel" }));

    await waitFor(() => expect(apiMock.putChannelConfig).toHaveBeenCalledTimes(1));
    expect(apiMock.putChannelConfig).toHaveBeenCalledWith("dingtalk", {
      config: { enabled: true },
      skip_verify: undefined,
    });
    await waitFor(() => expect(apiMock.getChannelsConfig).toHaveBeenCalledTimes(2));
    expect(apiMock.getChannelStatus).toHaveBeenCalledTimes(2);
    expect(toast.success).toHaveBeenCalledWith("Channel enabled");
  });

  it("offers Enable anyway when the enable transition is rejected with 422", async () => {
    apiMock.putChannelConfig.mockRejectedValueOnce(
      new ApiError("HTTP 401: invalid appKey/appSecret", 422, "invalid_credentials"),
    );
    await renderExpanded();

    fireEvent.click(screen.getByRole("checkbox", { name: "Enable channel" }));

    const anyway = await screen.findByRole("button", { name: "Enable anyway" });
    expect(screen.getByText(
      "The provider rejected these credentials, so the channel was not enabled.",
    )).toBeInTheDocument();
    expect(screen.getByText("Provider response: HTTP 401: invalid appKey/appSecret")).toBeInTheDocument();

    fireEvent.click(anyway);

    await waitFor(() => expect(apiMock.putChannelConfig).toHaveBeenCalledTimes(2));
    expect(apiMock.putChannelConfig).toHaveBeenLastCalledWith("dingtalk", {
      config: { enabled: true },
      skip_verify: true,
    });
  });

  it("adds list values on Enter and removes them again", async () => {
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({
      channels: {
        dingtalk: dingtalkEntry({
          values: { enabled: false, client_id: "ding_appkey", allow_from: [], group_user_isolation: false },
        }),
      },
    }));
    await renderExpanded();

    const listInput = screen.getByPlaceholderText("Type a value and press Enter");
    fireEvent.change(listInput, { target: { value: "user-2" } });
    fireEvent.keyDown(listInput, { key: "Enter" });

    expect(screen.getByText("user-2")).toBeInTheDocument();
    expect(listInput).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: "Remove user-2" }));
    expect(screen.queryByText("user-2")).not.toBeInTheDocument();
  });

  it("saves typed values and clears a stored secret with clear_<field>", async () => {
    await renderExpanded();

    fireEvent.change(screen.getByPlaceholderText("Keep current (****abcd)"), {
      target: { value: "new-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await waitFor(() => expect(apiMock.putChannelConfig).toHaveBeenCalledTimes(1));
    expect(apiMock.putChannelConfig).toHaveBeenLastCalledWith("dingtalk", {
      config: {
        client_id: "ding_appkey",
        client_secret: "new-secret",
        allow_from: ["user-1"],
        group_user_isolation: false,
      },
    });
    expect(toast.success).toHaveBeenCalledWith("Channel configuration saved");

    // Clearing the stored secret sends the clear flag and no secret value.
    fireEvent.click(screen.getByRole("checkbox", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await waitFor(() => expect(apiMock.putChannelConfig).toHaveBeenCalledTimes(2));
    const [, secondBody] = apiMock.putChannelConfig.mock.calls[1] as [string, Record<string, unknown>];
    expect(secondBody.clear_client_secret).toBe(true);
    expect((secondBody.config as Record<string, unknown>).client_secret).toBeUndefined();
  });

  it("disables Save until the form is dirty", async () => {
    await renderExpanded();

    const save = screen.getByRole("button", { name: "Save configuration" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Keep current (****abcd)"), {
      target: { value: "typed-secret" },
    });
    expect(save).toBeEnabled();
  });

  it("tests with a pending secret clear excluded", async () => {
    await renderExpanded();

    fireEvent.click(screen.getByRole("checkbox", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    await waitFor(() => expect(apiMock.testChannel).toHaveBeenCalledTimes(1));
    const [name, body] = apiMock.testChannel.mock.calls[0] as [string, { config?: Record<string, unknown> }];
    expect(name).toBe("dingtalk");
    expect(body).toMatchObject({
      config: expect.objectContaining({ client_id: "ding_appkey" }),
      clear_client_secret: true,
    });
    expect(body.config?.client_secret).toBeUndefined();
  });

  it("disables every control and explains a non-writable YAML config", async () => {
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({ writable: false }));
    await renderExpanded();

    expect(screen.getByText(/stored in a YAML file/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("ding_appkey")).toBeDisabled();
    expect(screen.getByPlaceholderText("Keep current (****abcd)")).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Enable channel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save configuration" })).toBeDisabled();
  });

  it("surfaces the install hint when the runtime SDK is missing", async () => {
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({
      channels: {
        dingtalk: dingtalkEntry({
          sdk_available: false,
          install_hint: "pip install 'vibe-trading-ai[dingtalk]'",
        }),
      },
    }));
    await renderExpanded();

    // The same hint also renders in the status row's recovery column.
    expect(screen.getAllByText(/pip install 'vibe-trading-ai\[dingtalk\]'/).length).toBeGreaterThan(0);
  });

  it("toggles the DingTalk setup guide with its steps and external link", async () => {
    await renderExpanded();

    expect(screen.queryByText(/Create an app in the DingTalk developer console/)).not.toBeInTheDocument();

    const guideToggle = screen.getByRole("button", { name: "DingTalk setup guide" });
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(guideToggle);

    expect(guideToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Create an app in the DingTalk developer console/)).toBeInTheDocument();
    expect(screen.getByText(/enable Stream Mode/)).toBeInTheDocument();
    expect(screen.getByText(/Copy the app's AppKey into Client ID/)).toBeInTheDocument();
    expect(screen.getByText(/Publish the app/)).toBeInTheDocument();
    expect(screen.getByText(/then enable the channel/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the DingTalk developer console" }))
      .toHaveAttribute("href", "https://open-dev.dingtalk.com/");

    fireEvent.click(guideToggle);
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Create an app in the DingTalk developer console/)).not.toBeInTheDocument();
  });

  it("renders every QQ field from the backend help_keys with localized labels", async () => {
    await renderQqExpanded();

    expect(screen.getByText("AppID")).toBeInTheDocument();
    expect(screen.getByText("AppSecret")).toBeInTheDocument();
    expect(screen.getByText("Allowed senders")).toBeInTheDocument();
    expect(screen.getByText("Message format")).toBeInTheDocument();
    expect(screen.getByText("Ack message")).toBeInTheDocument();
    expect(screen.getByText("Media directory")).toBeInTheDocument();
    expect(screen.getByText("Download chunk size")).toBeInTheDocument();
    expect(screen.getByText("Max download size (bytes)")).toBeInTheDocument();
    expect(screen.getByText(/The bot's AppID from the QQ Open Platform/)).toBeInTheDocument();
    // The secret field keeps the generic masked placeholder and password type.
    const secretInput = screen.getByPlaceholderText("Keep current (****9f2c)");
    expect(secretInput).toHaveAttribute("type", "password");
    expect(secretInput).toHaveValue("");
  });

  it("toggles the QQ setup guide with its steps and external link", async () => {
    await renderQqExpanded();

    expect(screen.queryByText(/Register on the QQ Open Platform/)).not.toBeInTheDocument();

    const guideToggle = screen.getByRole("button", { name: "QQ setup guide" });
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(guideToggle);

    expect(guideToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Register on the QQ Open Platform/)).toBeInTheDocument();
    expect(screen.getByText(/no public callback URL is needed/)).toBeInTheDocument();
    expect(screen.getByText(/Copy the AppID and AppSecret/)).toBeInTheDocument();
    expect(screen.getByText(/Paste them into the AppID and AppSecret fields above/)).toBeInTheDocument();
    expect(screen.getByText(/Add the bot to a QQ group/)).toBeInTheDocument();
    expect(screen.getByText(/click Test connection, then enable the channel/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the QQ Open Platform" }))
      .toHaveAttribute("href", "https://q.qq.com/");

    fireEvent.click(guideToggle);
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Register on the QQ Open Platform/)).not.toBeInTheDocument();
  });

  it("renders no setup guide for a channel without a guide definition", async () => {
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({
      channels: {
        dingtalk: dingtalkEntry(),
        signal: qqEntry({ display_name: "Signal", fields: [], values: { enabled: false }, secrets: {} }),
      },
    }));
    render(<ChannelSettings />);
    await screen.findByText("IM Channels");
    fireEvent.click(await screen.findByRole("button", { name: "Configure Signal" }));

    expect(await screen.findByText("This channel has no configurable fields.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /setup guide/ })).not.toBeInTheDocument();
  });
});
