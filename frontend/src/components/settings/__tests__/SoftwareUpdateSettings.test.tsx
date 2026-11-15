import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SoftwareUpdateSettings } from "../SoftwareUpdateSettings";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { checkForUpdates: vi.fn() } }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("checks without installing and offers the server's own upgrade instructions", async () => {
  vi.mocked(api.checkForUpdates).mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({ current_version: "0.1.18", latest_version: "0.1.19", available: true, method: "container" });
  render(<SoftwareUpdateSettings />);
  expect(api.checkForUpdates).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("updates.check"));
  expect(await screen.findByRole("alert")).toHaveTextContent("updates.checkFailed");
  fireEvent.click(screen.getByText("updates.check"));
  expect(await screen.findByText("updates.container")).toBeInTheDocument();
  expect(screen.queryByText("updates.install")).not.toBeInTheDocument();
});

it("uses the Desktop bridge, blocks duplicate installs, and allows a new check after failure", async () => {
  let rejectInstall!: (reason: Error) => void;
  const desktop = {
    isDesktop: true,
    checkForUpdates: vi.fn().mockResolvedValue({ current_version: "0.3.0", latest_version: "0.3.1", available: true, method: "desktop", recovery: "none" }),
    installUpdate: vi.fn(() => new Promise<void>((_, reject) => { rejectInstall = reject; })),
  };
  vi.stubGlobal("vibeDesktop", desktop);
  render(<SoftwareUpdateSettings />);
  fireEvent.click(screen.getByText("updates.check"));
  fireEvent.click(await screen.findByText("updates.install"));
  expect(screen.getByText("updates.install")).toBeDisabled();
  expect(desktop.installUpdate).toHaveBeenCalledOnce();
  expect(api.checkForUpdates).not.toHaveBeenCalled();
  rejectInstall(new Error("handoff failed"));
  expect(await screen.findByRole("alert")).toHaveTextContent("updates.installFailed");
  fireEvent.click(screen.getByText("updates.check"));
  await waitFor(() => expect(desktop.checkForUpdates).toHaveBeenCalledTimes(2));
});
