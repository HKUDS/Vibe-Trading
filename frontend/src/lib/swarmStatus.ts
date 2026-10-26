import type {
  SwarmAgentDisplayStatus,
  SwarmAgentStatus,
  SwarmRunStatus,
} from "@/types/agent";

type AnyRecord = Record<string, unknown>;

function asRecord(value: unknown): AnyRecord {
  return value && typeof value === "object" ? value as AnyRecord : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asTokenSource(value: unknown): SwarmRunStatus["token_source"] {
  return value === "provider" || value === "estimated" ? value : undefined;
}

/**
 * Conservative provenance merge — mirrors the backend runtime's
 * `_merge_token_source`: a missing/unknown incoming label never overwrites a
 * real one, and one "estimated" contribution contaminates the cumulative total.
 */
function mergeTokenSource(
  current: SwarmRunStatus["token_source"],
  incoming: unknown,
): SwarmRunStatus["token_source"] {
  const label = asTokenSource(incoming);
  if (label === undefined) return current;
  if (current == null || label === "estimated") return label;
  return current;
}

/**
 * Recompute run totals as the sum over agents. Idempotent under replayed
 * events because each task_completed re-sets (not accumulates) its agent's
 * own values. Returns undefined — never a fabricated 0 — when no agent
 * reported a given direction.
 */
function recomputeRunTokenTotals(status: SwarmRunStatus): SwarmRunStatus {
  const sum = (pick: (agent: SwarmAgentStatus) => number | undefined) => {
    const values = status.agents.map(pick).filter((v): v is number => v != null);
    return values.length > 0 ? values.reduce((acc, v) => acc + v, 0) : undefined;
  };
  return {
    ...status,
    total_input_tokens: sum((agent) => agent.input_tokens),
    total_output_tokens: sum((agent) => agent.output_tokens),
  };
}

function timestampMs(value: unknown): number | undefined {
  if (typeof value !== "string") return undefined;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : undefined;
}

function serverRunTimes(record: AnyRecord): {
  startedAt?: number;
  completedAt?: number;
} {
  const tasks = Array.isArray(record.tasks) ? record.tasks.map(asRecord) : [];
  const taskStarts = tasks
    .map((task) => timestampMs(task.started_at))
    .filter((value): value is number => value != null);
  const taskCompletions = tasks
    .map((task) => timestampMs(task.completed_at))
    .filter((value): value is number => value != null);
  const explicitStart = timestampMs(record.started_at)
    ?? timestampMs(record.created_at)
    ?? timestampMs(record.timestamp);
  const explicitCompletion = timestampMs(record.completed_at);

  return {
    startedAt: explicitStart ?? (taskStarts.length > 0 ? Math.min(...taskStarts) : undefined),
    completedAt: explicitCompletion
      ?? (taskCompletions.length > 0 ? Math.max(...taskCompletions) : undefined),
  };
}

function normalizeRunStatus(value: unknown): SwarmRunStatus["status"] {
  const status = asString(value, "unknown");
  if (["pending", "running", "completed", "failed", "cancelled"].includes(status)) {
    return status as SwarmRunStatus["status"];
  }
  return "unknown";
}

function mapTaskStatus(value: unknown): SwarmAgentDisplayStatus {
  switch (asString(value)) {
    case "in_progress":
      return "running";
    case "completed":
      return "done";
    case "failed":
      return "failed";
    case "blocked":
      return "blocked";
    case "cancelled":
      return "cancelled";
    case "pending":
    default:
      return "waiting";
  }
}

function eventAgentKey(event: AnyRecord): { agentId: string; taskId?: string } {
  const data = asRecord(event.data);
  return {
    agentId: asString(event.agent_id) || asString(data.agent_id),
    taskId: asString(event.task_id) || asString(data.task_id) || undefined,
  };
}

function updateAgent(
  status: SwarmRunStatus,
  selector: { agentId?: string; taskId?: string },
  update: (agent: SwarmAgentStatus) => SwarmAgentStatus,
): SwarmRunStatus {
  const idx = status.agents.findIndex((agent) => (
    (selector.taskId && agent.taskId === selector.taskId) ||
    (selector.agentId && agent.agentId === selector.agentId)
  ));
  if (idx < 0) {
    if (!selector.agentId) return status;
    return {
      ...status,
      agents: [
        ...status.agents,
        update({ agentId: selector.agentId, taskId: selector.taskId, status: "waiting" }),
      ],
    };
  }

  const agents = [...status.agents];
  agents[idx] = update(agents[idx]);
  return { ...status, agents };
}

export function buildSwarmStatusFromStarted(data: AnyRecord): SwarmRunStatus | null {
  const runId = asString(data.run_id);
  if (!runId) return null;

  const agentMeta = new Map<string, { role?: string }>();
  const agentsRaw = Array.isArray(data.agents) ? data.agents : [];
  for (const item of agentsRaw) {
    const agent = asRecord(item);
    const id = asString(agent.id);
    if (id) agentMeta.set(id, { role: asString(agent.role) || undefined });
  }

  const tasksRaw = Array.isArray(data.tasks) ? data.tasks : [];
  const agents: SwarmAgentStatus[] = tasksRaw.map((item) => {
    const task = asRecord(item);
    const agentId = asString(task.agent_id);
    const meta = agentMeta.get(agentId);
    return {
      agentId,
      taskId: asString(task.id) || undefined,
      role: meta?.role,
      status: mapTaskStatus(task.status),
      iterations: asNumber(task.worker_iterations) ?? 0,
      lastText: asString(task.summary) || undefined,
      error: asString(task.error) || undefined,
    };
  }).filter((agent) => agent.agentId);

  for (const [agentId, meta] of agentMeta) {
    if (!agents.some((agent) => agent.agentId === agentId)) {
      agents.push({ agentId, role: meta.role, status: "waiting", iterations: 0 });
    }
  }

  return {
    runId,
    preset: asString(data.preset) || asString(data.preset_name) || "swarm",
    status: normalizeRunStatus(data.status),
    currentLayer: 0,
    totalLayers: 0,
    startedAt: serverRunTimes(data).startedAt ?? 0,
    agents,
  };
}

/**
 * Mark a run as stopped by the user. The cancel request reaches the runtime
 * asynchronously, so the card is settled locally first — otherwise it keeps
 * showing "running" until the last worker notices the flag.
 */
export function stopSwarmRun(status: SwarmRunStatus, at = Date.now()): SwarmRunStatus {
  return {
    ...status,
    status: "cancelled",
    completedAt: status.completedAt ?? at,
    agents: status.agents.map((agent) => (
      agent.status === "running" || agent.status === "waiting"
        ? { ...agent, status: "cancelled" }
        : agent
    )),
  };
}

export function applySwarmEvent(current: SwarmRunStatus, rawEvent: unknown): SwarmRunStatus {
  // A stopped run is terminal. Events already in flight when the user pressed
  // stop (a worker finishing its iteration, the runtime's own run_completed)
  // arrive afterwards and would repaint the card as running or completed, so
  // they are dropped rather than applied.
  if (current.status === "cancelled") return current;

  const event = asRecord(rawEvent);
  const data = asRecord(event.data);
  const type = asString(event.type);
  const eventTime = timestampMs(event.timestamp);
  const { agentId, taskId } = eventAgentKey(event);

  if (type === "layer_started") {
    const layer = asNumber(data.layer) ?? current.currentLayer;
    return {
      ...current,
      status: "running",
      currentLayer: layer,
      totalLayers: Math.max(current.totalLayers, layer + 1),
    };
  }

  if (type === "run_started") {
    return {
      ...current,
      status: "running",
      startedAt: current.startedAt || eventTime || 0,
    };
  }

  if (type === "run_completed") {
    return {
      ...current,
      status: normalizeRunStatus(data.status),
      completedAt: eventTime ?? current.completedAt,
    };
  }

  if (type === "run_error") {
    return {
      ...current,
      status: "failed",
      completedAt: eventTime ?? current.completedAt,
    };
  }

  if (type === "task_started" || type === "worker_started") {
    return updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      agentId: agent.agentId || agentId,
      taskId: agent.taskId || taskId,
      status: "running",
      startedAt: eventTime ?? agent.startedAt,
    }));
  }

  if (type === "tool_call") {
    return updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: "running",
      tool: asString(data.tool, agent.tool || "?"),
      iterations: Math.max(agent.iterations ?? 0, (asNumber(data.iteration) ?? (agent.iterations ?? 0)) + 1),
    }));
  }

  if (type === "tool_result") {
    return updateAgent(current, { agentId, taskId }, (agent) => {
      const tool = asString(data.tool, agent.tool || "?");
      const ok = asString(data.status, "ok") === "ok";
      return {
        ...agent,
        tool: `${tool} ${ok ? "ok" : "error"}`,
        elapsed_s: (asNumber(data.elapsed_ms) ?? 0) / 1000 || agent.elapsed_s,
      };
    });
  }

  if (type === "task_heartbeat") {
    return updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: agent.status === "waiting" ? "running" : agent.status,
      tool: asString(data.tool, agent.tool || ""),
      elapsed_s: asNumber(data.elapsed_s) ?? agent.elapsed_s,
    }));
  }

  if (type === "worker_text") {
    const content = asString(data.content).trim();
    const lastLine = content.split("\n").map((line) => line.trim()).filter(Boolean).pop();
    if (!lastLine) return current;
    return updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      lastText: lastLine.slice(0, 160),
    }));
  }

  if (type === "task_completed" || type === "worker_completed") {
    const withTaskTokens = updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: "done",
      elapsed_s: agent.startedAt && eventTime
        ? Math.max(0, (eventTime - agent.startedAt) / 1000)
        : agent.elapsed_s,
      iterations: asNumber(data.iterations) ?? agent.iterations,
      lastText: asString(data.summary) || agent.lastText,
      input_tokens: asNumber(data.input_tokens) ?? agent.input_tokens,
      output_tokens: asNumber(data.output_tokens) ?? agent.output_tokens,
      cache_read_tokens: asNumber(data.cache_read_tokens) ?? agent.cache_read_tokens,
      cache_creation_tokens: asNumber(data.cache_creation_tokens) ?? agent.cache_creation_tokens,
    }));
    return recomputeRunTokenTotals({
      ...withTaskTokens,
      token_source: mergeTokenSource(current.token_source, data.token_source),
    });
  }

  if (["task_failed", "worker_failed", "worker_timeout", "worker_incomplete"].includes(type)) {
    const withTokens = updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: "failed",
      elapsed_s: agent.startedAt && eventTime
        ? Math.max(0, (eventTime - agent.startedAt) / 1000)
        : agent.elapsed_s,
      error: asString(data.error) || asString(data.reason) || agent.error,
      input_tokens: asNumber(data.input_tokens) ?? agent.input_tokens,
      output_tokens: asNumber(data.output_tokens) ?? agent.output_tokens,
      cache_read_tokens: asNumber(data.cache_read_tokens) ?? agent.cache_read_tokens,
      cache_creation_tokens: asNumber(data.cache_creation_tokens) ?? agent.cache_creation_tokens,
    }));
    return recomputeRunTokenTotals({
      ...withTokens,
      token_source: mergeTokenSource(current.token_source, data.token_source),
    });
  }

  if (type === "task_cancelled" || type === "worker_cancelled") {
    // cancel_run() reached this worker mid-flight: a user stop, not a failure.
    const withTokens = updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: "cancelled",
      elapsed_s: agent.startedAt && eventTime
        ? Math.max(0, (eventTime - agent.startedAt) / 1000)
        : agent.elapsed_s,
      iterations: asNumber(data.iterations) ?? agent.iterations,
      input_tokens: asNumber(data.input_tokens) ?? agent.input_tokens,
      output_tokens: asNumber(data.output_tokens) ?? agent.output_tokens,
      cache_read_tokens: asNumber(data.cache_read_tokens) ?? agent.cache_read_tokens,
      cache_creation_tokens: asNumber(data.cache_creation_tokens) ?? agent.cache_creation_tokens,
    }));
    return recomputeRunTokenTotals({
      ...withTokens,
      token_source: mergeTokenSource(current.token_source, data.token_source),
    });
  }

  if (type === "task_blocked") {
    const blockedBy = Array.isArray(data.blocked_by) ? data.blocked_by.join(", ") : asString(data.reason);
    return updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: "blocked",
      error: blockedBy ? `Blocked by ${blockedBy}` : agent.error,
    }));
  }

  if (type === "task_retry") {
    const attempt = asNumber(data.attempt);
    return updateAgent(current, { agentId, taskId }, (agent) => ({
      ...agent,
      status: "retry",
      tool: attempt ? `retry ${attempt}` : "retry",
    }));
  }

  return current;
}

export function buildSwarmStatusFromToolResultPreview(preview: string): SwarmRunStatus | null {
  if (!preview.includes("run_id") && !preview.includes("preset")) return null;

  try {
    const parsed = JSON.parse(preview) as AnyRecord;
    const runId = asString(parsed.run_id);
    if (!runId) return null;
    const times = serverRunTimes(parsed);
    const status = normalizeRunStatus(parsed.status);
    const usage = asRecord(parsed.token_usage);
    return {
      runId,
      preset: asString(parsed.preset) || "swarm",
      status,
      currentLayer: 0,
      totalLayers: 0,
      startedAt: times.startedAt ?? 0,
      completedAt: ["completed", "failed", "cancelled"].includes(status)
        ? times.completedAt
        : undefined,
      total_input_tokens: asNumber(usage.total_input_tokens),
      total_output_tokens: asNumber(usage.total_output_tokens),
      token_source: asTokenSource(usage.token_source),
      agents: [],
    };
  } catch {
    const runId = preview.match(/"run_id"\s*:\s*"([^"]+)"/)?.[1];
    if (!runId) return null;
    const preset = preview.match(/"preset"\s*:\s*"([^"]+)"/)?.[1] || "swarm";
    const rawStatus = preview.match(/"status"\s*:\s*"([^"]+)"/)?.[1] || "unknown";
    const status = normalizeRunStatus(rawStatus);
    const startedAt = timestampMs(
      preview.match(/"(?:started_at|created_at|timestamp)"\s*:\s*"([^"]+)"/)?.[1],
    );
    const completedAt = timestampMs(
      preview.match(/"completed_at"\s*:\s*"([^"]+)"/)?.[1],
    );
    return {
      runId,
      preset,
      status,
      currentLayer: 0,
      totalLayers: 0,
      startedAt: startedAt ?? 0,
      completedAt: ["completed", "failed", "cancelled"].includes(status)
        ? completedAt
        : undefined,
      agents: [],
    };
  }
}

// Stops the detail payload regressing a status the stream already advanced past.
const STATUS_RANK: Record<SwarmAgentDisplayStatus, number> = {
  waiting: 0,
  running: 1,
  retry: 2,
  done: 3,
  failed: 3,
  blocked: 3,
  cancelled: 3,
};

function advancedStatus(
  live: SwarmAgentDisplayStatus,
  authoritative: SwarmAgentDisplayStatus,
): SwarmAgentDisplayStatus {
  return STATUS_RANK[authoritative] >= STATUS_RANK[live] ? authoritative : live;
}

/**
 * Merge the server's reconciled roster from the run detail into a status built
 * from the event stream, which loses earlier frames on reload or reconnect.
 * Merges rather than replaces so stream-only per-task tokens survive.
 */
export function mergeSwarmRunRoster(
  status: SwarmRunStatus,
  payload: Record<string, unknown>,
): SwarmRunStatus {
  const tasks = Array.isArray(payload.tasks) ? payload.tasks.map(asRecord) : [];
  if (tasks.length === 0) return status;

  const live = new Map(status.agents.map((agent) => [agent.agentId, agent]));
  const merged: SwarmAgentStatus[] = tasks
    .filter((task) => asString(task.agent_id))
    .map((task) => {
      const agentId = asString(task.agent_id);
      const existing = live.get(agentId);
      live.delete(agentId);
      const authoritative = mapTaskStatus(task.status);
      return {
        ...(existing ?? { agentId, iterations: 0 }),
        agentId,
        taskId: asString(task.id) || existing?.taskId,
        status: existing ? advancedStatus(existing.status, authoritative) : authoritative,
        iterations: existing?.iterations ?? asNumber(task.worker_iterations) ?? 0,
        lastText: existing?.lastText ?? (asString(task.summary) || undefined),
        error: existing?.error ?? (asString(task.error) || undefined),
      };
    });

  // Never drop an agent the detail omits; the roster may only grow.
  for (const leftover of live.values()) merged.push(leftover);

  return { ...status, agents: merged };
}

/** Status built from the run detail alone, for a cold load with nothing in memory. */
export function buildSwarmStatusFromRunDetail(
  payload: Record<string, unknown>,
  runId: string,
): SwarmRunStatus | null {
  const id = asString(payload.id) || runId;
  if (!id) return null;
  const times = serverRunTimes(payload);
  return {
    runId: id,
    preset: asString(payload.preset_name) || asString(payload.preset) || "swarm",
    status: normalizeRunStatus(payload.status),
    currentLayer: 0,
    totalLayers: 0,
    startedAt: times.startedAt ?? 0,
    completedAt: times.completedAt,
    total_input_tokens: asNumber(payload.total_input_tokens),
    total_output_tokens: asNumber(payload.total_output_tokens),
    provider: asString(payload.provider) || undefined,
    model: asString(payload.model) || undefined,
    token_source: asTokenSource(payload.token_source),
    agents: [],
  };
}

export function mergeSwarmRunUsage(
  status: SwarmRunStatus,
  payload: Record<string, unknown>,
): SwarmRunStatus {
  const withRoster = mergeSwarmRunRoster(status, payload);
  return {
    ...withRoster,
    total_input_tokens: asNumber(payload.total_input_tokens) ?? withRoster.total_input_tokens,
    total_output_tokens: asNumber(payload.total_output_tokens) ?? withRoster.total_output_tokens,
    provider: asString(payload.provider) || withRoster.provider,
    model: asString(payload.model) || withRoster.model,
    token_source: asTokenSource(payload.token_source) ?? withRoster.token_source,
  };
}
