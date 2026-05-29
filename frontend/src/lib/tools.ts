/**
 * Single source of truth for tool name → user-facing label.
 */
export const TOOL_LABELS: Record<string, string> = {
  load_skill: "Load strategy knowledge",
  write_file: "Generate code",
  edit_file: "Edit code",
  read_file: "Read file",
  run_backtest: "Run backtest",
  bash: "Run command",
  read_url: "Read webpage",
  read_document: "Read document",
  compact: "Compact context",
  create_task: "Create task",
  update_task: "Update task",
  spawn_subagent: "Spawn sub-agent",
};

export function localizeToolName(tool: string, fallback?: string): string {
  if (tool in TOOL_LABELS) {
    return TOOL_LABELS[tool];
  }
  if (fallback !== undefined) {
    return fallback;
  }
  return tool;
}
