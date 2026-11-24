"""Coordinate session leases, input queues, and execution attempts."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

from functools import partial

import asyncio
import copy
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
from src.session.maintenance import compact_history
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


class SessionService:
    """Own the active attempts and durable input queue for a session store."""

    def __init__(
        self,
        store: SessionStore,
        event_bus: EventBus,
        runs_dir: Path,
        *,
        policy: ToolPolicy,
    ) -> None:
        """Initialize the session service."""
        self.policy = policy
        self.store = store
        self.event_bus = event_bus
        self.thread_events = ThreadEvents(event_bus, store.thread_path)
        self.runs_dir = runs_dir
        # Reserve synchronously in send_message. The runtime handle arrives after discovery.
        self._active_loops: Dict[str, "AgentRuntime"] = {}
        # A task handle also allows cancellation during registry discovery.
        self._active_tasks: Dict[str, "asyncio.Task"] = {}
        # Event-loop shutdown must leave the attempt recoverable.
        self._user_cancel_requests: set[str] = set()
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._search_index = get_shared_index()
        self._background_handles: Dict[str, Any] = {}
        self._runtimes = SessionRuntimes(store.thread_log)
        self._shutting_down = False
        # Use the run directory's runtime root to isolate stores.
        from src.tools.background_tools import init_background_store

        self._background_store = init_background_store(Path(runs_dir).parent)
        self.pending_inputs = PendingInputQueue(
            lambda session_id: store.thread_path(session_id).parent / PENDING_INPUTS_FILENAME
        )
        self._factory = SessionAgentFactory(
            policy=policy,
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
        """Return the session's runtime, rebuilding it from its thread if needed."""
        return self._runtimes.get(session_id)

    def _reserve_session(self, session_id: str) -> None:
        """Claim a session for one in-flight run."""
        with self._inflight_lock:
            if self._shutting_down:
                raise SessionBusyError("shutting down; no new runs are accepted")
            if session_id in self._inflight:
                raise SessionBusyError(
                    f"Session {session_id} already has a run in progress"
                )
            self._inflight.add(session_id)

    def shutdown(self, *, timeout: float = 5.0) -> list[str]:
        """Stop accepting work, cancel owned background work, and wait for reaping."""
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
            # Closing the process-wide task table would stop unrelated sessions.
            pending.extend(background.cancel_all(timeout=remaining)["pending"])
        return pending

    def _release_session(self, session_id: str) -> None:
        """Release a session claim. Safe to call when no claim is held."""
        with self._inflight_lock:
            self._inflight.discard(session_id)

    def create_session(
        self,
        title: str = "",
        config: Optional[Dict[str, Any]] = None,
        owner: Optional["Principal"] = None,
    ) -> Session:
        """Create a new session."""
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
        source = self.store.get_session(source_session_id)
        if source is None:
            raise ValueError(f"Session {source_session_id} not found")
        source_items = self.store.thread_log(source_session_id).read()
        turn_items = [item for item in source_items if item.turn_id == turn_id]
        if not any(item.type == "turn_start" for item in turn_items):
            raise ValueError(f"Turn {turn_id} not found in session {source_session_id}")
        end = next((item for item in turn_items if item.type == "turn_end"), None)
        if end is None:
            raise SessionBusyError("Cannot fork from a turn that is still running")
        if end.get("status") != "completed":
            raise ValueError(f"Turn {turn_id} is not completed")
        copied = [item for item in source_items if item.seq <= end.seq]
        fork = Session(
            title=title or f"{source.title or source_session_id} (fork)",
            config=copy.deepcopy(source.config),
            owner=source.owner,
            forked_from_session_id=source_session_id,
            forked_from_turn_id=turn_id,
        )
        self.store.create_session(fork)
        target_log = self.store.thread_log(fork.session_id)
        workspace_dir = str(target_log.path.parent / "workspace")
        try:
            for item in copied:
                payload = copy.deepcopy(item.data)
                if item.type == "state":
                    payload["workspace_dir"] = workspace_dir
                    payload["workspace"] = workspace_dir
                target_log.append(item.type, item.turn_id, **payload)
        except BaseException:
            self.store.delete_session(fork.session_id)
            raise
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
            compact=partial(compact_recorded_history, policy=self.policy), policy=self.policy,
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
        """Delete an idle session after purging its searchable text."""
        with self._inflight_lock:
            if session_id in self._inflight:
                raise SessionBusyError("Stop the active run before deleting its session")
            # Retry stale index cleanup even if the session directory is gone.
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
        """Accept a message and start or queue a user turn.

        Args:
            include_shell_tools: Shell entitlement of the sending request.
            queue_if_busy: Durably enqueue instead of refusing a busy session.

        Returns:
            A message/attempt receipt or a queued receipt with a 1-based position.

        Raises:
            ValueError: The session is missing.
            SessionBusyError: The service is shutting down or the session cannot accept the request.
            PendingInputLimitError: The durable queue is full.
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
            else:
                log.append("inject", turn_id, role=role, content=content)
            log.append("turn_end", turn_id, status="completed")
            self._search_index.index_message(session_id, role, content)
            self.event_bus.emit(session_id, "message.received", {"message_id": message.message_id, "role": role, "content": content})
            return {"message_id": message.message_id}

        # Claim before persisting so concurrent sends cannot both start attempts.
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
        """Record the user message and schedule its turn."""
        session_id = session.session_id
        message = Message(
            session_id=session_id,
            role="user",
            content=content,
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
        """Start a turn from the oldest waiting input. The caller holds the claim."""
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
        """After a turn ended on its own, let the oldest waiting input start one."""
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
        """Accept a message for a busy session and announce it."""
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
        """Return the messages waiting to join a session, oldest first."""
        return self.pending_inputs.public_items(session_id)

    def discard_pending_input(self, session_id: str, input_id: str) -> Optional[Dict[str, Any]]:
        """Remove a waiting message at the user's request."""
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
            Whether cancellation succeeded. True means an active loop, in-flight task,
            or owned background task received a cancel signal.
        """
        background_handle = self._background_handles.get(session_id)
        background_cancelled = False
        if background_handle is not None:
            background_cancelled = bool(background_handle.cancel_all().get("requested"))
        loop = self._active_loops.get(session_id)
        if loop is not None:
            loop.cancel()
            return True
        # Cancel discovery itself if the runtime does not exist yet.
        task = self._active_tasks.get(session_id)
        if task is not None and not task.done():
            self._user_cancel_requests.add(session_id)
            task.cancel()
            return True
        return background_cancelled

    async def _run_attempt(self, session: Session, attempt: Attempt, *, include_shell_tools: bool = False) -> None:
        """Execute an Attempt in the background."""
        try:
            await self._attempts.run(
                session, attempt, self._factory.run, include_shell_tools=include_shell_tools,
            )
        finally:
            if attempt.status not in (AttemptStatus.COMPLETED, AttemptStatus.WAITING_USER):
                background = self._background_handles.get(session.session_id)
                if background is not None:
                    background.cancel_all()
            self._active_tasks.pop(session.session_id, None)
            self._user_cancel_requests.discard(session.session_id)
            self._release_session(session.session_id)
            # Leave waiting inputs queued after an explicit stop.
            if attempt.status in (AttemptStatus.COMPLETED, AttemptStatus.FAILED):
                self._start_next_input(session.session_id)
