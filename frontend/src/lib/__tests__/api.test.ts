import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";

async function loadApiModule() {
  vi.resetModules();
  return import("../api");
}

describe("generated report download", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it("downloads PDF bytes with bearer authentication and keeps the key out of the URL", async () => {
    vi.stubGlobal("localStorage", { getItem: vi.fn((key) => key === "vibe_trading_api_auth_key" ? "report-test-key" : "en"), setItem: vi.fn(), removeItem: vi.fn() });
    const fetch = vi.fn().mockResolvedValue(new Response("%PDF-contents", { headers: { "content-type": "application/pdf" } }));
    vi.stubGlobal("fetch", fetch);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:report");
      static revokeObjectURL = vi.fn();
    });
    const { downloadGeneratedReport } = await loadApiModule();
    await downloadGeneratedReport("a".repeat(32), "研究报告.pdf");
    expect(fetch).toHaveBeenCalledWith(`/api/reports/${"a".repeat(32)}`, expect.objectContaining({ headers: { Authorization: "Bearer report-test-key" } }));
    expect(click).toHaveBeenCalledOnce();
  });
});

describe("api request helper", () => {
  it("translates the server's message-size error into a recovery instruction", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: "message_too_long", max_length: 100_000, message: "Shorten input" },
    }), { status: 422, headers: { "content-type": "application/json" } })));
    const { api } = await loadApiModule();
    await expect(api.sendMessage("session", "oversized")).rejects.toMatchObject({
      status: 422, code: "message_too_long", message: expect.stringContaining("Shorten it"),
    });
  });
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => ""),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("rejects non-JSON responses with a descriptive error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<!doctype html><html><body>SPA</body></html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        }),
      ),
    );

    const { api } = await loadApiModule();

    await expect(api.getChannelStatus()).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      message: expect.stringContaining("Expected JSON from /channels/status, got text/html"),
    } satisfies Partial<ApiError>);
  });

  it("posts an authenticated connector verification request with an encoded profile id", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "remote-test-key"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", connection_state: "connected" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await expect(api.verifyConnector("longbridge/live sdk")).resolves.toMatchObject({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/live/connectors/longbridge%2Flive%20sdk/verify?force=true",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer remote-test-key" }),
      }),
    );
  });

  it("sends the stored API key when fetching a correlation matrix", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "remote-test-key"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ labels: ["A", "B"], matrix: [[1, 0], [0, 1]] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await expect(api.getCorrelation("A,B", 90, "pearson")).resolves.toEqual({
      labels: ["A", "B"],
      matrix: [[1, 0], [0, 1]],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/correlation?codes=A%2CB&days=90&method=pearson",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer remote-test-key" }),
      }),
    );
  });

  it("sends the stored API key when fetching a correlation regime timeline", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "remote-test-key"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    const regime = {
      labels: ["A", "B"],
      dates: ["2024-01-01"],
      density: [0.5],
      smoothed: [0.5],
      fused: [0],
      episodes: [],
      params: {},
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(regime), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await expect(api.getCorrelationRegime("A,B", 90)).resolves.toEqual(regime);
    expect(fetchMock).toHaveBeenCalledWith(
      "/correlation/regime?codes=A%2CB&days=90",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer remote-test-key" }),
      }),
    );
  });

  it("resolves authorization errors through the active i18n key", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "server fallback" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const apiModule = await loadApiModule();
    const { default: i18n } = await import("@/i18n");
    i18n.addResource(
      "en",
      "translation",
      "agent.authRequired",
      "Add an API key in Settings.",
    );
    await i18n.changeLanguage("en");

    expect(apiModule.AUTH_REQUIRED_MESSAGE).toBe("Add an API key in Settings.");
    await expect(apiModule.api.getCorrelation("A,B", 90, "pearson")).rejects.toMatchObject({
      status: 401,
      message: "Add an API key in Settings.",
    } satisfies Partial<ApiError>);
  });
});

describe("API failure recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubEnv("VITE_API_TIMEOUT_MS", "1000");
    vi.stubGlobal("localStorage", { getItem: () => "", setItem: vi.fn(), removeItem: vi.fn() });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  function hangUntilAbort(signal: AbortSignal) {
    return new Promise<never>((_, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    });
  }

  it("bounds a stalled conversation-list request and clears its timer", async () => {
    vi.stubGlobal("fetch", vi.fn((_url, init) => hangUntilAbort(init.signal)));
    const { api } = await loadApiModule();
    const pending = expect(api.listSessions()).rejects.toMatchObject({
      code: "request_timeout", message: expect.stringContaining("timed out"),
    });
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the timeout active while reading a stalled response body", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => ({
      ok: true,
      text: () => hangUntilAbort(init.signal),
    })));
    const { api } = await loadApiModule();
    const pending = expect(api.listSessions()).rejects.toMatchObject({ code: "request_timeout" });
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
  });

  it("explains a failed server connection in the active locale", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const { api } = await loadApiModule();
    await expect(api.listSessions()).rejects.toMatchObject({
      code: "network_error", message: expect.stringContaining("Check that it is running"),
    });
  });

  it("does not replay a timed-out write and reports its uncertain outcome", async () => {
    const fetch = vi.fn((_url, init) => hangUntilAbort(init.signal));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    const pending = expect(api.renameSession("session", "new title")).rejects.toMatchObject({
      code: "request_timeout", message: expect.stringContaining("check the current state"),
    });
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
    expect(fetch).toHaveBeenCalledOnce();
  });
});
