"""Pydantic models for the Vibe-Trading API server.

Extracted verbatim from ``api_server.py`` (PR-0 of the api_server refactor).
This is a LEAF module — it imports only from stdlib + Pydantic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Pydantic Models
# ============================================================================

class Artifact(BaseModel):
    """Artifact file metadata."""
    name: str = Field(..., description="File name")
    path: str = Field(..., description="File path")
    type: str = Field(..., description="File type: csv, json, txt, etc.")
    size: int = Field(..., description="Size in bytes")
    exists: bool = Field(..., description="Whether the file exists")


class BacktestMetrics(BaseModel):
    """Backtest summary metrics."""
    model_config = {"extra": "allow"}

    final_value: float = Field(..., description="Ending portfolio value")
    total_return: float = Field(..., description="Total return")
    annual_return: float = Field(..., description="Annualized return")
    max_drawdown: float = Field(..., description="Max drawdown")
    sharpe: float = Field(..., description="Sharpe ratio")
    win_rate: float = Field(..., description="Win rate")
    trade_count: int = Field(..., description="Number of trades")



class RAGSelection(BaseModel):
    """RAG routing result."""
    selected_api: str = Field(..., description="Selected API code")
    selected_name: str = Field(..., description="Selected API name")
    selected_score: float = Field(..., description="Match score")


class RunInfo(BaseModel):
    """Compact run row for list views."""
    run_id: str
    status: str
    created_at: str
    prompt: Optional[str] = None
    total_return: Optional[float] = None
    sharpe: Optional[float] = None
    codes: List[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class RunResponse(BaseModel):
    """API response payload for a single run."""

    status: str = Field(..., description="Run status: success, failed, aborted")
    run_id: str = Field(..., description="Run identifier")
    elapsed_seconds: float = Field(..., description="Execution time in seconds")
    reason: Optional[str] = Field(None, description="Failure reason when available")

    planner_output: Optional[Dict[str, Any]] = Field(None, description="Planner output")
    strategy_spec: Optional[Dict[str, Any]] = Field(None, description="Strategy specification")
    rag_selection: Optional[RAGSelection] = Field(None, description="Selected RAG metadata")

    metrics: Optional[BacktestMetrics] = Field(None, description="Backtest metrics")
    artifacts: List[Artifact] = Field(default_factory=list, description="Run artifacts")
    run_card: Optional[Dict[str, Any]] = Field(None, description="Trust Layer run card payload")
    llm_usage: Optional[Dict[str, Any]] = Field(None, description="Provider-reported AgentLoop usage summary")

    equity_curve: Optional[List[Dict[str, Any]]] = Field(None, description="Equity preview")
    trade_log: Optional[List[Dict[str, Any]]] = Field(None, description="Trade preview")

    artifacts_equity_csv: Optional[List[Dict[str, Any]]] = Field(None, description="Full equity rows")
    artifacts_metrics_csv: Optional[List[Dict[str, Any]]] = Field(None, description="Full metrics rows")
    artifacts_trades_csv: Optional[List[Dict[str, Any]]] = Field(None, description="Full trade rows")
    validation: Optional[Dict[str, Any]] = Field(None, description="Statistical validation results")

    run_directory: str = Field(..., description="Run directory path")
    run_stage: Optional[str] = Field(None, description="UI-facing run stage")
    run_context: Optional[Dict[str, Any]] = Field(None, description="Normalized request context")
    price_series: Optional[Dict[str, List[Dict[str, Any]]]] = Field(None, description="Grouped OHLC series")
    indicator_series: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = Field(
        None,
        description="Grouped indicator overlays",
    )
    trade_markers: Optional[List[Dict[str, Any]]] = Field(None, description="Trade markers for charts")
    run_logs: Optional[List[Dict[str, Any]]] = Field(None, description="Structured stdout/stderr lines")


class HealthResponse(BaseModel):
    """Health check payload."""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
    timestamp: str = Field(..., description="Server timestamp")


class LLMProviderOption(BaseModel):
    """Supported LLM provider metadata for the settings UI."""

    name: str
    label: str
    api_key_env: Optional[str] = None
    base_url_env: str
    default_model: str
    default_base_url: str
    api_key_required: bool = True
    auth_type: str = "api_key"
    login_command: Optional[str] = None


class LLMSettingsResponse(BaseModel):
    """Current LLM runtime settings."""

    provider: str
    model_name: str
    base_url: str
    api_key_env: Optional[str] = None
    api_key_configured: bool
    api_key_hint: Optional[str] = None
    api_key_required: bool
    temperature: float
    timeout_seconds: int
    max_retries: int
    reasoning_effort: str
    sse_timeout_seconds: int
    env_path: str
    providers: List[LLMProviderOption]


class UpdateLLMSettingsRequest(BaseModel):
    """Update LLM settings persisted to agent/.env."""

    provider: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    temperature: float = 0.0
    timeout_seconds: int = Field(120, ge=1, le=3600)
    max_retries: int = Field(2, ge=0, le=20)
    reasoning_effort: Optional[str] = None


class DataSourceSettingsResponse(BaseModel):
    """Current data source credential settings."""

    tushare_token_configured: bool
    tushare_token_hint: Optional[str] = None
    baostock_supported: bool
    baostock_installed: bool
    baostock_message: str
    env_path: str


class UpdateDataSourceSettingsRequest(BaseModel):
    """Update project-local data source credentials."""

    tushare_token: Optional[str] = None
    clear_tushare_token: bool = False


# ---- V4 Session Models ----

class CreateSessionRequest(BaseModel):
    """Create session request body."""
    title: str = Field("", description="Session title")
    config: Optional[Dict[str, Any]] = Field(None, description="Session config")


class SessionResponse(BaseModel):
    """Session record."""
    session_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    last_attempt_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Send chat message: natural-language strategy description."""
    content: str = Field(..., description="Natural language strategy description", min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    """Stored chat message."""
    message_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    linked_attempt_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CreateGoalRequest(BaseModel):
    """Create or replace a finance research goal."""

    objective: str = Field(..., min_length=1, max_length=5000)
    criteria: List[str] = Field(default_factory=list)
    ui_summary: str = ""
    protocol: str = "thesis_review"
    risk_tier: str = "research_general"
    token_budget: Optional[int] = Field(None, ge=1)
    turn_budget: Optional[int] = Field(None, ge=1)
    time_budget_seconds: Optional[int] = Field(None, ge=1)


class UpdateGoalRequest(BaseModel):
    """Edit mutable finance research goal fields."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    objective: Optional[str] = Field(None, min_length=1, max_length=5000)
    ui_summary: Optional[str] = Field(None, max_length=500)


class AddGoalEvidenceRequest(BaseModel):
    """Append evidence to a finance research goal."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=10000)
    criterion_id: Optional[str] = None
    claim_id: Optional[str] = None
    evidence_type: str = "evidence"
    tool_call_id: Optional[str] = None
    run_id: Optional[str] = None
    source_provider: Optional[str] = None
    source_type: Optional[str] = None
    source_uri: Optional[str] = None
    symbol_universe: List[str] = Field(default_factory=list)
    benchmark: List[str] = Field(default_factory=list)
    timeframe: Optional[str] = None
    method: Optional[str] = None
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    artifact_path: Optional[str] = None
    artifact_hash: Optional[str] = None
    data_as_of: Optional[str] = None
    confidence: Optional[str] = None
    caveat: Optional[str] = None
    contradicts_claim_ids: List[str] = Field(default_factory=list)


class GoalSnapshotResponse(BaseModel):
    """Finance research goal snapshot."""

    goal: Dict[str, Any]
    claims: List[Dict[str, Any]]
    criteria: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    evidence_count: int = 0


class AddGoalEvidenceResponse(BaseModel):
    """Response after appending goal evidence."""

    evidence: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class GoalAuditRowRequest(BaseModel):
    """One criterion row for goal status audits."""

    criterion_id: str = Field(..., min_length=1)
    result: str = Field(..., min_length=1)
    evidence_ids: List[str] = Field(default_factory=list)
    notes: str = ""


class UpdateGoalStatusRequest(BaseModel):
    """Update a finance research goal status."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    audit: List[GoalAuditRowRequest] = Field(default_factory=list)
    recap: Optional[str] = None


class UpdateGoalStatusResponse(BaseModel):
    """Response after changing a goal status."""

    goal: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class UpdateGoalResponse(BaseModel):
    """Response after editing a goal."""

    goal: Dict[str, Any]
    snapshot: GoalSnapshotResponse


# ---- Live trading channel: consent commit + kill switch ----


class CommitMandateRequest(BaseModel):
    """Surface-originated mandate commit (Consent §1 / §3).

    This is the ONLY write path that activates a live-trading mandate. It is a
    privileged HTTP action the user surface sends on an explicit click/keypress
    — NOT a tool the agent model can call. ``consent_ack`` MUST be ``true``.
    """

    broker: str = Field(..., min_length=1, max_length=64)
    proposal_id: str = Field(..., pattern=r"^mp_[0-9a-f]{32}$")
    selected_ordinal: int = Field(..., ge=1, le=10)
    adjustments: Optional[Dict[str, Any]] = None
    consent_ack: bool = Field(..., description="Explicit affirmative; must be true")
    session_id: Optional[str] = None
    account_ref: str = Field("", max_length=128)
    lifetime_days: int = Field(30, ge=1, le=365)


class LiveHaltRequest(BaseModel):
    """Trip or clear the live kill switch (Consent §4).

    Tripping/clearing is a privileged surface action, never an agent tool. When
    ``broker`` is omitted the GLOBAL switch is used (halts every broker).
    """

    broker: Optional[str] = Field(None, max_length=64)
    reason: str = Field("user requested halt", max_length=500)
    session_id: Optional[str] = None


class LiveAuthorizeRequest(BaseModel):
    """Kick off (or describe) the OAuth bootstrap for a live broker (C2).

    Vibe-Trading never holds funds and never operates a venue, so the OAuth
    bootstrap runs through the broker's own user-authorized device flow on the
    client (CLI / desktop MCP), not a server-side redirect. This endpoint is the
    web on-ramp: it tells a Web UI user exactly how to discover/start the flow.
    """

    broker: str = Field(..., min_length=1, max_length=64)


class LiveRunnerControlRequest(BaseModel):
    """Start or stop the persistent live runner for one broker (SPEC §7.5).

    The runner wakes on schedule/market events and trades autonomously inside a
    committed mandate. Starting it is a privileged surface action, never an
    agent tool. A committed, unexpired mandate must already exist.
    """

    broker: str = Field(..., min_length=1, max_length=64)
    session_id: Optional[str] = None


class BrokerAuthState(BaseModel):
    """Per-broker authorization snapshot for ``GET /live/status``."""

    broker: str
    oauth_token_present: bool = Field(..., description="Whether an OAuth token cache exists")
    is_live_broker: bool = Field(..., description="Whether this key is a recognized live broker")


class MandateLimits(BaseModel):
    """Flattened active-mandate limits surfaced to the UI (Mandate layer a/b)."""

    max_order_notional_usd: float
    max_total_exposure_usd: float
    max_leverage: float
    max_trades_per_day: int
    allowed_instruments: List[str]
    account_funding_usd: float


class ActiveMandateState(BaseModel):
    """Active-mandate snapshot with the expiry countdown (SPEC §9 dec. 2)."""

    broker: str
    account_ref: str
    created_at: str
    expires_at: str
    expires_in_seconds: Optional[int] = Field(
        None, description="Seconds until expiry; negative when already expired"
    )
    expired: bool
    limits: MandateLimits


class RunnerLivenessState(BaseModel):
    """Runner liveness snapshot via the §7.5 liveness contract."""

    broker: str
    alive: bool
    last_tick: Optional[float] = Field(None, description="Unix epoch of last heartbeat tick")
    last_tick_age_seconds: Optional[float] = None


class LiveBrokerStatus(BaseModel):
    """Combined live-channel status for a single broker."""

    auth: BrokerAuthState
    mandate: Optional[ActiveMandateState] = None
    runner: RunnerLivenessState
    halted: bool = Field(..., description="Per-broker OR global kill switch is tripped")


class LiveStatusResponse(BaseModel):
    """Top-level live-channel status (C2)."""

    global_halted: bool = Field(..., description="Whether the GLOBAL kill switch is tripped")
    brokers: List[LiveBrokerStatus]


class ChannelPairingCommandRequest(BaseModel):
    """Pairing command executed through the IM control surface."""

    channel: str = Field(..., min_length=1, max_length=64)
    command: str = Field("list", max_length=500)


# ---- Models defined later in api_server.py ----


class UpdateSessionRequest(BaseModel):
    """Session update fields."""
    title: Optional[str] = None


class LiveRunnerUnavailable(RuntimeError):
    """Raised when a live runner cannot be wired (broker not configured/authorized).

    Distinct from a programming error so the start endpoint can map it to a 503
    rather than a 500: the runtime is fine, the broker channel just isn't ready.
    """


class CreateScheduledRunRequest(BaseModel):
    """Request body for POST /scheduled-runs."""

    id: Optional[str] = Field(None, description="Job id; auto-generated UUID when omitted")
    prompt: str = Field(..., min_length=1, description="Research prompt or backtest description")
    schedule: str = Field(..., min_length=1, description="Interval-ms or 5-field cron expression")
    next_run_at: Optional[int] = Field(None, description="Epoch-ms for next run; defaults to now")
    config: Dict[str, Any] = Field(default_factory=dict, description="Optional backtest parameters")


class ScheduledRunResponse(BaseModel):
    """API response for a single scheduled job."""

    id: str
    prompt: str
    schedule: str
    next_run_at: int
    status: str
    created_at: int
    config: Dict[str, Any] = Field(default_factory=dict)
