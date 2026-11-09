import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("research comparison export", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", { getItem: vi.fn(() => ""), setItem: vi.fn(), removeItem: vi.fn() });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("encodes the exact revision pair and requested format", async () => {
    const payload = { filename: "comparison.md", media_type: "text/markdown; charset=utf-8", content: "# Comparison\n", sha256: "abc" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("../api");

    await expect(api.exportResearchArtifactComparison("ra/1", "from/?", "to#", "markdown")).resolves.toEqual(payload);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/research-artifacts/ra%2F1/export?format=markdown&from_revision_id=from%2F%3F&to_revision_id=to%23",
      expect.anything(),
    );
  });
});
