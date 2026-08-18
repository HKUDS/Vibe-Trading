import { describe, expect, it } from "vitest";
import { escapeHtml } from "../escapeHtml";

describe("escapeHtml", () => {
  it("escapes ampersand", () => {
    expect(escapeHtml("a & b")).toBe("a &amp; b");
  });

  it("escapes less-than", () => {
    expect(escapeHtml("a < b")).toBe("a &lt; b");
  });

  it("escapes greater-than", () => {
    expect(escapeHtml("a > b")).toBe("a &gt; b");
  });

  it("escapes double quote", () => {
    expect(escapeHtml('a " b')).toBe("a &quot; b");
  });

  it("escapes single quote", () => {
    expect(escapeHtml("a ' b")).toBe("a &#39; b");
  });

  it("escapes all five characters in one pass without double-escaping", () => {
    expect(escapeHtml(`<img src="x" onerror='alert(&)'>`)).toBe(
      "&lt;img src=&quot;x&quot; onerror=&#39;alert(&amp;)&#39;&gt;",
    );
  });

  it("passes already-safe strings through unchanged", () => {
    expect(escapeHtml("plain text 123")).toBe("plain text 123");
    expect(escapeHtml("2024-01-02")).toBe("2024-01-02");
    expect(escapeHtml("600519.SH")).toBe("600519.SH");
    expect(escapeHtml("")).toBe("");
  });
});
