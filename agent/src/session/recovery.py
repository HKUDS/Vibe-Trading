"""Reconcile interrupted attempts and durable input claims at service startup."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

from src.session.models import AttemptStatus, Message
from src.session.pending_inputs import PENDING_INPUTS_FILENAME, PendingInputQueue
from src.session.runtime import SessionRuntime
from src.session.search import SessionSearchIndex
from src.session.store import SessionStore


logger = logging.getLogger(__name__)


def recover_interrupted_attempts(
    store: SessionStore, runtime_for: Callable[[str], SessionRuntime], search_index: SessionSearchIndex,
) -> None:
    """Finalize attempts that could not outlive the previous process.

    A newly constructed service has no live AgentRuntime instances. Any
    attempt still marked pending or running therefore belongs to the
    previous process. This is only valid because the service is built once
    per process: two servers sharing one sessions directory would mark each
    other's in-flight attempts interrupted.

    The thread log already holds every tool result the turn finished; its
    turn is closed as ``interrupted`` so the next turn's replay shows those
    results, stubs the call that was cut off and tells the model the turn
    stopped. The transcript reply keeps the streamed-text snapshot, which
    covers text the model was still writing when no assistant item existed.
    """
    recoverable = {AttemptStatus.PENDING, AttemptStatus.RUNNING}
    for attempt in store.list_attempts():
        if attempt.status not in recoverable:
            continue
        runtime = runtime_for(attempt.session_id)
        partial = runtime.partial_response(attempt.attempt_id)
        # A terminal thread reply may have committed before attempt.json.
        reply = store.get_message_for_attempt(attempt.session_id, attempt.attempt_id)
        status = reply.metadata.get("status") if reply is not None else None
        if status not in ("completed", "cancelled", "failed", "waiting_user"):
            status = AttemptStatus.INTERRUPTED.value
        summary = _format_interrupted_message(partial)
        runtime.finish_turn(
            attempt.attempt_id,
            prompt=attempt.prompt,
            status=status,
            run_dir=attempt.run_dir,
            summary=summary,
            metadata={"status": status, "partial": bool(partial), "recovery_reason": "service_restart"},
        )
        if reply is None:
            reply = Message(
                session_id=attempt.session_id, role="assistant", content=summary,
                linked_attempt_id=attempt.attempt_id,
            )
            search_index.index_message(reply.session_id, reply.role, reply.content)
        if status == AttemptStatus.COMPLETED.value:
            attempt.mark_completed(summary=reply.content)
        elif status == AttemptStatus.CANCELLED.value:
            attempt.mark_cancelled(reason="cancelled by user")
        elif status == AttemptStatus.FAILED.value:
            attempt.mark_failed(error="execution failed")
        elif status == AttemptStatus.WAITING_USER.value:
            attempt.mark_waiting_user(summary=reply.content)
        else:
            attempt.mark_interrupted("service restarted before attempt completed")
        store.update_attempt(attempt)


def recover_pending_inputs(store: SessionStore, pending_inputs: PendingInputQueue) -> None:
    """Settle queued inputs a previous process was writing when it stopped.

    Runs after the attempts are reconciled, so a turn the process lost is
    already closed in the thread. An input whose claimed turn holds it is
    delivered: it leaves the queue, and is settled from the thread if
    the process stopped before the turn closed. Any other claimed input waits
    again. Waiting inputs are kept and do not start a turn on their own:
    a restart must not spend tokens nobody asked for now; the next
    message sent to the session, or a discard, settles them.
    """
    for path in sorted(store.base_dir.glob(f"*/{PENDING_INPUTS_FILENAME}")):
        session_id = path.parent.name

        def turn_prompt(turn_id: str, session_id: str = session_id) -> Optional[str]:
            attempt = store.get_attempt(session_id, turn_id)
            return attempt.prompt if attempt is not None else None

        try:
            pending_inputs.reconcile(
                session_id,
                store.thread_log(session_id).read(),
                turn_prompt=turn_prompt,
            )
        except OSError as exc:
            logger.warning("Could not reconcile pending inputs of %s: %s", session_id, exc)


def _format_interrupted_message(partial: Optional[str]) -> str:
    """Build the transcript message for a recovered attempt.

    Args:
        partial: Durable assistant text captured before restart.

    Returns:
        User-facing interruption notice, including partial text when any.
    """
    if partial:
        return (
            "Vibe Trading restarted before this response finished. "
            "The partial response recovered below may be incomplete:\n\n"
            f"{partial}\n\n"
            "Review it before sending a follow-up or retrying the request."
        )
    return (
        "Vibe Trading restarted before this response finished, so no "
        "complete assistant response was saved. Review any completed tool "
        "actions before retrying the request."
    )
