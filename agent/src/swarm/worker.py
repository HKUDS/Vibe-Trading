"""Swarm task preparation, kernel ports and worker result delivery."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable, NamedTuple, Protocol

from src.product.context import ContextBuilder
from src.product.resources.instructions import build_instruction_block
from src.product.usage import _normalize_llm_usage
from src.kernel.progress import HeartbeatTimer
from src.product.resources.skills import SkillsLoader
from src.agent.tools import BaseTool, ToolRegistry
from src.product.result_artifacts import deliver_tool_result
from src.product.tool_invocation import ToolRefusal, prepare_tool_call
from src.config.schema import AgentConfig
from src.kernel.contracts import (
    Continue, Iteration, LLMResponse, LLMRuntimeSnapshot, LoopContext, LoopPorts, RunLimits, Stop,
)
from src.kernel.events import EventSink
from src.kernel.loop import run_loop
from src.providers.chat import ChatLLM
from src.providers.response import ProviderStreamError
from src.providers.messages import repair_provider_messages
from src.providers.content_filter import (
    CONTENT_FILTER_SKIP_MESSAGE,
    MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS,
    compute_content_filter_warnings,
)
from src.swarm.artifacts import agent_artifact_dir, collect_artifacts
from src.swarm.models import (
    SwarmAgentSpec,
    SwarmEvent,
    SwarmTask,
    WorkerResult,
    WorkerStatus,
)
from src.swarm.context import WorkerContext
from src.swarm import checkpoint
from src.tools import build_swarm_registry
from src.data_gateway.guidance import DATA_ACCESS_POLICY
from src.tools.mcp import MCPRemoteTool
from src.tools.redaction import redact_payload, redact_tool_result

logger = logging.getLogger(__name__)


class _CancellationSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


def _default_max_iterations() -> int:
    from src.config.accessor import get_env_config
    return get_env_config().swarm.swarm_worker_max_iter


def _default_timeout_seconds() -> int:
    from src.config.accessor import get_env_config
    return get_env_config().swarm.swarm_worker_timeout


def _heartbeat_interval_s() -> float:
    """Resolve the heartbeat tick interval from env, robust to garbage values.

    Matches the parsing discipline in :func:`SwarmStore.compute_stale_threshold`
    — both sides use the same env var, so they must fail the same way. A bad
    value (``"abc"``, empty) falls back to 3.0s instead of crashing import.
    """
    from src.config.accessor import get_env_config

    return get_env_config().swarm.swarm_heartbeat_interval_s


def _stream_retry_delay_s() -> float:
    """Resolve the delay before the single stream retry, robust to garbage.

    Returns:
        Seconds to sleep between a failed ``stream_chat`` attempt and its one
        retry. Configurable via ``SWARM_STREAM_RETRY_DELAY_S``; a bad value
        falls back to 1.0s instead of crashing import.
    """
    from src.config.accessor import get_env_config

    return get_env_config().swarm.swarm_stream_retry_delay_s


def _stream_retry_max_delay_s() -> float:
    """Resolve the cap for the escalating stream-retry delay, robust to garbage.

    Returns:
        Upper bound in seconds for both the escalated exponential delay and a
        provider-suggested ``Retry-After``. Configurable via
        ``SWARM_STREAM_RETRY_MAX_DELAY_S``; a non-numeric value fails config
        validation, mirroring the other swarm delay knobs.
    """
    from src.config.accessor import get_env_config

    return get_env_config().swarm.swarm_stream_retry_max_delay_s


def _escalated_stream_retry_delay_s(streak: int) -> float:
    """Return the capped exponential delay for the one-based failure streak.

    Doubles per consecutive retryable failure (1.0s, 2.0s, 4.0s, ...) so a
    sustained provider outage backs off instead of burning the retry budget
    at a constant cadence. The exponent is clamped at 62 (mirroring
    ``src/swarm/runtime.py``'s worker-level backoff) and the result is capped
    at ``_STREAM_RETRY_MAX_DELAY_S`` so a long outage never exceeds the
    configured ceiling.

    Args:
        streak: Number of consecutive retryable stream failures including the
            current one; values below 1 are treated as 1.

    Returns:
        Seconds to sleep before the stream retry, never negative.
    """
    ceiling = min(
        _STREAM_RETRY_DELAY_S * (2 ** min(max(streak, 1) - 1, 62)),
        _STREAM_RETRY_MAX_DELAY_S,
    )
    return max(ceiling, 0.0)


_HEARTBEAT_INTERVAL_S = _heartbeat_interval_s()
_STREAM_RETRY_DELAY_S = _stream_retry_delay_s()
_STREAM_RETRY_MAX_DELAY_S = _stream_retry_max_delay_s()
# Test override; production uses the model window and configured cost ceiling.
_MAX_TOKEN_ESTIMATE: int | None = None


def _emit(
    callback: Callable[[SwarmEvent], None] | None,
    event_type: str,
    agent_id: str,
    task_id: str,
    data: dict | None = None,
) -> None:
    """Emit a swarm event via callback if provided.

    Args:
        callback: Optional event callback function.
        event_type: Event type string.
        agent_id: Agent identifier.
        task_id: Task identifier.
        data: Additional event data.
    """
    if callback is None:
        return
    event = SwarmEvent(
        type=event_type,
        agent_id=agent_id,
        task_id=task_id,
        data=data or {},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    try:
        callback(event)
    except Exception:
        logger.warning("Event callback failed for %s", event_type, exc_info=True)


def _filter_skill_descriptions(loader: SkillsLoader, skill_names: list[str]) -> str:
    """Return skill descriptions filtered to the given whitelist.

    Args:
        loader: SkillsLoader instance with all skills loaded.
        skill_names: Skill names to include. Empty list means include all.

    Returns:
        Formatted skill descriptions string.
    """
    if not skill_names:
        return loader.get_descriptions()
    lines: list[str] = []
    for skill in loader.skills:
        if skill.name in skill_names:
            lines.append(f"  - {skill.name}: {skill.description}")
    return "\n".join(lines) if lines else "(no matching skills)"


class UsageMeasure(NamedTuple):
    """Token usage of a single LLM call, with cache breakdown and provenance.

    Attributes:
        input_tokens: Input tokens — provider-reported or heuristic estimate.
        output_tokens: Output tokens — provider-reported or heuristic estimate.
        cache_read_tokens: Prompt-cache read tokens (0 when estimated).
        cache_creation_tokens: Prompt-cache creation tokens (0 when estimated).
        token_source: ``"provider"`` when the counts came from real
            ``usage_metadata``, ``"estimated"`` when they came from the
            ``len // 4`` heuristic.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    token_source: str


def _measure_usage(
    messages: list[dict],
    response: object,
) -> UsageMeasure:
    """Return full token usage for a single LLM call, real if available.

    Prefers the provider-reported counts attached to the response by
    :func:`src.providers.response.parse_response` (``usage_metadata``), normalized through
    :func:`src.product.usage._normalize_llm_usage` — the exact same
    normalization the main agent loop applies behind ``llm_usage.json``, so
    the swarm never grows a second cache-token accounting rule. Falls back to a
    character-length heuristic (``len // 4``) only when the provider didn't
    return usage data — keeps the behaviour contract for legacy or partial
    responses while making per-run totals (which feed
    ``SwarmRun.total_input_tokens`` / ``total_output_tokens`` and the cache
    totals) reflect real billing instead of a CJK-hostile char-count guess.

    Args:
        messages: Messages sent to the LLM for this call. Used only for
            the fallback estimate when ``response.usage_metadata`` is
            missing.
        response: ``LLMResponse`` from ``ChatLLM.chat`` /
            ``ChatLLM.stream_chat``.

    Returns:
        :class:`UsageMeasure` with input/output tokens, the prompt-cache
        breakdown (zero on the heuristic path — a cache count is never
        estimated) and the ``token_source`` provenance label. Any token
        component may be zero — that simply means the provider didn't
        report it and the fallback couldn't compute it either (e.g.
        binary content).
    """
    if isinstance(response, LLMResponse) and response.usage_metadata:
        normalized = _normalize_llm_usage(response.usage_metadata)
        if normalized is not None:
            return UsageMeasure(
                input_tokens=normalized["input_tokens"],
                output_tokens=normalized["output_tokens"],
                cache_read_tokens=normalized.get("cache_read_tokens", 0),
                cache_creation_tokens=normalized.get("cache_creation_tokens", 0),
                token_source="provider",
            )

    # Fallback: provider didn't return usage_metadata. Estimate from
    # serialized message length and response content length. ~4 chars per
    # English token; under-counts for CJK / Thai / emoji-heavy prompts but
    # at least preserves the prior behaviour.
    try:
        input_tokens = len(json.dumps(messages, ensure_ascii=False)) // 4
    except Exception:
        input_tokens = 0

    if isinstance(response, LLMResponse):
        output_tokens = len(response.content or "") // 4
    else:
        output_tokens = 0

    return UsageMeasure(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        token_source="estimated",
    )


def _estimate_tokens(
    messages: list[dict],
    response: object,
) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) for a single LLM call.

    Thin wrapper over :func:`_measure_usage` preserving the historical
    2-tuple contract for existing callers and tests; the cache breakdown
    and ``token_source`` provenance label are available from
    :func:`_measure_usage` directly.

    Args:
        messages: Messages sent to the LLM for this call.
        response: ``LLMResponse`` from ``ChatLLM.chat`` /
            ``ChatLLM.stream_chat``.

    Returns:
        Tuple of (input_tokens, output_tokens).
    """
    measured = _measure_usage(messages, response)
    return measured.input_tokens, measured.output_tokens


def build_worker_prompt(
    agent_spec: SwarmAgentSpec,
    upstream_summaries: dict[str, str],
    skill_descriptions: str,
    grounding_block: str = "",
    available_tools: set[str] | None = None,
) -> str:
    """Build the worker's system prompt with role, upstream context, and skills.

    Args:
        agent_spec: The agent's role specification.
        upstream_summaries: Mapping of context_key -> upstream task summary.
        skill_descriptions: Pre-filtered skill description text.
        grounding_block: Optional "Ground Truth" markdown produced by
            :func:`src.swarm.grounding.format_grounding_block`. Spliced in
            ahead of the Execution Rules section so the worker sees real
            recent prices before any tool decision. Empty string skips the
            section entirely.
        available_tools: Actual registered tool names after runtime policy filtering.
            Defaults to the spec whitelist for standalone prompt inspection.

    Returns:
        Complete system prompt string for the worker LLM.
    """
    # Static, agent-invariant blocks first: for a given agent_spec these are
    # byte-identical on every call (skill_descriptions/tools come from the
    # agent's own YAML spec, not the current task), so they form one stable
    # prompt-cache-eligible prefix across a swarm's repeated calls to the
    # same agent. Anything that varies per call (upstream context, grounding
    # data, the current date) is appended after, in the same relative order
    # as before -- a cache hit only needs a stable *prefix*, so moving the
    # variable tail doesn't need to preserve position, only what precedes it.
    prompt_parts = [f"## Role\n\n{agent_spec.role}"]

    if skill_descriptions and skill_descriptions != "(no matching skills)":
        prompt_parts.append(
            f"## Available Skills (use load_skill to access full documentation)\n\n{skill_descriptions}"
        )

    prompt_parts.append(DATA_ACCESS_POLICY)

    prompt_parts.append(
        "## Research Evidence and Assumptions\n\n"
        "Base claims about observed market/company facts on tool results, dated "
        "snapshots, or the supplied upstream evidence. Identify the source and "
        "observation date when they affect the conclusion. Reusing upstream data "
        "is valid; distinguish it from a new retrieval by this role. Independent "
        "judgment does not imply newly verified facts. Compute derived metrics "
        "with the available tools and keep their sample windows and assumptions "
        "attached. Clearly label proposed prices, scenarios and sizing as your "
        "assumptions or recommendations. When data is missing, explain the gap "
        "and give the useful analysis that is still supported. No fixed citation "
        "or declaration format is required."
    )

    # From here on, content varies per call (upstream context substitution,
    # grounding data, the date), so none of it extends the cacheable prefix
    # above -- relative order matches the original layout exactly.
    upstream_block = ""
    if upstream_summaries:
        sections = []
        for key, summary in upstream_summaries.items():
            sections.append(f"### {key}\n{summary}")
        upstream_block = (
            "## Upstream Context (from previous agents)\n\n"
            + "\n\n".join(sections)
        )
    prompt_parts.append(agent_spec.system_prompt.replace("{upstream_context}", upstream_block))

    # Swarm workers have a purpose-built prompt instead of ContextBuilder, but
    # they are still agent runs and must receive the runtime-root standing
    # instructions. A CLI launch directory is intentionally unavailable here.
    instruction_block = build_instruction_block()
    if instruction_block:
        prompt_parts.append(instruction_block)

    if grounding_block:
        # Placed before Execution Rules so it's in scope when the worker
        # plans its first tool call. The block already contains an explicit
        # instruction to prefer these prices over training data.
        prompt_parts.append(grounding_block)

    enabled_tools = set(agent_spec.tools or []) if available_tools is None else available_tools
    iteration_budget = agent_spec.max_iterations or _default_max_iterations()
    prompt_parts.append(
        "## Execution Rules\n\n"
        f"You have at most {iteration_budget} model iterations. Reuse supplied data "
        "and upstream reports; call available tools when more evidence or calculations "
        "are needed. Load a skill when its methodology or API contract is useful. "
        "Deliver the requested analysis directly in your final response. "
        "Create files when requested or useful; a report.md file is optional. "
        "Explain unavailable inputs and distinguish assumptions from observed results. "
        "Using an upstream report is not a new independent retrieval of its facts. "
        "Attribute inherited facts and separate your calculations from new data fetches; "
        "refetch only when needed, without imposing a citation format. "
        "Respond in the task's language."
    )
    if "bash" not in enabled_tools:
        prompt_parts.append(
            "Shell execution is unavailable. Use assigned data and calculation tools "
            "directly; do not write scripts you cannot execute."
        )

    now = datetime.now(timezone.utc)
    prompt_parts.append(
        f"## Current Date & Time\n\n"
        f"Today is {now.strftime('%A, %B %d, %Y %H:%M UTC')}"
    )
    # Resume refreshes this turn-specific guidance along with the timestamp.
    # Keep it outside the checkpoint fingerprint so saved work stays usable.
    prompt_parts.append(
        "## Delivery\n\n"
        "Lead with a short summary of the findings or deliverables, then give supporting detail. "
        "Reuse evidence already visible in this conversation. Read a saved result page only "
        "when the visible result lacks a detail needed for the task."
    )

    return "\n\n".join(prompt_parts)


def run_worker(
    agent_spec: SwarmAgentSpec,
    task: SwarmTask,
    upstream_summaries: dict[str, str],
    user_vars: dict[str, str],
    run_dir: Path,
    event_callback: Callable[[SwarmEvent], None] | None = None,
    include_shell_tools: bool = False,
    grounding_block: str = "",
    agent_config: AgentConfig | None = None,
    cancel_event: _CancellationSignal | None = None,
    resume: bool = False,
    *,
    policy: ToolPolicy,
    successful_reads: dict[tuple[str, str], str] | None = None,
) -> WorkerResult:
    """Run one worker task, releasing the per-task LLM client on exit.

    Builds a fresh :class:`ChatLLM` for the task and guarantees it is closed
    even on early returns (timeout, token limit, tool error). The underlying
    LangChain adapter owns a pooled ``httpx.Client`` that is not promptly
    refcount-collected; without this, long-running swarm deployments
    accumulate one CLOSE-WAIT socket per task (#1141).

    Args:
        agent_spec: Agent role specification with tools/skills/model config.
        task: The task to execute, including prompt template.
        upstream_summaries: Summaries from upstream tasks keyed by input_from keys.
        user_vars: User-provided variables for template rendering.
        run_dir: Path to .swarm/runs/{run_id}/ directory.
        event_callback: Optional callback for swarm events.
        successful_reads: Successful read results retained across node retries.
        include_shell_tools: Whether this worker may register shell tools.
        grounding_block: Optional pre-rendered "Ground Truth" markdown that
            anchors the worker on real recent prices for symbols mentioned in
            ``user_vars``. Forwarded verbatim to :func:`build_worker_prompt`.
        agent_config: Optional resolved agent config carrying remote MCP
            server definitions. Threaded from :class:`SwarmRuntime` and
            consumed by :func:`build_swarm_registry` to merge remote MCP
            tools with the local-tool pool before applying the agent's
            whitelist. ``None`` preserves the prior local-only behavior.
        cancel_event: Cooperative stop signal for the run or its layer.
            Passed to streaming as ``should_cancel`` and checked before tool
            dispatch. A tool call already executing is not interrupted.

    Returns:
        WorkerResult with status, summary, artifacts, and iteration count.
    """
    llm = ChatLLM(model_name=agent_spec.model_name, policy=policy)
    result = None
    try:
        result = _run_worker_impl(
            agent_spec=agent_spec,
            task=task,
            upstream_summaries=upstream_summaries,
            user_vars=user_vars,
            run_dir=run_dir,
            llm=llm,
            policy=policy,
            event_callback=event_callback,
            include_shell_tools=include_shell_tools,
            grounding_block=grounding_block,
            agent_config=agent_config,
            cancel_event=cancel_event,
            resume=resume,
            successful_reads=successful_reads,
        )
        return result
    finally:
        if result is None or result.status != "completed":
            _worker_background(run_dir, agent_spec.id, task.id).cancel_all()
        llm.close()


def _worker_background(run_dir: Path, agent_id: str, task_id: str):
    """Return the canonical background handle for a worker."""
    from src.tools.background_tools import BackgroundScope, get_background_manager

    return get_background_manager().for_scope(BackgroundScope(
        owner_id=f"swarm:{Path(run_dir).resolve()}:{agent_id}:{task_id}", attempt_id=task_id,
    ))


def _run_worker_impl(
    agent_spec: SwarmAgentSpec,
    task: SwarmTask,
    upstream_summaries: dict[str, str],
    user_vars: dict[str, str],
    run_dir: Path,
    event_callback: Callable[[SwarmEvent], None] | None = None,
    include_shell_tools: bool = False,
    grounding_block: str = "",
    agent_config: AgentConfig | None = None,
    *,
    llm: ChatLLM,
    policy: ToolPolicy,
    cancel_event: _CancellationSignal | None = None,
    resume: bool = False,
    successful_reads: dict[tuple[str, str], str] | None = None,
) -> WorkerResult:
    """Prepare a worker task, bind its kernel ports, and deliver its result.

    Args:
        agent_spec: Agent role specification with tools/skills/model config.
        task: The task to execute, including prompt template.
        upstream_summaries: Summaries from upstream tasks keyed by input_from keys.
        user_vars: User-provided variables for template rendering.
        run_dir: Path to .swarm/runs/{run_id}/ directory.
        llm: Pre-built ChatLLM; ownership stays with the caller
            (:func:`run_worker` closes it in a ``finally``).
        event_callback: Optional callback for swarm events.
        include_shell_tools: Whether this worker may register shell tools.
        grounding_block: Optional pre-rendered "Ground Truth" markdown that
            anchors the worker on real recent prices for symbols mentioned in
            ``user_vars``. Forwarded verbatim to :func:`build_worker_prompt`.
        agent_config: Optional resolved agent config carrying remote MCP
            server definitions. Threaded from :class:`SwarmRuntime` and
            consumed by :func:`build_swarm_registry` to merge remote MCP
            tools with the local-tool pool before applying the agent's
            whitelist. ``None`` preserves the prior local-only behavior.
        cancel_event: Cooperative stop signal for the run or its layer.
            Passed to streaming as ``should_cancel`` and checked before tool
            dispatch. A tool call already executing is not interrupted.

    Returns:
        WorkerResult with status, summary, artifacts, and iteration count.
    """
    agent_id = agent_spec.id
    task_id = task.id
    max_iterations = agent_spec.max_iterations or _default_max_iterations()
    timeout = agent_spec.timeout_seconds or _default_timeout_seconds()

    _emit(event_callback, "worker_started", agent_id, task_id)

    # 1. Build per-worker tool registry — local pool plus any operator-
    #    surfaced MCP tools, projected onto the agent's whitelist. The
    #    documented ``skills:`` boundary is enforced at runtime by rebuilding
    #    ``load_skill`` with the allowlist baked in; an empty ``skills`` list
    #    means unrestricted, matching the prompt-side filter semantics
    #    (``_filter_skill_descriptions`` treats empty as include-all).
    # Each worker owns its background tasks. Two workers running the same
    # preset concurrently must never read or cancel each other's commands, and
    # neither may see the tasks of the session that launched the swarm.
    background = _worker_background(run_dir, agent_id, task_id)
    background_scope = background.scope
    registry = build_swarm_registry(
        agent_spec.tools,
        policy=policy,
        agent_config=agent_config,
        include_shell_tools=include_shell_tools,
        skill_allowlist=agent_spec.skills or None,
        background_manager=background,
        background_scope=background_scope,
    )

    from src.swarm.evidence_handoff import prepare_handoff
    try:
        evidence_note = prepare_handoff(run_dir, task, agent_artifact_dir(run_dir, agent_id, task_id))
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Upstream evidence copy unavailable; retaining supplied reports", exc_info=True)
        evidence_note = "Upstream evidence files could not be copied. The supplied reports remain available; do not claim independent source verification from them."

    # 2. Build system prompt with filtered skills
    skills_loader = SkillsLoader()
    skill_desc = _filter_skill_descriptions(skills_loader, agent_spec.skills)
    system_prompt = build_worker_prompt(
        agent_spec, upstream_summaries, skill_desc, grounding_block=grounding_block,
        available_tools={name for name in agent_spec.tools if registry.get(name) is not None},
    )

    if evidence_note:
        system_prompt += "\n\n" + evidence_note

    # Token accounting accumulators — initialized before the first exit path
    # (template render failure) so every WorkerResult return below carries the
    # accumulated cache breakdown and provenance label, never silent defaults.
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
    token_source: str | None = None

    # 4. Resolve prompt template with user vars (missing vars → LLM infers)
    class _FallbackDict(dict):
        """Dict that hints LLM to infer missing template variables."""
        def __missing__(self, key: str) -> str:
            return f"(determine the appropriate {key} based on the objective)"

    template_vars = _FallbackDict(user_vars)

    try:
        user_prompt = task.prompt_template.format_map(_FallbackDict(template_vars))
    except (KeyError, ValueError) as exc:
        error_msg = f"Failed to render prompt template: {exc}"
        _emit(event_callback, "worker_failed", agent_id, task_id, {"error": error_msg})
        return WorkerResult(
            status="failed", summary="", iterations=0, error=error_msg,
            input_tokens=total_input_tokens, output_tokens=total_output_tokens,
            cache_read_tokens=total_cache_read_tokens,
            cache_creation_tokens=total_cache_creation_tokens,
            token_source=token_source,
        )

    # 5. Build initial messages
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    artifact_dir = agent_artifact_dir(run_dir, agent_id, task_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    get_tool = getattr(registry, "get", None)
    model = agent_spec.model_name or getattr(llm, "model_name", "") or ""
    worker_context = WorkerContext(
        model=model,
        artifact_dir=artifact_dir,
        can_read_files=callable(get_tool) and get_tool("read_file") is not None,
    )

    def account_response(response: LLMResponse) -> None:
        """Count each attempt, retaining cache fields and estimated provenance."""
        nonlocal total_input_tokens, total_output_tokens
        nonlocal total_cache_read_tokens, total_cache_creation_tokens, token_source
        measured = _measure_usage(messages, response)
        total_input_tokens += measured.input_tokens
        total_output_tokens += measured.output_tokens
        total_cache_read_tokens += measured.cache_read_tokens
        total_cache_creation_tokens += measured.cache_creation_tokens
        token_source = (
            "estimated"
            if token_source == "estimated" or measured.token_source == "estimated"
            else "provider"
        )

    t0 = time.monotonic()
    iteration = 0
    terminal: WorkerResult | None = None

    # Threshold for injecting a "wrap up" nudge (80% of budget)
    wrap_up_at = max(1, int(max_iterations * 0.8))
    last_assistant_content = ""
    if successful_reads is None:
        successful_reads = {}

    resume_key = checkpoint.context_key(messages)
    if resume:
        restored = checkpoint.restore(artifact_dir, key=resume_key, system=messages[0], run_dir=run_dir)
        if restored is not None:
            messages, last_assistant_content = restored
            _emit(event_callback, "worker_resumed", agent_id, task_id, {"messages": len(messages)})
        else:
            successful_reads.clear()
            _emit(event_callback, "worker_resume_unavailable", agent_id, task_id,
                  {"reason": "Saved conversation is unavailable or incompatible; restarting from supplied reports."})

    starting_message_count = len(messages)

    def save_checkpoint() -> None:
        checkpoint.save(artifact_dir, key=resume_key, messages=messages,
                        last_content=last_assistant_content, run_dir=run_dir)


    content_filter_count = 0
    consecutive_content_filter_count = 0
    stream_failure_streak = 0

    def stop_requested() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def finish(
        status: WorkerStatus, summary: str, iterations: int, *, warning_iterations: int, error: str | None = None,
    ) -> Stop:
        nonlocal terminal
        terminal = WorkerResult(
            status=status, summary=summary, error=error,
            artifact_paths=collect_artifacts(run_dir, artifact_dir),
            iterations=iterations,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cache_read_tokens=total_cache_read_tokens,
            cache_creation_tokens=total_cache_creation_tokens,
            token_source=token_source,
            content_filter_warnings=compute_content_filter_warnings(content_filter_count, warning_iterations),
        )
        return Stop(status.value)

    def finish_cancelled(iterations: int) -> Stop:
        summary = _resolve_summary(artifact_dir, last_assistant_content)
        _emit(event_callback, "worker_cancelled", agent_id, task_id, {"iterations": iterations})
        _finalize_run(artifact_dir, summary, messages)
        return finish(WorkerStatus.cancelled, summary, iterations, warning_iterations=iteration + 1)

    def on_cancel() -> None:
        finish_cancelled(iteration)

    def before_cancel_check(completed: int) -> Stop | None:
        nonlocal iteration
        iteration = completed
        save_checkpoint()
        elapsed = time.monotonic() - t0
        if elapsed > timeout:
            fallback = f"Worker timed out after {elapsed:.0f}s ({iteration} iterations)"
            summary = _resolve_summary(artifact_dir, _best_summary(messages, last_assistant_content) or fallback)
            _emit(event_callback, "worker_timeout", agent_id, task_id, {"elapsed": elapsed})
            _finalize_run(artifact_dir, summary, messages)
            return finish(WorkerStatus.timeout, summary, iteration, warning_iterations=iteration + 1)
        return None

    def prepare_request(view: LoopContext, step: Iteration) -> Stop | None:
        # Inject wrap-up nudge when approaching iteration limit
        if iteration == wrap_up_at:
            remaining = max_iterations - iteration
            wrap_up_content = (
                f"[SYSTEM] You have {remaining} iterations remaining. "
                "Finish the most useful remaining work and deliver your conclusions, "
                "available results and any unresolved limitations in your final response. "
                "Create a file only if the user requested one or it improves the deliverable."
            )
            messages.append({
                "role": "user",
                "content": wrap_up_content,
            })

        # On last iteration, call LLM without tool definitions to force text output
        view.tools = None if step.text_only else registry.get_definitions()
        tool_defs = view.tools
        compacted = worker_context.compact(messages, tool_defs)
        if compacted:
            _emit(event_callback, "worker_context_offloaded", agent_id, task_id,
                  {"iteration": iteration, "results": compacted})
        token_estimate = worker_context.tokens(messages, tool_defs)
        token_limit = (worker_context.budget(messages, tool_defs).total
                       if _MAX_TOKEN_ESTIMATE is None else _MAX_TOKEN_ESTIMATE)
        if token_estimate > token_limit:
            summary = last_assistant_content or f"Worker context too large (~{token_estimate} tokens, {iteration} iterations)"
            summary = _resolve_summary(artifact_dir, summary)
            _emit(event_callback, "worker_token_limit", agent_id, task_id, {"tokens": token_estimate})
            _finalize_run(artifact_dir, summary, messages)
            return finish(WorkerStatus.token_limit, summary, iteration, warning_iterations=iteration + 1)

        return finish_cancelled(iteration) if stop_requested() else None

    def request(view: LoopContext, emit: EventSink) -> LLMResponse | Continue | Stop:
        nonlocal stream_failure_streak, last_assistant_content
        nonlocal content_filter_count, consecutive_content_filter_count
        # Stream the LLM — moonshot/kimi non-streaming invoke is unreliable
        # (issue #42), and streaming also feeds dashboard live progress.
        streamed_text: list[str] = []
        try:
            def _on_text_chunk(delta: str) -> None:
                streamed_text.append(delta)
                emit("worker_text", {"content": delta, "iteration": iteration})

            # LLM streaming can stall for 30s+ between request start and the
            # first text chunk (slow first-token providers, reasoning models'
            # think phase, pure-tool-call responses with no text). Without a
            # ticker, the stale-run reaper would mark a healthy run failed
            # the moment its silence exceeds the heartbeat-based threshold.
            # Wrap the call in the same HeartbeatTimer used for tool execution
            # so events.jsonl gets a fresh entry every few seconds no matter
            # what the provider is doing.
            def _on_llm_heartbeat(payload: dict) -> None:
                _emit(
                    event_callback,
                    "task_heartbeat",
                    agent_id,
                    task_id,
                    {**payload, "iteration": iteration, "phase": "llm"},
                )

            def _stream_once() -> LLMResponse:
                """Run one heartbeat-wrapped streaming LLM call.

                Recomputes the remaining time budget at call time so the
                single retry after a stream failure never reuses a stale
                timeout.

                Returns:
                    Parsed ``LLMResponse`` from ``ChatLLM.stream_chat``.

                Raises:
                    ProviderStreamError: When provider streaming fails.
                """
                remaining_timeout = max(10, int(timeout - (time.monotonic() - t0)))
                stream_kwargs: dict[str, Any] = {}
                if cancel_event is not None:
                    stream_kwargs["should_cancel"] = cancel_event.is_set
                with HeartbeatTimer(
                    tool_name=f"llm:{agent_spec.model_name or 'default'}",
                    interval=_HEARTBEAT_INTERVAL_S,
                    emit=_on_llm_heartbeat,
                ):
                    try:
                        return llm.stream_chat(
                            repair_provider_messages(view.messages),
                            tools=view.tools,
                            timeout=remaining_timeout,
                            on_text_chunk=_on_text_chunk,
                            **stream_kwargs,
                        )
                    except ProviderStreamError as error:
                        usage = getattr(error, "usage_metadata", None)
                        account_response(LLMResponse(usage_metadata=usage))
                        _emit(event_callback, "worker_stream_usage", agent_id, task_id,
                              {"iteration": iteration, "usage": usage,
                               "status": "failed_stream"})
                        raise


            # A transient mid-stream hiccup (connection reset) used to be
            # absorbed by ChatLLM's silent non-streaming fallback; it now
            # surfaces as ProviderStreamError, so retry the stream exactly
            # once before taking the existing failure path. Deterministic
            # 4xx errors skip the retry and fail immediately. The delay
            # escalates across consecutive retryable failures, honoring the
            # provider's Retry-After header (bounded by the configured cap)
            # when present. A successful retry does not reset the streak —
            # only a clean first-attempt success does.
            try:
                response = _stream_once()
            except ProviderStreamError as stream_exc:
                if not stream_exc.retryable:
                    raise
                stream_failure_streak += 1
                retry_delay_s = (
                    min(stream_exc.retry_after_s, _STREAM_RETRY_MAX_DELAY_S)
                    if stream_exc.retry_after_s is not None
                    else _escalated_stream_retry_delay_s(stream_failure_streak)
                )
                logger.warning(
                    "Provider stream failed for agent=%s task=%s iteration=%d "
                    "(provider=%s model=%s); retrying once in %.2fs: %s",
                    agent_id,
                    task_id,
                    iteration,
                    stream_exc.provider,
                    stream_exc.model,
                    retry_delay_s,
                    stream_exc,
                )
                # Wait on the cancel event, not time.sleep: the delay now
                # escalates to the configured cap (30s by default) and a
                # provider Retry-After can ask for that much on the first
                # failure. A blocking sleep would hold a cancelled worker
                # for the whole delay before the check below sees the flag.
                if cancel_event is not None:
                    cancel_event.wait(retry_delay_s)
                else:
                    time.sleep(retry_delay_s)
                if cancel_event is None or not cancel_event.is_set():
                    response = _stream_once()
            else:
                stream_failure_streak = 0

            # Preserve streamed prose on cancellation, but never execute
            # unfinished tool calls from an interrupted provider response.
            if stop_requested():
                last_assistant_content = "".join(streamed_text) or last_assistant_content
                save_checkpoint()
                return finish_cancelled(iteration)
        except Exception as exc:
            last_assistant_content = "".join(streamed_text) or last_assistant_content
            error_msg = f"LLM call failed at iteration {iteration}: {exc}"
            logger.warning(error_msg)
            _emit(event_callback, "worker_failed", agent_id, task_id, {"error": error_msg})
            summary = _resolve_summary(artifact_dir, last_assistant_content or "")
            save_checkpoint()
            _finalize_run(artifact_dir, summary, messages)
            return finish(WorkerStatus.failed, summary, iteration, warning_iterations=iteration + 1, error=error_msg)

        # Accumulate token counts (provider-reported when available, with the
        # cache breakdown). The provenance label is sticky-estimated, mirroring
        # runtime._merge_token_source: one heuristic iteration contaminates the
        # cumulative total, so a partly-estimated sum never reads as billed.
        worker_context.observe(view.messages, view.tools, getattr(response, "usage_metadata", None))
        account_response(response)

        # Track last meaningful assistant content
        if response.content:
            last_assistant_content = response.content
            save_checkpoint()

        # Content-filter skip: provider blocked the response — continue to
        # the next iteration instead of finalising on empty/garbage content.
        if response.content_filter_triggered:
            content_filter_count += 1
            consecutive_content_filter_count += 1
            if consecutive_content_filter_count >= MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS:
                _emit(
                    event_callback,
                    "content_filter_circuit_breaker",
                    agent_id,
                    task_id,
                    {"count": content_filter_count},
                )
                summary = _resolve_summary(artifact_dir, last_assistant_content or "")
                _finalize_run(artifact_dir, summary, messages)
                error = (
                    f"content_filter_circuit_breaker: {MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS} consecutive "
                    "LLM responses were blocked by content moderation"
                )
                return finish(WorkerStatus.failed, summary, iteration + 1, warning_iterations=iteration + 1, error=error)
            _emit(
                event_callback,
                "content_filter_skipped",
                agent_id,
                task_id,
                {"iteration": iteration, "content_filter_count": content_filter_count},
            )
            messages.append({
                "role": "user",
                "content": f"<system>{CONTENT_FILTER_SKIP_MESSAGE}</system>",
            })
            return Continue.NEXT

        consecutive_content_filter_count = 0
        return response

    def record_partial(response: LLMResponse, reason: str) -> None:
        summary = response.content or ""
        messages.append({"role": "assistant", "content": summary})
        _finalize_run(artifact_dir, summary, messages)
        error = "Model output was truncated; increase the provider output-token limit and retry."
        _emit(event_callback, "worker_token_limit", agent_id, task_id, {"reason": reason, "error": error})
        finish(WorkerStatus.token_limit, summary, iteration + 1, warning_iterations=iteration + 1, error=error)

    def after_text(response: LLMResponse) -> Stop:
        summary = response.content or ""
        # The final response supersedes any previous draft. Files remain separate artifacts.
        messages.append({"role": "assistant", "content": summary})
        if not summary:
            summary = _resolve_summary(artifact_dir, summary)
        _finalize_run(artifact_dir, summary, messages)
        reason = _delivery_error(response.content or "") if resume and not response.content else _delivery_error(summary)
        if reason:
            _emit(event_callback, "worker_incomplete", agent_id, task_id,
                  {"iterations": iteration + 1, "reason": reason})
            return finish(WorkerStatus.incomplete, summary, iteration + 1, warning_iterations=iteration + 1, error=reason)
        _emit(event_callback, "worker_completed", agent_id, task_id, {"iterations": iteration + 1})
        return finish(WorkerStatus.completed, summary, iteration + 1, warning_iterations=iteration + 1)

    def run_tools(response: LLMResponse) -> Continue | Stop:
        # Append assistant message with tool calls
        messages.append(
            ContextBuilder.format_assistant_tool_calls(
                response.tool_calls,
                content=response.content,
                reasoning_content=response.reasoning_content,
            )
        )

        # Execute each tool call — inject run_dir so tools write inside artifact_dir
        save_checkpoint()
        for tc in response.tool_calls:
            if stop_requested():
                break
            mcp_meta = _remote_tool_metadata(registry, tc.name)
            _emit(
                event_callback, "item.started", agent_id, task_id,
                {"kind": "tool.started", "live_id": f"tool:{tc.id}", "iteration": iteration,
                 "item": {"type": "tool_result", "name": tc.name, "tool_call_id": tc.id,
                          "arguments": _preview_tool_arguments(tc.arguments), **mcp_meta}},
            )
            tc_start = time.monotonic()
            read_key = None
            tool = registry.get(tc.name)
            args, run_dir_refusal = _tool_arguments(tool, tc.arguments, artifact_dir)

            # Wrap tool execution in a heartbeat so the events.jsonl tail has a
            # fresh timestamp every few seconds. The stale-run reaper relies on
            # this signal to tell a hung tool call apart from a dead host; the
            # CLI dashboard / SSE clients also get live "still working" ticks.
            def _on_heartbeat(payload: dict) -> None:
                _emit(
                    event_callback,
                    "task_heartbeat",
                    agent_id,
                    task_id,
                    {**payload, "iteration": iteration, "phase": "tool"},
                )

            with HeartbeatTimer(
                tool_name=tc.name,
                interval=_HEARTBEAT_INTERVAL_S,
                emit=_on_heartbeat,
            ):
                if stop_requested():
                    break
                if run_dir_refusal is not None:
                    result = json.dumps(
                        {"status": "error", "error": run_dir_refusal},
                        ensure_ascii=False,
                    )
                elif tool is None:
                    # The registry retains its existing unavailable-tool diagnostic.
                    result = registry.execute(tc.name, args)
                else:
                    prepared = prepare_tool_call(
                        tc.name, args, check_policy=registry.check_policy,
                        hooks=getattr(registry, "hooks", None), call_id=tc.id, session_id="",
                    )
                    if isinstance(prepared, ToolRefusal):
                        result = prepared.result
                    elif stop_requested():
                        break
                    else:
                        if getattr(tool, "is_readonly", False) is True:
                            read_key = (tc.name, json.dumps(prepared.arguments, sort_keys=True))
                        if read_key in successful_reads:
                            result = _repeat_read_result(successful_reads[read_key])
                            read_key = None
                        else:
                            result = registry.execute(tc.name, prepared.arguments)
                            if prepared.post_result is not None:
                                prepared.post_result(result, "ok")
            # Redact before storing or previewing any tool payload.
            result = redact_tool_result(result)
            result_is_error = _is_error_result(result)
            if read_key is not None and not result_is_error:
                successful_reads[read_key] = result
            tc_elapsed = time.monotonic() - tc_start
            _emit(
                event_callback,
                "item.completed",
                agent_id,
                task_id,
                {
                    "kind": "tool.failed" if result_is_error else "tool.completed",
                    "live_id": f"tool:{tc.id}",
                    "item": {"type": "tool_result", "name": tc.name,
                    "tool_call_id": tc.id,
                    "elapsed_ms": int(tc_elapsed * 1000),
                    "status": "error" if result_is_error else "ok",
                    "iteration": iteration,
                    "content": _preview_tool_result(result),
                    **mcp_meta},
                },
            )
            messages.append(
                ContextBuilder.format_tool_result(
                    tc.id, tc.name, deliver_tool_result(result, artifact_dir, registry)
                )
            )
            worker_context.pending.add(tc.id)
            save_checkpoint()

        if stop_requested():
            return finish_cancelled(iteration + 1)

        return Continue.NEXT

    snapshot = getattr(llm, "runtime_snapshot", None)
    if not isinstance(snapshot, LLMRuntimeSnapshot):
        snapshot = LLMRuntimeSnapshot("", model, "")
    context = LoopContext(messages, snapshot, None)
    ports = LoopPorts(
        before_iteration=lambda view: None,
        prepare_request=prepare_request,
        request=request,
        record_partial=record_partial,
        after_text=after_text,
        run_tools=run_tools,
        poll_inputs=lambda: None,
        on_cancel=on_cancel,
        read_delta=lambda: messages[starting_message_count:],
        read_usage=lambda: {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cache_read_tokens": total_cache_read_tokens,
            "cache_creation_tokens": total_cache_creation_tokens,
        },
        before_cancel_check=before_cancel_check,
    )
    turn = run_loop(
        context, ports, RunLimits(max_iterations, frozenset({"length", "max_tokens", "max_output_tokens"})),
        cancel_event if cancel_event is not None else Event(),
        lambda kind, data: _emit(event_callback, kind, agent_id, task_id, data),
    )
    if turn.reason == "max_iterations":
        fallback = f"Worker hit iteration limit ({max_iterations} iterations)"
        summary = _resolve_summary(artifact_dir, _best_summary(messages, last_assistant_content) or fallback)
        _finalize_run(artifact_dir, summary, messages)
        _emit(event_callback, "worker_iteration_limit", agent_id, task_id)
        finish(
            WorkerStatus.incomplete, summary, max_iterations, warning_iterations=iteration + 1,
            error="iteration limit reached before a final response",
        )
    assert terminal is not None
    return terminal


def _best_summary(messages: list[dict], fallback: str) -> str:
    """Extract the best summary from all assistant messages."""
    texts = [
        m["content"] for m in messages
        if m.get("role") == "assistant" and m.get("content")
        and len(m["content"].strip()) > 100
    ]
    if texts:
        return max(texts, key=len)
    return fallback


def _remote_tool_metadata(registry: ToolRegistry, tool_name: str) -> dict[str, str]:
    """Return MCP routing metadata for ``tool_name`` if it's a remote MCP tool.

    Auditors of ``events.jsonl`` need to tell at a glance which remote MCP
    server a swarm worker reached and what the *original* (non-prefixed)
    tool name was. The local-side name is already in ``data["tool"]``; this
    helper supplies the missing ``server`` + ``remote_tool`` pair when the
    registered tool is an :class:`MCPRemoteTool`. Local-only tools yield
    an empty dict so the event payload is unchanged for them.
    """
    tool = registry.get(tool_name)
    if not isinstance(tool, MCPRemoteTool):
        return {}
    spec = getattr(tool, "_spec", None)
    if spec is None:
        return {}
    return {"server": spec.server_name, "remote_tool": spec.remote_name}


def _tool_arguments(
    tool: BaseTool | None, arguments: dict[str, Any], artifact_dir: Path
) -> tuple[dict[str, Any], str | None]:
    """Confine a worker tool call's ``run_dir`` to the agent's own workspace.

    Returns the arguments to execute with, plus a refusal reason when the
    model's ``run_dir`` is not usable.

    A tool that does not declare ``run_dir`` is workspace-scoped: the worker
    supplies one so it reads and writes inside ``artifact_dir`` **and only
    there** — that value is the confinement root the file tools resolve
    against, so it is not the model's to choose.

    A tool that *does* declare ``run_dir`` is being pointed at a directory by
    the model, so that value is honoured within the same boundary: a relative
    value resolves under the workspace (the filesystem the model's own file
    tools showed it), an absolute value inside the workspace is taken as-is,
    and anything resolving outside is refused. Refusing is deliberate — the
    alternative, silently swapping in the workspace, is what made a real run
    pass ten paths that were all discarded while the error named no directory.
    """
    args = dict(arguments)
    declared = (getattr(tool, "parameters", None) or {}).get("properties") or {}
    workspace = artifact_dir.resolve()

    if "run_dir" not in declared:
        args["run_dir"] = str(artifact_dir)
        return args, None

    value = str(args.get("run_dir") or "").strip()
    if not value:
        args["run_dir"] = str(artifact_dir)
        return args, None

    supplied = Path(value)
    resolved = (
        supplied.resolve()
        if supplied.is_absolute()
        else (workspace / supplied).resolve()
    )
    if not resolved.is_relative_to(workspace):
        return args, (
            f"run_dir {value!r} is outside this agent's workspace. A run_dir "
            f"must be inside {workspace} — pass a relative path such as "
            '"runs/<name>" to point at a directory you created there.'
        )
    args["run_dir"] = str(resolved)
    return args, None


def _preview_tool_arguments(arguments: dict) -> dict[str, str]:
    """Return a short, redacted argument preview for streamed events."""
    preview: dict[str, str] = {}
    for key, value in redact_payload(arguments).items():
        if key == "run_dir":
            continue
        preview[key] = _truncate_preview(value)
    return preview


def _preview_tool_result(result: str) -> str:
    """Return a short, redacted result preview for streamed events.

    Delegates to the shared :func:`redact_tool_result` choke point so a
    plain-text result is pattern-scrubbed instead of streamed raw (a JSON
    result was already scrubbed by key).
    """
    return _truncate_preview(redact_tool_result(result))


def _truncate_preview(value: Any, *, limit: int = 200) -> str:
    """Stringify and truncate an event preview payload."""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


_UNPARSED_TOOL_MARKERS = (
    "<\uff5ctool\u2581calls\u2581begin\uff5c>",
    "<tool_calls_begin>",
    "<tool_call_begin>",
    "<tool_sep>",
    "tool\u2581sep",
)
def _repeat_read_result(result: str) -> str:
    """Identify reused evidence while retaining its original payload."""
    try:
        payload = json.loads(result)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        payload["_vibe_repeat"] = True
        return json.dumps(payload, ensure_ascii=False)
    return f"{result}\n\n[Repeat: prior successful read]"


def _is_error_result(result: str) -> bool:
    """Did a tool call return a top-level error envelope?

    Parses the result as JSON and checks for a top-level ``status == "error"``.
    Also treats ``ok`` / ``success`` explicitly set to ``False`` as an error,
    since some tools (e.g. ``get_stock_news``) report failure only through
    those fields, with no ``status`` key at all.
    A nested ``status`` (e.g. inside ``data``) is intentionally ignored — only
    the envelope matters for the deliverable contract.

    Falls back to a fast substring check on the head for truncated or
    non-JSON payloads, so the function is robust to streaming / partial
    output without ever raising.
    """
    text = (result or "").strip()
    if not text or not text.startswith("{"):
        return False
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        # Truncated / non-JSON payload — keep the original heuristic so we
        # never raise from a classifier on the worker hot path.
        head = text[:160].lower()
        return '"status": "error"' in head or '"status":"error"' in head
    if not isinstance(parsed, dict):
        return False
    if parsed.get("status") == "error":
        return True
    return parsed.get("ok") is False or parsed.get("success") is False


def _delivery_error(summary: str) -> str | None:
    """Detect missing output or unparsed provider protocol, not report quality."""
    text = (summary or "").strip()
    if not text:
        return "empty response"
    if any(marker in text.lower() for marker in _UNPARSED_TOOL_MARKERS):
        return "unparsed tool-call markup (provider did not parse tool calls)"
    return None


def _resolve_summary(artifact_dir: Path, fallback: str) -> str:
    """Return report.md content if it exists, otherwise fall back to text."""
    report_path = artifact_dir / "report.md"
    try:
        if report_path.is_file():
            content = report_path.read_text(encoding="utf-8").strip()
            if content:
                return content
    except Exception:
        logger.warning("Failed to read report.md from %s", artifact_dir, exc_info=True)
    return fallback


def _finalize_run(artifact_dir: Path, summary: str, messages: list[dict]) -> None:
    """Persist a worker's terminal summary and message log together.

    Both files are written through one call, so a terminal path that reports a
    summary cannot omit the message log: ``messages.json`` is the only record
    of the arguments a model asked a tool for, which is what a post-mortem of a
    bad tool call needs. Provider failures retain the same evidence.

    Args:
        artifact_dir: Path to artifacts/{agent_id}/{task_id}/ directory.
        summary: Final summary text for this worker run.
        messages: Message history, including tool call arguments.
    """
    _write_summary(artifact_dir, summary)
    _persist_messages(artifact_dir, messages)


def _persist_messages(artifact_dir: Path, messages: list[dict]) -> None:
    """Persist messages to disk for post-mortem analysis."""
    try:
        path = artifact_dir / "messages.json"
        path.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("Failed to persist messages to %s", artifact_dir, exc_info=True)


def _write_summary(artifact_dir: Path, summary: str) -> None:
    """Write worker summary to artifacts directory.

    Args:
        artifact_dir: Path to artifacts/{agent_id}/{task_id}/ directory.
        summary: Summary text to write.
    """
    try:
        summary_path = artifact_dir / "summary.md"
        summary_path.write_text(summary, encoding="utf-8")
    except Exception:
        logger.warning("Failed to write summary to %s", artifact_dir, exc_info=True)
