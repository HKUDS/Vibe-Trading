import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import "@/i18n";
import i18n from "@/i18n";
import { api } from "@/lib/api";
import { HistoryStorageSettings } from "../HistoryStorageSettings";

vi.mock("@/lib/api", () => ({ api: {
  dataCapabilities: vi.fn(), dataScans: vi.fn(), createDataScan: vi.fn(), cancelDataScan: vi.fn(),
  historyStorage: vi.fn(), historyJobs: vi.fn(), saveHistoryStorage: vi.fn(),
  planHistory: vi.fn(), createHistory: vi.fn(), historyAction: vi.fn(),
  pinHistory: vi.fn(), deleteHistory: vi.fn(), pruneHistory: vi.fn(),
} }));
const storage = { quota_bytes: 256 * 1024 ** 2, retention_days: 30, used_bytes: 1024 ** 2, reserved_bytes: 0, path: "/test" };
beforeEach(async () => {
  vi.clearAllMocks(); await i18n.changeLanguage("en");
  vi.mocked(api.historyStorage).mockResolvedValue(storage);
  vi.mocked(api.historyJobs).mockResolvedValue([]);
  vi.mocked(api.dataScans).mockResolvedValue([]);
  vi.mocked(api.dataCapabilities).mockResolvedValue({history_datasets: {markets: ["us_equity", "crypto"], intervals: ["1m", "5m", "1D"], sources: [{source: "yahoo", markets: ["us_equity"], intervals: ["1m", "1D"], requires_auth: false}]}});
});
afterEach(cleanup);
it("estimates first and starts only after the download action", async () => {
  vi.mocked(api.planHistory).mockResolvedValue({ chunks: 2, estimated_max_rows: 96, estimated_uncompressed_bytes: 20000, storage });
  vi.mocked(api.createHistory).mockResolvedValue({ id: "abc", state: "paused", pinned: 0, error: null });
  vi.mocked(api.historyAction).mockResolvedValue({ id: "abc", state: "queued", pinned: 0, error: null });
  render(<HistoryStorageSettings />);
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2021-11-15" } });
  fireEvent.change(screen.getByLabelText("To"), { target: { value: "2021-11-16" } });
  fireEvent.click(screen.getByRole("button", { name: "Estimate first" }));
  await screen.findByRole("button", { name: "Download" });
  expect(api.createHistory).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Download", exact: true }));
  await waitFor(() => expect(api.historyAction).toHaveBeenCalledWith("abc", "resume"));
});
it("shows failed quota changes and keeps the saved usage visible", async () => {
  vi.mocked(api.saveHistoryStorage).mockRejectedValue(new Error("New quota is below current usage"));
  render(<HistoryStorageSettings />);
  await screen.findByText(/1.0 \/ 256.0 MiB used/);
  fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("below current usage");
  expect(screen.getByText(/1.0 \/ 256.0 MiB used/)).toBeVisible();
});

it("exposes auto routing and keeps one-minute data and unverified coverage explicit", async () => {
  vi.mocked(api.historyJobs).mockResolvedValue([{id: "one", state: "downloaded", pinned: 0, error: null, spec: {codes: ["AAPL.US"], start_date: "2026-11-12", end_date: "2026-11-12", interval: "1m"}}]);
  render(<HistoryStorageSettings />);
  await screen.findByText(/1 registered sources/);
  expect(screen.getByLabelText("Data source")).toHaveValue("auto");
  fireEvent.change(screen.getByLabelText("Interval"), {target: {value: "1m"}});
  expect(screen.getByLabelText("Interval")).toHaveValue("1m");
  expect(screen.getByText(/Downloaded · coverage unverified/)).toBeVisible();
  expect(screen.getByText(/Only calendar\/grid-verified datasets/)).toBeVisible();
});

it("shows automatic recovery and lets the user pause it without a resume call", async () => {
  vi.mocked(api.historyJobs).mockResolvedValue([{ id: "waiting", state: "failed", pinned: 0, error: "ConnectionError", auto_resume: 1, retry_at: Date.now() / 1000 + 30, retry_count: 1 }]);
  vi.mocked(api.historyAction).mockResolvedValue({ id: "waiting", state: "paused", pinned: 0, error: null, retry_at: 0 });
  render(<HistoryStorageSettings />);
  expect(await screen.findByText(/automatically retrying in/)).toBeVisible();
  expect(api.historyAction).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Pause", exact: true }));
  await waitFor(() => expect(api.historyAction).toHaveBeenCalledWith("waiting", "cancel"));
});

it("shows a durable waiting job as queued and pauses it rather than starting it again", async () => {
  vi.mocked(api.historyJobs).mockResolvedValue([{ id: "waiting-slot", state: "waiting", pinned: 0, error: null, auto_resume: 1, retry_at: 0 }]);
  vi.mocked(api.historyAction).mockResolvedValue({ id: "waiting-slot", state: "paused", pinned: 0, error: null });
  render(<HistoryStorageSettings />);
  await screen.findByText(/Queued/);
  expect(api.historyAction).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Pause", exact: true }));
  await waitFor(() => expect(api.historyAction).toHaveBeenCalledWith("waiting-slot", "cancel"));
});
