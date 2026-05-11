"""Swarm multi-agent system — data models.

All Pydantic models defined here, shared by store / task_store / mailbox / worker / runtime.
Enums use str+Enum to ensure JSON-serialization compatibility.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """SwarmTask lifecycle status.

    Transitions:
        pending -> blocked -> in_progress -> completed | failed | cancelled
    """

    pending = "pending"
    blocked = "blocked"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RunStatus(str, Enum):
    """SwarmRun lifecycle status.

    Transitions:
        pending -> running -> completed | failed | cancelled
    """

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SwarmAgentSpec(BaseModel):
    """Role definition for a single agent in a Swarm.

    Parsed from YAML presets, describes the agent's identity, available tools, and constraints.

    Attributes:
        id: Unique identifier, e.g. "macro_analyst".
        role: Role description.
        system_prompt: System prompt injected into the LLM.
        tools: Whitelist of allowed tool names.
        skills: List of allowed skill names.
        max_iterations: Maximum ReAct loop iterations.
        timeout_seconds: Worker timeout in seconds.
        model_name: Override default model; None uses global config.
        max_retries: Maximum retry attempts on failure.
    """

    id: str
    role: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    max_iterations: int = 25
    timeout_seconds: int = 300
    model_name: str | None = None
    max_retries: int = 2


class SwarmTask(BaseModel):
    """A task node in the Swarm DAG.

    Each task is bound to an agent. Dependencies are declared via depends_on,
    and blocked_by tracks remaining incomplete upstream tasks at runtime.

    Attributes:
        id: Unique identifier, e.g. "analyze_macro".
        agent_id: ID of the agent executing this task.
        prompt_template: User prompt template supporting {var} placeholders.
        depends_on: DAG-declared upstream task IDs (immutable).
        blocked_by: Remaining incomplete upstream task IDs (shrinks at runtime).
        input_from: Mapping to pull summaries from upstream tasks, e.g. {"macro": "analyze_macro"}.
        status: Current task status.
        summary: Summary text after completion.
        artifacts: List of output file paths.
        error: Error message on failure.
        started_at: ISO-format start time.
        completed_at: ISO-format completion time.
        worker_iterations: Actual ReAct iterations executed by the worker.
    """

    id: str
    agent_id: str
    prompt_template: str
    depends_on: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    input_from: dict[str, str] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.pending
    summary: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    worker_iterations: int = 0


class SwarmMessage(BaseModel):
    """Message passed between agents via the Mailbox file inbox.

    Carries only summaries and artifact paths to avoid context bloat.

    Attributes:
        id: Unique message ID.
        type: Message type, e.g. "task_result", "request", "broadcast".
        from_agent: Sending agent ID.
        to: Receiving agent ID.
        content: Message body (summary level).
        artifact_paths: Associated artifact file paths.
        timestamp: ISO-format timestamp.
    """

    id: str
    type: str
    from_agent: str
    to: str
    content: str
    artifact_paths: list[str] = Field(default_factory=list)
    timestamp: str


class SwarmEvent(BaseModel):
    """Swarm event log entry.

    Appended to events.jsonl; supports SSE streaming and post-run audit.

    Attributes:
        type: Event type, e.g. "run_started", "task_completed", "task_failed".
        agent_id: Associated agent ID (optional).
        task_id: Associated task ID (optional).
        data: Arbitrary additional data.
        timestamp: ISO-format timestamp.
    """

    type: str
    agent_id: str | None = None
    task_id: str | None = None
    data: dict = Field(default_factory=dict)
    timestamp: str


class SwarmRun(BaseModel):
    """Complete state of a single Swarm preset execution.

    Persisted as .swarm/runs/{id}/run.json; the top-level aggregate root.

    Attributes:
        id: Unique run ID (UUID).
        preset_name: Preset name used, e.g. "research_team".
        status: Run status.
        user_vars: User-provided variables for template rendering.
        agents: List of participating agent definitions.
        tasks: All task entries.
        created_at: ISO-format creation time.
        completed_at: ISO-format completion time.
        final_report: Final aggregated report text.
        total_input_tokens: Cumulative input tokens across all workers.
        total_output_tokens: Cumulative output tokens across all workers.
        provider: LLM provider name in effect when the run started
            (e.g. ``"openai"``, ``"anthropic"``, ``"deepseek"``). Captured from
            ``LANGCHAIN_PROVIDER`` at run-creation time. ``None`` if the
            provider could not be resolved. Per-agent overrides — declared via
            :attr:`SwarmAgentSpec.model_name` — are not reflected here; this
            field is the run-level default.
        model: LLM model name in effect when the run started, captured from
            ``LANGCHAIN_MODEL_NAME``. Same scoping rules as :attr:`provider`.
    """

    id: str
    preset_name: str
    status: RunStatus = RunStatus.pending
    user_vars: dict[str, str] = Field(default_factory=dict)
    agents: list[SwarmAgentSpec] = Field(default_factory=list)
    tasks: list[SwarmTask] = Field(default_factory=list)
    created_at: str
    completed_at: str | None = None
    final_report: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    provider: str | None = None
    model: str | None = None


class WorkerResult(BaseModel):
    """Return value after worker execution completes.

    Attributes:
        status: "completed" or "failed".
        summary: Execution summary.
        artifact_paths: List of generated artifact file paths.
        iterations: Actual ReAct iterations executed.
        error: Error message on failure.
        input_tokens: Cumulative input tokens (exact or estimated).
        output_tokens: Cumulative output tokens (exact or estimated).
    """

    status: str
    summary: str
    artifact_paths: list[str] = Field(default_factory=list)
    iterations: int = 0
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
