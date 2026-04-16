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
    """Estimate token usage for a single LLM call.

    Tries to read actual token counts from the LLM response metadata
    (LangChain's usage_metadata). Falls back to character-length estimation
    (len // 4) if metadata is unavailable.

    Args:
        messages: Messages sent to the LLM for this call.
        response: LLMResponse from ChatLLM.chat().

    Returns:
        Tuple of (input_tokens, output_tokens).
    """
    from src.providers.chat import LLMResponse

    input_tokens = 0
    output_tokens = 0

    # response is an LLMResponse; it doesn't carry raw metadata.
    # Estimate: input = serialized messages length // 4, output = content length // 4
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
) -> str:
    """Build the worker's system prompt with role, upstream context, and skills.

    Args:
        agent_spec: The agent's role specification.
        upstream_summaries: Mapping of context_key -> upstream task summary.
        skill_descriptions: Pre-filtered skill description text.

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
        "**Phase 3 — Summarize (0 tool calls):**\n"
        "- Write your final findings as a concise markdown summary directly in your response.\n"
        "- Include specific numbers, dates, and actionable conclusions.\n"
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

    Returns:
        WorkerResult with status, summary, artifacts, and iteration count.
    """
    agent_id = agent_spec.id
    task_id = task.id
    max_iterations = agent_spec.max_iterations or _DEFAULT_MAX_ITERATIONS
    timeout = agent_spec.timeout_seconds or _DEFAULT_TIMEOUT_SECONDS

    _emit(event_callback, "worker_started", agent_id, task_id)

    # 1. Build filtered tool registry
    registry = build_filtered_registry(agent_spec.tools)

    # 2. Create LLM
    llm = ChatLLM(model_name=agent_spec.model_name)

    # 3. Build system prompt with filtered skills
    skills_loader = SkillsLoader()
    skill_desc = _filter_skill_descriptions(skills_loader, agent_spec.skills)
    system_prompt = build_worker_prompt(agent_spec, upstream_summaries, skill_desc)

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
            summary = last_assistant_content or f"Worker timed out after {elapsed:.0f}s ({iteration} iterations)"
            _emit(event_callback, "worker_timeout", agent_id, task_id, {"elapsed": elapsed})
            _write_summary(artifact_dir, summary)
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
                    "Stop calling tools and immediately output your final analysis summary as plain text. "
                    "Do not call any more tools."
                ),
            })

        # On last iteration, call LLM without tool definitions to force text output
        is_last_iteration = iteration == max_iterations - 1
        tool_defs = None if is_last_iteration else registry.get_definitions()

        # Call LLM with remaining timeout
        try:
            remaining_timeout = max(10, int(timeout - elapsed))
            response = llm.chat(messages, tools=tool_defs, timeout=remaining_timeout)
        except Exception as exc:
            error_msg = f"LLM call failed at iteration {iteration}: {exc}"
            logger.warning(error_msg)
            _emit(event_callback, "worker_failed", agent_id, task_id, {"error": error_msg})
            return WorkerResult(
                status="failed",
                summary=last_assistant_content or "",
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

        # Emit agent thinking text for live streaming
        if response.content and response.content.strip():
            _emit(event_callback, "worker_text", agent_id, task_id,
                  {"content": response.content, "iteration": iteration})

        # Track last meaningful assistant content
        if response.content and len(response.content.strip()) > 20:
            last_assistant_content = response.content

        # If no tool calls, this is the final response
        if not response.has_tool_calls:
            summary = response.content or last_assistant_content or "(no summary)"
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
                response.tool_calls, content=response.content
            )
        )

        # Execute each tool call — inject run_dir so tools write inside artifact_dir
        for tc in response.tool_calls:
            _emit(
                event_callback, "tool_call", agent_id, task_id,
                {"tool": tc.name, "iteration": iteration},
            )
            tc_start = time.monotonic()
            args = {**tc.arguments, "run_dir": str(artifact_dir)}
            result = registry.execute(tc.name, args)
            tc_elapsed = time.monotonic() - tc_start
            _emit(
                event_callback, "tool_result", agent_id, task_id,
                {"tool": tc.name, "elapsed_ms": int(tc_elapsed * 1000),
                 "status": "ok", "iteration": iteration},
            )
            messages.append(
                ContextBuilder.format_tool_result(tc.id, tc.name, result[:10_000])
            )

    # Hit iteration limit — use last meaningful content as summary
    summary = last_assistant_content or f"Worker hit iteration limit ({max_iterations} iterations)"
    _emit(event_callback, "worker_iteration_limit", agent_id, task_id)
    _write_summary(artifact_dir, summary)
    return WorkerResult(
        status="completed",
        summary=summary,
        artifact_paths=_collect_artifacts(artifact_dir),
        iterations=max_iterations,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )


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
