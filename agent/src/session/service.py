"""Session lifecycle orchestration for message flow, attempt creation, and execution scheduling.

V5: Uses AgentLoop instead of the fixed pipeline behind the generate skill.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.session.events import EventBus
from src.session.models import (
    Attempt,
    AttemptStatus,
    Message,
    Principal,
    Session,
)
from src.session.search import get_shared_index
from src.session.store import SessionStore

if TYPE_CHECKING:
    from src.agent.loop import AgentLoop

# Dedicated thread pool limited to four concurrent agents to avoid exhausting the default executor.
_AGENT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")


#: Terminal attempt status -> SSE event name. Cancellation is its own event so
#: the UI can distinguish a user stop from a failure, both live and on reload.
_TERMINAL_EVENTS = {
    "completed": "attempt.completed",
    "cancelled": "attempt.cancelled",
    "failed": "attempt.failed",
}


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
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._search_index = get_shared_index()

    def _reserve_session(self, session_id: str) -> None:
        """Claim a session for one in-flight run.

        Args:
            session_id: Session to claim.

        Raises:
            SessionBusyError: If the session is already claimed.
        """
        with self._inflight_lock:
            if session_id in self._inflight:
                raise SessionBusyError(
                    f"Session {session_id} already has a run in progress"
                )
            self._inflight.add(session_id)

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

    def list_sessions(self, limit: int = 50) -> list[Session]:
        """List all sessions."""
        return self.store.list_sessions(limit)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        self.event_bus.clear(session_id)
        return self.store.delete_session(session_id)

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
            session.updated_at = datetime.now().isoformat()
            self.store.update_session(session)
            self.event_bus.emit(session_id, "attempt.created", {"attempt_id": attempt.attempt_id, "prompt": content})

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
            Whether cancellation succeeded. True means an active loop existed and received a cancel signal.
        """
        loop = self._active_loops.get(session_id)
        if loop is not None:
            loop.cancel()
            return True
        # No loop yet: the run is still building its registry. Cancel the task
        # itself so the claim is released instead of stranding the session.
        task = self._active_tasks.get(session_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

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
            self.store.update_attempt(attempt)
            self.event_bus.emit(session.session_id, "attempt.started", {"attempt_id": attempt.attempt_id})
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

            self.store.update_attempt(attempt)
            reply_metadata = {}
            if attempt.run_dir:
                reply_metadata["run_id"] = Path(attempt.run_dir).name
            reply_metadata["status"] = attempt.status.value
            if attempt.metrics:
                reply_metadata["metrics"] = attempt.metrics
            reply_metadata["elapsed_ms"] = max(0, round((time.perf_counter() - started_at) * 1000))
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
                content=self._format_result_message(attempt),
                linked_attempt_id=attempt.attempt_id,
                metadata=reply_metadata,
                tool_trail=(
                    result.get("tool_trail", [])
                    if attempt.status == AttemptStatus.COMPLETED
                    else []
                ),
            )
            self.store.append_message(reply)
            self._search_index.index_message(session.session_id, "assistant", reply.content)
            self.event_bus.emit(
                session.session_id,
                _TERMINAL_EVENTS.get(attempt.status.value, "attempt.failed"),
                {"attempt_id": attempt.attempt_id, "status": attempt.status.value,
                 "summary": attempt.summary, "error": attempt.error, "run_dir": attempt.run_dir,
                 **{key: reply_metadata[key] for key in ("elapsed_ms", *runtime_keys) if key in reply_metadata}},
            )

        except asyncio.CancelledError:
            # cancel_current() cancels this task when the run has not reached
            # its AgentLoop yet. CancelledError is a BaseException, so it would
            # slip past the handler below and leave the attempt stuck RUNNING.
            attempt.mark_cancelled(reason="cancelled by user")
            self.store.update_attempt(attempt)
            self.event_bus.emit(
                session.session_id,
                "attempt.cancelled",
                {"attempt_id": attempt.attempt_id, "status": attempt.status.value},
            )
            raise
        except Exception as exc:
            attempt.mark_failed(error=str(exc))
            self.store.update_attempt(attempt)
            self.event_bus.emit(session.session_id, "attempt.failed", {"attempt_id": attempt.attempt_id, "error": str(exc)})
        finally:
            # The only release path for the claim taken in send_message.
            self._active_tasks.pop(session.session_id, None)
            self._release_session(session.session_id)

    async def _run_with_agent(
        self,
        attempt: Attempt,
        messages: list = None,
        *,
        include_shell_tools: bool = False,
        session_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an attempt with the V5 AgentLoop.

        Args:
            attempt: Current execution attempt.
            messages: Session message history.
            include_shell_tools: Whether the registry may include shell tools.
            session_config: Optional session-level config overrides. MCP server
                definitions under the ``mcpServers`` key are merged on top of
                the user config file via ``load_runtime_agent_config`` so each
                session can extend or override the global MCP server list.

        Returns:
            Result dictionary containing status, run_dir, run_id, metrics, and related fields.
        """
        from src.tools import build_registry
        from src.providers.chat import ChatLLM
        from src.agent.loop import AgentLoop
        from src.memory.persistent import PersistentMemory
        from src.config.loader import load_runtime_agent_config, sanitize_session_overrides

        llm = ChatLLM()
        pm = PersistentMemory()

        session_id = attempt.session_id
        attempt_id = attempt.attempt_id
        loop = asyncio.get_running_loop()
        tool_trail: list[Dict[str, Any]] = []

        safe_overrides = sanitize_session_overrides(session_config) if session_config else session_config
        agent_config = load_runtime_agent_config(overrides=safe_overrides)

        def event_callback(event_type: str, data: Dict[str, Any]) -> None:
            """Forward AgentLoop events to the SSE event bus."""
            if event_type in {"tool_call", "tool_result"}:
                self._record_tool_trail_event(tool_trail, event_type, data)
            data["attempt_id"] = attempt_id
            self.event_bus.emit(session_id, event_type, data)

        def _mcp_collision_warn(msg: str) -> None:
            """Forward MCP server-name collision warnings to the operator event channel."""
            self.event_bus.emit(session_id, "mcp.warning", {"attempt_id": attempt_id, "message": msg})

        registry = await loop.run_in_executor(
            _AGENT_EXECUTOR,
            lambda: build_registry(
                persistent_memory=pm,
                include_shell_tools=include_shell_tools,
                agent_config=agent_config,
                session_id=session_id,
                event_callback=event_callback,
                warn_callback=_mcp_collision_warn,
            ),
        )

        agent = AgentLoop(
            registry=registry,
            llm=llm,
            event_callback=event_callback,
            max_iterations=50,
            persistent_memory=pm,
        )
        self._active_loops[session_id] = agent

        # Build the message history context.
        history = self._convert_messages_to_history(messages) if messages else None

        try:
            result = await loop.run_in_executor(
                _AGENT_EXECUTOR,
                lambda: agent.run(
                    user_message=attempt.prompt,
                    history=history,
                    session_id=session_id,
                ),
            )
        finally:
            self._active_loops.pop(session_id, None)

        result["tool_trail"] = tool_trail

        # Load metrics from the run output when available.
        if result.get("run_dir"):
            metrics = self._load_metrics(Path(result["run_dir"]))
            if metrics:
                result["metrics"] = metrics

        return result

    @staticmethod
    def _record_tool_trail_event(
        tool_trail: list[Dict[str, Any]],
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Consolidate live tool events into a compact history record.

        Args:
            tool_trail: Mutable per-attempt trail.
            event_type: Agent event type (`tool_call` or `tool_result`).
            data: Already-redacted live event payload.
        """
        tool = str(data.get("tool") or "")
        if not tool:
            return

        call_id_value = data.get("call_id")
        call_id = call_id_value if isinstance(call_id_value, str) and call_id_value else None

        if event_type == "tool_call":
            entry: Dict[str, Any] = {
                "tool": tool,
                "status": "running",
                "arguments": (
                    dict(data["arguments"])
                    if isinstance(data.get("arguments"), dict)
                    else {}
                ),
                "timestamp": int(time.time() * 1000),
            }
            if call_id:
                entry["call_id"] = call_id
            tool_trail.append(entry)
            return

        match = None
        if call_id:
            match = next(
                (
                    entry
                    for entry in tool_trail
                    if entry.get("call_id") == call_id
                    and entry.get("status") == "running"
                ),
                None,
            )
        if match is None:
            match = next(
                (
                    entry
                    for entry in tool_trail
                    if entry.get("tool") == tool
                    and entry.get("status") == "running"
                ),
                None,
            )
        if match is None:
            match = {
                "tool": tool,
                "arguments": {},
                "timestamp": int(time.time() * 1000),
            }
            tool_trail.append(match)

        match["status"] = "ok" if data.get("status") == "ok" else "error"
        elapsed_ms = data.get("elapsed_ms")
        if isinstance(elapsed_ms, (int, float)) and not isinstance(elapsed_ms, bool):
            match["elapsed_ms"] = max(0, int(elapsed_ms))
        match["preview"] = str(data.get("preview") or "")
        if call_id:
            match["call_id"] = call_id

    @staticmethod
    def _convert_messages_to_history(messages: list) -> list[Dict[str, Any]]:
        """Convert Session messages into OpenAI-format history.

        Keeps the readable ``[prev_run: {run_id}]`` marker instead of removing it
        completely, and trims by character budget instead of a hard six-message cap
        so the LLM can still see previous artifact paths and strategy content during
        iterative updates.

        Args:
            messages: Session message list without the current turn.

        Returns:
            OpenAI-format messages trimmed from the newest items within the token budget.
        """
        import re
        from pathlib import Path

        def _shorten_run_dir(match: re.Match) -> str:
            path_str = match.group(0).replace("Run directory:", "").strip()
            run_id = Path(path_str).name if path_str else ""
            return f"[prev_run: {run_id}]" if run_id else ""

        history = []
        for msg in messages[:-1]:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if not content.strip() or role not in ("user", "assistant"):
                continue
            content = re.sub(r"Run directory:\s*\S+", _shorten_run_dir, content).strip()
            if content:
                history.append({"role": role, "content": content})

        # Trim from the newest messages within a character budget of roughly 3000 tokens.
        MAX_HISTORY_CHARS = 12000
        total_chars = 0
        trimmed: list = []
        for msg in reversed(history):
            content = msg.get("content", "")
            remaining = MAX_HISTORY_CHARS - total_chars
            if len(content) <= remaining:
                trimmed.append(msg)
                total_chars += len(content)
                continue
            # A single oversized message must not wipe the whole window: when
            # nothing has been kept yet, the newest turn survives truncated
            # rather than the agent starting with no history at all.
            if not trimmed:
                trimmed.append({**msg, "content": content[:remaining] + "\n[... truncated]"})
            break
        return list(reversed(trimmed))

    @staticmethod
    def _load_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
        """Load metrics.csv from a run directory."""
        import csv
        metrics_path = run_dir / "artifacts" / "metrics.csv"
        if not metrics_path.exists():
            return None
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                if rows:
                    return {k: float(v) for k, v in rows[0].items() if v}
        except Exception:
            pass
        return None

    @staticmethod
    def _format_result_message(attempt: Attempt) -> str:
        """Format the final execution result message.

        Args:
            attempt: The terminal attempt.

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
            return "Run cancelled."
        return f"Execution failed: {attempt.error or 'unknown error'}"
