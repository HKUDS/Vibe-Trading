/** Chat message types */
export type AgentMessageType =
  | "user" | "thinking" | "tool_call" | "tool_result"
  | "answer" | "error" | "run_complete" | "compact" | "swarm_status";

export type SwarmAgentDisplayStatus =
  | "waiting"
  | "running"
  | "done"
  | "failed"
  | "blocked"
  | "retry"
  | "cancelled";

export interface SwarmAgentStatus {
  agentId: string;
  taskId?: string;
  role?: string;
  status: SwarmAgentDisplayStatus;
  tool?: string;
  elapsed_s?: number;
  iterations?: number;
  startedAt?: number;
  lastText?: string;
  error?: string;
  layer?: number;
  // Per-task cost telemetry from the swarm.event task_completed payload.
  // Names mirror the backend event keys; absent when the worker never reported.
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
}

export interface SwarmRunStatus {
  runId: string;
  preset: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "unknown";
  currentLayer: number;
  totalLayers: number;
  startedAt: number;
  completedAt?: number;
  finalReport?: string;
  reportIsPartial?: boolean;
  agents: SwarmAgentStatus[];
  // Run-level cost telemetry. Names mirror the GET /swarm/runs/{id} response,
  // but the values arrive from swarm events or, on replay, are hydrated from
  // that endpoint. All optional: absent on runs created before the fields existed.
  total_input_tokens?: number;
  total_output_tokens?: number;
  provider?: string | null;
  model?: string | null;
  /** Origin of the token counts (exact provider usage vs local estimate), per the backend's run metadata. */
  token_source?: string | null;
}

export interface AgentMessage {
  id: string;
  type: AgentMessageType;
  content: string;
  tool?: string;
  args?: Record<string, string>;
  status?: "running" | "ok" | "error";
  elapsed_ms?: number;
  timestamp: number;
  runId?: string;
  swarmRunId?: string;
  swarmStatus?: SwarmRunStatus;
  metrics?: Record<string, number>;
  equityCurve?: Array<{ time: string; equity: number | string }>;
  /** Phase label for thinking entries */
  stage?: string;
  /** Shadow Account id if render_shadow_report fired in this turn (RunCompleteCard renders a "View Shadow Report" button). */
  shadowId?: string;
}

/** Tool call tracking entry */
export interface ToolCallEntry {
  id: string;
  tool: string;
  arguments: Record<string, string>;
  status: "running" | "ok" | "error";
  preview?: string;
  elapsed_ms?: number;
  /** Live elapsed seconds while the tool is running (heartbeat). */
  elapsed_s?: number;
  /**
   * Structured progress emitted from the tool. All fields optional —
   * presence of `current`/`total > 0` indicates a determinate progress signal.
   */
  progress?: {
    stage?: string;
    current?: number;
    total?: number;
    message?: string;
  };
  timestamp: number;
}
