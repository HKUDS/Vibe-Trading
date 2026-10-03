import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Scheduled } from "@/pages/Scheduled";
import { ApiError, api, type ScheduledRun, type VerdictRecord } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listScheduledRuns: vi.fn(),
      createScheduledRun: vi.fn(),
      updateScheduledRun: vi.fn(),
      deleteScheduledRun: vi.fn(),
      getChannelStatus: vi.fn(),
    },
  };
});

const mocked = api as unknown as {
  listScheduledRuns: ReturnType<typeof vi.fn>;
  createScheduledRun: ReturnType<typeof vi.fn>;
  updateScheduledRun: ReturnType<typeof vi.fn>;
  deleteScheduledRun: ReturnType<typeof vi.fn>;
  getChannelStatus: ReturnType<typeof vi.fn>;
};

function run(overrides: Partial<ScheduledRun> = {}): ScheduledRun {
  return {
    id: "auckland-scan",
    prompt: "pre-open scan of NZX names",
    title: "",
    source_type: "prompt",
    playbook_slug: null,
    end_at: null,
    schedule: "30 23 * * 1-5",
    next_run_at: 1_790_000_000_000,
    status: "pending",
    created_at: 1_780_000_000_000,
    last_run_at: null,
    consecutive_failures: 0,
    last_error: null,
    failure_kind: null,
    config: {},
    timezone: "Pacific/Auckland",
    delivery_channel: null,
    delivery_target: null,
    delivery_target_ref: null,
    delivery_target_label: null,
    delivery_status: "none",
    delivery_error: null,
    delivery_updated_at: null,
    delivery_attempts: 0,
    delivery_provider_message_id: null,
    last_verdict: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listScheduledRuns.mockResolvedValue([]);
  mocked.getChannelStatus.mockResolvedValue({
    running: true,
    inbound_queue: 0,
    outbound_queue: 0,
    session_count: 0,
    channels: {
      email: {
        name: "email",
        display_name: "Email",
        configured: true,
        enabled: true,
        available: true,
        loaded: true,
        running: true,
        delivery_target_label: "Recipient email address",
        delivery_target_kind: "email_address",
        delivery_target_placeholder: "name@example.com",
        delivery_target_input_type: "email",
      },
      telegram: {
        name: "telegram",
        display_name: "Telegram",
        configured: true,
        enabled: true,
        available: true,
        loaded: true,
        running: true,
        delivery_target_label: "Telegram chat",
        delivery_target_kind: "chat",
        delivery_target_placeholder: "Chat, group, or user ID",
        delivery_target_input_type: "text",
        delivery_target_suggestions: [
          { kind: "private_chat", target: "1381234567" },
          { kind: "private_chat", target: "123456" },
        ],
      },
      discord: {
        name: "discord",
        display_name: "Discord",
        configured: true,
        enabled: false,
        available: true,
        loaded: false,
        running: false,
      },
    },
  });
});

describe("Scheduled page", () => {
  it("renders the stored local cadence and timezone without UTC conversion", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run()]);
    render(<Scheduled />);

    expect(await screen.findByText("Mon–Fri at 23:30")).toBeInTheDocument();
    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Pacific/Auckland")).toBeInTheDocument();
    expect(within(row).getByText("pre-open scan of NZX names")).toBeInTheDocument();
  });

  it("shows legacy timezone-less jobs as UTC", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run({ timezone: null, schedule: "0 9 * * *" })]);
    render(<Scheduled />);

    expect(await screen.findByText("Daily at 09:00")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem")).getByText("UTC")).toBeInTheDocument();
  });

  it("creates a job from the wall-clock composer", async () => {
    mocked.createScheduledRun.mockResolvedValue(run());
    render(<Scheduled />);
    await screen.findByText(/No scheduled runs yet/);

    fireEvent.change(screen.getByLabelText("Research prompt"), {
      target: { value: "scan the pre-open movers" },
    });
    fireEvent.change(screen.getByLabelText("Local time"), { target: { value: "23:30" } });
    fireEvent.submit(screen.getByRole("button", { name: /Schedule run/ }));

    await waitFor(() =>
      expect(mocked.createScheduledRun).toHaveBeenCalledWith(
        expect.objectContaining({
          prompt: "scan the pre-open movers",
          schedule: "30 23 * * 1-5",
          timezone: expect.any(String),
        }),
      ),
    );
  });


  it("edits prompt, wall-clock schedule, and delivery without recreating the job", async () => {
    mocked.listScheduledRuns.mockResolvedValue([
      run({
        prompt: "old briefing",
        schedule: "20 10 * * 1-5",
        timezone: "America/Buenos_Aires",
        delivery_channel: "email",
        delivery_target: "old@example.com",
      }),
    ]);
    mocked.updateScheduledRun.mockResolvedValue(run());
    render(<Scheduled />);

    fireEvent.click(await screen.findByRole("button", { name: /Edit scheduled run/ }));
    expect(screen.getByLabelText("Research prompt")).toHaveValue("old briefing");
    expect(screen.getByLabelText("Local time")).toHaveValue("10:20");
    expect(screen.getByLabelText("Delivery channel")).toHaveValue("email");
    expect(await screen.findByLabelText("Recipient email address")).toHaveValue("old@example.com");

    fireEvent.change(screen.getByLabelText("Research prompt"), {
      target: { value: "updated briefing" },
    });
    fireEvent.change(screen.getByLabelText("Local time"), { target: { value: "10:35" } });
    fireEvent.change(screen.getByLabelText("Recipient email address"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(mocked.updateScheduledRun).toHaveBeenCalledWith(
        "auckland-scan",
        expect.objectContaining({
          prompt: "updated briefing",
          schedule: "35 10 * * 1-5",
          timezone: "America/Buenos_Aires",
          delivery_channel: "email",
          delivery_target: "new@example.com",
        }),
      ),
    );
    expect(mocked.createScheduledRun).not.toHaveBeenCalled();
  });

  it("lists only enabled configured channels and adapts the destination field", async () => {
    render(<Scheduled />);
    await screen.findByText(/No scheduled runs yet/);

    const channel = screen.getByLabelText("Delivery channel");
    await within(channel).findByRole("option", { name: "Email" });
    expect(within(channel).getByRole("option", { name: "Email" })).toBeInTheDocument();
    expect(within(channel).getByRole("option", { name: "Telegram" })).toBeInTheDocument();
    expect(within(channel).queryByRole("option", { name: "Discord" })).not.toBeInTheDocument();

    fireEvent.change(channel, { target: { value: "email" } });
    const target = screen.getByLabelText("Recipient email address");
    expect(target).toHaveAttribute("type", "email");
    expect(target).toHaveAttribute("placeholder", "name@example.com");
  });

  it("keeps manual target entry and can fill it from a known Telegram destination", async () => {
    render(<Scheduled />);
    await screen.findByText(/No scheduled runs yet/);

    const channel = screen.getByLabelText("Delivery channel");
    await within(channel).findByRole("option", { name: "Telegram" });
    fireEvent.change(channel, { target: { value: "telegram" } });

    const target = await screen.findByLabelText("Telegram chat");
    expect(target).toHaveValue("");
    expect(target).toHaveAttribute("placeholder", "Chat, group, or user ID");

    const knownTarget = screen.getByLabelText("Known destination");
    fireEvent.change(knownTarget, { target: { value: "1381234567" } });

    expect(target).toHaveValue("1381234567");
    expect(
      within(knownTarget).getByRole("option", { name: "Private chat · 138••••67" }),
    ).toBeInTheDocument();
    expect(
      within(knownTarget).getByRole("option", { name: "Private chat · 1••••6" }),
    ).toBeInTheDocument();
    expect(within(knownTarget).queryByRole("option", { name: /123456/ })).not.toBeInTheDocument();
  });

  it("surfaces a validation error from the backend", async () => {
    mocked.createScheduledRun.mockRejectedValue(
      new ApiError("timezone 'Not/AZone' is not a recognized IANA timezone key", 422),
    );
    render(<Scheduled />);
    await screen.findByText(/No scheduled runs yet/);

    fireEvent.change(screen.getByLabelText("Research prompt"), {
      target: { value: "scan" },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Schedule run/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "not a recognized IANA timezone",
    );
  });

  it("deletes only after an explicit confirm click, and cancel disarms", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run()]);
    mocked.deleteScheduledRun.mockResolvedValue(undefined);
    render(<Scheduled />);

    fireEvent.click(await screen.findByRole("button", { name: /Delete scheduled run/ }));
    expect(mocked.deleteScheduledRun).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: /Confirm deleting/ })).not.toBeInTheDocument();
    expect(mocked.deleteScheduledRun).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Delete scheduled run/ }));
    fireEvent.click(screen.getByRole("button", { name: /Confirm deleting/ }));
    await waitFor(() =>
      expect(mocked.deleteScheduledRun).toHaveBeenCalledWith("auckland-scan"),
    );
  });

  it("blocks a whitespace-only prompt client-side", async () => {
    render(<Scheduled />);
    await screen.findByText(/No scheduled runs yet/);

    fireEvent.change(screen.getByLabelText("Research prompt"), {
      target: { value: "   " },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Schedule run/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a research prompt",
    );
    expect(mocked.createScheduledRun).not.toHaveBeenCalled();
  });
});


describe("briefing delivery", () => {
  it("keeps delivery off unless a channel is selected", async () => {
    render(<Scheduled />);
    fireEvent.change(screen.getByLabelText(/prompt/i), {
      target: { value: "pre-open scan" },
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule|create/i }));

    await waitFor(() => expect(mocked.createScheduledRun).toHaveBeenCalled());
    const body = mocked.createScheduledRun.mock.calls[0][0];
    expect(body.delivery_channel).toBeNull();
    expect(body.delivery_target).toBeNull();
  });

  it("refuses a channel with no target instead of sending nowhere", async () => {
    render(<Scheduled />);
    fireEvent.change(screen.getByLabelText(/prompt/i), {
      target: { value: "pre-open scan" },
    });
    const channel = screen.getByLabelText(/delivery channel/i);
    await within(channel).findByRole("option", { name: "Telegram" });
    fireEvent.change(channel, {
      target: { value: "telegram" },
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule|create/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(mocked.createScheduledRun).not.toHaveBeenCalled();
  });

  it("sends the channel and target it was given", async () => {
    render(<Scheduled />);
    fireEvent.change(screen.getByLabelText(/prompt/i), {
      target: { value: "pre-open scan" },
    });
    const channel = screen.getByLabelText(/delivery channel/i);
    await within(channel).findByRole("option", { name: "Telegram" });
    fireEvent.change(channel, {
      target: { value: "telegram" },
    });
    fireEvent.change(await screen.findByLabelText(/telegram chat/i), {
      target: { value: " chat-9 " },
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule|create/i }));

    await waitFor(() => expect(mocked.createScheduledRun).toHaveBeenCalled());
    const body = mocked.createScheduledRun.mock.calls[0][0];
    expect(body.delivery_channel).toBe("telegram");
    expect(body.delivery_target).toBe("chat-9");
  });

  it("shows a monitor's delivery state, and shows nothing when it has none", async () => {
    mocked.listScheduledRuns.mockResolvedValue([
      run({ id: "with", delivery_channel: "telegram", delivery_status: "sent" }),
      run({ id: "without" }),
    ]);
    render(<Scheduled />);

    expect(await screen.findByText(/delivered to telegram/i)).toBeInTheDocument();
    expect(screen.queryAllByText(/delivered to/i)).toHaveLength(1);
  });

  it("surfaces why a delivery failed rather than only that it did", async () => {
    mocked.listScheduledRuns.mockResolvedValue([
      run({
        delivery_channel: "telegram",
        delivery_status: "failed",
        delivery_error: "channel unreachable",
      }),
    ]);
    render(<Scheduled />);

    expect(await screen.findByText(/channel unreachable/i)).toBeInTheDocument();
  });
});

function verdict(overrides: Partial<VerdictRecord> = {}): VerdictRecord {
  return {
    session_id: "sess-1",
    recorded_at: 1_789_000_000_000,
    parse: "ok",
    outcome: "FLAT",
    items: [{ symbol: "600519.SH", state: "FLAT", reason: "band held" }],
    previous: null,
    ...overrides,
  };
}

describe("Scheduled page verdict cell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.listScheduledRuns.mockResolvedValue([]);
  });

  it("renders the latest verdict with its delta and the recorded time", async () => {
    mocked.listScheduledRuns.mockResolvedValue([
      run({
        last_verdict: verdict({
          outcome: "DRIFT",
          items: [{ symbol: "600519.SH", state: "DRIFT", reason: "band crossed" }],
          previous: verdict({ session_id: "sess-0", outcome: "FLAT", recorded_at: 1_788_000_000_000 }),
        }),
      }),
    ]);
    render(<Scheduled />);

    expect(await screen.findByText(/600519.SH DRIFT/)).toBeInTheDocument();
    expect(screen.getByText(/FLAT → DRIFT/)).toBeInTheDocument();
    expect(screen.getByText(/as of/)).toBeInTheDocument();
  });

  it("shows an explicit empty state when no run has recorded one", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run({ last_verdict: null })]);
    render(<Scheduled />);

    expect(await screen.findByText("No verdict yet")).toBeInTheDocument();
  });

  it("renders nothing for ad-hoc monitors permanently at no_verdict_section", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run({ last_verdict: verdict({ parse: "no_verdict_section", items: [] }) })]);
    render(<Scheduled />);

    await screen.findByRole("listitem");
    expect(screen.queryByText(/No verdict yet/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("verdict-line-auckland-scan")).toBeNull();
  });

  it("never shows a wrong verdict: a malformed section reads as unreadable", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run({ last_verdict: verdict({ parse: "contract_violation", items: [] }) })]);
    render(<Scheduled />);

    expect(await screen.findByText("Latest verdict unreadable")).toBeInTheDocument();
  });

  it("reads an empty item list as a real 'no calls' answer", async () => {
    mocked.listScheduledRuns.mockResolvedValue([run({ last_verdict: verdict({ items: [] }) })]);
    render(<Scheduled />);

    expect(await screen.findByText(/No calls/)).toBeInTheDocument();
  });
});
