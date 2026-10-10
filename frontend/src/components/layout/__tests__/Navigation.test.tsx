import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import i18n from "@/i18n";
import { SidebarNavigation } from "../SidebarNavigation";
import { PageHelp } from "../PageHelp";

beforeAll(async () => { await i18n.changeLanguage("en"); });

function renderNavigation(path = "/", collapsed = false) {
  return render(<MemoryRouter initialEntries={[path]}><SidebarNavigation collapsed={collapsed} /><PageHelp /></MemoryRouter>);
}

it("keeps every feature directly reachable and distinguishes tasks from tools and setup", () => {
  renderNavigation();
  expect(within(screen.getByRole("region", { name: "Everyday research" })).getAllByRole("link").map((link) => link.getAttribute("href")))
    .toEqual(["/", "/reports", "/portfolio"]);
  expect(within(screen.getByRole("region", { name: "Specialized analysis" })).getAllByRole("link").map((link) => link.getAttribute("href")))
    .toEqual(["/alpha-zoo", "/options", "/correlation"]);
  expect(within(screen.getByRole("region", { name: "Automation & setup" })).getAllByRole("link").map((link) => link.getAttribute("href")))
    .toEqual(["/scheduled", "/runtime", "/settings"]);
  expect(screen.getByRole("link", { name: "Research assistant" })).toHaveAttribute("aria-current", "page");
});

it("retains labels and help in a compact sidebar, including nested factor routes", () => {
  renderNavigation("/alpha-zoo/compare", true);
  const link = screen.getByRole("link", { name: "Factor research" });
  expect(link).toHaveAttribute("aria-current", "page");
  expect(link).toHaveAttribute("title", expect.stringContaining("stock-selection signals"));
  expect(screen.getByRole("navigation").querySelectorAll('[aria-current="page"]')).toHaveLength(1);
});

it("explains the backtest prerequisite and the separate location of chat-generated documents", () => {
  renderNavigation("/reports");
  fireEvent.click(screen.getByText("How to use Backtest reports"));
  expect(screen.getByText(/Download PDFs and other chat-generated documents/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Start with the research assistant" })).toHaveAttribute("href", "/");
});

it("resets page help on navigation and states the scheduler prerequisite", () => {
  renderNavigation("/reports");
  fireEvent.click(screen.getByText("How to use Backtest reports"));
  fireEvent.click(screen.getByRole("link", { name: "Scheduled research" }));
  const summary = screen.getByText("How to use Scheduled research");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(summary);
  expect(screen.getByText(/local scheduler must be enabled/)).toBeVisible();
});

it("opens a labeled feature menu in compact mode and returns focus on Escape", () => {
  renderNavigation("/", true);
  const trigger = screen.getByRole("button", { name: "Browse features" });
  fireEvent.click(trigger);
  const menu = screen.getByRole("navigation", { name: "Browse features" });
  expect(within(menu).getByText("Options analysis")).toBeVisible();
  expect(within(menu).getByText("Trading status")).toBeVisible();
  expect(within(menu).getAllByRole("link")).toHaveLength(9);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("navigation", { name: "Browse features" })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("closes the feature menu after selecting a destination", () => {
  renderNavigation("/", true);
  fireEvent.click(screen.getByRole("button", { name: "Browse features" }));
  const menu = screen.getByRole("navigation", { name: "Browse features" });
  fireEvent.click(within(menu).getByRole("link", { name: "Backtest reports" }));
  expect(screen.queryByRole("navigation", { name: "Browse features" })).not.toBeInTheDocument();
  expect(screen.getByText("How to use Backtest reports")).toBeInTheDocument();
});
