import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getApiAuthKey, setApiAuthKey, authHeaders, withAuthTicket } from "../apiAuth";

describe("apiAuth", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("getApiAuthKey", () => {
    it("returns empty string when nothing stored", () => {
      expect(getApiAuthKey()).toBe("");
    });
    it("returns stored key", () => {
      localStorage.setItem("vibe_trading_api_auth_key", "my-secret");
      expect(getApiAuthKey()).toBe("my-secret");
    });
  });

  describe("setApiAuthKey", () => {
    it("stores trimmed value", () => {
      setApiAuthKey("  abc-123  ");
      expect(localStorage.getItem("vibe_trading_api_auth_key")).toBe("abc-123");
    });
    it("removes key when value is empty/whitespace", () => {
      setApiAuthKey("abc");
      setApiAuthKey("   ");
      expect(localStorage.getItem("vibe_trading_api_auth_key")).toBeNull();
    });
    it("removes key when value is empty string", () => {
      setApiAuthKey("abc");
      setApiAuthKey("");
      expect(localStorage.getItem("vibe_trading_api_auth_key")).toBeNull();
    });
  });

  describe("authHeaders", () => {
    it("returns empty object when no key set", () => {
      expect(authHeaders()).toEqual({});
    });
    it("returns Bearer header when key exists", () => {
      setApiAuthKey("token-xyz");
      expect(authHeaders()).toEqual({ Authorization: "Bearer token-xyz" });
    });
  });

  describe("withAuthTicket", () => {
    it("returns url unchanged and makes no request when no key (dev/loopback)", async () => {
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);
      await expect(withAuthTicket("http://api/stream")).resolves.toBe("http://api/stream");
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("mints a ticket via header-authed POST and appends ?ticket=", async () => {
      setApiAuthKey("token-xyz");
      const fetchSpy = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ticket: "TICKET-123" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", fetchSpy);

      const url = await withAuthTicket("http://api/stream");

      expect(url).toBe("http://api/stream?ticket=TICKET-123");
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const [path, init] = fetchSpy.mock.calls[0];
      expect(path).toBe("/auth/sse-ticket");
      expect(init.method).toBe("POST");
      expect(init.headers).toEqual({ Authorization: "Bearer token-xyz" });
    });

    it("never puts the raw API key in the returned URL", async () => {
      setApiAuthKey("super-secret-key");
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ ticket: "one-shot" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        ),
      );
      const url = await withAuthTicket("http://api/stream");
      expect(url).not.toContain("super-secret-key");
      expect(url).not.toContain("api_key=");
      expect(url).toContain("ticket=one-shot");
    });

    it("joins with & when the url already has a query string", async () => {
      setApiAuthKey("k");
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ ticket: "t1" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        ),
      );
      const url = await withAuthTicket("http://api/stream?replay=active");
      expect(url).toBe("http://api/stream?replay=active&ticket=t1");
    });

    it("throws when the ticket endpoint returns a non-OK status", async () => {
      setApiAuthKey("k");
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 401 })));
      await expect(withAuthTicket("http://api/stream")).rejects.toThrow(/HTTP 401/);
    });

    it("throws when the response is missing a ticket", async () => {
      setApiAuthKey("k");
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({}), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        ),
      );
      await expect(withAuthTicket("http://api/stream")).rejects.toThrow(/missing ticket/);
    });
  });
});
