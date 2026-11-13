"""Swarm multi-agent system — data models.

All Pydantic models defined here, shared by store / task_store / worker / runtime.
Enums use str+Enum to ensure JSON-serialization compatibility.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from src.tools.redaction import redact_text


_PUBLIC_METADATA_MAX_LENGTH = 128
_REDACTED_METADATA = "[redacted]"
_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_PUBLIC_PROVIDERS = frozenset(
    {
        "anthropic",
        "claude-cli",
        "dashscope",
        "deepseek",
        "gemini",
        "glm",
        "groq",
        "iflytek",
        "kimi",
        "kimi-coding",
        "mimo",
        "minimax",
        "modelscope",
        "moonshot",
        "nvidia",
        "nvidia-nim",
        "ollama",
        "openai",
        "openai-codex",
        "openai_codex",
        "opencode",
        "opencode-go",
        "opencode-zen",
        "openrouter",
        "qwen",
        "siliconflow-cn",
        "siliconflow-global",
        "spark",
        "zai",
        "zhipu",
    }
)
_MODEL_ENDPOINT_PREFIX = re.compile(
    r"^(?:/|localhost|(?:[0-9]{1,3}\.){3}[0-9]{1,3}|\[[0-9a-f:.]+\]|[^/:]+\.[a-z]{2,}|[^/:]+(?=:[0-9]+(?:/|$)))(?::[0-9]+)?(?:/|$)|^[^/]+/(?:api|v[0-9]+(?:alpha|beta)?[0-9]*)(?:/|$)",
    re.IGNORECASE,
)
_PUBLIC_MODEL_IDENTIFIER = re.compile(
    r"^(?:[A-Za-z0-9][A-Za-z0-9._:+-]*|[A-Za-z0-9][A-Za-z0-9._:+-]*/(?=[A-Za-z0-9._:+-]*[-.0-9])[A-Za-z0-9][A-Za-z0-9._:+-]*)$"
)
#: Credential-shaped tokens that carry no issuer prefix in free-text
#: redaction but must never reach public metadata: underscore-style key
#: families (Stripe/OpenAI/Hugging Face), Google/AWS key prefixes, and bare
#: high-entropy tokens.
_CREDENTIAL_TOKEN = re.compile(
    r"^(?:sk|rk|pk|hf)[_-][A-Za-z0-9_-]{4,}$"
    r"|^AIza[A-Za-z0-9_-]{16,}$"
    r"|^ASIA[0-9A-Z]{16,}$"
    r"|^[A-Za-z0-9_-]{40,}$"
)


def public_metadata_value(
    value: str | None,
    *,
    allowed_values: frozenset[str] | None = None,
) -> str | None:
    """Return a bounded, credential-free value for public run metadata."""
    if value is None:
        return None
    metadata = value.strip()
    if not metadata:
        return None
    if len(metadata) > _PUBLIC_METADATA_MAX_LENGTH:
        return _REDACTED_METADATA
    if not metadata.isprintable() or "://" in metadata or metadata.startswith("//"):
        return _REDACTED_METADATA
    if allowed_values is not None and metadata not in allowed_values:
        return _REDACTED_METADATA
    if redact_text(metadata) != metadata:
        return _REDACTED_METADATA
    if _CREDENTIAL_TOKEN.fullmatch(metadata):
        return _REDACTED_METADATA
    return metadata


def public_provider_metadata(value: str | None) -> str | None:
    """Return an approved public provider label for run metadata."""
    return public_metadata_value(
        value.lower() if value is not None else None,
        allowed_values=_PUBLIC_PROVIDERS,
    )


def public_model_metadata(value: str | None) -> str | None:
    """Return a model identifier only when it cannot be mistaken for an endpoint."""
    metadata = public_metadata_value(value)
    if metadata is None or metadata == _REDACTED_METADATA:
        return metadata
    if "?" in metadata or "#" in metadata or "@" in metadata:
        return _REDACTED_METADATA
    if _MODEL_ENDPOINT_PREFIX.match(metadata) or not _PUBLIC_MODEL_IDENTIFIER.fullmatch(metadata):
        return _REDACTED_METADATA
    return metadata


def public_reasoning_effort(value: str | None) -> str | None:
    return public_metadata_value(
        value.lower() if value is not None else None,
        allowed_values=_REASONING_EFFORTS,
    )


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


class WorkerStatus(str, Enum):
    """Terminal status a worker returns.

    ``incomplete`` is distinct from ``failed``: the worker ran without an
    exception but produced no substantive deliverable (plan-only stub,
    fabricated/mock numbers, unparsed tool markup, or a data agent that
    made no tool call and wrote no report). It must never be folded into
    ``completed`` (see P01/P03).

    ``cancelled`` mirrors ``TaskStatus.cancelled``: the worker stopped
    because ``cancel_run()`` was signalled, not because it failed. It must
    never be retried (see ``SwarmRuntime._run_worker_with_retries``).
    """

    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    token_limit = "token_limit"
    incomplete = "incomplete"
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


class SwarmEvent(BaseModel):
    """Swarm event log entry.

    Appended to events.jsonl; supports SSE streaming and post-run audit.

    Attributes:
        type: Event type, e.g. "run_started", "task_completed", "task_failed",
            "task_blocked" (upstream not completed → downstream skipped).
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
        cache_read_tokens: Cumulative prompt-cache read tokens across all
            workers, normalized exactly like ``llm_usage.json``'s
            ``cache_read_tokens`` (see
            :func:`src.agent.llm_usage._normalize_llm_usage`). ``0`` for runs
            persisted before cache tracking existed.
        cache_creation_tokens: Cumulative prompt-cache creation tokens across
            all workers (``cache_creation`` + ``ephemeral_5m_input_tokens`` +
            ``ephemeral_1h_input_tokens``). ``0`` for old runs.
        token_source: Provenance label for the cumulative token totals —
            ``"provider"`` when every contributing worker reported real usage,
            ``"estimated"`` when at least one fell back to the ``len // 4``
            heuristic. ``None`` for runs persisted before this label existed
            (honestly "unlabeled", never silently "provider").
        provider: LLM provider name in effect when the run started
            (e.g. ``"openai"``, ``"anthropic"``, ``"deepseek"``). Captured from
            ``LANGCHAIN_PROVIDER`` at run-creation time. ``None`` if the
            provider could not be resolved. Per-agent overrides — declared via
            :attr:`SwarmAgentSpec.model_name` — are not reflected here; this
            field is the run-level default.
        model: LLM model name in effect when the run started, captured from
            ``LANGCHAIN_MODEL_NAME``. Same scoping rules as :attr:`provider`.
        grounding_data: Pre-fetched OHLCV bars for any suffixed stock or
            crypto symbols mentioned in :attr:`user_vars`. Captured once at
            run-creation time by :mod:`src.swarm.grounding` so workers see
            real recent prices instead of training-data prices. Keyed by the
            original symbol string; each value is the list of bars returned
            by the loader. ``None`` when no symbols were detected or every
            fetch failed.
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
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    token_source: str | None = None
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    use_responses_api: bool | None = None
    grounding_data: dict[str, list[dict]] | None = None


class WorkerResult(BaseModel):
    """Return value after worker execution completes.

    Attributes:
        status: WorkerStatus — completed|failed|timeout|token_limit|incomplete.
        summary: Execution summary.
        artifact_paths: List of generated artifact file paths.
        iterations: Actual ReAct iterations executed.
        error: Error message on failure.
        input_tokens: Cumulative input tokens (exact or estimated).
        output_tokens: Cumulative output tokens (exact or estimated).
        cache_read_tokens: Cumulative prompt-cache read tokens, normalized
            exactly like ``llm_usage.json``'s ``cache_read_tokens`` (see
            :func:`src.agent.llm_usage._normalize_llm_usage`). Defaults to
            ``0`` so results constructed without cache data (runtime
            timeout/error paths, pre-cache ``run.json``) stay valid.
        cache_creation_tokens: Cumulative prompt-cache creation tokens
            (``cache_creation`` + ``ephemeral_5m_input_tokens`` +
            ``ephemeral_1h_input_tokens``). Defaults to ``0``.
        token_source: Provenance of the token counts above — ``"provider"``
            when every measured LLM call reported real ``usage_metadata``,
            ``"estimated"`` when at least one fell back to the ``len // 4``
            heuristic (sticky: a partly-heuristic total is never labeled as
            billed data). ``None`` when no LLM call was measured (early
            exits, runtime timeout/error paths, old persisted data) —
            honestly unlabeled.
    """

    status: WorkerStatus
    summary: str
    artifact_paths: list[str] = Field(default_factory=list)
    iterations: int = 0
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    token_source: str | None = None
    content_filter_warnings: list[str] = Field(default_factory=list)
