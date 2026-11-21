"""Session lifecycle orchestration for message flow, attempt creation, and execution scheduling.

The conversation, not the attempt, is the unit: each session has one
:class:`~src.session.runtime.SessionRuntime` whose ``thread.jsonl`` records
every turn in full. A turn's model input is replayed from it, and the
``messages.jsonl`` display row is projected from it when the turn ends.

A caller that opts in (``queue_if_busy``, the web send route) may send while a
turn runs: the message waits in :mod:`src.session.pending_inputs` and joins
the running turn after its current tool batch, or starts the next turn.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.session.checkpoint import ResponseCheckpoint
from src.session.events import EventBus, ThreadEvents
from src.session.pending_inputs import (
    PENDING_INPUTS_FILENAME,
    PendingInput,
    PendingInputQueue,
    QueuedInputDelivery,
)
from src.session.models import (
    Attempt,
    AttemptStatus,
    Message,
    Principal,
    Session,
)
from src.session.runtime import SessionRuntime
from src.session.search import get_shared_index
from src.session.store import SessionStore
from src.session.thread import TurnProjection, project_turn

if TYPE_CHECKING:
    from src.agent.loop import AgentLoop

# Dedicated thread pool limited to four concurrent agents to avoid exhausting the default executor.
_AGENT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")
logger = logging.getLogger(__name__)


#: Shown after whatever a stopped turn had streamed, or alone if it streamed
#: nothing. The turn's finished tool results stay in the thread either way.
STOPPED_MARKER = "_Stopped before the answer was complete._"


def _cancel_session_swarm_runs(session_id: str) -> int:
    """Signal every live swarm run started by this session.

    Imported lazily: ``src.swarm.runtime`` pulls in worker/tool modules that
    would create an import cycle at module load, and this helper is only needed
    on the cancel path.

    Args:
        session_id: Session whose swarm runs should stop.

    Returns:
        Number of runs that received a cancel signal.
    """
    try:
        from src.swarm.runtime import cancel_runs_for_session
    except Exception:  # pragma: no cover - swarm extra missing in slim installs
        logger.debug("Swarm runtime unavailable; skipping swarm cancel", exc_info=True)
        return 0
    return cancel_runs_for_session(session_id)


class SessionBusyError(RuntimeError):
    """Raised when a session already has an in-flight run.

    One AgentLoop per session: two loops writing the same session would
    interleave their messages and attempts. A second concurrent send is
    therefore rejected unless its caller opted in to queueing
    (``send_message(queue_if_busy=True)``). Callers surface this as HTTP 409
    so the user can wait for the running attempt or cancel it first.
    """


class SessionService:
    """Session lifecycle service.

    Attributes:
        store: Session persistence store.
        event_bus: SSE event bus.
        runs_dir: Root runs directory.
    """

    def __init__(
        self,
        store: SessionStore,
        event_bus: EventBus,
        runs_dir: Path,
    ) -> None:
        """Initialize the session service.

        Args:
            store: Session persistence store.
            event_bus: SSE event bus.
            runs_dir: Root runs directory.
        """
        self.store = store
        self.event_bus = event_bus
        # Every event of a running turn is published through this item/run
        # seam, with thread.jsonl as the durable source of truth.
        self.thread_events = ThreadEvents(event_bus, store.thread_path)
        self.runs_dir = runs_dir
        # _active_loops is the cancellation handle only. It is populated after
        # the registry is built, which is far too late to serve as the
        # concurrency gate, so in-flight sessions are tracked separately and
        # reserved synchronously in send_message.
        self._active_loops: Dict[str, "AgentLoop"] = {}
        # Task handles are kept from the moment the run is scheduled, so a run
        # still building its registry can be cancelled. _active_loops only
        # exists once construction finished, which is far too late to be the
        # only cancellation route: a hung discovery would otherwise hold the
        # claim forever and lock the session behind 409.
        self._active_tasks: Dict[str, "asyncio.Task"] = {}
        # Only task cancellation requested through cancel_current is a user
        # cancellation. Event-loop shutdown also raises CancelledError, but
        # that attempt must remain recoverable on the next process start.
        self._user_cancel_requests: set[str] = set()
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._search_index = get_shared_index()
        self._background_handles: Dict[str, Any] = {}
        # One runtime per conversation, alive across its turns. Rebuilt from
        # the thread's state items on first use after a restart.
        self._runtimes: Dict[str, SessionRuntime] = {}
        self._runtimes_lock = threading.Lock()
        self._shutting_down = False
        # Durable records live under the runtime root that owns runs_dir, so a
        # test pointing runs_dir at a temp root gets its own isolated store.
        from src.tools.background_tools import init_background_store

        self._background_store = init_background_store(Path(runs_dir).parent)
        # Messages sent while a turn runs, durable per session directory.
        self.pending_inputs = PendingInputQueue(
            lambda session_id: store.thread_path(session_id).parent / PENDING_INPUTS_FILENAME
        )
        self._recover_interrupted_attempts()
        self._recover_pending_inputs()

    def _recover_interrupted_attempts(self) -> None:
        """Finalize attempts that could not outlive the previous process.

        A newly constructed service has no live AgentLoop instances. Any
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
        for attempt in self.store.list_attempts():
            if attempt.status not in recoverable:
                continue
            runtime = self.runtime(attempt.session_id)
            partial = runtime.partial_response(attempt.attempt_id)
            if partial is None:
                partial = self.store.get_partial_response(
                    attempt.session_id, attempt.attempt_id
                )
            has_partial = bool(partial)
            existing_reply = self.store.get_message_for_attempt(
                attempt.session_id, attempt.attempt_id
            )
            if existing_reply is None:
                projection = self._close_recovered_turn(
                    attempt, AttemptStatus.INTERRUPTED.value
                )
                if not self._has_projected_user(attempt.session_id, attempt):
                    self._append_projected_user(attempt)
                reply = Message(
                    session_id=attempt.session_id,
                    role="assistant",
                    content=self._format_interrupted_message(partial),
                    linked_attempt_id=attempt.attempt_id,
                    metadata={
                        "status": AttemptStatus.INTERRUPTED.value,
                        "partial": has_partial,
                        "recovery_reason": "service_restart",
                    },
                    tool_trail=projection.tool_trail if projection is not None else [],
                )
                self.store.append_message(reply)
                self._search_index.index_message(
                    attempt.session_id, "assistant", reply.content
                )
                attempt.mark_interrupted("service restarted before attempt completed")
            else:
                # The append-only reply is committed before attempt.json. If a
                # process exits between those writes, finish the second half
                # from the reply's terminal metadata instead of mislabelling a
                # complete response as interrupted.
                reply_status = existing_reply.metadata.get("status")
                thread_status = (
                    reply_status
                    if reply_status in {"completed", "cancelled", "failed"}
                    else AttemptStatus.INTERRUPTED.value
                )
                self._close_recovered_turn(attempt, thread_status)
                if reply_status == AttemptStatus.COMPLETED.value:
                    attempt.mark_completed(summary=existing_reply.content)
                elif reply_status == AttemptStatus.CANCELLED.value:
                    attempt.mark_cancelled(reason="cancelled by user")
                elif reply_status == AttemptStatus.FAILED.value:
                    attempt.mark_failed(error="execution failed")
                else:
                    attempt.mark_interrupted(
                        "service restarted before attempt completed"
                    )
            self.store.update_attempt(attempt)
            self.store.delete_partial_response(attempt.session_id, attempt.attempt_id)

    def _recover_pending_inputs(self) -> None:
        """Settle queued inputs a previous process was writing when it stopped.

        Runs after the attempts are reconciled, so a turn the process lost is
        already closed in the thread. An input whose claimed turn holds it is
        delivered: it leaves the queue, and gets its ``messages.jsonl`` row if
        the process stopped before writing one. Any other claimed input waits
        again. Waiting inputs are kept and do not start a turn on their own:
        a restart must not spend tokens nobody asked for now; the next
        message sent to the session, or a discard, settles them.
        """
        for path in sorted(self.store.base_dir.glob(f"*/{PENDING_INPUTS_FILENAME}")):
            session_id = path.parent.name

            def turn_prompt(turn_id: str, session_id: str = session_id) -> Optional[str]:
                attempt = self.store.get_attempt(session_id, turn_id)
                return attempt.prompt if attempt is not None else None

            try:
                delivered = self.pending_inputs.reconcile(
                    session_id,
                    self.store.thread_log(session_id).read(),
                    turn_prompt=turn_prompt,
                )
            except OSError as exc:
                logger.warning("Could not reconcile pending inputs of %s: %s", session_id, exc)
                continue
            if not delivered:
                continue
            # Delivered inputs are persisted by the terminal turn projection.
            # The thread item already records them while the turn is live.

    def _close_recovered_turn(
        self, attempt: Attempt, status: str
    ) -> Optional[TurnProjection]:
        """Write the missing ``turn_end`` of a turn the previous process lost.

        A session without a thread log predates it; recovery does not create
        one for it.

        Args:
            attempt: The attempt being reconciled.
            status: Thread status to close the turn with.

        Returns:
            The turn's projection, or None for a session with no thread log.
        """
        runtime = self.runtime(attempt.session_id)
        if not runtime.thread.path.exists():
            return None
        return runtime.finish_turn(
            attempt.attempt_id,
            prompt=attempt.prompt,
            status=status,
            run_dir=attempt.run_dir,
        )

    def runtime(self, session_id: str) -> SessionRuntime:
        """Return the session's runtime, rebuilding it from its thread if needed.

        Args:
            session_id: Session ID.

        Returns:
            The session runtime.
        """
        with self._runtimes_lock:
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                runtime = SessionRuntime(self.store.thread_log(session_id), session_id)
                self._runtimes[session_id] = runtime
            return runtime

    def _has_projected_user(self, session_id: str, attempt: Attempt) -> bool:
        if not self.store._messages_file(session_id).exists():
            return False
        return any(
            message.role == "user" and message.content == attempt.prompt
            for message in self.store.get_messages(session_id, limit=None)
        )

    def _append_projected_user(self, attempt: Attempt) -> None:
        items = self.store.thread_log(attempt.session_id).turn_items(attempt.attempt_id)
        user_items = [item for item in items if item.type == "user"]
        message_path = self.store._messages_file(attempt.session_id)
        existing = self.store.get_messages(attempt.session_id, limit=None) if message_path.exists() else []
        for item in user_items:
            metadata = {}
            input_id = item.get("input_id")
            if isinstance(input_id, str) and input_id:
                metadata["queued_input_id"] = input_id
            content = item.get("content") or ""
            if any(
                message.role == "user"
                and message.content == content
                and message.metadata == metadata
                for message in existing
            ):
                continue
            self.store.append_message(Message(
                session_id=attempt.session_id,
                role="user",
                content=content,
                metadata=metadata,
            ))
            self._search_index.index_message(attempt.session_id, "user", content)
            existing.append(Message(
                session_id=attempt.session_id,
                role="user",
                content=content,
                metadata=metadata,
            ))
        if not user_items and not self._has_projected_user(attempt.session_id, attempt):
            self.store.append_message(Message(
                session_id=attempt.session_id,
                role="user",
                content=attempt.prompt,
            ))
            self._search_index.index_message(attempt.session_id, "user", attempt.prompt)

    @staticmethod
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

    def _reserve_session(self, session_id: str) -> None:
        """Claim a session for one in-flight run.

        Args:
            session_id: Session to claim.

        Raises:
            SessionBusyError: If the session is already claimed.
        """
        with self._inflight_lock:
            if self._shutting_down:
                raise SessionBusyError("shutting down; no new runs are accepted")
            if session_id in self._inflight:
                raise SessionBusyError(
                    f"Session {session_id} already has a run in progress"
                )
            self._inflight.add(session_id)

    def _publish_background_completion(self, owner_id: str, payload: dict) -> None:
        """Route a background task's terminal state to its owning session.

        The AgentLoop that started the task may already have exited by the time
        the command finishes, so this cannot depend on a later iteration draining
        the queue. The payload keeps the attempt that started the task, which is
        the attempt the completion belongs to, not whichever one is current.
        """
        if not owner_id.startswith("session:"):
            return
        session_id = owner_id[len("session:"):]
        self.event_bus.emit(session_id, "background.completed", payload)

    def shutdown(self, *, timeout: float = 5.0) -> list[str]:
        """Stop accepting work, cancel owned background work, and wait for reaping.

        Does not tear down the event bus or thread pools this service may share
        with other hosts. Returns task ids still running after the wait, so an
        incomplete cleanup is reported instead of being called a success.
        """
        with self._inflight_lock:
            self._shutting_down = True
        with self._inflight_lock:
            tasks = [task for task in self._active_tasks.values() if not task.done()]
        for active_loop in list(self._active_loops.values()):
            active_loop.cancel()
        for task in tasks:
            task.get_loop().call_soon_threadsafe(task.cancel)
        deadline = time.monotonic() + max(0.0, timeout)
        while any(not task.done() for task in tasks) and time.monotonic() < deadline:
            time.sleep(0.01)
        pending = [f"attempt:{session_id}" for session_id, task in list(self._active_tasks.items())
                   if not task.done()]
        for background in list(self._background_handles.values()):
            remaining = max(0.0, deadline - time.monotonic())
            # cancel_all, not shutdown: these handles sit over the process-wide
            # table, and closing it would stop unrelated hosts in this process.
            # New work is refused by the _shutting_down gate in send_message.
            pending.extend(background.cancel_all(timeout=remaining)["pending"])
        return pending

    def _release_session(self, session_id: str) -> None:
        """Release a session claim. Safe to call when no claim is held.

        Args:
            session_id: Session to release.
        """
        with self._inflight_lock:
            self._inflight.discard(session_id)

    def create_session(
        self,
        title: str = "",
        config: Optional[Dict[str, Any]] = None,
        owner: Optional["Principal"] = None,
    ) -> Session:
        """Create a new session.

        Args:
            title: Session title.
            config: Session configuration.
            owner: Principal the session belongs to, from the authenticated
                request. Optional because sessions are also created by the CLI
                and by internal paths that have no request context; those get
                ``None``, which reads as "owner unknown" and is deliberately
                distinct from a principal that authenticated but cannot be
                attributed to a person (see ``Principal.attributable``).

        Returns:
            The newly created Session.
        """
        session = Session(title=title, config=config or {}, owner=owner)
        self.store.create_session(session)
        self._search_index.index_session(session.session_id, title)
        self.event_bus.emit(session.session_id, "session.created", {"session_id": session.session_id, "title": title})
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Return a session by ID."""
        return self.store.get_session(session_id)

    def update_session(self, session: Session) -> None:
        """Persist session metadata and refresh its search label."""
        self.store.update_session(session)
        self._search_index.index_session(session.session_id, session.title)

    def list_sessions(self, limit: int = 50) -> list[Session]:
        """List all sessions."""
        return self.store.list_sessions(limit)

    def delete_session(self, session_id: str) -> bool:
        """Delete an idle session after purging its searchable text.

        Args:
            session_id: Session to delete.

        Returns:
            Whether the on-disk session existed and was deleted.

        Raises:
            SessionBusyError: If a run could recreate the deleted content.
            Exception: If the search purge fails; the on-disk session remains
                available so the user can retry instead of receiving false success.
        """
        with self._inflight_lock:
            if session_id in self._inflight:
                raise SessionBusyError("Stop the active run before deleting its session")
            # Purge even when the directory is absent: a retry can clear stale
            # index rows left by an older version or an interrupted deletion.
            self._search_index.remove_session(session_id)
            deleted = self.store.delete_session(session_id)
            with self._runtimes_lock:
                self._runtimes.pop(session_id, None)
            self.event_bus.clear(session_id)
            background = self._background_handles.pop(session_id, None)
            if background is not None:
                background.cancel_all()
            return deleted

    async def send_message(
        self,
        session_id: str,
        content: str,
        role: str = "user",
        *,
        include_shell_tools: bool = False,
        queue_if_busy: bool = False,
    ) -> Dict[str, Any]:
        """Send a message to a session and trigger execution.

        Args:
            session_id: Session ID.
            content: Message content, already validated by the caller exactly
                as for any message (a queued one included).
            role: Message role.
            include_shell_tools: Whether this attempt may use shell tools.
            queue_if_busy: Accept a user message for a session whose turn is
                running instead of refusing it. It waits durably and joins the
                running turn after its current tool batch, or starts the next
                turn when that turn ends first. While earlier queued messages
                still wait, a new one goes behind them and the oldest starts
                the turn. Callers that do not opt in (channels, scheduler,
                bridges) are refused as before.

        Returns:
            ``message_id`` and ``attempt_id`` for a message that started its
            own turn. A queued message returns ``status: "queued"``, its
            ``input_id``, its 1-based ``position`` among waiting messages and
            ``attempt_id``: the turn running now or just started.

        Raises:
            ValueError: If the session does not exist.
            SessionBusyError: If the session already has a run in progress
                and the caller did not opt in, or the service is shutting
                down. Callers surface this as HTTP 409; the user can wait for
                the running attempt or cancel it first.
            PendingInputLimitError: If the message would be queued but the
                session already holds the maximum number of waiting messages.
        """
        session = self.store.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        if self._shutting_down:
            raise SessionBusyError("shutting down; no new runs are accepted")

        if role != "user":
            message = Message(session_id=session_id, role=role, content=content)
            self.store.append_message(message)
            self._search_index.index_message(session_id, role, content)
            self.event_bus.emit(session_id, "message.received", {"message_id": message.message_id, "role": role, "content": content})
            return {"message_id": message.message_id}

        # Claim the session before persisting anything. Reserving after the
        # user message is appended (or relying on _active_loops, which is only
        # populated once the registry is built) lets two concurrent sends both
        # store a message and create an attempt.
        try:
            self._reserve_session(session_id)
        except SessionBusyError:
            if not queue_if_busy or self._shutting_down:
                raise
            return self._queue_input(
                session_id, content,
                running_turn=session.last_attempt_id,
                include_shell_tools=include_shell_tools,
            )
        handed_off = False
        try:
            if queue_if_busy and self.pending_inputs.waiting(session_id):
                # Messages queued earlier still wait (a stop or a restart kept
                # them): they go first, so the conversation keeps send order.
                started = self._start_queued_turn(session)
                handed_off = started is not None
                return self._queue_input(
                    session_id, content,
                    running_turn=started["attempt_id"] if started else None,
                    include_shell_tools=include_shell_tools,
                )
            result = self._start_turn(session, content, include_shell_tools=include_shell_tools)
            # _run_attempt now owns the claim and releases it in its finally.
            handed_off = True
            return result
        finally:
            if not handed_off:
                self._release_session(session_id)

    def _start_turn(
        self,
        session: Session,
        content: str,
        *,
        include_shell_tools: bool,
        attempt: Optional[Attempt] = None,
        queued: Optional[PendingInput] = None,
    ) -> Dict[str, Any]:
        """Record the user message and schedule its turn.

        The caller holds the session claim; once the task is scheduled,
        :meth:`_run_attempt` owns it.

        Args:
            session: The session.
            content: The user's message.
            include_shell_tools: Whether the turn may use shell tools.
            attempt: A prepared attempt (a queued input claimed it already).
            queued: The queued input this turn delivers, if any.

        Returns:
            ``message_id`` and ``attempt_id``.
        """
        session_id = session.session_id
        message = Message(
            session_id=session_id,
            role="user",
            content=content,
            metadata={"queued_input_id": queued.input_id} if queued is not None else {},
        )
        self.event_bus.emit(session_id, "message.received", {"message_id": message.message_id, "role": "user", "content": content})

        if attempt is None:
            attempt = Attempt(session_id=session_id, parent_attempt_id=session.last_attempt_id, prompt=content)
        self.store.create_attempt(attempt)
        session.config["include_shell_tools"] = include_shell_tools
        session.last_attempt_id = attempt.attempt_id
        session.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.update_session(session)
        # Through thread_events: the session's thread is read from here on,
        # before this turn records anything.
        self.thread_events.emit(session_id, "attempt.created", {"attempt_id": attempt.attempt_id, "prompt": content})
        if queued is not None:
            self.thread_events.emit(
                session_id, "input.delivered",
                {"attempt_id": attempt.attempt_id, "input_id": queued.input_id,
                 "message_id": message.message_id},
            )

        task = asyncio.create_task(
            self._run_attempt(session, attempt, include_shell_tools=include_shell_tools)
        )
        self._active_tasks[session_id] = task
        return {"message_id": message.message_id, "attempt_id": attempt.attempt_id}

    def _start_queued_turn(self, session: Session) -> Optional[Dict[str, Any]]:
        """Start a turn from the oldest waiting input. The caller holds the claim.

        The input is claimed for the new attempt before anything is written
        and removed from the queue only once that attempt exists, so a crash
        in between is settled by :meth:`_recover_pending_inputs`.

        Args:
            session: The session.

        Returns:
            The started turn's ``message_id`` / ``attempt_id``, or None when
            no input was waiting.
        """
        session_id = session.session_id
        attempt = Attempt(session_id=session_id, parent_attempt_id=session.last_attempt_id)
        pending = self.pending_inputs.claim_next(session_id, attempt.attempt_id, after_seq=0)
        if pending is None:
            return None
        attempt.prompt = pending.content
        try:
            result = self._start_turn(
                session, pending.content,
                include_shell_tools=pending.include_shell_tools,
                attempt=attempt, queued=pending,
            )
        except BaseException:
            if self.store.get_attempt(session_id, attempt.attempt_id) is None:
                self.pending_inputs.release(session_id, pending.input_id)
            raise
        self.pending_inputs.complete(session_id, pending.input_id)
        return result

    def _start_next_input(self, session_id: str) -> None:
        """After a turn ended on its own, let the oldest waiting input start one.

        Never raises: it runs in the finally of the turn that just ended.

        Args:
            session_id: Session ID.
        """
        try:
            if self._shutting_down or not self.pending_inputs.waiting(session_id):
                return
            session = self.store.get_session(session_id)
            if session is None:
                return
            try:
                self._reserve_session(session_id)
            except SessionBusyError:
                return  # Another send started a turn; it takes the queue.
            started = None
            try:
                started = self._start_queued_turn(session)
            finally:
                if started is None:
                    self._release_session(session_id)
        except Exception:  # noqa: BLE001 - the inputs stay queued and listed
            logger.warning("Could not start a turn from the queue of %s", session_id, exc_info=True)

    def _queue_input(
        self,
        session_id: str,
        content: str,
        *,
        running_turn: Optional[str],
        include_shell_tools: bool,
    ) -> Dict[str, Any]:
        """Accept a message for a busy session and announce it.

        Args:
            session_id: Session ID.
            content: The user's message.
            running_turn: The turn running now, which may take it.
            include_shell_tools: The sending request's shell-tool entitlement.

        Returns:
            The queued receipt.
        """
        pending = self.pending_inputs.add(
            session_id, content,
            queued_during=running_turn,
            include_shell_tools=include_shell_tools,
        )
        waiting = self.pending_inputs.waiting(session_id)
        position = next(
            (index for index, item in enumerate(waiting, start=1) if item.input_id == pending.input_id),
            len(waiting),
        )
        self.thread_events.emit(
            session_id, "input.queued",
            {"attempt_id": running_turn, "input_id": pending.input_id,
             "content": content, "position": position},
        )
        return {
            "status": "queued",
            "input_id": pending.input_id,
            "attempt_id": running_turn,
            "position": position,
        }

    def _append_user_row(self, session_id: str, pending: PendingInput, turn_id: Optional[str]) -> Message:
        """Write the display row of a queued input that joined a running turn.

        Args:
            session_id: Session ID.
            pending: The delivered input.
            turn_id: The turn it joined.

        Returns:
            The appended message.
        """
        message = Message(
            session_id=session_id,
            role="user",
            content=pending.content,
            metadata={"queued_input_id": pending.input_id, "delivered_to_attempt_id": turn_id},
        )
        return message

    def _input_joined_turn(self, session_id: str, turn_id: str, pending: PendingInput, item: Any) -> None:
        """Show a queued input that the running turn just took.

        Args:
            session_id: Session ID.
            turn_id: The running turn.
            pending: The input.
            item: Its recorded ``user`` thread item.
        """
        # Publishes the recorded user item (completing the queued live item)
        # before the legacy event.
        self.thread_events.emit(
            session_id, "input.delivered",
            {"attempt_id": turn_id, "input_id": pending.input_id,
             "seq": item.seq},
        )

    def list_pending_inputs(self, session_id: str) -> list[Dict[str, Any]]:
        """Return the messages waiting to join a session, oldest first.

        Args:
            session_id: Session ID.

        Returns:
            Client views of the pending inputs.
        """
        return [item.public() for item in self.pending_inputs.list(session_id)]

    def discard_pending_input(self, session_id: str, input_id: str) -> Optional[Dict[str, Any]]:
        """Remove a waiting message at the user's request.

        Args:
            session_id: Session ID.
            input_id: The input to remove.

        Returns:
            The removed input's view, or None when it is not waiting (unknown,
            or being written into a turn right now).
        """
        removed = self.pending_inputs.discard(session_id, input_id)
        if removed is None:
            return None
        self.thread_events.emit(
            session_id, "input.discarded",
            {"attempt_id": removed.queued_during, "input_id": removed.input_id},
        )
        return removed.public()

    def get_messages(self, session_id: str, limit: int = 100) -> list[Message]:
        """Return the message history."""
        return self.store.get_messages(session_id, limit)

    def cancel_current(self, session_id: str) -> bool:
        """Cancel the currently running AgentLoop for a session.

        Args:
            session_id: Session ID.

        Returns:
            Whether cancellation succeeded. True means an active loop, task,
            swarm run, or owned background task received a cancel signal.
        """
        background_handle = self._background_handles.get(session_id)
        background_cancelled = False
        if background_handle is not None:
            background_cancelled = bool(background_handle.cancel_all().get("requested"))
        loop = self._active_loops.get(session_id)
        if loop is not None:
            loop.cancel()
            # The loop only stops the ReAct cycle; tools that spawned their own
            # background work (swarm) keep burning tokens unless told directly.
            _cancel_session_swarm_runs(session_id)
            return True
        # No loop yet: the run is still building its registry. Cancel the task
        # itself so the claim is released instead of stranding the session.
        task = self._active_tasks.get(session_id)
        if task is not None and not task.done():
            self._user_cancel_requests.add(session_id)
            task.cancel()
            _cancel_session_swarm_runs(session_id)
            return True
        # Loop already returned (budget exhausted, turn ended) but a swarm it
        # started may still be running in the background.
        if _cancel_session_swarm_runs(session_id):
            return True
        return background_cancelled

    async def _run_attempt(self, session: Session, attempt: Attempt, *, include_shell_tools: bool = False) -> None:
        """Execute an Attempt in the background.

        The whole body runs under try/finally: this coroutine owns the
        in-flight claim taken in :meth:`send_message`, and a failure anywhere —
        including in the pre-run bookkeeping below — must not leave the session
        permanently busy.
        """
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
            result = await self._run_with_agent(
                attempt,
                messages=messages,
                include_shell_tools=include_shell_tools,
                session_config=dict(session.config),
            )
            status = result.get("status")
            if status == "success":
                attempt.mark_completed(summary=result.get("content", ""))
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

            reply_content = self._format_result_message(
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
                self.runtime(session.session_id).thread.read(),
                attempt.attempt_id,
                run_dir=attempt.run_dir,
            )
            reports = [entry["artifact"] for entry in prefinish_projection.tool_trail
                       if entry.get("status") == "ok" and isinstance(entry.get("artifact"), dict)]
            if reports:
                reply_metadata["generated_reports"] = reports
                links = [f"[{str(report['filename']).replace('[', '').replace(']', '')}]({report['download_url']})"
                         for report in reports]
                reply_content += "\n\n" + "\n\n".join(dict.fromkeys(links))
            projection = self.runtime(session.session_id).finish_turn(
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
                pending_inputs=(self.list_pending_inputs(session.session_id)
                                if attempt.status == AttemptStatus.CANCELLED else None),
            )
            reply = Message(
                session_id=session.session_id, role="assistant",
                content=reply_content,
                linked_attempt_id=attempt.attempt_id,
                metadata=reply_metadata,
                # Every terminal attempt keeps its steps. A failed run saved an
                # empty trail, so after a reload the history said "0 steps"
                # for a run that made eight rounds of tool calls — hiding the
                # one thing a failure report needs.
                tool_trail=projection.tool_trail,
            )
            if not self._has_projected_user(session.session_id, attempt):
                self._append_projected_user(attempt)
            reports = [entry["artifact"] for entry in reply.tool_trail
                       if entry.get("status") == "ok" and isinstance(entry.get("artifact"), dict)]
            if reports:
                reply.metadata["generated_reports"] = reports
                # Persist and stream the same concrete download links even if
                # the model forgot to include them in its final answer.
                links = [f"[{str(report['filename']).replace('[', '').replace(']', '')}]({report['download_url']})"
                         for report in reports]
                reply.content += "\n\n" + "\n\n".join(dict.fromkeys(links))
            self.store.append_message(reply)
            # The append-only transcript is the user-visible source of truth.
            # Commit it before attempt.json so startup recovery can finish a
            # process interrupted between the two writes.
            self.store.update_attempt(attempt)
            self.store.delete_partial_response(session.session_id, attempt.attempt_id)
            self._search_index.index_message(session.session_id, "assistant", reply.content)
            self.thread_events.sync(session.session_id)

        except asyncio.CancelledError:
            if session.session_id in self._user_cancel_requests:
                # cancel_current() cancels this task when the run has not
                # reached its AgentLoop yet. Keep that explicit user action
                # distinct from event-loop cancellation during server shutdown.
                attempt.mark_cancelled(reason="cancelled by user")
                self._finish_thread_turn_quietly(session.session_id, attempt)
                self.store.update_attempt(attempt)
                self.store.delete_partial_response(
                    session.session_id, attempt.attempt_id
                )
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
            self.store.delete_partial_response(session.session_id, attempt.attempt_id)
            self.thread_events.sync(session.session_id)
        finally:
            if attempt.status != AttemptStatus.COMPLETED:
                background = self._background_handles.get(session.session_id)
                if background is not None:
                    background.cancel_all()
            # The only release path for the claim taken in send_message.
            self._active_tasks.pop(session.session_id, None)
            self._user_cancel_requests.discard(session.session_id)
            self._release_session(session.session_id)
            # A turn that ended on its own hands over to the oldest message
            # sent while it ran. A stop does not: those messages stay queued
            # and are reported with the cancellation.
            if attempt.status in (AttemptStatus.COMPLETED, AttemptStatus.FAILED):
                self._start_next_input(session.session_id)

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

    async def _run_with_agent(
        self,
        attempt: Attempt,
        messages: list = None,
        *,
        include_shell_tools: bool = False,
        session_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an attempt with the V5 AgentLoop.

        The registry and LLM client are built per attempt: the registry binds
        this attempt's event callback, cancel flag and background handle, and
        rebuilding it is how a changed config (MCP servers, tool gates) takes
        effect. What a conversation carries across turns lives in its
        :class:`SessionRuntime` instead.

        Args:
            attempt: Current execution attempt.
            messages: The session's ``messages.jsonl`` rows; read only for
                history recorded before the session had a thread log.
            include_shell_tools: Whether the registry may include shell tools.
            session_config: Optional session-level config overrides. MCP server
                definitions under the ``mcpServers`` key are merged on top of
                the user config file via ``load_runtime_agent_config`` so each
                session can extend or override the global MCP server list.

        Returns:
            Result dictionary containing status, run_dir, run_id, metrics, and related fields.
        """
        from src.tools import build_registry
        from src.tools.background_tools import BackgroundScope, get_background_manager
        from src.session.model_selection import chat_llm_for_session
        from src.agent.loop import AgentLoop
        from src.agent.memory import WorkspaceMemory
        from src.memory.persistent import PersistentMemory
        from src.config.loader import load_runtime_agent_config, sanitize_session_overrides

        llm = chat_llm_for_session(session_config)
        try:
            pm = PersistentMemory()

            session_id = attempt.session_id
            attempt_id = attempt.attempt_id
            loop = asyncio.get_running_loop()
            runtime = self.runtime(session_id)
            checkpoint = ResponseCheckpoint(self.store, attempt, runtime=runtime)

            safe_overrides = sanitize_session_overrides(session_config) if session_config else session_config
            agent_config = load_runtime_agent_config(overrides=safe_overrides)

            def event_callback(event_type: str, data: Dict[str, Any]) -> None:
                """Forward AgentLoop events to the SSE event bus."""
                try:
                    checkpoint.handle_event(event_type, data)
                except OSError as exc:
                    # A checkpoint failure must not hide the live response or stop
                    # the agent. The terminal attempt write still gets a chance.
                    logger.warning(
                        "Could not checkpoint response for attempt %s: %s",
                        attempt_id,
                        exc,
                    )
                data["attempt_id"] = attempt_id
                self.thread_events.emit(session_id, event_type, data)

            def _mcp_collision_warn(msg: str) -> None:
                """Forward MCP server-name collision warnings to the operator event channel."""
                self.event_bus.emit(session_id, "mcp.warning", {"attempt_id": attempt_id, "message": msg})

            # One flag per turn, shared by the AgentLoop and the swarm tool. The
            # loop's own cancel() sets it, so a user stop reaches long-running tools
            # without a second cancellation channel that can drift out of sync.
            turn_cancel = threading.Event()

            # Background tasks belong to the session, not to the attempt: a later
            # attempt must still read what an earlier one started. The attempt id is
            # kept on each task so cancellation can be attributed later.
            background_scope = BackgroundScope(
                owner_id=f"session:{session_id}", attempt_id=attempt_id
            )
            background = get_background_manager(Path(self.runs_dir).parent).for_scope(
                background_scope,
                on_completion=self._publish_background_completion,
            )
            self._background_handles[session_id] = background

            registry = await loop.run_in_executor(
                _AGENT_EXECUTOR,
                lambda: build_registry(
                    persistent_memory=pm,
                    include_shell_tools=include_shell_tools,
                    agent_config=agent_config,
                    session_id=session_id,
                    event_callback=event_callback,
                    warn_callback=_mcp_collision_warn,
                    cancel_event=turn_cancel,
                    background_manager=background,
                    background_scope=background_scope,
                ),
            )

            from src.config.accessor import get_env_config

            recorder = runtime.begin_turn(attempt_id, messages or [])
            queued_inputs = QueuedInputDelivery(
                self.pending_inputs,
                session_id=session_id,
                turn_id=attempt_id,
                recorder=recorder,
                shell_tools=include_shell_tools,
                on_delivered=lambda pending, item: self._input_joined_turn(
                    session_id, attempt_id, pending, item
                ),
            )
            agent = AgentLoop(
                registry=registry,
                llm=llm,
                event_callback=event_callback,
                max_iterations=get_env_config().agent_tuning.vibe_trading_agent_max_iterations,
                persistent_memory=pm,
                cancel_event=turn_cancel,
                background_manager=background,
                thread_recorder=recorder,
                queued_inputs=queued_inputs,
                memory=WorkspaceMemory(session_workspace=str(runtime.workspace_path)),
            )
            self._active_loops[session_id] = agent

            try:
                result = await loop.run_in_executor(
                    _AGENT_EXECUTOR,
                    lambda: agent.run(
                        user_message=attempt.prompt,
                        history=recorder.history or None,
                        session_id=session_id,
                    ),
                )
            except asyncio.CancelledError:
                agent.cancel()
                raise
            finally:
                self._active_loops.pop(session_id, None)
                try:
                    checkpoint.flush()
                except OSError as exc:
                    logger.warning(
                        "Could not flush response checkpoint for attempt %s: %s",
                        attempt_id,
                        exc,
                    )

            result["streamed_text"] = checkpoint.text
            result["usage"] = recorder.usage

            # Load metrics from the run output when available.
            if result.get("run_dir"):
                metrics = self._load_metrics(Path(result["run_dir"]))
                if metrics:
                    result["metrics"] = metrics

            return result
        finally:
            await llm.aclose()

    @staticmethod
    def _load_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
        """Load metrics.csv from a run directory.

        A run's metrics row can carry a non-numeric column (e.g.
        ``benchmark_ticker``) alongside the numeric metrics, so each field is
        converted independently: one unconvertible field is skipped rather
        than discarding every metric in the row.
        """
        import csv
        metrics_path = run_dir / "artifacts" / "metrics.csv"
        if not metrics_path.exists():
            return None
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            return None
        if not rows:
            return None
        metrics: Dict[str, Any] = {}
        for key, value in rows[0].items():
            if not value:
                continue
            try:
                metrics[key] = float(value)
            except (TypeError, ValueError):
                continue
        return metrics or None

    @staticmethod
    def _format_result_message(attempt: Attempt, streamed_text: str = "") -> str:
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
        return f"Execution failed: {attempt.error or 'unknown error'}"
