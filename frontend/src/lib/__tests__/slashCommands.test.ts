import { describe, expect, it } from "vitest";
import { filterCapabilities, getSlashContext } from "../slashCommands";

describe("slash command parsing", () => {
  it("opens the root, skill, and tool menus only at a token boundary", () => {
    expect(getSlashContext("/", 1)?.kind).toBe("root");
    expect(getSlashContext("look /skill", 11)?.kind).toBe("skills");
    expect(getSlashContext("look /tool", 10)?.kind).toBe("tools");
    expect(getSlashContext("BTC/USDT", 8)).toBeNull();
  });

  it("filters by stable name, category, or backend description", () => {
    const items = [
      { name: "technical-basic", category: "analysis", description: "momentum" },
      { name: "get_market_data", category: "market-data", description: "行情数据" },
    ];
    expect(filterCapabilities(items, "market")).toHaveLength(1);
    expect(filterCapabilities(items, "momentum")[0].name).toBe("technical-basic");
  });
});
