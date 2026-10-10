import { useCallback, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";

const drafts = new Map<string, unknown>();
const listeners = new Map<string, Set<() => void>>();

/** Forget a draft when explicitly starting over. */
export function clearAnalysisState(key: string): void {
  const storageKey = `vibe-analysis-v1:${key}`;
  drafts.delete(storageKey);
  try { sessionStorage.removeItem(storageKey); } catch { /* blocked storage */ }
}

/** Tab-local drafts remain available while a background analysis finishes. */
export function useAnalysisState<T extends object>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const storageKey = `vibe-analysis-v1:${key}`;
  if (!drafts.has(storageKey)) {
    let value = initial;
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
      if (saved && typeof saved === "object" && !Array.isArray(saved)
        && Object.entries(initial).every(([name, fallback]) => (fallback === null && !(name in saved)) || name in saved && (fallback === null
          || (Array.isArray(fallback) ? Array.isArray(saved[name])
            : typeof fallback === "object" ? saved[name] !== null && typeof saved[name] === "object" && !Array.isArray(saved[name])
            : typeof saved[name] === typeof fallback || (typeof fallback === "string" && saved[name] === null))))) value = { ...initial, ...saved };
    } catch { /* blocked or invalid storage falls back to a fresh draft */ }
    drafts.set(storageKey, value);
  }
  const subscribe = useCallback((listener: () => void) => {
    const group = listeners.get(storageKey) ?? new Set();
    listeners.set(storageKey, group);
    group.add(listener);
    return () => { group.delete(listener); };
  }, [storageKey]);
  const getSnapshot = useCallback(() => drafts.get(storageKey) as T, [storageKey]);
  const value = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const setValue = useCallback<Dispatch<SetStateAction<T>>>((update) => {
    const previous = drafts.get(storageKey) as T;
    const next = typeof update === "function" ? (update as (v: T) => T)(previous) : update;
    drafts.set(storageKey, next);
    try { sessionStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* retain memory when storage is blocked */ }
    listeners.get(storageKey)?.forEach((listener) => listener());
  }, [storageKey]);
  return [value, setValue];
}
