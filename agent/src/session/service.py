"""Session lifecycle orchestration for message flow, attempt creation, and execution scheduling.

The conversation, not the attempt, is the unit: each session has one
:class:`~src.session.runtime.SessionRuntime` whose ``thread.jsonl`` records
every turn in full. A turn's model input is replayed from it, and the
``messages.jsonl`` display row is projected from it when the turn ends.
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
from src.session.thread import TurnProjection

if TYPE_CHECKING:
    from src.agent.loop import AgentLoop

# Dedicated thread pool limited to four concurrent agents to avoid exhausting the default executor.
_AGENT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")
logger = logging.getLogger(__name__)


#: Terminal attempt status -> SSE event name. Cancellation is its own event so
#: the UI can distinguish a user stop from a failure, both live and on reload.
_TERMINAL_EVENTS = {
    "completed": "attempt.completed",
    "cancelled": "attempt.cancelled",
    "failed": "attempt.failed",
}

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

    One AgentLoop per session: a second concurrent send is rejected rather
    than queued, because two loops writing the same session would interleave
    their messages and attempts. Callers surface this as HTTP 409 so the user
    can wait for the running attempt or cancel it first.
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
        # Every event of a running turn is published through this, so item
        # and run events derived from thread.jsonl precede the legacy event.
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
        self._recover_interrupted_attempts()

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
    ) -> Dict[str, Any]:
        """Send a message to a session and trigger execution.

        Args:
            session_id: Session ID.
            content: Message content.
            role: Message role.
            include_shell_tools: Whether this attempt may use shell tools.

        Returns:
            Dictionary containing message_id and attempt_id.

        Raises:
            ValueError: If the session does not exist.
            SessionBusyError: If the session already has a run in progress.
                Callers surface this as HTTP 409; the user can wait for the
                running attempt or cancel it first.
        """
        session = self.store.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        if self._shutting_down:
            raise SessionBusyError("shutting down; no new runs are accepted")

        # Claim the session before persisting anything. Reserving after the
        # user message is appended (or relying on _active_loops, which is only
        # populated once the registry is built) lets two concurrent sends both
        # store a message and create an attempt.
        if role == "user":
            self._reserve_session(session_id)
        handed_off = False

        try:
            message = Message(session_id=session_id, role=role, content=content)
            self.store.append_message(message)
            self._search_index.index_message(session_id, role, content)
            self.event_bus.emit(session_id, "message.received", {"message_id": message.message_id, "role": role, "content": content})

            if role != "user":
                return {"message_id": message.message_id}

            attempt = Attempt(session_id=session_id, parent_attempt_id=session.last_attempt_id, prompt=content)
            self.store.create_attempt(attempt)
            session.config["include_shell_tools"] = include_shell_tools
            session.last_attempt_id = attempt.attempt_id
            session.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.update_session(session)
            # Through thread_events: the session's thread is read from here on,
            # before this turn records anything.
            self.thread_events.emit(session_id, "attempt.created", {"attempt_id": attempt.attempt_id, "prompt": content})

            task = asyncio.create_task(
                self._run_attempt(session, attempt, include_shell_tools=include_shell_tools)
            )
            self._active_tasks[session_id] = task
            # _run_attempt now owns the claim and releases it in its finally.
            handed_off = True
            return {"message_id": message.message_id, "attempt_id": attempt.attempt_id}
        finally:
            if role == "user" and not handed_off:
                self._release_session(session_id)

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
            # so it survives the event ring buffer that first announced it.
            wall_started_at = attempt.started_at or time.time()
            self.store.update_attempt(attempt)
            self.event_bus.emit(
                session.session_id,
                "attempt.started",
                {"attempt_id": attempt.attempt_id, "started_at": wall_started_at},
            )
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

            reply_metadata = {}
            if attempt.run_dir:
                reply_metadata["run_id"] = Path(attempt.run_dir).name
            reply_metadata["status"] = attempt.status.value
            if attempt.metrics:
                reply_metadata["metrics"] = attempt.metrics
            reply_metadata["elapsed_ms"] = max(0, round((time.perf_counter() - started_at) * 1000))
            # turn_end first: the display row below is projected from it.
            projection = self.runtime(session.session_id).finish_turn(
                attempt.attempt_id,
                prompt=attempt.prompt,
                status=attempt.status.value,
                usage=result.get("usage"),
                elapsed_ms=reply_metadata["elapsed_ms"],
                run_dir=attempt.run_dir,
            )
            reply_metadata["started_at"] = wall_started_at
            runtime_keys = (
                "provider",
                "configured_model",
                "model",
                "model_source",
                "reasoning_effort",
            )
            for key in runtime_keys:
                value = result.get(key)
                if value is not None:
                    reply_metadata[key] = value

            reply = Message(
                session_id=session.session_id, role="assistant",
                content=self._format_result_message(
                    attempt, streamed_text=result.get("streamed_text") or ""
                ),
                linked_attempt_id=attempt.attempt_id,
                metadata=reply_metadata,
                # Every terminal attempt keeps its steps. A failed run saved an
                # empty trail, so after a reload the history said "0 steps"
                # for a run that made eight rounds of tool calls — hiding the
                # one thing a failure report needs.
                tool_trail=projection.tool_trail,
            )
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
            self.thread_events.emit(
                session.session_id,
                _TERMINAL_EVENTS.get(attempt.status.value, "attempt.failed"),
                {"attempt_id": attempt.attempt_id, "status": attempt.status.value,
                 "summary": reply.content, "error": attempt.error, "run_dir": attempt.run_dir,
                 "started_at": wall_started_at, "ended_at": time.time(),
                 **{key: reply_metadata[key] for key in ("elapsed_ms", *runtime_keys) if key in reply_metadata}},
            )

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
                self.thread_events.emit(
                    session.session_id,
                    "attempt.cancelled",
                    {"attempt_id": attempt.attempt_id, "status": attempt.status.value},
                )
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
            self.thread_events.emit(session.session_id, "attempt.failed", {"attempt_id": attempt.attempt_id, "error": str(exc)})
        finally:
            if attempt.status != AttemptStatus.COMPLETED:
                background = self._background_handles.get(session.session_id)
                if background is not None:
                    background.cancel_all()
            # The only release path for the claim taken in send_message.
            self._active_tasks.pop(session.session_id, None)
            self._user_cancel_requests.discard(session.session_id)
            self._release_session(session.session_id)

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
        from src.providers.chat import ChatLLM
        from src.agent.loop import AgentLoop
        from src.memory.persistent import PersistentMemory
        from src.config.loader import load_runtime_agent_config, sanitize_session_overrides

        llm = ChatLLM()
        try:
            pm = PersistentMemory()

            session_id = attempt.session_id
            attempt_id = attempt.attempt_id
            loop = asyncio.get_running_loop()
            checkpoint = ResponseCheckpoint(self.store, attempt)

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

            recorder = self.runtime(session_id).begin_turn(attempt_id, messages or [])
            agent = AgentLoop(
                registry=registry,
                llm=llm,
                event_callback=event_callback,
                max_iterations=get_env_config().agent_tuning.vibe_trading_agent_max_iterations,
                persistent_memory=pm,
                cancel_event=turn_cancel,
                background_manager=background,
                thread_recorder=recorder,
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
