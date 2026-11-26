"""Swarm multi-agent system — data models."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.tools.path_utils import is_runtime_path
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
#: Redact unprefixed credential-like tokens before exposing public metadata.
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
    """Filter and normalize a value for public run metadata.

    Args:
        value: Candidate metadata value. Surrounding whitespace is stripped.
        allowed_values: Optional exact-value allowlist.

    Returns:
        The accepted value, None for absent or blank input, or a redaction marker for disallowed
        input.
    """
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
    """Return an approved public provider label for run metadata.

    Args:
        value: Candidate provider label, matched case-insensitively.

    Returns:
        Normalized approved provider label, redaction marker for rejected input, or None for absent
        or blank input.
    """
    return public_metadata_value(
        value.lower() if value is not None else None,
        allowed_values=_PUBLIC_PROVIDERS,
    )


def public_model_metadata(value: str | None) -> str | None:
    """Filter a public model identifier for endpoint and credential patterns.

    Args:
        value: Candidate model identifier.

    Returns:
        The trimmed identifier if accepted, a redaction marker if rejected, or None for absent or
        blank input.
    """
    metadata = public_metadata_value(value)
    if metadata is None or metadata == _REDACTED_METADATA:
        return metadata
    if "?" in metadata or "#" in metadata or "@" in metadata:
        return _REDACTED_METADATA
    if _MODEL_ENDPOINT_PREFIX.match(metadata) or not _PUBLIC_MODEL_IDENTIFIER.fullmatch(metadata):
        return _REDACTED_METADATA
    return metadata


def public_reasoning_effort(value: str | None) -> str | None:
    """Return an approved reasoning-effort label for run metadata.

    Args:
        value: Candidate reasoning-effort label, matched case-insensitively.

    Returns:
        Normalized approved label, redaction marker for rejected input, or None for absent or blank
        input.
    """
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


#: Kinds of upstream evidence a task may select: tool observations, recorded shell or
#: quantlib calculations, and files the producer wrote.
INPUT_KINDS = frozenset({"observation", "calculation", "analysis"})


def _workspace_file(name: Any) -> bool:
    """Return whether ``name`` is a normalized relative POSIX path inside a workspace."""
    if not isinstance(name, str) or not name:
        return False
    path = PurePosixPath(name)
    return not (path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name or name == ".")


def _validate_file_selection(item: Any) -> None:
    """Check one ``input_from`` file selection: a path, or a path with copy_to and/or execution."""
    if isinstance(item, dict):
        if "path" not in item or set(item) - {"path", "copy_to", "execution"} or len(item) < 2:
            raise ValueError("A selected file object needs path plus copy_to and/or execution")
        if "execution" in item and not isinstance(item["execution"], bool):
            raise ValueError("input_from file execution must be a boolean")
        if "copy_to" in item:
            target = item["copy_to"]
            # A copy may not replace the consumer's runtime state or its copied evidence.
            if not _workspace_file(target) or is_runtime_path(target):
                raise ValueError("copy_to must name a deliverable path inside the consumer workspace")
        item = item["path"]
    if not _workspace_file(item):
        raise ValueError("input_from files must be relative paths inside the producer workspace")


class SwarmTask(BaseModel):
    """A task node in the Swarm DAG.

    ``input_from`` maps an alias to an upstream task id (its report and full evidence index), or
    to a selection ``{task, kinds, files}`` that hands over only the chosen evidence: ``kinds``
    from observation / calculation / analysis, and ``files`` as producer-workspace paths or
    ``{path, copy_to, execution}`` objects. ``tools`` narrows the agent's whitelist for this
    task: None inherits it, an empty list allows no tools.
    """

    id: str
    agent_id: str
    prompt_template: str
    depends_on: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    input_from: dict[str, str | dict[str, Any]] = Field(default_factory=dict)
    tools: list[str] | None = None
    status: TaskStatus = TaskStatus.pending
    summary: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    worker_iterations: int = 0

    @field_validator("input_from")
    @classmethod
    def _validate_inputs(cls, inputs: dict) -> dict:
        """Refuse malformed evidence selections before any task is dispatched.

        Args:
            inputs: Alias to upstream task id or selection object.

        Returns:
            The unchanged bindings.

        Raises:
            ValueError: If a binding names no task, has an unknown key or kind, selects nothing,
                or names a file outside the workspace or a copy over runtime state.
        """
        for binding in inputs.values():
            if isinstance(binding, str):
                if not binding:
                    raise ValueError("input_from task must not be empty")
                continue
            if set(binding) - {"task", "kinds", "files"}:
                raise ValueError("input_from selections support task, kinds and files only")
            if not isinstance(binding.get("task"), str) or not binding["task"]:
                raise ValueError("input_from selection requires a task")
            kinds, files = binding.get("kinds", []), binding.get("files", [])
            if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds):
                raise ValueError("input_from kinds must be a list of strings")
            if set(kinds) - INPUT_KINDS:
                raise ValueError("input_from kinds must be observation, calculation or analysis")
            if not isinstance(files, list):
                raise ValueError("input_from files must be a list")
            if not kinds and not files:
                raise ValueError("input_from selection requires kinds or files")
            for item in files:
                _validate_file_selection(item)
        return inputs

    def input_tasks(self) -> dict[str, str]:
        """Map every input alias to its upstream task id, for plain and selected bindings.

        Returns:
            Alias to upstream task id.
        """
        return {alias: binding if isinstance(binding, str) else binding["task"]
                for alias, binding in self.input_from.items()}

    def effective_tools(self, agent: SwarmAgentSpec) -> list[str]:
        """Narrow an agent's tool whitelist for this task; never widen it.

        Args:
            agent: Agent that executes this task.

        Returns:
            The agent's tools when the task inherits them, else the task's own list.

        Raises:
            ValueError: If the task names a tool the agent is not allowed.
        """
        if self.tools is None:
            return agent.tools
        extra = sorted(set(self.tools) - set(agent.tools))
        if extra:
            raise ValueError(
                f"Task '{self.id}' tools must be a subset of agent '{agent.id}' tools; not allowed: {', '.join(extra)}"
            )
        return list(self.tools)


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
    prefetch_grounding: bool = True
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
