"""Synchronous request and tool scheduling for a single bounded run."""
from __future__ import annotations

from .contracts import (
    CancellationToken, Continue, Iteration, LoopContext, LoopPorts, LoopResult, RunLimits, Stop,
)
from .events import EventSink


def run_loop(
    context: LoopContext, ports: LoopPorts, limits: RunLimits,
    cancel: CancellationToken, emit: EventSink,
) -> LoopResult:
    """Schedule a prepared turn and return its delivered messages and usage."""
    count = 0
    final_retry = False
    reason = "max_iterations"
    while count < limits.max_iterations or final_retry:
        if ports.before_cancel_check is not None:
            stop = ports.before_cancel_check(count)
            if stop:
                reason = stop.reason
                break
        if cancel.is_set():
            ports.on_cancel()
            reason = "cancelled"
            break
        stop = ports.before_iteration(context)
        if stop:
            reason = stop.reason
            break

        count += 1
        iteration = Iteration(count, count >= limits.max_iterations, final_retry)
        final_retry = False
        stop = ports.prepare_request(context, iteration)
        if stop:
            reason = stop.reason
            break
        response = ports.request(context, emit)
        if isinstance(response, Stop):
            reason = response.reason
            break
        if isinstance(response, Continue):
            continue

        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason in limits.partial_finish_reasons:
            ports.record_partial(response, finish_reason)
            reason = finish_reason
            break
        if response.has_tool_calls and not iteration.final_answer_retry:
            decision = ports.run_tools(response)
            if decision is Continue.NEXT:
                ports.poll_inputs()
        else:
            decision = ports.after_text(response)
        if isinstance(decision, Stop):
            reason = decision.reason
            break
        final_retry = decision is Continue.FINAL_ANSWER and count == limits.max_iterations

    return LoopResult(ports.read_delta(), reason, count, ports.read_usage())
