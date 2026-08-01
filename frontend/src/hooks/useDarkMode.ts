import { useCallback, useEffect, useRef, useState } from "react";
import { safeGet, safeSet } from "@/lib/storage";
import { publishThemeChange } from "@/lib/theme-store";

const STORAGE_KEY = "qa-theme";

function getSystemPreference(): boolean {
  if (typeof window.matchMedia !== "function") return false;
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

function getPreferredTheme(): boolean {
  const saved = safeGet(STORAGE_KEY);
  if (saved === "dark") return true;
  if (saved === "light") return false;
  return getSystemPreference();
}

export function useDarkMode() {
  const [dark, setDark] = useState(getPreferredTheme);
  const darkRef = useRef(dark);

  useEffect(() => {
    darkRef.current = dark;
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    publishThemeChange();
  }, [dark]);

  useEffect(() => {
    const syncTheme = (nextDark: boolean) => {
      const changed = darkRef.current !== nextDark;
      darkRef.current = nextDark;
      setDark(nextDark);
      if (!changed) publishThemeChange();
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY && event.key !== null) return;
      syncTheme(getPreferredTheme());
    };
    window.addEventListener("storage", onStorage);

    if (typeof window.matchMedia !== "function") {
      return () => window.removeEventListener("storage", onStorage);
    }

    let mediaQuery: MediaQueryList;
    try {
      mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return () => window.removeEventListener("storage", onStorage);
    }

    const onSystemChange = (event: MediaQueryListEvent) => {
      if (safeGet(STORAGE_KEY) !== null) return;
      syncTheme(event.matches);
    };
    mediaQuery.addEventListener("change", onSystemChange);

    return () => {
      window.removeEventListener("storage", onStorage);
      mediaQuery.removeEventListener("change", onSystemChange);
    };
  }, []);

  const toggle = useCallback(() => {
    const nextDark = !darkRef.current;
    darkRef.current = nextDark;
    safeSet(STORAGE_KEY, nextDark ? "dark" : "light");
    setDark(nextDark);
  }, []);

  return { dark, toggle };
}
