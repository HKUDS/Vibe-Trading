"""Swarm multi-agent system — data models."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from src.tools.redaction import redact_text
from src.providers.registry import provider_names


_PUBLIC_METADATA_MAX_LENGTH = 128
_REDACTED_METADATA = "[redacted]"
_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_PUBLIC_PROVIDERS = provider_names() | {"openai_codex"}
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
    """SwarmTask lifecycle status."""

    pending = "pending"
    blocked = "blocked"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RunStatus(str, Enum):
    """SwarmRun lifecycle status."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class WorkerStatus(str, Enum):
    """Terminal status a worker returns."""

    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    token_limit = "token_limit"
    incomplete = "incomplete"
    cancelled = "cancelled"


class SwarmAgentSpec(BaseModel):
    """Role definition for a single agent in a Swarm."""

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
    """A task node in the Swarm DAG."""

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
    """Swarm event log entry."""

    type: str
    agent_id: str | None = None
    task_id: str | None = None
    data: dict = Field(default_factory=dict)
    timestamp: str


class SwarmRun(BaseModel):
    """Complete state of a single Swarm preset execution."""

    id: str
    preset_name: str
    status: RunStatus = RunStatus.pending
    user_vars: dict[str, str] = Field(default_factory=dict)
    agents: list[SwarmAgentSpec] = Field(default_factory=list)
    tasks: list[SwarmTask] = Field(default_factory=list)
    created_at: str
    completed_at: str | None = None
    final_report: str | None = None
    report_is_partial: bool = False
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
    """Return value after worker execution completes."""

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
