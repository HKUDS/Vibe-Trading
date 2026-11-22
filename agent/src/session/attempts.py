"""Terminal attempt records, transcript summaries and search projections."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.session.event_projection import ThreadEvents
from src.session.models import Attempt, AttemptStatus, Message, Session
from src.session.runtime import SessionRuntime
from src.session.search import SessionSearchIndex
from src.session.store import SessionStore
from src.session.replay import project_turn


#: Shown after whatever a stopped turn had streamed, or alone if it streamed
#: nothing. The turn's finished tool results stay in the thread either way.
STOPPED_MARKER = "_Stopped before the answer was complete._"


logger = logging.getLogger(__name__)


@dataclass
class AttemptRunner:
    """Run attempts and commit their terminal state to the thread, store and index."""

    store: SessionStore
    runtime: Callable[[str], SessionRuntime]
    thread_events: ThreadEvents
    search_index: SessionSearchIndex
    list_pending_inputs: Callable[[str], list[dict]]
    user_cancel_requests: set[str]

    async def run(self, session: Session, attempt: Attempt, run_agent: Callable, *, include_shell_tools: bool) -> None:
        """Record a terminal result, or leave the attempt recoverable on host shutdown."""
        started_at = time.perf_counter()
        try:
            attempt.mark_running()
            # Wall-clock start (epoch seconds) is the one timing fact clients
            # cannot reconstruct on their own: a client that (re)connects
            # mid-attempt resumes its elapsed timer from it, and history
            # hydration derives the finished attempt's duration from it rather
            # than from the first tool call. It lives on the persisted attempt
            # so it survives reconnects and durable thread replay.
            wall_started_at = attempt.started_at or time.time()
            self.store.update_attempt(attempt)
            messages = self.store.get_messages(session.session_id)
            result = await run_agent(
                attempt, messages=messages,
                include_shell_tools=include_shell_tools,
                session_config=dict(session.config),
            )
            self._commit_result(attempt, result, started_at, wall_started_at)
            self.thread_events.sync(session.session_id)

        except asyncio.CancelledError:
            if session.session_id in self.user_cancel_requests:
                # cancel_current() cancels this task when the run has not
                # reached its AgentRuntime yet. Keep that explicit user action
                # distinct from event-loop cancellation during server shutdown.
                attempt.mark_cancelled(reason="cancelled by user")
                self._finish_thread_turn_quietly(session.session_id, attempt)
                self.store.update_attempt(attempt)
                self.thread_events.sync(session.session_id)
            else:
                logger.info(
                    "Leaving attempt %s recoverable after service task cancellation",
                    attempt.attempt_id,
                )
            raise
        except Exception as exc:
            attempt.mark_failed(error=str(exc))
            self._finish_thread_turn_quietly(session.session_id, attempt)
            self.store.update_attempt(attempt)
            self.thread_events.sync(session.session_id)

    def _finish_thread_turn_quietly(self, session_id: str, attempt: Attempt) -> None:
        """Close the turn in the thread on an error path, never raising.

        Args:
            session_id: Session ID.
            attempt: The attempt, already marked terminal.
        """
        try:
            self.runtime(session_id).finish_turn(
                attempt.attempt_id,
                prompt=attempt.prompt,
                status=attempt.status.value,
                run_dir=attempt.run_dir,
                pending_inputs=(self.list_pending_inputs(session_id)
                                if attempt.status == AttemptStatus.CANCELLED else None),
            )
        except Exception:  # noqa: BLE001 - the attempt's own terminal write still runs
            logger.warning("Could not close thread turn %s", attempt.attempt_id, exc_info=True)

    def _commit_result(self, attempt: Attempt, result: dict, started_at: float, wall_started_at: float) -> None:
        """Write the completed thread projection before updating its attempt record and search index."""
        session_id = attempt.session_id
        status = result.get("status")
        if status == "success":
            attempt.mark_completed(summary=result.get("content", ""))
        elif status == "waiting_user":
            attempt.mark_waiting_user(summary=result.get("content", ""))
        elif status == "cancelled":
            # A cooperative cancel is not an outage; AttemptStatus.CANCELLED
            # existed but was dead because every non-success landed in the
            # failure branch.
            attempt.mark_cancelled(reason=result.get("reason", "cancelled by user"))
        else:
            attempt.mark_failed(error=result.get("reason", "unknown"))
        attempt.run_dir = result.get("run_dir")
        if result.get("metrics"):
            # Metrics were loaded from the run directory but never reached
            # the attempt, so the reply metadata below was always empty.
            attempt.metrics = result["metrics"]

        reply_content = format_result_message(
            attempt, streamed_text=result.get("streamed_text") or ""
        )
        runtime_keys = (
            "provider",
            "configured_model",
            "model",
            "model_source",
            "reasoning_effort",
        )
        reply_metadata = {}
        if attempt.run_dir:
            reply_metadata["run_id"] = Path(attempt.run_dir).name
        reply_metadata["status"] = attempt.status.value
        if attempt.metrics:
            reply_metadata["metrics"] = attempt.metrics
        reply_metadata["elapsed_ms"] = max(0, round((time.perf_counter() - started_at) * 1000))
        reply_metadata["started_at"] = wall_started_at
        for key in runtime_keys:
            value = result.get(key)
            if value is not None:
                reply_metadata[key] = value
        # Project the recorded tool results once before closing the turn so
        # generated report links are included in the durable run summary.
        prefinish_projection = project_turn(
            self.runtime(session_id).thread.read(),
            attempt.attempt_id,
            run_dir=attempt.run_dir,
        )
        reports = [entry["artifact"] for entry in prefinish_projection.tool_results
                   if entry.get("status") == "ok" and isinstance(entry.get("artifact"), dict)]
        if reports:
            reply_metadata["generated_reports"] = reports
            links = [f"[{str(report['filename']).replace('[', '').replace(']', '')}]({report['download_url']})"
                     for report in reports]
            reply_content += "\n\n" + "\n\n".join(dict.fromkeys(links))
        self.runtime(session_id).finish_turn(
            attempt.attempt_id,
            prompt=attempt.prompt,
            status=attempt.status.value,
            usage=result.get("usage"),
            elapsed_ms=reply_metadata["elapsed_ms"],
            run_dir=attempt.run_dir,
            summary=reply_content,
            error=attempt.error,
            provider=result.get("provider"),
            model=result.get("model"),
            pending_inputs=(self.list_pending_inputs(session_id)
                            if attempt.status == AttemptStatus.CANCELLED else None),
            metadata=reply_metadata,
        )
        reply = Message(
            session_id=session_id, role="assistant",
            content=reply_content,
            linked_attempt_id=attempt.attempt_id,
            metadata=reply_metadata,
        )
        self.store.update_attempt(attempt)
        for item in self.store.thread_log(session_id).turn_items(attempt.attempt_id):
            if item.type == "user":
                self.search_index.index_message(session_id, "user", item.get("content") or "")
        self.search_index.index_message(session_id, "assistant", reply.content)


def format_result_message(attempt: Attempt, streamed_text: str = "") -> str:
    """Format the final execution result message.

    Args:
        attempt: The terminal attempt.
        streamed_text: Text the turn streamed to the user; a stopped turn
            keeps it instead of replacing it with a bare notice.

    Returns:
        The reply text shown in the transcript.
    """
    if attempt.status == AttemptStatus.COMPLETED:
        if attempt.summary:
            return attempt.summary
        # Do not dress an empty answer up as a finished strategy run: say
        # that nothing came back so the user knows to retry or rephrase.
        return (
            "The run finished without producing any text output. "
            "Check the run artifacts, or rephrase the request and try again."
        )
    if attempt.status == AttemptStatus.CANCELLED:
        streamed = streamed_text.strip()
        return f"{streamed}\n\n{STOPPED_MARKER}" if streamed else STOPPED_MARKER
    if attempt.status == AttemptStatus.WAITING_USER:
        return attempt.summary or "Please answer the question above."
    return f"Execution failed: {attempt.error or 'unknown error'}"
