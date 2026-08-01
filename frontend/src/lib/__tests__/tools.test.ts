import i18n from "@/i18n";
import { localizeToolName, TOOL_LABELS } from "../tools";

describe("TOOL_LABELS", () => {
  it("maps known tool names to user-facing labels", () => {
    expect(TOOL_LABELS["backtest"]).toBe("Run backtest");
    expect(TOOL_LABELS["write_file"]).toBe("Generate code");
    expect(TOOL_LABELS["edit_file"]).toBe("Edit code");
    expect(TOOL_LABELS["bash"]).toBe("Run command");
    expect(TOOL_LABELS["compact"]).toBe("Summarize conversation");
  });

  it("maps every demo-path tool to an English user-facing label", () => {
    expect(TOOL_LABELS).toMatchObject({
      get_market_data: "Get market data",
      screen_market: "Screen market",
      factor_analysis: "Analyze factors",
      run_swarm: "Run agent team",
      web_search: "Search the web",
      financial_rigor: "Verify financial analysis",
      render_shadow_report: "Create shadow report",
      get_fundamentals: "Get fundamentals",
    });
  });

  it("contains all trading connector tools", () => {
    const tradingKeys = Object.keys(TOOL_LABELS).filter((k) => k.startsWith("trading_"));
    expect(tradingKeys.length).toBeGreaterThanOrEqual(6);
  });
});

describe("localizeToolName", () => {
  it("resolves the tools.<name> i18n key", () => {
    i18n.addResource("en", "translation", "tools.localized_test_tool", "Localized tool");

    expect(localizeToolName("localized_test_tool")).toBe("Localized tool");
  });

  it("returns fallback for unknown tools when fallback provided", () => {
    expect(localizeToolName("unknown_tool", "My Fallback")).toBe("My Fallback");
  });

  it("humanizes unknown tools with no fallback", () => {
    expect(localizeToolName("some_new_tool")).toBe("Some new tool");
  });

  it("uses TOOL_LABELS as the default before an explicit fallback", () => {
    expect(localizeToolName("bash", "ignored")).toBe("Run command");
  });
});
