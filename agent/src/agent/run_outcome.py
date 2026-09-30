"""Final outcome of an agent run: status resolution, end event, result dict.

Extracted from the tail of ``AgentLoop._run_bound`` (issue #1624, roadmap
item 3: split ``loop.py`` along its existing seams). This module owns the
decision ladder that maps how a run ended — stall, cancellation,
no-progress, content-filter circuit breaker, success, empty model
response, max iterations — onto ``(status, reason)`` plus the ``end``
trace event and the caller-facing result dict.

Everything here is pure: no state-store writes, no trace writes. The
side-effectful calls (``state_store.mark_*``, ``trace.write/close``) stay
in ``loop.py`` right after ``resolve_final_status`` returns, in the same
order they executed before the extraction.

Behavior is unchanged: every branch condition and message string moved
verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from src.providers.chat import LLMRuntimeSnapshot
from src.providers.content_filter import (
    MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS,
    compute_content_filter_warnings,
)


@dataclass
class OutcomeInputs:
    """The run-end facts the status ladder reads.

    Attributes:
        stall_reason: Reason the stall watchdog already recorded, if any.
            A non-None value wins the ladder: the watchdog already wrote
            the failed state, so the run's terminal status must stay
            honest instead of overwriting it.
        cancelled: Whether the user cancel event is set.
        no_progress_reason: Reason the no-progress check recorded, if any.
        content_filter_circuit_breaker: Whether the content-filter skip
            streak tripped the breaker.
        has_output: Whether the run produced any user-visible output —
            a metrics artifact or a non-empty final answer.
        released_fallback: Whether the grounding gate degraded the final
            answer to the deterministic fallback.
        released_fallback_reason: Reason captured at the release site, if
            the release path set one.
        grounding_validation_count: Rejected-draft count from the
            grounding ledger, used only to build the lazily-worded
            fallback reason when none was captured.
        pending_write_directive: The ``run ended without writing the task
            target file(s)`` directive, or ``None``. Evaluated lazily by
            the caller only on the success path.
        empty_model_response_iter: Iteration of the final empty model
            response, if the run died that way.
        empty_response_provider: Provider name for the empty-response
            failure message.
        empty_response_model: Configured model name for the
            empty-response failure message.
        max_iterations: The run's iteration budget (for the failure
            message).
    """

    stall_reason: Optional[str]
    cancelled: bool
    no_progress_reason: Optional[str]
    content_filter_circuit_breaker: bool
    has_output: bool
    released_fallback: bool
    released_fallback_reason: Optional[str]
    grounding_validation_count: int
    pending_write_directive: Callable[[], Optional[str]]
    empty_model_response_iter: Optional[int]
    empty_response_provider: str
    empty_response_model: str
    max_iterations: int


@dataclass
class RunOutcome:
    """Terminal status plus the side effects the caller must still perform.

    Attributes:
        status: One of ``success``, ``failed``, ``cancelled``.
        reason: Human-readable terminal reason, or ``None`` on a clean
            success. Propagates into the result dict so SessionService
            can surface a meaningful UI message instead of
            ``Execution failed: unknown`` (issue #114).
        mark: Which ``RunStateStore`` transition to record, or ``None``
            when the stall watchdog already wrote the failed state.
        degraded: Whether the final answer was released through the
            degraded fallback path. Drives the ``degraded`` flag on both
            the end event and the result dict.
    """

    status: str
    reason: Optional[str]
    mark: Optional[str]
    degraded: bool


def resolve_final_status(inputs: OutcomeInputs) -> RunOutcome:
    """Run the terminal-status decision ladder.

    The branch order is load-bearing and unchanged from the pre-extraction
    ``_run_bound`` tail: stall (already recorded) → cancelled → no
    progress → content-filter breaker → success → empty response → max
    iterations.
    """
    if inputs.stall_reason is not None:
        # The stall watchdog already wrote the failed state; keep this
        # run's terminal status honest instead of overwriting it.
        return RunOutcome("failed", inputs.stall_reason, None, False)
    if inputs.cancelled:
        return RunOutcome("cancelled", "cancelled by user", "cancelled", False)
    if inputs.no_progress_reason is not None:
        return RunOutcome("failed", inputs.no_progress_reason, "failure", False)
    if inputs.content_filter_circuit_breaker:
        reason = (
            f"content_filter_circuit_breaker: "
            f"{MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS} consecutive LLM "
            "responses were blocked by content moderation"
        )
        return RunOutcome("failed", reason, "failure", False)
    if inputs.has_output:
        if inputs.released_fallback:
            reason = inputs.released_fallback_reason or (
                "final answer degraded to the deterministic fallback after "
                f"{inputs.grounding_validation_count} "
                "rejected drafts could not be corrected within the iteration budget"
            )
            return RunOutcome("success", reason, "success", True)
        pending_directive = inputs.pending_write_directive()
        if pending_directive:
            reason = (
                "run ended without writing the task target file(s): "
                + pending_directive
            )
            return RunOutcome("success", reason, "success", True)
        return RunOutcome("success", None, "success", False)
    if inputs.empty_model_response_iter is not None:
        reason = (
            "empty_model_response: "
            f"provider={inputs.empty_response_provider} "
            f"model={inputs.empty_response_model} "
            f"iteration {inputs.empty_model_response_iter} "
            "returned no content and no tool calls"
        )
        return RunOutcome("failed", reason, "failure", False)
    reason = f"reached max iterations ({inputs.max_iterations}) without final answer"
    return RunOutcome("failed", reason, "failure", False)


def build_end_event(
    outcome: RunOutcome,
    run_iteration: int,
    iterations: int,
) -> dict[str, Any]:
    """The ``end`` trace event for a finished run."""
    end_event: dict[str, Any] = {
        "type": "end",
        "iter": run_iteration,
        "status": outcome.status,
        "iterations": iterations,
    }
    if outcome.degraded:
        end_event["degraded"] = True
    if outcome.reason is not None:
        end_event["reason"] = outcome.reason
    return end_event


def build_result_dict(
    outcome: RunOutcome,
    run_dir: Path,
    react_trace: Any,
    iterations: int,
    max_iterations: int,
    final_content: str,
    runtime: LLMRuntimeSnapshot,
    last_response_model: Optional[str],
    content_filter_count: int,
) -> dict[str, Any]:
    """The caller-facing result dict for a finished run."""
    result: dict[str, Any] = {
        "status": outcome.status,
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "content": final_content,
        "react_trace": react_trace,
        "iterations": iterations,
        "max_iterations": max_iterations,
    }
    if outcome.degraded:
        result["degraded"] = True
    configured_model = runtime.configured_model
    result.update(
        {
            "provider": runtime.provider,
            "configured_model": configured_model,
            "model": last_response_model or configured_model,
            "model_source": "provider_response" if last_response_model else "configured",
            "reasoning_effort": runtime.reasoning_effort,
        }
    )
    if outcome.reason is not None:
        result["reason"] = outcome.reason
    cf_warnings = compute_content_filter_warnings(
        content_filter_count, max(1, iterations),
    )
    if cf_warnings:
        result["content_filter_warnings"] = cf_warnings
    return result
