const STORAGE_KEY = "vibe_trading_api_auth_key";

export function getApiAuthKey(): string {
  return window.localStorage.getItem(STORAGE_KEY) || "";
}

export function setApiAuthKey(value: string): void {
  const trimmed = value.trim();
  if (trimmed) {
    window.localStorage.setItem(STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}

export function authHeaders(): Record<string, string> {
  const key = getApiAuthKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

/**
 * Append a short-lived, single-use SSE ticket to an EventSource URL.
 *
 * A browser `EventSource` cannot set an `Authorization` header, so we exchange
 * the stored API key (sent in a header on this POST) for a one-shot ticket via
 * `POST /auth/sse-ticket`, then open the stream with `?ticket=`. This keeps the
 * long-lived key out of URLs, browser history, and proxy/access logs.
 *
 * When no key is stored the backend is in loopback dev mode (auth bypassed), so
 * the URL is returned unchanged and no ticket round-trip is made. Tickets are
 * single-use: every connect/reconnect must mint a fresh one, so callers invoke
 * this per connection attempt rather than caching the result.
 */
export async function withAuthTicket(url: string): Promise<string> {
  const key = getApiAuthKey();
  if (!key) return url;
  const res = await fetch("/auth/sse-ticket", {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to obtain SSE ticket (HTTP ${res.status})`);
  }
  const data: unknown = await res.json();
  const ticket = (data as { ticket?: unknown } | null)?.ticket;
  if (typeof ticket !== "string" || !ticket) {
    throw new Error("SSE ticket response missing ticket");
  }
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}ticket=${encodeURIComponent(ticket)}`;
}
