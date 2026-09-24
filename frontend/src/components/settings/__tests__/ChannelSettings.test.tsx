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

function emailEntry(overrides: Record<string, unknown> = {}) {
  return {
    display_name: "Email",
    available: true,
    loaded: true,
    install_hint: "",
    error: "",
    supports_test: true,
    sdk_available: true,
    fields: [
      { key: "consent_granted", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.consent_granted" },
      { key: "imap_host", type: "text", secret: false, required: true, help_key: "settings.channels.fields.email.imap_host" },
      { key: "imap_port", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.imap_port" },
      { key: "imap_username", type: "text", secret: false, required: true, help_key: "settings.channels.fields.email.imap_username" },
      { key: "imap_password", type: "password", secret: true, required: true, help_key: "settings.channels.fields.email.imap_password" },
      { key: "imap_mailbox", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.imap_mailbox" },
      { key: "imap_use_ssl", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.imap_use_ssl" },
      { key: "smtp_host", type: "text", secret: false, required: true, help_key: "settings.channels.fields.email.smtp_host" },
      { key: "smtp_port", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.smtp_port" },
      { key: "smtp_username", type: "text", secret: false, required: true, help_key: "settings.channels.fields.email.smtp_username" },
      { key: "smtp_password", type: "password", secret: true, required: true, help_key: "settings.channels.fields.email.smtp_password" },
      { key: "smtp_use_tls", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.smtp_use_tls" },
      { key: "smtp_use_ssl", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.smtp_use_ssl" },
      { key: "verify_tls", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.verify_tls" },
      { key: "from_address", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.from_address" },
      { key: "auto_reply_enabled", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.auto_reply_enabled" },
      { key: "poll_interval_seconds", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.poll_interval_seconds" },
      { key: "mark_seen", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.mark_seen" },
      { key: "post_action", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.post_action" },
      { key: "post_action_move_mailbox", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.post_action_move_mailbox" },
      { key: "post_action_expunge", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.post_action_expunge" },
      { key: "post_action_ignore_skipped", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.post_action_ignore_skipped" },
      { key: "max_body_chars", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.max_body_chars" },
      { key: "subject_prefix", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.subject_prefix" },
      { key: "allow_from", type: "list", secret: false, required: false, help_key: "settings.channels.fields.email.allow_from" },
      { key: "verify_dkim", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.verify_dkim" },
      { key: "verify_spf", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.email.verify_spf" },
      { key: "allowed_attachment_types", type: "list", secret: false, required: false, help_key: "settings.channels.fields.email.allowed_attachment_types" },
      { key: "max_attachment_size", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.max_attachment_size" },
      { key: "max_attachments_per_email", type: "text", secret: false, required: false, help_key: "settings.channels.fields.email.max_attachments_per_email" },
    ],
    values: {
      enabled: false,
      consent_granted: false,
      imap_host: "imap.example.com",
      imap_port: 993,
      imap_username: "bot@example.com",
      imap_mailbox: "INBOX",
      imap_use_ssl: true,
      smtp_host: "smtp.example.com",
      smtp_port: 587,
      smtp_username: "bot@example.com",
      smtp_use_tls: true,
      smtp_use_ssl: false,
      verify_tls: true,
      from_address: "",
      auto_reply_enabled: true,
      poll_interval_seconds: 30,
      mark_seen: true,
      post_action: "",
      post_action_move_mailbox: "",
      post_action_expunge: false,
      post_action_ignore_skipped: true,
      max_body_chars: 12000,
      subject_prefix: "Re: ",
      allow_from: [],
      verify_dkim: true,
      verify_spf: true,
      allowed_attachment_types: [],
      max_attachment_size: 2000000,
      max_attachments_per_email: 5,
    },
    secrets: {
      imap_password: { set: true, masked: "****1a2b" },
      smtp_password: { set: true, masked: "****c3d4" },
    },
    ...overrides,
  };
}

function websocketEntry(overrides: Record<string, unknown> = {}) {
  return {
    display_name: "WebSocket",
    available: true,
    loaded: true,
    install_hint: "",
    error: "",
    supports_test: true,
    sdk_available: true,
    fields: [
      { key: "host", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.host" },
      { key: "port", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.port" },
      { key: "unix_socket_path", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.unix_socket_path" },
      { key: "path", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.path" },
      { key: "token", type: "password", secret: true, required: false, help_key: "settings.channels.fields.websocket.token" },
      { key: "token_issue_path", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.token_issue_path" },
      { key: "token_issue_secret", type: "password", secret: true, required: false, help_key: "settings.channels.fields.websocket.token_issue_secret" },
      { key: "token_ttl_s", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.token_ttl_s" },
      { key: "websocket_requires_token", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.websocket.websocket_requires_token" },
      { key: "allow_from", type: "list", secret: false, required: false, help_key: "settings.channels.fields.websocket.allow_from" },
      { key: "streaming", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.websocket.streaming" },
      { key: "max_message_bytes", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.max_message_bytes" },
      { key: "ping_interval_s", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.ping_interval_s" },
      { key: "ping_timeout_s", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.ping_timeout_s" },
      { key: "ssl_certfile", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.ssl_certfile" },
      { key: "ssl_keyfile", type: "text", secret: false, required: false, help_key: "settings.channels.fields.websocket.ssl_keyfile" },
    ],
    values: {
      enabled: false,
      host: "127.0.0.1",
      port: 8765,
      unix_socket_path: "",
      path: "/",
      token_issue_path: "",
      token_ttl_s: 300,
      websocket_requires_token: true,
      allow_from: ["*"],
      streaming: true,
      max_message_bytes: 37748736,
      ping_interval_s: 20,
      ping_timeout_s: 20,
      ssl_certfile: "",
      ssl_keyfile: "",
    },
    secrets: {
      token: { set: true, masked: "****9z8y" },
      token_issue_secret: { set: true, masked: "****7x6w" },
    },
    ...overrides,
  };
}

function feishuEntry(overrides: Record<string, unknown> = {}) {
  return {
    display_name: "Feishu",
    available: true,
    loaded: true,
    install_hint: "",
    error: "",
    supports_test: true,
    sdk_available: true,
    fields: [
      { key: "app_id", type: "text", secret: false, required: true, help_key: "settings.channels.fields.feishu.app_id" },
      { key: "app_secret", type: "password", secret: true, required: true, help_key: "settings.channels.fields.feishu.app_secret" },
      { key: "encrypt_key", type: "password", secret: true, required: false, help_key: "settings.channels.fields.feishu.encrypt_key" },
      { key: "verification_token", type: "password", secret: true, required: false, help_key: "settings.channels.fields.feishu.verification_token" },
      { key: "allow_from", type: "list", secret: false, required: false, help_key: "settings.channels.fields.feishu.allow_from" },
      { key: "react_emoji", type: "text", secret: false, required: false, help_key: "settings.channels.fields.feishu.react_emoji" },
      { key: "done_emoji", type: "text", secret: false, required: false, help_key: "settings.channels.fields.feishu.done_emoji" },
      { key: "tool_hint_prefix", type: "text", secret: false, required: false, help_key: "settings.channels.fields.feishu.tool_hint_prefix" },
      { key: "group_policy", type: "text", secret: false, required: false, help_key: "settings.channels.fields.feishu.group_policy" },
      { key: "reply_to_message", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.feishu.reply_to_message" },
      { key: "streaming", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.feishu.streaming" },
      { key: "domain", type: "text", secret: false, required: false, help_key: "settings.channels.fields.feishu.domain" },
      { key: "topic_isolation", type: "bool", secret: false, required: false, help_key: "settings.channels.fields.feishu.topic_isolation" },
    ],
    values: {
      enabled: false,
      app_id: "cli_a9f8e7d6c5b4",
      allow_from: [],
      react_emoji: "THUMBSUP",
      done_emoji: "",
      tool_hint_prefix: "",
      group_policy: "mention",
      reply_to_message: true,
      streaming: true,
      domain: "feishu",
      topic_isolation: false,
    },
    secrets: {
      app_secret: { set: true, masked: "****abcd" },
      encrypt_key: { set: true, masked: "****ef01" },
      verification_token: { set: true, masked: "****2345" },
    },
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

/** Render the card with the Email config panel expanded. */
async function renderEmailExpanded() {
  apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({
    channels: { dingtalk: dingtalkEntry(), email: emailEntry() },
  }));
  render(<ChannelSettings />);
  await screen.findByText("IM Channels");
  fireEvent.click(await screen.findByRole("button", { name: "Configure Email" }));
  expect(await screen.findByDisplayValue("imap.example.com")).toBeInTheDocument();
}

/** Render the card with the WebSocket config panel expanded. */
async function renderWebsocketExpanded() {
  apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({
    channels: { dingtalk: dingtalkEntry(), websocket: websocketEntry() },
  }));
  render(<ChannelSettings />);
  await screen.findByText("IM Channels");
  fireEvent.click(await screen.findByRole("button", { name: "Configure WebSocket" }));
  expect(await screen.findByDisplayValue("127.0.0.1")).toBeInTheDocument();
}

/** Render the card with the three guided IM channels available. */
function guidedChannelsConfig() {
  return channelsConfig({
    channels: { dingtalk: dingtalkEntry(), qq: qqEntry(), feishu: feishuEntry() },
  });
}

/** Render the card with the Feishu config panel expanded. */
async function renderFeishuExpanded() {
  apiMock.getChannelsConfig.mockResolvedValue(guidedChannelsConfig());
  render(<ChannelSettings />);
  await screen.findByText("IM Channels");
  fireEvent.click(await screen.findByRole("button", { name: "Configure Feishu" }));
  expect(await screen.findByDisplayValue("cli_a9f8e7d6c5b4")).toBeInTheDocument();
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

  it("renders every Email field from the backend help_keys with localized labels", async () => {
    await renderEmailExpanded();

    expect(screen.getByText("Consent granted")).toBeInTheDocument();
    expect(screen.getByText("IMAP host")).toBeInTheDocument();
    expect(screen.getByText("IMAP username")).toBeInTheDocument();
    expect(screen.getByText("IMAP mailbox")).toBeInTheDocument();
    expect(screen.getByText("SMTP host")).toBeInTheDocument();
    expect(screen.getByText("From address")).toBeInTheDocument();
    expect(screen.getByText("Automatic replies")).toBeInTheDocument();
    expect(screen.getByText("After processing")).toBeInTheDocument();
    expect(screen.getByText("Allowed senders")).toBeInTheDocument();
    expect(screen.getByText("Verify DKIM")).toBeInTheDocument();
    expect(screen.getByText("Verify TLS certificate")).toBeInTheDocument();
    expect(screen.getByText("Allowed attachment types")).toBeInTheDocument();
    expect(screen.getByText("Max attachments per email")).toBeInTheDocument();
    expect(screen.getByText(/Inbound mail server host, e\.g\. imap\.gmail\.com/)).toBeInTheDocument();
    // Both anti-spoofing fields carry the same warning, so match them together.
    expect(screen.getAllByText(/Disabling both DKIM and SPF accepts spoofed From headers/)).toHaveLength(2);
    // Secrets keep the generic masked placeholder and password type.
    const imapSecret = screen.getByPlaceholderText("Keep current (****1a2b)");
    expect(imapSecret).toHaveAttribute("type", "password");
    expect(imapSecret).toHaveValue("");
    const smtpSecret = screen.getByPlaceholderText("Keep current (****c3d4)");
    expect(smtpSecret).toHaveAttribute("type", "password");
    expect(smtpSecret).toHaveValue("");
  });

  it("toggles the Email setup guide with its steps and external link", async () => {
    await renderEmailExpanded();

    expect(screen.queryByText(/IMAP and SMTP host names and ports/)).not.toBeInTheDocument();

    const guideToggle = screen.getByRole("button", { name: "Email setup guide" });
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(guideToggle);

    expect(guideToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/no public callback URL is needed/)).toBeInTheDocument();
    expect(screen.getByText(/IMAP and SMTP host names and ports/)).toBeInTheDocument();
    expect(screen.getByText(/create an app password/)).toBeInTheDocument();
    expect(screen.getByText(/it probes the IMAP login, the mailbox folder, and the SMTP login/)).toBeInTheDocument();
    expect(screen.getByText(/Tick Consent granted, then enable the channel/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Vibe-Trading docs" }))
      .toHaveAttribute("href", "https://vibetrading.wiki/docs/");

    fireEvent.click(guideToggle);
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/IMAP and SMTP host names and ports/)).not.toBeInTheDocument();
  });

  it("renders every WebSocket field from the backend help_keys with localized labels", async () => {
    await renderWebsocketExpanded();

    expect(screen.getByText("Bind host")).toBeInTheDocument();
    expect(screen.getByText("Bind port")).toBeInTheDocument();
    expect(screen.getByText("Unix socket path")).toBeInTheDocument();
    expect(screen.getByText("Upgrade path")).toBeInTheDocument();
    expect(screen.getByText("Static token")).toBeInTheDocument();
    expect(screen.getByText("Token issue path")).toBeInTheDocument();
    expect(screen.getByText("Require token")).toBeInTheDocument();
    expect(screen.getByText("Allowed clients")).toBeInTheDocument();
    expect(screen.getByText("Max message bytes")).toBeInTheDocument();
    expect(screen.getByText("TLS certificate path")).toBeInTheDocument();
    expect(screen.getByText(/wildcard host such as 0\.0\.0\.0 or ::/)).toBeInTheDocument();
    // Certificate and key share the same pairing rule, so match them together.
    expect(screen.getAllByText(/Set both certificate and key, or neither/)).toHaveLength(2);
    const tokenSecret = screen.getByPlaceholderText("Keep current (****9z8y)");
    expect(tokenSecret).toHaveAttribute("type", "password");
    expect(tokenSecret).toHaveValue("");
    const issueSecret = screen.getByPlaceholderText("Keep current (****7x6w)");
    expect(issueSecret).toHaveAttribute("type", "password");
    expect(issueSecret).toHaveValue("");
  });

  it("toggles the WebSocket setup guide with its steps and external link", async () => {
    await renderWebsocketExpanded();

    expect(screen.queryByText(/keep 127\.0\.0\.1 for local-only use/)).not.toBeInTheDocument();

    const guideToggle = screen.getByRole("button", { name: "WebSocket setup guide" });
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(guideToggle);

    expect(guideToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/keep 127\.0\.0\.1 for local-only use/)).toBeInTheDocument();
    expect(screen.getByText(/token-issue path plus its bearer secret/)).toBeInTheDocument();
    expect(screen.getByText(/ws:\/\/host:port\/path\?client_id=\.\.\.&token=\.\.\./)).toBeInTheDocument();
    expect(screen.getByText(/hot-swaps the server/)).toBeInTheDocument();
    expect(screen.getByText(/validates the SSL certificate\/key material/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Vibe-Trading docs" }))
      .toHaveAttribute("href", "https://vibetrading.wiki/docs/");

    fireEvent.click(guideToggle);
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/keep 127\.0\.0\.1 for local-only use/)).not.toBeInTheDocument();
  });

  it("renders every Feishu field from the backend help_keys with localized labels", async () => {
    await renderFeishuExpanded();

    expect(screen.getByText("App ID")).toBeInTheDocument();
    expect(screen.getByText("App Secret")).toBeInTheDocument();
    expect(screen.getByText("Encrypt Key")).toBeInTheDocument();
    expect(screen.getByText("Verification Token")).toBeInTheDocument();
    expect(screen.getByText("Allowed senders")).toBeInTheDocument();
    expect(screen.getByText("Working emoji")).toBeInTheDocument();
    expect(screen.getByText("Done emoji")).toBeInTheDocument();
    expect(screen.getByText("Tool hint prefix")).toBeInTheDocument();
    expect(screen.getByText("Group policy")).toBeInTheDocument();
    expect(screen.getByText("Quote the original message")).toBeInTheDocument();
    expect(screen.getByText("Streaming replies")).toBeInTheDocument();
    expect(screen.getByText("Domain")).toBeInTheDocument();
    expect(screen.getByText("Per-topic sessions")).toBeInTheDocument();
    expect(screen.getByText(/starts with cli_/)).toBeInTheDocument();
    // Both Event Subscription secrets document the long-connection optionality.
    expect(screen.getAllByText(/Optional for long-connection mode/)).toHaveLength(2);
    expect(screen.getByText(/default THUMBSUP/)).toBeInTheDocument();
    // The three secret fields keep the generic masked placeholder and password type.
    for (const masked of ["****abcd", "****ef01", "****2345"]) {
      const secretInput = screen.getByPlaceholderText(`Keep current (${masked})`);
      expect(secretInput).toHaveAttribute("type", "password");
      expect(secretInput).toHaveValue("");
    }
  });

  it("toggles the Feishu setup guide with its steps and external link", async () => {
    await renderFeishuExpanded();

    expect(screen.queryByText(/Create a Custom App on the Feishu Open Platform/)).not.toBeInTheDocument();

    const guideToggle = screen.getByRole("button", { name: "Feishu / Lark bot setup" });
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(guideToggle);

    expect(guideToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/WebSocket long connection, so no public IP/)).toBeInTheDocument();
    expect(screen.getByText(/Create a Custom App on the Feishu Open Platform/)).toBeInTheDocument();
    expect(screen.getByText(/Add the Bot capability to the app/)).toBeInTheDocument();
    expect(screen.getByText(/subscribe to receiving messages \(im\.message\.receive_v1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Copy the App ID and App Secret from Credentials & Basic Info/)).toBeInTheDocument();
    expect(screen.getByText(/Create a version and publish the app/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Feishu Open Platform" }))
      .toHaveAttribute("href", "https://open.feishu.cn/");

    fireEvent.click(guideToggle);
    expect(guideToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Create a Custom App on the Feishu Open Platform/)).not.toBeInTheDocument();
  });

  it("never renders smuggled Feishu secret values, only the masked placeholders", async () => {
    // A contract-violating response that carries raw secrets in `values`
    // still must not reach the DOM: secret widgets bind to empty drafts.
    const feishu = feishuEntry({
      values: {
        ...feishuEntry().values,
        app_secret: "leaked-app-secret",
        encrypt_key: "leaked-encrypt-key",
        verification_token: "leaked-verification-token",
      },
    });
    apiMock.getChannelsConfig.mockResolvedValue(channelsConfig({ channels: { feishu } }));
    render(<ChannelSettings />);
    await screen.findByText("IM Channels");
    fireEvent.click(await screen.findByRole("button", { name: "Configure Feishu" }));
    expect(await screen.findByDisplayValue("cli_a9f8e7d6c5b4")).toBeInTheDocument();

    const secretInputs = Array.from(document.querySelectorAll("input[type=password]"));
    expect(secretInputs).toHaveLength(3);
    for (const secretInput of secretInputs) {
      expect(secretInput).toHaveValue("");
    }
    expect(document.body.textContent).not.toContain("leaked-app-secret");
    expect(document.body.textContent).not.toContain("leaked-encrypt-key");
    expect(document.body.textContent).not.toContain("leaked-verification-token");
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
