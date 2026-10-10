import { Activity, BarChart3, Bot, CalendarClock, CandlestickChart, FileText, Layers, Settings, WalletCards } from "lucide-react";

export const NAVIGATION_GROUPS = [
  { id: "research", items: [
    { id: "agent", to: "/", icon: Bot },
    { id: "reports", to: "/reports", icon: FileText },
    { id: "portfolio", to: "/portfolio", icon: WalletCards },
  ] },
  { id: "analysis", items: [
    { id: "alphaZoo", to: "/alpha-zoo", icon: Layers },
    { id: "optionsLab", to: "/options", icon: CandlestickChart },
    { id: "correlation", to: "/correlation", icon: BarChart3 },
  ] },
  { id: "automation", items: [
    { id: "scheduled", to: "/scheduled", icon: CalendarClock },
    { id: "runtime", to: "/runtime", icon: Activity },
    { id: "settings", to: "/settings", icon: Settings },
  ] },
] as const;

export type NavigationItem = typeof NAVIGATION_GROUPS[number]["items"][number];

export function isNavigationActive(to: string, pathname: string): boolean {
  return to === "/" ? pathname === "/" || pathname === "/agent"
    : pathname === to || pathname.startsWith(`${to}/`);
}
