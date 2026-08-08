import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Scheduled } from "@/pages/Scheduled";
import { ApiError, api, type ScheduledRun } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listScheduledRuns: vi.fn(),
      createScheduledRun: vi.fn(),
      deleteScheduledRun: vi.fn(),
    },
  };
});

const mocked = api as unknown as {
  listScheduledRuns: ReturnType<typeof vi.fn>;
  createScheduledRun: ReturnType<typeof vi.fn>;
  deleteScheduledRun: ReturnType<typeof vi.fn>;
};

function run(overrides: Partial<ScheduledRun> = {}): ScheduledRun {
  return {
    id: "auckland-scan",
    prompt: "pre-open scan of NZX names",
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
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listScheduledRuns.mockResolvedValue([]);
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
