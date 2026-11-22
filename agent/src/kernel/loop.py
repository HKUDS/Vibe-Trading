"""Synchronous request and tool scheduling for a single bounded run."""
from __future__ import annotations

from .contracts import ContextT, LoopDecision, LoopPorts


def run_loop(context: ContextT, ports: LoopPorts[ContextT], *, max_iterations: int) -> None:
    """Drive the prepared turn through its host-bound request and response ports.

    Args:
        context: Turn counters and final-answer retry state. Preparation advances
            the iteration only after the host's cancellation and budget checks.
        ports: Operations bound by the runtime before the turn starts.
        max_iterations: Maximum ordinary iterations, excluding a pending final
            answer retry.
    """
    while context.iteration < max_iterations or context.final_answer_retry_pending:
        context.final_answer_retry = context.final_answer_retry_pending
        context.final_answer_retry_pending = False
        if ports.prepare_iteration(context) is LoopDecision.STOP:
            return
        response = ports.request(context)
        if response is LoopDecision.STOP:
            return
        if response is LoopDecision.CONTINUE:
            continue

        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason in {"length", "max_tokens"}:
            ports.record_partial(context, response, finish_reason)
            return
        if response.has_tool_calls and not context.final_answer_retry:
            decision = ports.run_tools(context, response)
        else:
            decision = ports.after_text(context, response)
        if decision is LoopDecision.STOP:
            return
