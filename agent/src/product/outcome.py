"""Resolve terminal run status and project the persisted and public outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from src.kernel.contracts import LLMRuntimeSnapshot
from src.providers.response import reported_model_source
from src.providers.content_filter import (
    MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS,
    compute_content_filter_warnings,
)


@dataclass
class OutcomeInputs:
    """Supply terminal facts and defer the pending-write check until success."""

    stall_reason: Optional[str]
    cancelled: bool
    no_progress_reason: Optional[str]
    content_filter_circuit_breaker: bool
    has_output: bool
    released_fallback: bool
    released_fallback_reason: Optional[str]
    pending_write_directive: Callable[[], Optional[str]]
    empty_model_response_iter: Optional[int]
    empty_response_provider: str
    empty_response_model: str
    max_iterations: int
    budget_reason: Optional[str] = None
    answer_released: bool = False
    truncation_reason: Optional[str] = None
    waiting_user: bool = False


@dataclass
class RunOutcome:
    """Terminal status plus the side effects the caller must still perform."""

    status: str
    reason: Optional[str]
    mark: Optional[str]
    degraded: bool


def resolve_final_status(inputs: OutcomeInputs) -> RunOutcome:
    """Select the terminal run status and any state update it requires.

    Args:
        inputs: Run facts used to resolve stop conditions, partial output, and delivery.

    Returns:
        The status, optional reason, requested state-store mark, and degradation flag.
    """
    if inputs.stall_reason is not None:
        # The watchdog already wrote this failure.
        return RunOutcome("failed", inputs.stall_reason, None, False)
    if inputs.cancelled:
        return RunOutcome("cancelled", "cancelled by user", "cancelled", False)
    if inputs.budget_reason is not None and not inputs.answer_released:
        return RunOutcome("failed", inputs.budget_reason, "failure", False)
    if inputs.no_progress_reason is not None:
        return RunOutcome("failed", inputs.no_progress_reason, "failure", False)
    if inputs.content_filter_circuit_breaker:
        reason = (
            f"content_filter_circuit_breaker: "
            f"{MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS} consecutive LLM "
            "responses were blocked by content moderation"
        )
        return RunOutcome("failed", reason, "failure", False)
    if inputs.truncation_reason is not None:
        return RunOutcome("failed", inputs.truncation_reason, "failure", False)
    if inputs.waiting_user:
        return RunOutcome("waiting_user", None, None, False)
    if inputs.has_output:
        if inputs.budget_reason is not None:
            # The answer that crossed a goal's token budget was released.
            return RunOutcome("success", inputs.budget_reason, "success", True)
        if inputs.released_fallback:
            reason = inputs.released_fallback_reason or (
                "final response could not be delivered; a fallback was shown"
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
    """Build the end trace event for a finished run.

    Args:
        outcome: Terminal decision supplying status, degradation, and reason.
        run_iteration: Host iteration number used in the trace.
        iterations: Number of iterations started during this turn.

    Returns:
        An end event containing status and counts, with reason and degradation when present.
    """
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
    iterations: int,
    max_iterations: int,
    final_content: str,
    runtime: LLMRuntimeSnapshot,
    last_response_model: Optional[str],
    content_filter_count: int,
) -> dict[str, Any]:
    """Build the caller-facing result for a finished run.

    Args:
        outcome: Terminal decision supplying status, degradation, and reason.
        run_dir: Run directory whose name is used as the run identifier.
        iterations: Number of iterations started.
        max_iterations: Configured regular iteration limit.
        final_content: Delivered text, if any.
        runtime: Snapshot of the configured provider, model, and reasoning effort.
        last_response_model: Last provider-reported model ID, if available.
        content_filter_count: Number of responses blocked by moderation.

    Returns:
        Run status, location, content, iteration counts, and model metadata, plus any warnings.
    """
    result: dict[str, Any] = {
        "status": outcome.status,
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "content": final_content,
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
            "model_source": reported_model_source(runtime, last_response_model),
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


def finish_outcome(state, *, iterations, activity, runtime, max_iterations, budget_reason, waiting_user, pending_write):
    """Commit the terminal status and event before the recorder flushes the turn.

    Args:
        state: Turn state carrying final content, stop conditions, and trace.
        iterations: Number of iterations started during the turn.
        activity: Run activity tracker supplying cancellation and watchdog state.
        runtime: Provider and model settings used to describe the result.
        max_iterations: Configured regular iteration limit.
        budget_reason: Goal budget stop reason, if any.
        waiting_user: Whether delivery paused to ask for user input.
        pending_write: Callback that checks for unwritten targets using the user prompt and start time.

    Returns:
        The caller-facing result after terminal state and trace updates.
    """
    run_dir = state.run_dir
    state_store = state.state_store
    outcome = resolve_final_status(
        OutcomeInputs(
            stall_reason=activity.stall_reason,
            cancelled=activity.cancel.is_set(),
            no_progress_reason=state.no_progress_reason,
            content_filter_circuit_breaker=state.content_filter_circuit_breaker,
            has_output=(run_dir / "artifacts" / "metrics.csv").exists() or bool(state.final_content),
            released_fallback=state.released_fallback,
            released_fallback_reason=state.released_fallback_reason,
            pending_write_directive=lambda: pending_write(
                state.user_message, state.run_started_wall
            ),
            empty_model_response_iter=state.empty_model_response_iter,
            empty_response_provider=runtime.provider,
            empty_response_model=runtime.configured_model or "(unset)",
            max_iterations=max_iterations,
            budget_reason=budget_reason,
            answer_released=bool(state.final_content),
            truncation_reason=state.truncation_reason,
            waiting_user=waiting_user,
        )
    )
    final_reason = outcome.reason
    if outcome.mark == "cancelled":
        state_store.mark_cancelled(run_dir, final_reason or "cancelled by user")
    elif outcome.mark == "failure":
        state_store.mark_failure(run_dir, final_reason or "")
    elif outcome.mark == "success":
        state_store.mark_success(run_dir)
    if outcome.mark == "success" and outcome.degraded and final_reason and not state.released_fallback:
        state.released_fallback = True

    state.trace.write(build_end_event(outcome, activity.iteration, iterations))

    return build_result_dict(
        outcome,
        run_dir,
        iterations,
        max_iterations,
        state.final_content,
        runtime,
        state.last_response_model,
        state.content_filter_count,
    )
