import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { Layout } from "../Layout";

const sessions = [
  {
    session_id: "session-1",
    title: "A very long session title that must truncate",
  },
];

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      "app.version": "v0.1.13",
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
  it("labels landmarks, brand, main content, and the new-chat affordance", () => {
    renderLayout();

    expect(screen.getByRole("complementary", { name: "Vibe-Trading sidebar" })).toHaveClass("max-md:w-12");
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Vibe-Trading" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New Chat" })).toHaveAttribute("title", "New Chat");
    expect(screen.getByText("Skip to main content")).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("main").parentElement).toHaveClass("relative");
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
});
