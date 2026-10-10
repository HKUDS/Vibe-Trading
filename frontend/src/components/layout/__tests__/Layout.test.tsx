import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { Layout } from "../Layout";
import { api } from "@/lib/api";
import { toast } from "sonner";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const sessions = [
  {
    session_id: "session-1",
    title: "A very long session title that must truncate",
  },
];

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      "app.version": "v0.1.16",
      "layout.agent": "Agent",
      "layout.alphaZoo": "Alpha Zoo",
      "layout.cancel": "Cancel",
      "layout.collapse": "Collapse",
      "layout.confirm": "Confirm",
      "layout.correlation": "Correlation Matrix",
      "layout.dark": "Dark",
      "layout.delete": "Delete",
      "layout.expand": "Expand",
      "layout.home": "Home",
      "layout.language": "Language",
      "layout.light": "Light",
      "layout.mainNavigation": "Main navigation",
      "layout.newChat": "New Chat",
      "layout.noSessions": "No sessions yet",
      "layout.rename": "Rename",
      "layout.reports": "Reports",
      "layout.runtime": "Runtime",
      "layout.sessions": "Sessions",
      "layout.settings": "Settings",
      "layout.sidebar": "Vibe-Trading sidebar",
      "layout.skipToMain": "Skip to main content",
    })[key] ?? key,
    i18n: {
      language: "en",
      languages: ["en"],
      changeLanguage: vi.fn().mockResolvedValue(undefined),
    },
  }),
}));

vi.mock("@/hooks/useDarkMode", () => ({
  useDarkMode: () => ({ dark: false, toggle: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    listSessions: vi.fn().mockResolvedValue([
      {
        session_id: "session-1",
        title: "A very long session title that must truncate",
      },
    ]),
    deleteSession: vi.fn().mockResolvedValue(undefined),
    renameSession: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock("@/stores/agent", () => ({
  useAgentStore: (selector: (state: {
    sseStatus: string;
    sseRetryAttempt: number;
    streamingSessionId: null;
  }) => unknown) => selector({
    sseStatus: "connected",
    sseRetryAttempt: 0,
    streamingSessionId: null,
  }),
}));

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/agent"]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/agent" element={<div>Agent content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Layout accessibility", () => {
  beforeEach(() => {
    window.localStorage.removeItem("qa-sidebar");
    vi.mocked(toast.error).mockClear();
    vi.mocked(api.listSessions).mockReset().mockResolvedValue(sessions as never);
    vi.mocked(api.renameSession).mockReset().mockResolvedValue({ status: "ok" });
    vi.mocked(api.deleteSession).mockReset().mockResolvedValue({ status: "ok" });
  });
  it("labels landmarks, brand, main content, and the new-chat affordance", () => {
    renderLayout();

    expect(screen.getByRole("complementary", { name: "Vibe-Trading sidebar" })).toHaveClass("max-md:w-12");
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Vibe-Trading" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New Chat" })).toHaveAttribute("title", "New Chat");
    expect(screen.getByText("Skip to main content")).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("main").parentElement).toHaveClass("relative");
    // Regression: <main> is a flex item inside a flex-col/overflow-hidden
    // parent. Without min-h-0, a flex item's default min-height:auto lets it
    // grow past its allotted space to fit tall content (e.g. a long
    // generated report) instead of respecting its own overflow-auto -- the
    // excess then gets hard-clipped by the parent's overflow-hidden with no
    // scrollbar at all, rather than scrolling into view.
    expect(screen.getByRole("main")).toHaveClass("flex-1", "min-h-0", "overflow-auto");
  });

  it("exposes session actions on keyboard focus and labels the rename input", async () => {
    renderLayout();

    const title = await screen.findByText(sessions[0].title);
    expect(title).toHaveClass("min-w-0", "truncate");

    const renameButton = screen.getByRole("button", { name: "Rename" });
    expect(renameButton.parentElement).toHaveClass("group-focus-within:opacity-100");
    fireEvent.click(renameButton);

    expect(screen.getByRole("textbox", { name: `Rename: ${sessions[0].title}` })).toHaveClass(
      "focus:ring-2",
      "focus:ring-primary/40",
    );
  });

  it("does not crash when localStorage access is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });

    expect(() => renderLayout()).not.toThrow();
  });

  it("uses button disclosure semantics for the language switcher", () => {
    renderLayout();

    const languageButton = screen.getByRole("button", { name: "Language" });
    expect(languageButton).toHaveAttribute("aria-expanded", "false");
    expect(languageButton).not.toHaveAttribute("aria-haspopup");
  });

  it("synchronizes the sidebar preference from another tab", () => {
    window.localStorage.setItem("qa-sidebar", "expanded");
    renderLayout();
    const sidebar = screen.getByRole("complementary", { name: "Vibe-Trading sidebar" });
    expect(sidebar).toHaveClass("w-64");

    window.localStorage.setItem("qa-sidebar", "collapsed");
    fireEvent(window, new StorageEvent("storage", { key: "qa-sidebar" }));

    expect(sidebar).toHaveClass("w-12");
  });

  it("shows a connection failure instead of an empty history, and retries", async () => {
    vi.mocked(api.listSessions).mockRejectedValueOnce(new Error("Backend unavailable"));
    renderLayout();
    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
    expect(screen.queryByText("No sessions yet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "connection.retry" }));
    expect(await screen.findByText(sessions[0].title)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retains the rename draft and surfaces a failed save", async () => {
    vi.mocked(api.renameSession).mockRejectedValueOnce(new Error("Rename failed"));
    renderLayout();
    await screen.findByText(sessions[0].title);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "My renamed chat" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Rename failed"));
    expect(input).toHaveValue("My renamed chat");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByText("My renamed chat")).toBeInTheDocument();
  });

  it("keeps a failed deletion visible so it can be retried", async () => {
    vi.mocked(api.deleteSession).mockRejectedValueOnce(new Error("Delete failed"));
    renderLayout();
    await screen.findByText(sessions[0].title);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Delete failed"));
    expect(screen.getByText(sessions[0].title)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByText(sessions[0].title)).not.toBeInTheDocument());
  });

  it("does not submit rename twice when Enter is followed by blur", async () => {
    let complete!: (value: { status: string }) => void;
    vi.mocked(api.renameSession).mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    renderLayout();
    await screen.findByText(sessions[0].title);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Renamed once" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(api.renameSession).toHaveBeenCalledOnce();
    await act(async () => complete({ status: "ok" }));
    expect(screen.getByText("Renamed once")).toBeInTheDocument();
  });

  it("keeps history, new chat and language reachable with a collapsed sidebar", async () => {
    window.localStorage.setItem("qa-sidebar", "collapsed");
    renderLayout();
    const trigger = screen.getByRole("button", { name: "Sessions" });
    expect(screen.queryByRole("link", { name: "New Chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Language" })).toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText(sessions[0].title)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New Chat" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});
