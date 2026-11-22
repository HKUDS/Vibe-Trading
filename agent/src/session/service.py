"""Session lifecycle orchestration for message flow, attempt creation, and execution scheduling.

The conversation, not the attempt, is the unit: each session has one
:class:`~src.session.runtime.SessionRuntime` whose ``thread.jsonl`` records
every turn in full. A turn's model input is replayed from it, and
display rows are derived from the thread when a consumer requests them.

A caller that opts in (``queue_if_busy``, the web send route) may send while a
turn runs: the message waits in :mod:`src.session.pending_inputs` and joins
the running turn after its current tool batch, or starts the next turn.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.kernel import events as vocabulary
from src.session.attempts import AttemptRunner
from src.session.event_projection import ThreadEvents
from src.session.events import EventBus
from src.session.factory import SessionAgentFactory, compact_recorded_history
from src.session.maintenance import compact_history, fork_completed_turn
from src.session.models import (
    Attempt,
    AttemptStatus,
    Message,
    Principal,
    Session,
    SessionBusyError,
)
from src.session.pending_inputs import (
    PENDING_INPUTS_FILENAME,
    PendingInput,
    PendingInputQueue,
)
from src.session.recovery import recover_interrupted_attempts, recover_pending_inputs
from src.session.runtime import SessionRuntime, SessionRuntimes
from src.session.search import get_shared_index
from src.session.store import SessionStore

if TYPE_CHECKING:
    from src.agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)


def _cancel_session_swarm_runs(session_id: str) -> int:
    """Cancel this session's live swarms, loading the optional worker runtime on demand."""
    try:
        from src.swarm.runtime import cancel_runs_for_session
    except Exception:  # pragma: no cover - swarm extra missing in slim installs
        logger.debug("Swarm runtime unavailable; skipping swarm cancel", exc_info=True)
        return 0
    return cancel_runs_for_session(session_id)


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
        # Reserve synchronously in send_message. The runtime handle arrives after discovery.
        self._active_loops: Dict[str, "AgentRuntime"] = {}
        # A task handle also allows cancellation during registry discovery.
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
        self._runtimes = SessionRuntimes(store.thread_log)
        self._shutting_down = False
        # Durable records live under the runtime root that owns runs_dir, so a
        # test pointing runs_dir at a temp root gets its own isolated store.
        from src.tools.background_tools import init_background_store

        self._background_store = init_background_store(Path(runs_dir).parent)
        # Messages sent while a turn runs, durable per session directory.
        self.pending_inputs = PendingInputQueue(
            lambda session_id: store.thread_path(session_id).parent / PENDING_INPUTS_FILENAME
        )
        self._factory = SessionAgentFactory(
            store=store, event_bus=event_bus, thread_events=self.thread_events,
            runs_dir=runs_dir, runtime=self._runtimes.get, pending_inputs=self.pending_inputs,
            active_loops=self._active_loops, background_handles=self._background_handles,
        )
        self._attempts = AttemptRunner(
            store=store, runtime=self._runtimes.get, thread_events=self.thread_events,
            search_index=self._search_index, list_pending_inputs=self.pending_inputs.public_items,
            user_cancel_requests=self._user_cancel_requests,
        )
        recover_interrupted_attempts(store, self.runtime, self._search_index)
        recover_pending_inputs(store, self.pending_inputs)

    def register_tool(self, tool: Any) -> str:
        """Register one explicit host tool for subsequent attempts."""
        return self._factory.register_tool(tool)

    def runtime(self, session_id: str) -> SessionRuntime:
        """Return the session's runtime, rebuilding it from its thread if needed.

        Args:
            session_id: Session ID.

        Returns:
            The session runtime.
        """
        return self._runtimes.get(session_id)

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

    def fork_session(
        self,
        source_session_id: str,
        turn_id: str,
        *,
        title: str = "",
    ) -> Session:
        """Create an independent session copied through one completed turn.

        The source thread is read once and appended to a fresh log. State
        snapshots are copied only through the selected turn, so identity and
        loaded-tool state cannot include authorisations earned later.
        """
        fork = fork_completed_turn(self.store, source_session_id, turn_id, title)
        self._search_index.index_session(fork.session_id, fork.title)
        self.event_bus.emit(
            fork.session_id,
            "session.forked",
            {
                "session_id": fork.session_id,
                "source_session_id": source_session_id,
                "source_turn_id": turn_id,
            },
        )
        return fork

    def _maintenance_busy(self, session_id: str) -> bool:
        """Return whether a turn or queued input makes maintenance unsafe."""
        with self._inflight_lock:
            if session_id in self._inflight:
                return True
        task = self._active_tasks.get(session_id)
        return bool(
            (task is not None and not task.done())
            or session_id in self._active_loops
            or self.pending_inputs.waiting(session_id)
        )

    async def compact_session(self, session_id: str, focus: str = "") -> Dict[str, Any]:
        """Compact a session's replayed history through the existing L3 path."""
        session = self.store.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        if self._maintenance_busy(session_id):
            raise SessionBusyError(
                "Cannot compact while a turn is running or queued input is waiting"
            )
        compacted = await compact_history(
            session, focus, runtime_for=self.runtime, runs_dir=Path(self.runs_dir),
            compact=compact_recorded_history,
        )
        self.thread_events.sync(session_id)
        self.event_bus.emit(
            session_id,
            "session.compacted",
            {"summary": compacted.get("summary"), "seq": compacted.seq},
        )
        return {
            "session_id": session_id,
            "summary": compacted.get("summary") or "",
            "seq": compacted.seq,
            "focus": focus.strip(),
        }

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
            self._runtimes.discard(session_id)
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
            log = self.store.thread_log(session_id)
            turn_id = message.message_id
            log.append("turn_start", turn_id, prompt="")
            if role == "assistant":
                log.append("assistant", turn_id, content=content, phase="final")
                log.append("turn_end", turn_id, status="completed")
            else:
                log.append("inject", turn_id, role=role, content=content)
                log.append("turn_end", turn_id, status="completed")
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
        if queued is not None:
            attempt.queued_input_id = queued.input_id
        self.store.create_attempt(attempt)
        session.config["include_shell_tools"] = include_shell_tools
        session.last_attempt_id = attempt.attempt_id
        session.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.update_session(session)
        self.thread_events.sync(session_id)
        task = asyncio.create_task(
            self._run_attempt(session, attempt, include_shell_tools=include_shell_tools)
        )
        self._active_tasks[session_id] = task
        return {"message_id": message.message_id, "attempt_id": attempt.attempt_id}

    def _start_queued_turn(self, session: Session) -> Optional[Dict[str, Any]]:
        """Start a turn from the oldest waiting input. The caller holds the claim.

        The input is claimed for the new attempt before anything is written
        and removed from the queue only once that attempt exists, so a crash
        in between is settled by :func:`src.session.recovery.recover_pending_inputs`.

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
            session_id,
            vocabulary.ITEM_STARTED,
            {
                "attempt_id": running_turn,
                "kind": vocabulary.ITEM_STARTED,
                "live_id": f"input:{pending.input_id}",
                "item": {
                    "type": "user",
                    "input_id": pending.input_id,
                    "content": content,
                    "status": "queued",
                    "position": position,
                },
            },
        )
        return {
            "status": "queued",
            "input_id": pending.input_id,
            "attempt_id": running_turn,
            "position": position,
        }

    def list_pending_inputs(self, session_id: str) -> list[Dict[str, Any]]:
        """Return the messages waiting to join a session, oldest first.

        Args:
            session_id: Session ID.

        Returns:
            Client views of the pending inputs.
        """
        return self.pending_inputs.public_items(session_id)

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
        if removed.queued_during:
            self.thread_events.emit(
                session_id,
                vocabulary.ITEM_COMPLETED,
                {
                    "attempt_id": removed.queued_during,
                    "kind": vocabulary.DISCARDED_KIND,
                    "live_id": f"input:{removed.input_id}",
                    "item": {"type": "user", "input_id": removed.input_id, "status": "discarded"},
                },
            )
        return removed.public()

    def get_messages(self, session_id: str, limit: int = 100) -> list[Message]:
        """Return the message history."""
        return self.store.get_messages(session_id, limit)

    def cancel_current(self, session_id: str) -> bool:
        """Cancel the currently running AgentRuntime for a session.

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
        try:
            await self._attempts.run(
                session, attempt, self._factory.run, include_shell_tools=include_shell_tools,
            )
        finally:
            if attempt.status not in (AttemptStatus.COMPLETED, AttemptStatus.WAITING_USER):
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
