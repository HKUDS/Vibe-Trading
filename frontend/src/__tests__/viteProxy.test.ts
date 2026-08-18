import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("Vite API proxy config", () => {
  const configPath = path.resolve(__dirname, "../../vite.config.ts");
  const config = fs.readFileSync(configPath, "utf8");

  it("proxies channel runtime endpoints", () => {
    expect(config).toContain('"/channels"');
  });

  it("proxies settings endpoints", () => {
    expect(config).toContain('"/settings/llm"');
    expect(config).toContain('"/settings/data-sources"');
  });

  it("proxies authentication endpoints", () => {
    expect(config).toContain('"/auth"');
  });

  it("keeps the portfolio SPA route on the HTML fallback while preserving API proxying", () => {
    expect(config).toContain('"/portfolio": apiProxyWithHtmlFallback');
  });
});
