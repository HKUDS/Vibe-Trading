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
    """Finalize interrupted attempts only under exclusive ownership of the session store.

    Args:
        store: Exclusively owned store containing pending and running attempts.
        runtime_for: Callable resolving the session runtime used to close each turn.
        search_index: Search index that receives recovered replies when the thread had no terminal
            reply.
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
    """Settle durable claims after attempt recovery without scheduling new turns.

    Args:
        store: Store containing session directories and committed thread items.
        pending_inputs: Queue whose outstanding claims are reconciled.
    """
    for path in sorted(store.base_dir.glob(f"*/{PENDING_INPUTS_FILENAME}")):
        session_id = path.parent.name

        def turn_prompt(turn_id: str, session_id: str = session_id) -> Optional[str]:
            """Look up the prompt of a persisted attempt.

            Args:
                turn_id: Turn ID used as the attempt ID.
                session_id: Session owning the attempt, bound to the current queue by default.

            Returns:
                The stored prompt, or None if the attempt is unavailable.
            """
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
    """Build the transcript message for a recovered attempt."""
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
