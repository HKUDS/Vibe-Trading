// Safe localStorage access. Storage APIs THROW (SecurityError/QuotaExceededError)
// in restricted contexts — blocked third-party iframes, WebViews with DOM storage
// off, zero-quota private modes. Only the index.html boot script guards itself;
// every in-app access must go through these wrappers so a locked-down browser
// degrades to in-memory defaults instead of white-screening the app.

export function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — preference simply won't persist */
  }
}

export function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}
