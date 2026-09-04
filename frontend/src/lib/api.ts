import i18n from "@/i18n";
import { authHeaders, withAuthTicket } from "@/lib/apiAuth";
import type {
  OptionsChainResponse,
  OptionsPayoffRequest,
  OptionsPayoffResponse,
} from "@/lib/options";

const BASE = "";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const AUTH_REQUIRED_MESSAGE_KEY = "agent.authRequired";

function getAuthRequiredMessage(): string {
  return i18n.t(AUTH_REQUIRED_MESSAGE_KEY as never);
}

// Keep the existing string export compatible with consumers while updating its
// live ES-module binding whenever the active locale changes.
export let AUTH_REQUIRED_MESSAGE = getAuthRequiredMessage();
i18n.on("languageChanged", () => {
  AUTH_REQUIRED_MESSAGE = getAuthRequiredMessage();
});

export function isAuthRequiredError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export interface CorrelationResponse {
  labels: string[];
  matrix: number[][];
}

export interface RegimeEpisode {
  start: string;
  end: string | null;
}

export interface CorrelationRegimeResponse {
  labels: string[];
  dates: string[];
  density: (number | null)[];
  smoothed: (number | null)[];
  fused: number[];
  episodes: RegimeEpisode[];
  params: {
    days: number;
    corr_window: number;
    edge_threshold: number;
    smooth_window: number;
    enter_threshold: number;
    exit_threshold: number;
  };
}

export interface PortfolioPosition {
  source_id?: string;
  profile_id?: string;
  source_label?: string;
  broker: string;
  symbol: string;
  name: string;
  asset_type: string;
  market: string;
  currency: string;
  quantity: number;
  cost_price?: number | null;
  market_price?: number | null;
  market_value_usd: number;
  market_value_cny: number;
  unrealized_pnl_usd?: number | null;
  priced: boolean;
  updated_at: string;
  pricing_basis?: string;
  price_error?: string;
}

export interface PortfolioConnectorCompatibility {
  level: "native" | "contract_tested" | "experimental";
  contract_version: number;
  asset_scope: string;
  note: string;
}

/**
 * One portfolio source as of the last refresh.
 *
 * A source that could not be read has `status === "error"`, no totals, and
 * contributes nothing to the snapshot totals; `last_success_at` (when present)
 * is the timestamp of the last read that did succeed, and is only ever shown
 * as history — never as a current valuation.
 */
export interface PortfolioAccount {
  source_id?: string;
  profile_id?: string;
  label?: string;
  broker: string;
  status: "ok" | "error";
  last_success_at?: string;
  total_usd?: number | null;
  total_cny?: number | null;
  priced_value_usd?: number;
  cash_usd?: number;
  unpriced_or_other_usd?: number;
  position_count?: number;
  priced_position_count?: number;
  unpriced_position_count?: number;
  error_code?: string;
  error?: string;
  failure_kind?: "authorization" | "transient";
  reconnect_required?: boolean;
  auth?: {
    method: string;
    renewal: "automatic" | "session" | "provider_managed";
    readonly: boolean;
    detail: string;
  };
  portfolio_compatibility?: PortfolioConnectorCompatibility;
}

export interface PortfolioSnapshot {
  snapshot_id: string;
  created_at: string;
  /** False whenever any enabled source did not reach `status === "ok"`. */
  complete: boolean;
  display_currency?: "USD" | "CNY";
  totals: { usd: number; cny: number };
  valuation?: {
    priced_usd: number;
    cash_usd: number;
    unpriced_or_other_usd: number;
    identified_coverage: number;
  };
  fx: { usd_cny: number; usd_hkd: number; fetched_at: string; stale: boolean };
  accounts: PortfolioAccount[];
  positions: PortfolioPosition[];
  combined_holdings?: Array<{
    symbol: string;
    market_value_usd: number;
    asset_type?: string;
    brokers?: string[];
    unrealized_pnl_usd?: number;
  }>;
  /** Backend-authored English notes; rendered verbatim, not translated. */
  warnings: string[];
}

export interface PortfolioHistoryPoint {
  id: string;
  created_at: string;
  complete: number;
  total_usd: string;
  total_cny: string;
}

export interface PortfolioRefreshState {
  running: boolean;
  current: string | null;
  sources?: Record<string, { status: "idle" | "pending" | "refreshing" | "ok" | "error"; error?: string | null }>;
  brokers?: Record<string, { status: "idle" | "pending" | "refreshing" | "ok" | "error"; error?: string | null }>;
}

export interface PortfolioReconnectState {
  running: boolean;
  source_id: string | null;
  status: "idle" | "authorizing" | "authorized" | "error" | "timeout";
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface PortfolioSourceSettings {
  connection_id: string;
  label: string;
  enabled: boolean;
  order: number;
  include_cash: boolean;
}

export interface PortfolioSettings {
  display_currency: "USD" | "CNY";
  sources: PortfolioSourceSettings[];
}

export interface PortfolioSourceCatalogItem {
  id: string;
  connection_id: string;
  profile_id: string;
  connector: string;
  label: string;
  environment: "paper" | "live";
  transport: "local_tws" | "remote_mcp" | "broker_sdk" | "local_plugin";
  capabilities: string[];
  readonly: boolean;
  notes: string;
  selected: boolean;
  source_id?: string | null;
  supports_reconnect: boolean;
  credential_fields: CredentialField[];
  credential_status: Record<string, boolean>;
  credentials_configured: boolean;
  portfolio_compatibility: PortfolioConnectorCompatibility;
}

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
}

export interface ConnectorOnboarding {
  schema_version: number;
  auth_type: string;
  credential_fields: CredentialField[];
  dependency: string | null;
  install_command: string | null;
  test_operation: string;
  setup_hint: string;
  secret_storage: "os_keyring" | null;
}

export interface LocalConnection {
  id: string;
  profile_id: string;
  label: string;
  connector: string;
  environment: "paper" | "live";
  transport: "local_tws" | "remote_mcp" | "broker_sdk" | "local_plugin";
  readonly: boolean;
  capabilities: string[];
  supports_reconnect: boolean;
  credential_fields: CredentialField[];
  credential_status: Record<string, boolean>;
  credentials_configured: boolean;
  onboarding?: ConnectorOnboarding;
  portfolio_compatibility: PortfolioConnectorCompatibility;
}

export interface ReadonlyConnectionProfile {
  id: string;
  connector: string;
  label: string;
  environment: "paper" | "live";
  transport: "local_tws" | "remote_mcp" | "broker_sdk" | "local_plugin";
  capabilities: string[];
  readonly: boolean;
  notes: string;
  local_plugin: boolean;
  credential_fields: CredentialField[];
  onboarding?: ConnectorOnboarding;
  supports_reconnect: boolean;
  portfolio_compatibility: PortfolioConnectorCompatibility;
  invalid_plugin?: boolean;
  directory?: string;
  error?: string;
}

export interface ConnectionsResponse {
  status: string;
  connections: LocalConnection[];
  profiles: ReadonlyConnectionProfile[];
  plugin_directory: string;
}

export interface PortfolioSettingsResponse {
  status: string;
  settings: PortfolioSettings;
  catalog: PortfolioSourceCatalogItem[];
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    // Options endpoints report errors under an `error` key
    // ({status:"error", error} / {ok:false, error}) rather than detail/message.
    detail = body.detail || body.message || body.error || detail;
  } catch { /* ignore */ }
  if (res.status === 401 || res.status === 403) {
    detail = getAuthRequiredMessage();
  }
  return new ApiError(detail, res.status);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...rest } = options ?? {};
  const mergedHeaders: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
  if (headers) {
    new Headers(headers).forEach((value, key) => {
      mergedHeaders[key] = value;
    });
  }
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: mergedHeaders,
  });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  const text = await res.text();
  if (!text) return {} as T;

  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const preview = text.slice(0, 80).replace(/\s+/g, " ");
    throw new ApiError(
      `Expected JSON from ${path}, got ${contentType || "unknown content type"}: ${preview}`,
      res.status,
    );
  }

  return JSON.parse(text) as T;
}

export interface UploadResult {
  status: string;
  file_path: string;
  filename: string;
}

async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", headers: authHeaders(), body: form });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  return res.json();
}

function appendQueryParam(url: string, key: string, value: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

export const api = {
  uploadFile,
  getCorrelation: (codes: string, days: number, method: "pearson" | "spearman") =>
    request<CorrelationResponse>(
      `/correlation?codes=${encodeURIComponent(codes)}&days=${encodeURIComponent(String(days))}&method=${encodeURIComponent(method)}`,
    ),
  getCorrelationRegime: (codes: string, days: number) =>
    request<CorrelationRegimeResponse>(
      `/correlation/regime?codes=${encodeURIComponent(codes)}&days=${encodeURIComponent(String(days))}`,
    ),
  getPortfolio: () => request<{ status: string; snapshot: PortfolioSnapshot | null }>("/api/portfolio"),
  refreshPortfolio: () => request<{ status: string; snapshot: PortfolioSnapshot }>("/api/portfolio/refresh", { method: "POST" }),
  getPortfolioRefreshStatus: () => request<{ status: string; refresh: PortfolioRefreshState }>("/api/portfolio/refresh-status"),
  reconnectPortfolioSource: (sourceId: string) =>
    request<{ status: string; reconnect: PortfolioReconnectState }>(`/api/portfolio/sources/${encodeURIComponent(sourceId)}/reconnect`, { method: "POST" }),
  getPortfolioReconnectStatus: () =>
    request<{ status: string; reconnect: PortfolioReconnectState }>("/api/portfolio/reconnect-status"),
  getPortfolioSettings: () => request<PortfolioSettingsResponse>("/api/portfolio/settings"),
  updatePortfolioSettings: (settings: PortfolioSettings) =>
    request<PortfolioSettingsResponse>("/api/portfolio/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getConnections: () => request<ConnectionsResponse>("/api/connections"),
  createConnection: (payload: { id: string; profile_id: string; label: string }) =>
    request<{ status: string; connection: LocalConnection }>("/api/connections", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  saveConnectionCredentials: (connectionId: string, values: Record<string, string>) =>
    request<{ status: string; credential_status: Record<string, boolean> }>(
      `/api/connections/${encodeURIComponent(connectionId)}/credentials`,
      { method: "POST", body: JSON.stringify({ values }) },
    ),
  checkConnection: (connectionId: string) =>
    request<{ status: string; connection_id: string; report: Record<string, unknown> }>(
      `/api/connections/${encodeURIComponent(connectionId)}/check`,
      { method: "POST" },
    ),
  deleteConnection: (connectionId: string) =>
    request<{ status: string; deleted: string }>(
      `/api/connections/${encodeURIComponent(connectionId)}`,
      { method: "DELETE" },
    ),
  getPortfolioHistory: (limit = 180) =>
    request<{ status: string; history: PortfolioHistoryPoint[] }>(`/api/portfolio/history?limit=${encodeURIComponent(String(limit))}`),
  downloadPortfolioCsv: async () => {
    const response = await fetch(`${BASE}/api/portfolio/export.csv`, { headers: authHeaders() });
    if (!response.ok) throw await errorFromResponse(response);
    return response.blob();
  },
  listRuns: (limit?: number) => request<RunListItem[]>(`/runs${limit ? `?limit=${encodeURIComponent(String(limit))}` : ""}`),
  getRun: (id: string, params: RunDetailParams = {}) => {
    const q = new URLSearchParams();
    if (params.chart_payload) q.set("chart_payload", params.chart_payload);
    if (params.chart_symbol) q.set("chart_symbol", params.chart_symbol);
    const qs = q.toString();
    return request<RunData>(`/runs/${id}${qs ? `?${qs}` : ""}`);
  },
  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${id}/code`),
  getRunFactor: (id: string) => request<FactorReportPayload>(`/runs/${id}/factor`),
  getRunAttribution: (id: string) => request<AttributionResponse>(`/runs/${encodeURIComponent(id)}/attribution`),
  getRunPine: (id: string) => request<PineScriptResult>(`/runs/${id}/pine`),
  listSessions: () => request<SessionItem[]>("/sessions"),
  createSession: (title?: string) => request<SessionItem>("/sessions", { method: "POST", body: JSON.stringify({ title: title || "" }) }),
  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "DELETE" }),
  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  // Codex-style LLM summary title from the first exchange; backend refuses to
  // overwrite a manual rename, so this is safe to fire-and-forget.
  autoTitleSession: (sid: string) => request<{ status: string; title: string }>(`/sessions/${sid}/title/auto`, { method: "POST" }),
  // Scheduled research: cadence + timezone are stored as authored (local
  // wall-clock cron + IANA key), so list rows render without any UTC math.
  listScheduledRuns: (signal?: AbortSignal) => request<ScheduledRun[]>("/scheduled-runs", { signal }),
  createScheduledRun: (body: CreateScheduledRunRequest) =>
    request<ScheduledRun>("/scheduled-runs", { method: "POST", body: JSON.stringify(body) }),
  deleteScheduledRun: (id: string) =>
    request<void>(`/scheduled-runs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  commitScheduledResearchProposal: (proposalId: string) =>
    request<ScheduledResearchProposal>(
      `/scheduled-runs/proposals/${encodeURIComponent(proposalId)}/commit`,
      { method: "POST" },
    ),
  discardScheduledResearchProposal: (proposalId: string) =>
    request<ScheduledResearchProposal>(
      `/scheduled-runs/proposals/${encodeURIComponent(proposalId)}/discard`,
      { method: "POST" },
    ),
  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}/cancel`, { method: "POST" }),
  getSessionMessages: (sid: string) => request<MessageItem[]>(`/sessions/${sid}/messages`),
  createGoal: (sid: string, body: CreateGoalRequest) =>
    request<GoalSnapshot>(`/sessions/${sid}/goal`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getGoal: (sid: string) => request<GoalSnapshot>(`/sessions/${sid}/goal`),
  updateGoal: (sid: string, body: UpdateGoalRequest) =>
    request<UpdateGoalResponse>(`/sessions/${sid}/goal`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addGoalEvidence: (sid: string, body: AddGoalEvidenceRequest) =>
    request<AddGoalEvidenceResponse>(`/sessions/${sid}/goal/evidence`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateGoalStatus: (sid: string, body: UpdateGoalStatusRequest) =>
    request<UpdateGoalStatusResponse>(`/sessions/${sid}/goal/status`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  // Returns the bare stream URL (no auth in the query string). The SSE ticket
  // is minted per connect/reconnect inside useSSE (tickets are single-use, so
  // baking one into a cached URL would break reconnection).
  sseUrl: (sid: string, options?: { replay?: "active" }) => {
    let url = `${BASE}/sessions/${sid}/events`;
    if (options?.replay) url = appendQueryParam(url, "replay", options.replay);
    return url;
  },

  // Swarm API
  listSwarmPresets: () => request<SwarmPreset[]>("/swarm/presets"),
  createSwarmRun: (preset_name: string, user_vars: Record<string, string>) =>
    request<{ id: string; status: string }>("/swarm/runs", {
      method: "POST",
      body: JSON.stringify({ preset_name, user_vars }),
    }),
  listSwarmRuns: () => request<SwarmRunSummary[]>("/swarm/runs"),
  getSwarmRun: (id: string) => request<Record<string, unknown>>(`/swarm/runs/${id}`),
  swarmSseUrl: (id: string) => withAuthTicket(`${BASE}/swarm/runs/${id}/events`),
  cancelSwarmRun: (id: string) =>
    request<{ status: string }>(`/swarm/runs/${id}/cancel`, { method: "POST" }),
  retrySwarmRun: (id: string) =>
    request<{ id: string; status: string; preset_name: string }>(`/swarm/runs/${id}/retry`, { method: "POST" }),
  getLLMSettings: () => request<LLMSettings>("/settings/llm"),
  updateLLMSettings: (settings: UpdateLLMSettingsRequest) =>
    request<LLMSettings>("/settings/llm", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  listLLMModels: (settings: ListLLMModelsRequest) =>
    request<LLMModelsResponse>("/settings/llm/models", {
      method: "POST",
      body: JSON.stringify(settings),
    }),
  getDataSourceSettings: () => request<DataSourceSettings>("/settings/data-sources"),
  updateDataSourceSettings: (settings: UpdateDataSourceSettingsRequest) =>
    request<DataSourceSettings>("/settings/data-sources", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getChannelStatus: () => request<ChannelRuntimeStatus>("/channels/status"),
  startChannels: () => request<ChannelRuntimeActionResponse>("/channels/start", { method: "POST" }),
  stopChannels: () => request<ChannelRuntimeActionResponse>("/channels/stop", { method: "POST" }),
  runChannelPairingCommand: (body: ChannelPairingCommandRequest) =>
    request<ChannelPairingCommandResponse>("/channels/pairing/command", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // Alpha Zoo API
  listAlphas: (params: AlphaListParams = {}) => {
    const q = new URLSearchParams();
    if (params.zoo) q.set("zoo", params.zoo);
    if (params.theme) q.set("theme", params.theme);
    if (params.universe) q.set("universe", params.universe);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<AlphaListResponse>(`/alpha/list${qs ? `?${qs}` : ""}`);
  },
  getAlpha: (alphaId: string) =>
    request<AlphaDetailResponse>(`/alpha/${encodeURIComponent(alphaId)}`),
  createAlphaBench: (body: AlphaBenchRequest) =>
    request<{ status: string; job_id: string }>("/alpha/bench", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaBenchStreamUrl: (jobId: string) =>
    withAuthTicket(`${BASE}/alpha/bench/${encodeURIComponent(jobId)}/stream`),
  createAlphaCompare: (body: AlphaCompareRequest) =>
    request<{ status: string; job_id: string }>("/alpha/compare", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaCompareStreamUrl: (jobId: string) =>
    withAuthTicket(`${BASE}/alpha/compare/${encodeURIComponent(jobId)}/stream`),

  // Options Lab
  analyzeOptionsPayoff: (body: OptionsPayoffRequest) =>
    request<OptionsPayoffResponse>("/options/payoff", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getOptionsChain: (ticker: string, expiration?: number) => {
    const q = new URLSearchParams();
    q.set("ticker", ticker);
    if (expiration !== undefined) q.set("expiration", String(expiration));
    return request<OptionsChainResponse>(`/options/chain?${q.toString()}`);
  },

  // Connector runtime channel — privileged surface actions (NOT agent tools).
  // commit is the ONLY action that writes a mandate; halt trips the kill switch.
  commitMandate: (body: CommitMandateRequest) =>
    request<CommitMandateResponse>("/mandate/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  haltLive: (session_id?: string, broker?: string, reason?: string) =>
    request<HaltLiveResponse>("/live/halt", {
      method: "POST",
      body: JSON.stringify({ session_id, broker, reason }),
    }),
  resumeLive: (session_id?: string, broker?: string) =>
    request<HaltLiveResponse>("/live/resume", {
      method: "POST",
      body: JSON.stringify({ session_id, broker }),
    }),
  // Read the persistent runtime status across all authorized brokers (SPEC §7.5).
  // Polled by the RunnerStatus panel; a plain authenticated GET, never a chat message.
  getLiveStatus: (signal?: AbortSignal) => request<LiveStatus>("/live/status", { signal }),
  verifyConnector: (profileId: string) =>
    request<ConnectorVerifyResponse>(`/live/connectors/${encodeURIComponent(profileId)}/verify?force=true`, {
      method: "POST",
    }),
  authorizeLive: (broker: string) =>
    request<LiveAuthorizeResponse>("/live/authorize", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  // Start/stop the persistent runner (SPEC §7.5). Privileged surface actions, not agent tools.
  startLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/start", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  stopLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/stop", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
};

// --- Scheduled research types ---

export interface VerdictItem {
  symbol: string;
  state: string;
  reason: string;
}

export interface VerdictRecord {
  session_id: string;
  recorded_at: number;
  parse: string;
  outcome: string;
  items: VerdictItem[];
  previous: VerdictRecord | null;
}

export interface ScheduledRun {
  id: string;
  prompt: string;
  title: string;
  source_type: "prompt" | "playbook";
  playbook_slug: string | null;
  end_at: number | null;
  schedule: string;
  next_run_at: number;
  status: string;
  created_at: number;
  last_run_at: number | null;
  consecutive_failures: number;
  last_error: string | null;
  failure_kind: string | null;
  config: Record<string, unknown>;
  timezone: string | null;
  // Delivery is opt-in per monitor: a null channel means results stay in the
  // app, which is what every monitor created before this did.
  delivery_channel: string | null;
  delivery_target: string | null;
  delivery_target_ref: string | null;
  delivery_target_label: string | null;
  delivery_status: string;
  delivery_error: string | null;
  delivery_updated_at: number | null;
  delivery_attempts: number;
  delivery_provider_message_id: string | null;
  // The latest run's parsed verdict, embedded with its predecessor so the list
  // renders a delta in one query. Null until a completed run records one.
  last_verdict: VerdictRecord | null;
}

export interface CreateScheduledRunRequest {
  id?: string;
  title?: string | null;
  prompt: string;
  schedule: string;
  timezone?: string | null;
  end_at?: number | null;
  config?: Record<string, unknown>;
  delivery_channel?: string | null;
  delivery_target?: string | null;
  delivery_target_ref?: string | null;
}

export interface ScheduledResearchProposalJob {
  id: string;
  title: string;
  state: string;
  source: { kind: string; playbook_slug?: string | null; prompt?: string | null };
  schedule: {
    expression: string;
    timezone: string | null;
    next_run_at: number | null;
    end_at: number | null;
  };
  delivery: {
    channel: string | null;
    target_ref: string | null;
    target_label: string | null;
    status: string;
  };
}

export interface ScheduledResearchProposal {
  type: "scheduled_research.proposal";
  proposal_id: string;
  operation: "create" | "cancel";
  status: "pending" | "committed" | "discarded" | "expired";
  expires_at: number;
  job: ScheduledResearchProposalJob;
  job_id?: string | null;
  committed_job_id?: string | null;
}

// --- Swarm types ---

export interface SwarmPreset {
  name: string;
  title: string;
  description: string;
  agent_count: number;
  variables: { name: string; description: string; required: boolean }[];
}

export interface SwarmRunSummary {
  id: string;
  preset_name: string;
  status: string;
  created_at: string;
  task_count: number;
  completed_count: number;
}

export interface LLMProviderOption {
  name: string;
  label: string;
  api_key_env?: string | null;
  base_url_env: string;
  default_model: string;
  default_base_url: string;
  base_url_options?: string[];
  api_key_required: boolean;
  auth_type?: string;
  login_command?: string | null;
}

export interface LLMSettings {
  provider: string;
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  api_key_required: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
  sse_timeout_seconds: number;
  env_path: string;
  providers: LLMProviderOption[];
}

export interface UpdateLLMSettingsRequest {
  provider: string;
  model_name: string;
  base_url: string;
  api_key?: string;
  clear_api_key?: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort?: string;
}

export interface ListLLMModelsRequest {
  provider: string;
  base_url?: string;
  api_key?: string;
}

export interface LLMModelsResponse {
  provider: string;
  models: string[];
  source: "provider" | "default";
  warning_code?:
    | "oauth_discovery_unsupported"
    | "api_key_required"
    | "model_list_unavailable"
    | null;
}

export interface SourceOrderEntry {
  market: string;
  env_var: string;
  default_order: string[];
  effective_order: string[];
  override?: string[] | null;
  override_invalid: boolean;
}

export interface SourceOrderUpdate {
  market: string;
  /** New order (permutation of default_order). null/omitted = reset to default. */
  order?: string[] | null;
}

export interface DataSourceSettings {
  tushare_token_configured: boolean;
  tushare_token_hint?: string | null;
  baostock_supported: boolean;
  baostock_installed: boolean;
  baostock_message: string;
  env_path: string;
  source_orders?: SourceOrderEntry[];
}

export interface UpdateDataSourceSettingsRequest {
  tushare_token?: string;
  clear_tushare_token?: boolean;
  source_orders?: SourceOrderUpdate[];
}

export interface ChannelAdapterStatus {
  name: string;
  display_name: string;
  configured: boolean;
  enabled: boolean;
  available: boolean;
  loaded: boolean;
  running: boolean;
  error?: string;
  install_hint?: string;
}

export interface ChannelRuntimeStatus {
  running: boolean;
  inbound_queue: number;
  outbound_queue: number;
  session_count: number;
  channels: Record<string, ChannelAdapterStatus>;
}

export interface ChannelRuntimeActionResponse extends ChannelRuntimeStatus {
  status: string;
}

export interface ChannelPairingCommandRequest {
  channel: string;
  command: string;
}

export interface ChannelPairingCommandResponse {
  channel: string;
  reply: string;
}

// --- Types matching backend API contracts ---

export interface RunListItem {
  run_id: string;
  status: string;
  created_at: string;
  prompt?: string;
  total_return?: number;
  sharpe?: number;
  codes?: string[];
  start_date?: string;
  end_date?: string;
}

export interface RunDetailParams {
  chart_payload?: "summary";
  chart_symbol?: string;
}

export interface PriceBar {
  time: string;
  timestamp?: string;
  code?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  time: string;
  timestamp?: string;
  code?: string;
  side: "BUY" | "SELL";
  price: number;
  qty?: number;
  reason?: string;
  text?: string;
}

export interface EquityPoint {
  time: string;
  equity: string | number;
  drawdown: string | number;
}

/** Monte Carlo fan-chart payload: percentile envelope + sampled paths over trade order. */
export interface MonteCarloEquityPaths {
  steps: number[];
  initial_capital: number;
  actual: number[];
  band_p5: number[];
  band_p25: number[];
  band_p50: number[];
  band_p75: number[];
  band_p95: number[];
  samples: number[][];
}

export interface ValidationData {
  monte_carlo?: {
    actual_sharpe: number;
    actual_max_dd: number;
    p_value_sharpe: number;
    p_value_max_dd: number;
    simulated_sharpe_mean: number;
    simulated_sharpe_std: number;
    simulated_sharpe_p5: number;
    simulated_sharpe_p95: number;
    n_simulations: number;
    n_trades: number;
    sharpe_samples?: number[];
    equity_paths?: MonteCarloEquityPaths;
    error?: string;
  };
  bootstrap?: {
    observed_sharpe: number;
    ci_lower: number;
    ci_upper: number;
    median_sharpe: number;
    prob_positive: number;
    confidence: number;
    n_bootstrap: number;
    sharpe_samples?: number[];
    error?: string;
  };
  walk_forward?: {
    n_windows: number;
    windows: Array<{
      window: number;
      start: string;
      end: string;
      return: number;
      sharpe: number;
      max_dd: number;
      trades: number;
      win_rate: number;
    }>;
    profitable_windows: number;
    consistency_rate: number;
    return_mean: number;
    return_std: number;
    sharpe_mean: number;
    sharpe_std: number;
    error?: string;
  };
}

export interface RiskXRayPayload {
  inputs?: {
    symbols?: string[];
    weights?: Record<string, number>;
    aligned_days?: number;
    return_observations?: number;
    first_date?: string;
    last_date?: string;
  };
  concentration?: { hhi?: number; effective_n?: number; top_weight?: number };
  volatility?: { annualized_vol?: number };
  drawdown?: { max_drawdown?: number };
  tail_risk?: Record<string, unknown>;
  diversification?: Record<string, unknown>;
  correlation?: Record<string, unknown>;
  skipped?: string[];
  warnings?: string[];
}

export interface RebalanceNotesPayload {
  rebalances?: Array<{
    date: string;
    turnover: number;
    entries?: Array<{ code: string; to: number }>;
    exits?: Array<{ code: string; from: number }>;
    top_moves?: Array<{ code: string; from: number; to: number; delta: number }>;
  }>;
  summary?: {
    target_change_count: number;
    /** Legacy key on runs produced before the #1275 execution-evidence fix. */
    rebalance_count?: number;
    turnover_total: number;
    turnover_mean: number;
    turnover_max: number;
    largest_rebalance_date?: string | null;
    rebalance_executed_bars?: number;
    rebalance_executed_fills?: number;
    rebalance_realized_turnover?: number;
  };
}

export interface FactorIcStats {
  ic_mean?: number | null;
  ic_std?: number | null;
  ir?: number | null;
  ic_positive_ratio?: number | null;
  ic_count?: number | null;
  [key: string]: unknown;
}

export interface FactorResult {
  name: string;
  path: string;
  ic_series: Array<{ date: string; ic: number }>;
  ic_stats?: FactorIcStats;
  group_equity: Array<{ date: string } & Record<string, number | string>>;
  n_groups: number;
  long_short_spread: number | null;
  group_final_equity: Record<string, number>;
  truncated?: {
    ic_series?: boolean;
    ic_stats?: boolean;
    group_equity?: boolean;
  };
}

export interface FactorReportPayload {
  exists: boolean;
  factors: FactorResult[];
  ic_correlation: { labels: string[]; matrix: number[][] } | null;
}

// --- Attribution types (GET /runs/{runId}/attribution) ---

export interface AttributionBenchmarkInfo {
  ticker: string | null;
  mode: "auto_equal_weight" | "explicit";
}

export interface AttributionRollingPoint {
  date: string;
  beta: number;
  alpha_annualized: number;
}

export interface AttributionCumulativePoint {
  date: string;
  portfolio: number;
  benchmark: number;
  /** Portfolio-minus-benchmark cumulative return; plotted as the active line. */
  active: number;
}

export interface AttributionFactor {
  beta: number;
  alpha_per_period: number;
  alpha_annualized: number;
  alpha_t_stat: number;
  r_squared: number;
  n_obs: number;
  rolling_window: number;
  rolling: AttributionRollingPoint[] | null;
  cumulative: AttributionCumulativePoint[];
}

export interface AttributionSectorEntry {
  sector: string;
  portfolio_weight: number;
  benchmark_weight: number;
  portfolio_return: number;
  benchmark_return: number;
  allocation: number;
  selection: number;
  interaction: number;
  total: number;
}

export interface AttributionBrinson {
  mode: "symbol" | "asset_class" | "invested_cash";
  portfolio_return: number;
  benchmark_return: number;
  active_return: number;
  allocation: number;
  selection: number;
  interaction: number;
  sectors: AttributionSectorEntry[];
}

export interface AttributionResponse {
  exists: boolean;
  benchmark: AttributionBenchmarkInfo | null;
  factor: AttributionFactor | null;
  brinson: AttributionBrinson | null;
  notes: string[];
}

export interface RunData {
  status: string;
  run_id: string;
  prompt?: string;
  elapsed_seconds?: number;
  run_directory?: string;
  run_stage?: string;
  run_context?: Record<string, unknown>;

  metrics?: BacktestMetrics;
  artifacts?: ArtifactInfo[];
  run_card?: RunCard;
  risk_xray?: RiskXRayPayload;
  rebalance_notes?: RebalanceNotesPayload;
  validation?: ValidationData;
  has_factor_artifacts?: boolean;

  chart_symbols?: string[];
  price_series?: Record<string, PriceBar[]>;
  indicator_series?: Record<string, Record<string, IndicatorPoint[]>>;
  trade_markers?: TradeMarker[];
  equity_curve?: EquityPoint[];
  trade_log?: Array<Record<string, string>>;
  /** Full equity.csv rows (timestamp/equity/drawdown as strings); not capped like equity_curve. */
  artifacts_equity_csv?: Array<Record<string, string>>;
  artifacts_metrics_csv?: Array<Record<string, string>>;
  artifacts_trades_csv?: Array<Record<string, string>>;
  /** Filled portfolio weights per date (rows: {timestamp, <symbol>: weight-string}). */
  artifacts_positions_csv?: Array<Record<string, string>>;
  /** Requested target weights per date, same row shape as artifacts_positions_csv. */
  artifacts_target_positions_csv?: Array<Record<string, string>>;
  run_logs?: Array<{ source?: string; line_number?: number; message?: string }>;
}

// --- Positions sector-map types (GET /runs/{runId}/positions/sectors) ---

/** Asset classes reported by the backend sector-map endpoint. */
export type SectorAssetClass =
  | "a_share"
  | "us_equity"
  | "hk_equity"
  | "india_equity"
  | "kr_equity"
  | "ca_equity"
  | "crypto"
  | "futures"
  | "forex";

export interface SectorInfo {
  asset_class: SectorAssetClass;
  /** Resolved industry name, or null when unresolved / not applicable. */
  industry: string | null;
  /** Provenance of `industry` (e.g. "eastmoney"), null when unresolved. */
  industry_source: string | null;
}

export interface SectorMapResponse {
  ok: boolean;
  run_id?: string;
  resolved_at?: string;
  cached?: boolean;
  symbols: Record<string, SectorInfo>;
  unresolved?: string[];
  /** Total symbol columns in positions.csv (may exceed `symbol_limit`). */
  total_symbols?: number;
  /** Max symbols that receive a network industry lookup per resolve. */
  symbol_limit?: number;
  /** Present when the run has no positions artifact. */
  note?: string;
}

/**
 * Fetch the resolved sector map for one run's positions artifact.
 * Uses the same auth-header + error-envelope conventions as every other
 * fetcher in this module (via the shared `request` helper).
 */
export function fetchRunSectorMap(runId: string, refresh?: boolean): Promise<SectorMapResponse> {
  const qs = refresh ? "?refresh=1" : "";
  return request<SectorMapResponse>(`/runs/${encodeURIComponent(runId)}/positions/sectors${qs}`);
}

export interface RunCard {
  schema_version?: string;
  generated_at?: string;
  run_dir?: string;
  backtest?: Record<string, unknown>;
  reproducibility?: Record<string, unknown>;
  data_sources?: string[];
  metrics?: Record<string, unknown>;
  validation?: unknown;
  warnings?: string[];
  artifacts?: RunCardArtifact[];
  [key: string]: unknown;
}

export interface RunCardArtifact {
  path: string;
  size_bytes: number;
  sha256: string;
}

export interface BacktestMetrics {
  final_value: number;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  win_rate: number;
  trade_count: number;
  [key: string]: number;
}


export interface IndicatorPoint {
  time: string;
  value: number;
}

export interface ArtifactInfo {
  name: string;
  path: string;
  type: string;
  size: number;
  exists: boolean;
}

export interface PineScriptResult {
  exists: boolean;
  content: string | null;
}

export interface SessionItem {
  session_id: string;
  title?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  last_attempt_id?: string;
}

// --- Goal types ---

export type GoalStatus =
  | "active"
  | "paused"
  | "waiting_user"
  | "needs_refresh"
  | "insufficient_evidence"
  | "compliance_blocked"
  | "blocked"
  | "budget_limited"
  | "usage_limited"
  | "complete"
  | "cancelled"
  | "superseded";

export type GoalRiskTier =
  | "research_general"
  | "market_specific_short_term"
  | "personalized_advice_or_position_sizing";

export interface GoalRecord {
  goal_id: string;
  session_id: string;
  status: GoalStatus;
  objective: string;
  ui_summary: string;
  source: string;
  protocol: string;
  risk_tier: GoalRiskTier;
  token_budget?: number | null;
  tokens_used: number;
  turn_budget?: number | null;
  turns_used: number;
  time_budget_seconds?: number | null;
  time_used_seconds: number;
  budget_wrapup_sent: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  recap?: string | null;
}

export interface GoalClaim {
  claim_id: string;
  goal_id: string;
  session_id: string;
  claim_type: string;
  text: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface GoalCriterion {
  criterion_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  required: boolean;
  status: string;
  freshness_requirement?: string | null;
  protocol_step?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalEvidence {
  evidence_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe: string[];
  benchmark: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  retrieved_at: string;
  data_as_of?: string | null;
  freshness_status: string;
  verification_status: string;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids: string[];
  created_at: string;
}

export interface GoalSnapshot {
  goal: GoalRecord;
  claims: GoalClaim[];
  criteria: GoalCriterion[];
  evidence: GoalEvidence[];
  evidence_count: number;
}

export interface CreateGoalRequest {
  objective: string;
  criteria?: string[];
  ui_summary?: string;
  protocol?: string;
  risk_tier?: GoalRiskTier;
  token_budget?: number;
  turn_budget?: number;
  time_budget_seconds?: number;
}

export interface AddGoalEvidenceRequest {
  goal_id: string;
  expected_goal_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type?: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe?: string[];
  benchmark?: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions?: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  data_as_of?: string | null;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids?: string[];
}

export interface UpdateGoalRequest {
  goal_id: string;
  expected_goal_id: string;
  objective?: string;
  ui_summary?: string;
}

export interface UpdateGoalResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

export interface AddGoalEvidenceResponse {
  evidence: GoalEvidence;
  snapshot: GoalSnapshot;
}

export interface GoalAuditRowRequest {
  criterion_id: string;
  result: string;
  evidence_ids?: string[];
  notes?: string;
}

export interface UpdateGoalStatusRequest {
  goal_id: string;
  expected_goal_id: string;
  status: GoalStatus;
  audit?: GoalAuditRowRequest[];
  recap?: string | null;
}

export interface UpdateGoalStatusResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

// --- Alpha Zoo types ---

export interface AlphaListParams {
  zoo?: string;
  theme?: string;
  universe?: string;
  limit?: number;
}

export interface AlphaSummary {
  id: string;
  zoo: string;
  theme: string[];
  universe: string[];
  nickname?: string;
  decay_horizon?: number | null;
  min_warmup_bars?: number | null;
  requires_sector?: boolean;
}

export interface AlphaListResponse {
  status: string;
  alphas: AlphaSummary[];
  total: number;
  returned: number;
  truncated: boolean;
}

export interface AlphaDetail {
  id: string;
  zoo: string;
  module_path?: string;
  meta: Record<string, unknown>;
}

export interface AlphaDetailResponse {
  status: string;
  alpha: AlphaDetail;
  source_code: string;
}

export interface AlphaBenchRequest {
  zoo: string;
  universe: string;
  period: string;
  top?: number;
}

export interface AlphaBenchTopRow {
  id: string;
  ic_mean: number;
  ir: number;
  theme: string[];
  formula_latex: string;
  category: "alive" | "reversed" | "dead";
}

export interface AlphaBenchResult {
  alive: number;
  reversed: number;
  dead: number;
  skipped?: number;
  top5_by_ir: AlphaBenchTopRow[];
  dead_examples: AlphaBenchTopRow[];
  by_theme: Record<string, { alive: number; reversed: number; dead: number }>;
}

export interface AlphaCompareRequest {
  alpha_ids: string[];
  universe: string;
  period: string;
  /** One of: ir | ic_mean | ic_positive_ratio | ic_count (default ir). */
  sort?: string;
}

export interface AlphaCompareRow {
  rank: number;
  id: string;
  zoo: string;
  ic_mean: number;
  ic_std: number;
  ir: number;
  ic_positive_ratio: number;
  ic_count: number;
  /** `delta_<sort>_vs_best` — gap to the top-ranked alpha on the active metric. */
  [deltaKey: string]: number | string;
}

export interface AlphaCompareSkip {
  id: string;
  reason: string;
}

export interface AlphaCompareResult {
  universe: string;
  period: string;
  sort: string;
  n_compared: number;
  n_skipped: number;
  winner: string;
  ranking: AlphaCompareRow[];
  skipped: AlphaCompareSkip[];
}

// --- Connector runtime channel types ---

/** One mandate profile inside a `mandate.proposal` event (SPEC Consent §1). */
export interface MandateProfile {
  ordinal: number;
  label: string;
  /** Concrete ticker list, or a structural universe descriptor (e.g. "tech_sector"). */
  universe: string[] | string;
  max_order_usd: number;
  daily_trade_cap: number;
  /** "none" for cash-only, otherwise a leverage descriptor/multiple. */
  leverage: string | number;
  instruments: string[];
  notes?: string;
}

/** Account block of a `mandate.proposal` event. */
export interface MandateProposalAccount {
  broker: string;
  type: string;
  funded_by: string;
}

/** Payload of the `mandate.proposal` SSE event (SPEC Consent §1). */
export interface MandateProposal {
  type?: string;
  proposal_id: string;
  session_id?: string;
  intent_normalized?: string;
  account?: MandateProposalAccount;
  ceilings_ref?: string;
  profiles: MandateProfile[];
  funding_note?: string;
  halt_note?: string;
  /** Present only when this proposal was triggered by a mandate breach (SPEC Consent §3). */
  reauth_for?: { breach_id?: string } | null;
}

/** Payload of the `mandate.committed` SSE event (SPEC Consent §1 COMMIT). */
export interface MandateCommitted {
  proposal_id?: string;
  mandate_id?: string;
  consent_record_id?: string;
  selected_ordinal?: number;
  broker?: string;
  /** Resolved limits, surfaced for the compact active-mandate badge. */
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

/** Payload of the `live.halted` SSE event (SPEC Consent §4). */
export interface LiveHalted {
  broker?: string | null;
  tripped_at?: string;
  by?: string;
  reason?: string;
}

/** Payload of the `live.action` SSE event (SPEC Consent §5 audit notify). */
export interface LiveAction {
  audit_id?: string;
  ts?: string;
  kind: string;
  intent_normalized?: string;
  outcome?: string;
  broker?: string;
  remote_tool?: string;
  error?: string | null;
}

export interface CommitMandateRequest {
  broker: string;
  proposal_id: string;
  selected_ordinal: number;
  /** Present only on the adjust path (SPEC Consent §3); null otherwise. */
  adjustments?: Record<string, unknown> | null;
  /** Explicit affirmative consent; the surface sets it on the user's click. */
  consent_ack: boolean;
  session_id?: string;
  account_ref?: string;
  lifetime_days?: number;
}

export interface CommitMandateResponse {
  mandate_id: string;
  consent_record_id: string;
  selected_ordinal?: number;
  broker?: string;
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

export interface HaltLiveResponse {
  halted: boolean;
  broker?: string | null;
  reason: string;
  sentinel: string;
}

export interface LiveAuthorizeRequest {
  broker: string;
}

export interface LiveAuthorizeResponse {
  broker: string;
  connector_profile: string;
  oauth_token_present: boolean;
  instruction: string;
  note?: string;
}

/** Mandate limits surfaced inside a `GET /live/status` broker entry (SPEC §7.5). */
export interface LiveMandateLimits {
  max_order_notional_usd?: number;
  max_total_exposure_usd?: number;
  max_leverage?: number;
  max_trades_per_day?: number;
  allowed_instruments?: string[];
  account_funding_usd?: number;
  [key: string]: unknown;
}

/** Active mandate block of a `GET /live/status` broker entry. */
export interface LiveMandateStatus {
  broker?: string;
  mandate_id?: string;
  account_ref?: string;
  created_at?: string;
  limits?: LiveMandateLimits;
  /** ISO timestamp the mandate auto-expires (SPEC §7.5 #7 proactive expiry). */
  expires_at?: string;
  expires_in_seconds?: number | null;
  expired?: boolean;
}

/** Runner liveness block of a `GET /live/status` broker entry (SPEC §7.5 #3). */
export interface LiveRunnerLiveness {
  broker?: string;
  alive: boolean;
  /** Unix epoch seconds of the last heartbeat tick; null if the runner never started. */
  last_tick?: number | string | null;
  last_tick_age_seconds?: number | null;
}

export interface LiveBrokerAuthStatus {
  broker: string;
  oauth_token_present: boolean;
  is_live_broker: boolean;
  /** Optional during rolling upgrades from OAuth-only runtime responses. */
  profile_id?: string | null;
  transport?: string | null;
  connection_state?: string | null;
  configured?: boolean | null;
  credential_source?: string | null;
  sdk_installed?: boolean | null;
  last_checked_at?: string | null;
  environment_identity?: string | null;
  readonly?: boolean | null;
  capabilities?: string[] | null;
  error_code?: string | null;
  error?: string | null;
}

export interface ConnectorVerifyResponse {
  status?: string;
  profile_id?: string | null;
  transport?: string | null;
  connection_state?: string | null;
  configured?: boolean | null;
  credential_source?: string | null;
  sdk_installed?: boolean | null;
  last_checked_at?: string | null;
  environment_identity?: string | null;
  readonly?: boolean | null;
  capabilities?: string[] | null;
  error_code?: string | null;
  error?: string | null;
  [key: string]: unknown;
}

/** One broker entry in the `GET /live/status` response. */
export interface LiveBrokerStatus {
  auth: LiveBrokerAuthStatus;
  mandate?: LiveMandateStatus | null;
  runner: LiveRunnerLiveness;
  halted: boolean;
}

/** Response of `GET /live/status` (SPEC §7.5 runner status panel + C2). */
export interface LiveStatus {
  brokers: LiveBrokerStatus[];
  global_halted: boolean;
}

/** Response of `POST /live/runner/start|stop`. */
export interface LiveRunnerResponse {
  broker: string;
  started?: boolean;
  already_running?: boolean;
  stopped?: boolean;
  was_running?: boolean;
}

export interface MessageItem {
  message_id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  linked_attempt_id?: string;
  metadata?: Record<string, unknown>;
  tool_trail?: ToolTrailItem[];
}

export interface ToolTrailItem {
  tool: string;
  status: "running" | "ok" | "error";
  arguments?: Record<string, string>;
  elapsed_ms?: number;
  preview?: string;
  call_id?: string;
  timestamp?: number;
}
