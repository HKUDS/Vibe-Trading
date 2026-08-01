import { useSyncExternalStore } from "react";

// Single source of truth for the applied theme. The `.dark` class on <html> is
// set before first paint by the inline script in index.html and toggled at
// runtime by useDarkMode; every consumer that must react to theme changes
// (echarts instances, code highlighting, canvas surfaces) subscribes here
// instead of instantiating its own useDarkMode state, which would never
// receive toggles made elsewhere.

const listeners = new Set<() => void>();

export function isDarkTheme(): boolean {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark");
}

export function publishThemeChange(): void {
  listeners.forEach((l) => l());
}

export function subscribeTheme(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function useThemeDark(): boolean {
  return useSyncExternalStore(subscribeTheme, isDarkTheme);
}
