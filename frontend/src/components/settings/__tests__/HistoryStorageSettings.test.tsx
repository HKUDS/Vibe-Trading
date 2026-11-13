import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import "@/i18n";
import i18n from "@/i18n";
import { api } from "@/lib/api";
import { HistoryStorageSettings } from "../HistoryStorageSettings";

vi.mock("@/lib/api", () => ({ api: {
  historyStorage: vi.fn(), historyJobs: vi.fn(), saveHistoryStorage: vi.fn(),
  planHistory: vi.fn(), createHistory: vi.fn(), historyAction: vi.fn(),
  pinHistory: vi.fn(), deleteHistory: vi.fn(), pruneHistory: vi.fn(),
} }));
const storage = { quota_bytes: 256 * 1024 ** 2, retention_days: 30, used_bytes: 1024 ** 2, reserved_bytes: 0, path: "/test" };
beforeEach(async () => {
  vi.clearAllMocks(); await i18n.changeLanguage("en");
  vi.mocked(api.historyStorage).mockResolvedValue(storage);
  vi.mocked(api.historyJobs).mockResolvedValue([]);
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
