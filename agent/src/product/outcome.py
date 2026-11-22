"""Resolve terminal run status and project the persisted and public outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from src.kernel.contracts import LLMRuntimeSnapshot
from src.providers.chat import reported_model_source
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
        released_fallback: Whether a delivery failure required a fallback answer.
        released_fallback_reason: Reason captured at the release site, if
            the release path set one.
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
        budget_reason: An exhausted research-goal token budget, if any.
        answer_released: Whether a final answer was released to the user.
            One that crossed the budget is a degraded success, not a failure.
        truncation_reason: Provider-reported output limit; partial text is retained.
    """

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

    The branch order is load-bearing: stall (already recorded) → cancelled →
    exhausted token budget → no
    progress → content-filter breaker → success → empty response → max
    iterations.
    """
    if inputs.stall_reason is not None:
        # The stall watchdog already wrote the failed state; keep this
        # run's terminal status honest instead of overwriting it.
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


def finish_outcome(setup, *, activity, runtime, max_iterations, budget_reason, waiting_user, pending_write):
    """Commit the terminal status and event before the recorder flushes the turn."""
    state = setup.state
    assert state is not None
    run_dir = setup.run_dir
    trace = setup.trace
    state_store = setup.state_store
    assert run_dir is not None and trace is not None and state_store is not None
    # Determine final status. The reason is also propagated into the
    # returned dict so SessionService can surface a meaningful UI
    # message instead of "Execution failed: unknown" (issue #114).
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
        # A success that ended without writing the target file(s): the
        # pre-extraction code flagged it degraded only for this case.
        state.released_fallback = True

    trace.write(build_end_event(outcome, activity.iteration, state.iteration))

    return build_result_dict(
        outcome,
        run_dir,
        state.iteration,
        max_iterations,
        state.final_content,
        runtime,
        state.last_response_model,
        state.content_filter_count,
    )
