import i18n from "@/i18n";

/**
 * Single source of truth for tool name → user-facing label.
 */
export const TOOL_LABELS: Record<string, string> = {
  load_skill: "Load strategy knowledge",
  write_file: "Generate code",
  edit_file: "Edit code",
  read_file: "Read file",
  backtest: "Run backtest",
  bash: "Run command",
  read_url: "Read webpage",
  read_document: "Read document",
  get_market_data: "Get market data",
  screen_market: "Screen market",
  factor_analysis: "Analyze factors",
  run_swarm: "Run agent team",
  web_search: "Search the web",
  financial_rigor: "Verify financial analysis",
  render_shadow_report: "Create shadow report",
  get_fundamentals: "Get fundamentals",
  trading_connections: "List trading connectors",
  trading_select_connection: "Select trading connector",
  trading_check: "Check trading connector",
  trading_account: "Read connector account",
  trading_positions: "Read connector positions",
  trading_orders: "Read connector orders",
  trading_quote: "Read connector quote",
  trading_history: "Read connector history",
  compact: "Summarize conversation",
  create_task: "Create task",
  update_task: "Update task",
  spawn_subagent: "Spawn sub-agent",
};

function humanizeToolName(tool: string): string {
  const humanized = tool.replace(/_/g, " ");
  return humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

export function localizeToolName(tool: string, fallback?: string): string {
  const defaultValue = TOOL_LABELS[tool] ?? fallback ?? humanizeToolName(tool);
  return i18n.t(`tools.${tool}` as never, { defaultValue });
}
