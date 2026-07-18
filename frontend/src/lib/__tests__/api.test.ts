import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";

async function loadApiModule() {
  vi.resetModules();
  return import("../api");
}

describe("api request helper", () => {
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
});
