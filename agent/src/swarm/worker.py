"""Swarm Worker: standalone worker execution engine with a lightweight ReAct loop.

Uses ChatLLM.chat + manual for-loop directly (without instantiating AgentLoop),
keeping the worker self-contained and the agent core unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.agent.context import ContextBuilder
from src.agent.skills import SkillsLoader
from src.providers.chat import ChatLLM
from src.swarm.models import (
    SwarmAgentSpec,
    SwarmEvent,
    SwarmTask,
    WorkerResult,
)
from src.tools import build_filtered_registry

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = int(os.getenv("SWARM_WORKER_MAX_ITER", "50"))
_DEFAULT_TIMEOUT_SECONDS = int(os.getenv("SWARM_WORKER_TIMEOUT", "300"))
_MAX_TOKEN_ESTIMATE = 60_000
_SENSITIVE_TOOL_ARGUMENT_KEYS = {
    "api_key",
    "authorization",
    "content",
    "env",
    "headers",
    "passphrase",
    "password",
    "secret",
    "token",
}


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


def _estimate_tokens(
    messages: list[dict],
    response: object,
) -> tuple[int, int]:
    """Return token usage for a single LLM call, real if available.

    Prefers the provider-reported counts attached to the response by
    :func:`ChatLLM._parse_response` (``usage_metadata``). Falls back to a
    character-length heuristic (``len // 4``) only when the provider
    didn't return usage data — keeps the behaviour contract for legacy
    or partial responses while making per-run totals (which feed
    ``SwarmRun.total_input_tokens`` / ``total_output_tokens``) reflect
    real billing instead of a CJK-hostile char-count guess.

    Args:
        messages: Messages sent to the LLM for this call. Used only for
            the fallback estimate when ``response.usage_metadata`` is
            missing.
        response: ``LLMResponse`` from ``ChatLLM.chat`` /
            ``ChatLLM.stream_chat``.

    Returns:
        Tuple of (input_tokens, output_tokens). Either component may be
        zero — that simply means the provider didn't report it and the
        fallback couldn't compute it either (e.g. binary content).
    """
    from src.providers.chat import LLMResponse

    if isinstance(response, LLMResponse) and response.usage_metadata:
        usage = response.usage_metadata
        real_input = int(usage.get("input_tokens") or 0)
        real_output = int(usage.get("output_tokens") or 0)
        if real_input or real_output:
            return real_input, real_output

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

    return input_tokens, output_tokens


def build_worker_prompt(
    agent_spec: SwarmAgentSpec,
    upstream_summaries: dict[str, str],
    skill_descriptions: str,
    grounding_block: str = "",
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

    Returns:
        Complete system prompt string for the worker LLM.
    """
    upstream_block = ""
    if upstream_summaries:
        sections = []
        for key, summary in upstream_summaries.items():
            sections.append(f"### {key}\n{summary}")
        upstream_block = (
            "## Upstream Context (from previous agents)\n\n"
            + "\n\n".join(sections)
        )

    prompt_parts = [
        f"## Role\n\n{agent_spec.role}",
        agent_spec.system_prompt.replace("{upstream_context}", upstream_block),
    ]

    if skill_descriptions and skill_descriptions != "(no matching skills)":
        prompt_parts.append(
            f"## Available Skills (use load_skill to access full documentation)\n\n{skill_descriptions}"
        )

    if grounding_block:
        # Placed before Execution Rules so it's in scope when the worker
        # plans its first tool call. The block already contains an explicit
        # instruction to prefer these prices over training data.
        prompt_parts.append(grounding_block)

    # Universal anti-fabrication rule. The grounding_block carries a similar
    # instruction but only renders when user_vars supplies explicit symbols.
    # Free-form prompts ("look at A-share short-term sentiment") otherwise
    # leave the worker with no guardrail and it cheerfully cites training-data
    # prices and sector weights. This block applies the rule unconditionally
    # — including to aggregator / synthesis agents that have no data tools
    # and previously had no instruction against inventing numbers.
    prompt_parts.append(
        "## Data Citation Discipline (HARD RULE)\n\n"
        "Every specific number you cite in your output — prices, percentages, "
        "volumes, fund flows, market-cap rankings, sector weights, ETF codes, "
        "ticker recommendations — MUST be traceable to one of:\n"
        "  (a) a tool call result obtained in THIS run,\n"
        "  (b) the Ground Truth block above (if present),\n"
        "  (c) the Upstream Context above (if present and the upstream agent "
        "itself sourced it from (a) or (b)).\n\n"
        "You may NOT cite numbers from memory or training data. Markets have "
        "moved since your cutoff; any specific price/percentage you recall is "
        "wrong by default.\n\n"
        "If you cannot back a number with (a), (b), or (c), you have two "
        "choices:\n"
        "  - call a data tool to fetch it (preferred), or\n"
        "  - omit the number and qualify the statement (e.g. \"directional "
        "only — not verified against live data\").\n\n"
        "This rule applies equally to synthesis / aggregator / editor roles "
        "that lack data tools. If upstream did not provide a specific number, "
        "do NOT introduce one from training data — say the upstream omitted "
        "it and proceed without."
    )

    prompt_parts.append(
        "## Execution Rules\n\n"
        "You have a HARD LIMIT of 20 tool calls. After that you will be cut off. Work efficiently.\n\n"
        "**Phase 1 — Plan (0 tool calls):** Before calling any tool, state your plan in 3-5 bullet points.\n\n"
        "**Phase 2 — Execute (≤15 tool calls):**\n"
        "- `load_skill` first to get data access methods and analysis patterns.\n"
        "- Write ONE focused Python script via `write_file`, then run it with `bash python script.py`.\n"
        "- Do NOT write long Python code inside bash. Use write_file + bash.\n"
        "- Do NOT fetch data with curl/requests. Use the patterns from load_skill (yfinance, OKX API via Python).\n"
        "- If a script fails, read the error, fix with `edit_file`, re-run. Max 2 retries per script.\n\n"
        "**Phase 3 — Summarize (MUST use write_file):**\n"
        "- You MUST call `write_file` with path `report.md` to save your final report as a markdown file.\n"
        "- This is REQUIRED, not optional. Your final response MUST include a write_file call for report.md.\n"
        "- The report must include specific numbers, dates, and actionable conclusions.\n"
        "- After writing report.md, output a brief 2-3 sentence summary in your text response.\n"
        "- Respond in the same language as the task prompt."
    )

    now = datetime.now()
    prompt_parts.append(
        f"## Current Date & Time\n\n"
        f"Today is {now.strftime('%A, %B %d, %Y %H:%M (local)')}."
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
) -> WorkerResult:
    """Execute a single worker task using a lightweight ReAct loop.

    Steps:
      1. Build filtered ToolRegistry from agent_spec.tools
      2. Create ChatLLM with agent_spec.model_name
      3. Build system prompt with role + upstream summaries + filtered skills
      4. Resolve task.prompt_template with user_vars
      5. Run ReAct loop (for iteration in range(max_iterations))
      6. Write summary to artifacts/{agent_id}/summary.md
      7. Return WorkerResult

    Args:
        agent_spec: Agent role specification with tools/skills/model config.
        task: The task to execute, including prompt template.
        upstream_summaries: Summaries from upstream tasks keyed by input_from keys.
        user_vars: User-provided variables for template rendering.
        run_dir: Path to .swarm/runs/{run_id}/ directory.
        event_callback: Optional callback for swarm events.
        include_shell_tools: Whether this worker may register shell tools.
        grounding_block: Optional pre-rendered "Ground Truth" markdown that
            anchors the worker on real recent prices for symbols mentioned in
            ``user_vars``. Forwarded verbatim to :func:`build_worker_prompt`.

    Returns:
        WorkerResult with status, summary, artifacts, and iteration count.
    """
    agent_id = agent_spec.id
    task_id = task.id
    max_iterations = agent_spec.max_iterations or _DEFAULT_MAX_ITERATIONS
    timeout = agent_spec.timeout_seconds or _DEFAULT_TIMEOUT_SECONDS

    _emit(event_callback, "worker_started", agent_id, task_id)

    # 1. Build filtered tool registry
    # TODO(v1): Swarm stays local-tool-only. Do not thread MCP config into this
    # path until swarm-specific config propagation and execution constraints are
    # designed explicitly.
    registry = build_filtered_registry(agent_spec.tools, include_shell_tools=include_shell_tools)

    # 2. Create LLM
    llm = ChatLLM(model_name=agent_spec.model_name)

    # 3. Build system prompt with filtered skills
    skills_loader = SkillsLoader()
    skill_desc = _filter_skill_descriptions(skills_loader, agent_spec.skills)
    system_prompt = build_worker_prompt(
        agent_spec, upstream_summaries, skill_desc, grounding_block=grounding_block,
    )

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
            input_tokens=0, output_tokens=0,
        )

    # 5. Build initial messages
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 6. ReAct loop
    artifact_dir = run_dir / "artifacts" / agent_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    iteration = 0
    summary = ""
    total_input_tokens = 0
    total_output_tokens = 0

    # Threshold for injecting a "wrap up" nudge (80% of budget)
    wrap_up_at = max(1, int(max_iterations * 0.8))
    last_assistant_content = ""

    _KEEP_RECENT_TOOLS = 3

    for iteration in range(max_iterations):
        # Microcompact: clear old tool results to prevent token bloat
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if len(tool_msgs) > _KEEP_RECENT_TOOLS:
            for msg in tool_msgs[:-_KEEP_RECENT_TOOLS]:
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 100:
                    msg["content"] = "[cleared]"

        # Check timeout
        elapsed = time.monotonic() - t0
        if elapsed > timeout:
            summary = _best_summary(messages, last_assistant_content) or f"Worker timed out after {elapsed:.0f}s ({iteration} iterations)"
            summary = _resolve_summary(artifact_dir, summary)
            _emit(event_callback, "worker_timeout", agent_id, task_id, {"elapsed": elapsed})
            _write_summary(artifact_dir, summary)
            _persist_messages(artifact_dir, messages)
            return WorkerResult(
                status="timeout",
                summary=summary,
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

        # Check token estimate
        token_estimate = len(json.dumps(messages, ensure_ascii=False)) // 4
        if token_estimate > _MAX_TOKEN_ESTIMATE:
            summary = last_assistant_content or f"Worker context too large (~{token_estimate} tokens, {iteration} iterations)"
            summary = _resolve_summary(artifact_dir, summary)
            _emit(event_callback, "worker_token_limit", agent_id, task_id, {"tokens": token_estimate})
            _write_summary(artifact_dir, summary)
            return WorkerResult(
                status="token_limit",
                summary=summary,
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

        # Inject wrap-up nudge when approaching iteration limit
        if iteration == wrap_up_at:
            remaining = max_iterations - iteration
            messages.append({
                "role": "user",
                "content": (
                    f"[SYSTEM] You have {remaining} iterations remaining. "
                    "If report.md is not written yet, make one final write_file call for report.md. "
                    "Otherwise stop calling tools and output your final analysis summary as plain text."
                ),
            })

        # On last iteration, call LLM without tool definitions to force text output
        is_last_iteration = iteration == max_iterations - 1
        tool_defs = None if is_last_iteration else registry.get_definitions()

        # Stream the LLM — moonshot/kimi non-streaming invoke is unreliable
        # (issue #42), and streaming also feeds dashboard live progress.
        try:
            remaining_timeout = max(10, int(timeout - elapsed))

            def _on_text_chunk(delta: str) -> None:
                _emit(event_callback, "worker_text", agent_id, task_id,
                      {"content": delta, "iteration": iteration})

            response = llm.stream_chat(
                messages,
                tools=tool_defs,
                timeout=remaining_timeout,
                on_text_chunk=_on_text_chunk,
            )
        except Exception as exc:
            error_msg = f"LLM call failed at iteration {iteration}: {exc}"
            logger.warning(error_msg)
            _emit(event_callback, "worker_failed", agent_id, task_id, {"error": error_msg})
            return WorkerResult(
                status="failed",
                summary=_resolve_summary(artifact_dir, last_assistant_content or ""),
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration,
                error=error_msg,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

        # Accumulate token counts
        iter_in, iter_out = _estimate_tokens(messages, response)
        total_input_tokens += iter_in
        total_output_tokens += iter_out

        # Track last meaningful assistant content
        if response.content and len(response.content.strip()) > 20:
            last_assistant_content = response.content

        # If no tool calls, this is the final response
        if not response.has_tool_calls:
            summary = response.content or last_assistant_content or "(no summary)"
            summary = _resolve_summary(artifact_dir, summary)
            _emit(event_callback, "worker_completed", agent_id, task_id, {"iterations": iteration + 1})
            _write_summary(artifact_dir, summary)
            return WorkerResult(
                status="completed",
                summary=summary,
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration + 1,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

        # Append assistant message with tool calls
        messages.append(
            ContextBuilder.format_assistant_tool_calls(
                response.tool_calls,
                content=response.content,
                reasoning_content=response.reasoning_content,
            )
        )

        # Execute each tool call — inject run_dir so tools write inside artifact_dir
        for tc in response.tool_calls:
            _emit(
                event_callback, "tool_call", agent_id, task_id,
                {"tool": tc.name, "iteration": iteration,
                 "arguments": _preview_tool_arguments(tc.arguments)},
            )
            tc_start = time.monotonic()
            args = {**tc.arguments, "run_dir": str(artifact_dir)}
            result = registry.execute(tc.name, args)
            tc_elapsed = time.monotonic() - tc_start
            _emit(
                event_callback, "tool_result", agent_id, task_id,
                {"tool": tc.name, "elapsed_ms": int(tc_elapsed * 1000),
                 "status": "ok", "iteration": iteration,
                 "result_preview": str(result)[:200]},
            )
            messages.append(
                ContextBuilder.format_tool_result(tc.id, tc.name, result[:10_000])
            )

    # Hit iteration limit — use last meaningful content as summary
    summary = _best_summary(messages, last_assistant_content) or f"Worker hit iteration limit ({max_iterations} iterations)"
    summary = _resolve_summary(artifact_dir, summary)
    _emit(event_callback, "worker_iteration_limit", agent_id, task_id)
    _write_summary(artifact_dir, summary)
    _persist_messages(artifact_dir, messages)
    return WorkerResult(
        status="completed",
        summary=summary,
        artifact_paths=_collect_artifacts(artifact_dir),
        iterations=max_iterations,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )


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


def _preview_tool_arguments(arguments: dict) -> dict[str, str]:
    """Return a short, redacted argument preview for streamed events."""
    preview: dict[str, str] = {}
    for key, value in arguments.items():
        if key == "run_dir":
            continue
        if _is_sensitive_tool_argument(key):
            preview[key] = "[redacted]"
            continue
        text = str(value)
        preview[key] = text if len(text) <= 200 else text[:200] + "..."
    return preview


def _is_sensitive_tool_argument(key: str) -> bool:
    """Return whether a tool argument name should be redacted in events."""
    normalized = key.strip().lower()
    return normalized in _SENSITIVE_TOOL_ARGUMENT_KEYS or any(
        marker in normalized
        for marker in ("api_key", "authorization", "password", "secret", "token")
    )


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
        artifact_dir: Path to artifacts/{agent_id}/ directory.
        summary: Summary text to write.
    """
    try:
        summary_path = artifact_dir / "summary.md"
        summary_path.write_text(summary, encoding="utf-8")
    except Exception:
        logger.warning("Failed to write summary to %s", artifact_dir, exc_info=True)


def _collect_artifacts(artifact_dir: Path) -> list[str]:
    """Collect all artifact file paths from agent's artifact directory.

    Args:
        artifact_dir: Path to artifacts/{agent_id}/ directory.

    Returns:
        List of artifact file path strings.
    """
    if not artifact_dir.exists():
        return []
    return [str(p) for p in artifact_dir.iterdir() if p.is_file()]
