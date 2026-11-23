"""Commit terminal turn effects and release completion waiters."""
from __future__ import annotations

import traceback

from src.product.outcome import finish_outcome
from src.providers.response import ProviderStreamError
from src.tools.redaction import redact_text


def complete_turn(
    setup, *, turn, activity, runtime, max_iterations, budget_reason,
    waiting_user, pending_write, conversation, tool_env,
):
    """Persist the terminal outcome and close the canonical turn."""
    result = finish_outcome(
        setup, iterations=turn.iterations, activity=activity, runtime=runtime, max_iterations=max_iterations,
        budget_reason=budget_reason, waiting_user=waiting_user,
        pending_write=pending_write,
    )
    conversation.end_turn(tool_env, turn.usage)
    recorder = conversation.thread
    items = recorder._runtime.thread.turn_items(recorder.turn_id)
    result["tool_count"] = sum(item.type == "tool_result" for item in items)
    activity.done.set()

    return result


def fail_turn(exc, setup, *, activity, conversation, tool_env, usage, max_iterations, logger):
    """Persist an iteration exception using the historical error envelope."""
    state = setup.state
    assert state is not None and setup.run_dir is not None and setup.trace is not None and setup.state_store is not None
    reason = redact_text(exc)
    logger.error("AgentRuntime error: %s", redact_text(traceback.format_exc()))
    error_code = "provider_stream_error" if isinstance(exc, ProviderStreamError) else "agent_loop_error"
    setup.trace.write({"type": "end", "iter": activity.iteration, "status": "error", "reason": reason, "iterations": state.iteration})
    setup.state_store.mark_failure(setup.run_dir, reason)
    conversation.end_turn(tool_env, usage)
    activity.done.set()
    return {"status": "failed", "error_code": error_code, "reason": reason, "run_dir": str(setup.run_dir), "run_id": setup.run_dir.name, "content": "", "iterations": state.iteration, "max_iterations": max_iterations}
