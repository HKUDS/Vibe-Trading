"""Client, stream handle and session records of the embeddable facade.

The client owns exactly one :class:`src.session.service.SessionService` and
reaches the kernel only through its public methods, the same calls the HTTP
session routes make, so every guard on that path (session claim, shell-tool
policy, mandate gate, grounding, budgets) applies unchanged.
"""

from __future__ import annotations

import asyncio
import copy
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, AsyncIterator, Callable, Dict, List, Mapping, Optional, Union

from src.session.events import EventBus, SSEEvent
from src.session.service import SessionBusyError, SessionService
from src.session.store import SessionStore
from vibe_trading._mapping import translate
from vibe_trading.events import TERMINAL_EVENTS, Event, RunResult


class RuntimeRootInUseError(RuntimeError):
    """Raised when another live session service already owns a runtime root.

    ``SessionService`` marks every pending or running attempt it finds on disk
    as interrupted when it is constructed, so a second service over the same
    sessions directory would interrupt the first one's in-flight runs.
    """


class SessionNotFoundError(LookupError):
    """Raised when a session id does not exist under the client's root."""


class ClientClosedError(RuntimeError):
    """Raised when a closed client is used, or closes under an open stream."""


@dataclass(frozen=True)
class ClientSettings:
    """Settings for :class:`Client`.

    Attributes:
        runtime_root: Runtime root holding ``sessions/`` and ``runs/``. The
            kernel binds its run and trace directories when ``src`` is first
            imported (``VIBE_TRADING_HOME``, else ``~/.vibe-trading``), so a
            root other than that one is refused rather than splitting one
            run's state across two roots. ``None`` uses the kernel's root.
        include_shell_tools: Whether runs may use shell tools (``bash``,
            ``background_run``, ``cancel_background``). Off by default, as on
            the HTTP API.
    """

    runtime_root: Optional[Path] = None
    include_shell_tools: bool = False


@dataclass(frozen=True)
class SessionInfo:
    """A stored chat session."""

    session_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    last_attempt_id: Optional[str]


@dataclass(frozen=True)
class MessageInfo:
    """A stored transcript message.

    Attributes:
        attempt_id: Run this message is the reply of, for assistant replies.
        metadata: Read-only copy of the stored reply metadata (status,
            provider, model, run_id, elapsed_ms ...).
    """

    message_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    attempt_id: Optional[str]
    metadata: Mapping[str, Any]


# Sessions directories owned by a live client in this process. Keyed by the
# resolved path so two spellings of one directory collide.
_CLAIMED_ROOTS: Dict[Path, "Client"] = {}
_CLAIM_LOCK = threading.Lock()


def _kernel_root() -> tuple[Path, Path]:
    """Return the runs and sessions directories the kernel's AgentLoop writes."""
    from src.agent import loop as agent_loop

    return Path(agent_loop.RUNS_DIR), Path(agent_loop.SESSIONS_DIR)


def _api_service_sessions_dirs() -> List[Path]:
    """Return sessions directories of HTTP-server services alive in this process.

    Only reads modules already imported; it never starts the HTTP runtime.
    """
    dirs = []
    for module_name in ("api_server", "src.api.state"):
        module = sys.modules.get(module_name)
        service = getattr(module, "_session_service", None) if module else None
        base_dir = getattr(getattr(service, "store", None), "base_dir", None)
        if base_dir is not None:
            dirs.append(Path(base_dir).resolve())
    return dirs


class Stream:
    """Handle on one run started by :meth:`Client.send`.

    Iterate it (once) for typed events; the last event is always one of
    ``RunCompleted`` / ``RunFailed`` / ``RunCancelled``. :meth:`wait` returns
    the final :class:`RunResult` whether or not the events were iterated.
    """

    def __init__(
        self,
        *,
        session_id: str,
        loop: asyncio.AbstractEventLoop,
        cancel: Callable[[str], bool],
        on_done: Callable[["Stream"], None],
    ) -> None:
        self._session_id = session_id
        self._loop = loop
        self._cancel = cancel
        self._on_done = on_done
        self._attempt_id: Optional[str] = None
        self._early: List[SSEEvent] = []
        self._queue: "asyncio.Queue[Union[Event, BaseException]]" = asyncio.Queue()
        self._result: "asyncio.Future[RunResult]" = loop.create_future()
        self._iterating = False

    @property
    def session_id(self) -> str:
        """Session the run belongs to."""
        return self._session_id

    @property
    def attempt_id(self) -> Optional[str]:
        """Kernel attempt id of the run."""
        return self._attempt_id

    @property
    def done(self) -> bool:
        """Whether the run has ended (or the client closed under it)."""
        return self._result.done()

    def _bind(self, attempt_id: str) -> None:
        self._attempt_id = attempt_id
        early, self._early = self._early, []
        for event in early:
            self._deliver(event)

    def _deliver(self, event: SSEEvent) -> None:
        """Translate one kernel event on the loop thread."""
        if self._result.done():
            return
        if self._attempt_id is None:
            self._early.append(event)
            return
        if event.data.get("attempt_id") != self._attempt_id:
            return
        public = translate(event.event_type, self._session_id, self._attempt_id, event.data)
        if public is None:
            return
        self._queue.put_nowait(public)
        if isinstance(public, TERMINAL_EVENTS):
            self._result.set_result(public.result)
            self._on_done(self)

    def _abort(self, error: BaseException) -> None:
        if self._result.done():
            return
        self._result.set_exception(error)
        # Retrieved here so an un-awaited stream does not log "exception was
        # never retrieved"; wait() still raises it.
        self._result.exception()
        self._queue.put_nowait(error)
        self._on_done(self)

    def __aiter__(self) -> AsyncIterator[Event]:
        if self._iterating:
            raise RuntimeError("a Stream can be iterated only once")
        self._iterating = True
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Event]:
        while True:
            item = await self._queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item
            if isinstance(item, TERMINAL_EVENTS):
                return

    async def wait(self) -> RunResult:
        """Wait for the run to end.

        Returns:
            The run's final result.

        Raises:
            ClientClosedError: The client closed before the run ended; the
                attempt is left for the kernel's restart recovery.
        """
        return await asyncio.shield(self._result)

    async def cancel(self) -> bool:
        """Ask the kernel to stop this run.

        Returns:
            Whether a cancel signal was delivered. False once the run ended,
            so a finished stream can never stop a later run of its session.
        """
        if self._result.done():
            return False
        return self._cancel(self._session_id)


class Client:
    """Embeddable entry point to the Vibe-Trading agent kernel.

    One client owns one ``SessionService`` for its runtime root. A second
    client (or an in-process HTTP server's service) on the same root raises
    :class:`RuntimeRootInUseError` instead of sharing it, because each
    service's construction interrupts the attempts it finds running; close
    the first client to release the root. Another *process* on the same root
    is not detected.

    Use it inside a running event loop; ``async with Client() as client``
    closes it on exit.
    """

    def __init__(self, settings: Optional[ClientSettings] = None) -> None:
        """Claim the runtime root and construct its session service.

        Args:
            settings: Client settings; defaults to :class:`ClientSettings`.

        Raises:
            ValueError: ``settings.runtime_root`` is not the kernel's root.
            RuntimeRootInUseError: Another live service owns the root.
        """
        self._settings = settings or ClientSettings()
        runs_dir, sessions_dir = _kernel_root()
        root = Path(self._settings.runtime_root or runs_dir.parent).expanduser()
        if (root / "runs").resolve() != runs_dir.resolve() or (
            root / "sessions"
        ).resolve() != sessions_dir.resolve():
            raise ValueError(
                f"runtime_root {root} is not the kernel's runtime root "
                f"(runs: {runs_dir}, sessions: {sessions_dir}); set "
                "VIBE_TRADING_HOME before the first import instead"
            )
        self._root = root
        self._claim = (root / "sessions").resolve()
        with _CLAIM_LOCK:
            if self._claim in _CLAIMED_ROOTS:
                raise RuntimeRootInUseError(
                    f"a vibe_trading Client already owns {self._claim}; close it first"
                )
            if self._claim in _api_service_sessions_dirs():
                raise RuntimeRootInUseError(
                    f"the HTTP server's session service in this process owns {self._claim}"
                )
            _CLAIMED_ROOTS[self._claim] = self
        try:
            self._service = SessionService(
                store=SessionStore(base_dir=root / "sessions"),
                event_bus=EventBus(),
                runs_dir=root / "runs",
            )
        except BaseException:
            self._release()
            raise
        self._listeners: Dict[Stream, Callable[[SSEEvent], None]] = {}
        self._closed = False

    @property
    def runtime_root(self) -> Path:
        """Runtime root this client owns."""
        return self._root

    @property
    def settings(self) -> ClientSettings:
        """Settings the client was created with."""
        return self._settings

    def _release(self) -> None:
        with _CLAIM_LOCK:
            if _CLAIMED_ROOTS.get(self._claim) is self:
                del _CLAIMED_ROOTS[self._claim]

    def _check_open(self) -> None:
        if self._closed:
            raise ClientClosedError("this Client is closed")

    def _require_session(self, session_id: str) -> None:
        if self._service.get_session(session_id) is None:
            raise SessionNotFoundError(f"session {session_id} not found")

    async def create_session(self, title: str = "") -> SessionInfo:
        """Create a session.

        Args:
            title: Session title.

        Returns:
            The created session.
        """
        self._check_open()
        session = self._service.create_session(title=title)
        return _session_info(session)

    async def list_sessions(self, limit: int = 50) -> List[SessionInfo]:
        """List stored sessions, most recent first.

        Args:
            limit: Maximum number of sessions.

        Returns:
            The sessions.
        """
        self._check_open()
        return [_session_info(session) for session in self._service.list_sessions(limit)]

    async def get_messages(self, session_id: str, limit: int = 100) -> List[MessageInfo]:
        """Return a session's transcript in chronological order.

        Args:
            session_id: Session id.
            limit: Maximum number of most recent messages.

        Returns:
            The messages.

        Raises:
            SessionNotFoundError: The session does not exist.
        """
        self._check_open()
        self._require_session(session_id)
        return [_message_info(message) for message in self._service.get_messages(session_id, limit)]

    async def delete_session(self, session_id: str) -> bool:
        """Delete an idle session, its search rows and its research goals.

        Args:
            session_id: Session id.

        Returns:
            Whether the session existed and was deleted.

        Raises:
            SessionBusyError: The session has a run in progress.
        """
        self._check_open()
        deleted = self._service.delete_session(session_id)
        if deleted:
            # The HTTP delete route clears the session's goals the same way.
            from src.goal import GoalStore

            GoalStore().delete_session_goals(session_id)
        return deleted

    async def send(self, session_id: str, text: str) -> Stream:
        """Send a user message and start a run.

        Args:
            session_id: Session id.
            text: User message.

        Returns:
            A handle on the started run.

        Raises:
            SessionNotFoundError: The session does not exist.
            SessionBusyError: The session already has a run in progress.
        """
        self._check_open()
        self._require_session(session_id)
        loop = asyncio.get_running_loop()
        stream = Stream(
            session_id=session_id,
            loop=loop,
            cancel=self._service.cancel_current,
            on_done=self._stream_done,
        )

        def listener(event: SSEEvent) -> None:
            # Runs on the publishing thread: only schedule, never translate.
            if event.session_id != session_id:
                return
            try:
                loop.call_soon_threadsafe(stream._deliver, event)
            except RuntimeError:
                pass  # The embedding event loop is closed.

        self._listeners[stream] = listener
        self._service.event_bus.add_listener(listener)
        try:
            sent = await self._service.send_message(
                session_id,
                text,
                include_shell_tools=self._settings.include_shell_tools,
            )
        except ValueError as exc:
            self._stream_done(stream)
            if self._service.get_session(session_id) is None:  # deleted meanwhile
                raise SessionNotFoundError(str(exc)) from exc
            raise
        except BaseException:
            self._stream_done(stream)
            raise
        stream._bind(sent["attempt_id"])
        return stream

    async def run(self, text: str, *, title: str = "") -> RunResult:
        """Create a session, send one message and wait for the result.

        Args:
            text: User message.
            title: Title of the new session.

        Returns:
            The run's final result.
        """
        session = await self.create_session(title=title)
        stream = await self.send(session.session_id, text)
        return await stream.wait()

    def _stream_done(self, stream: Stream) -> None:
        listener = self._listeners.pop(stream, None)
        if listener is not None:
            self._service.event_bus.remove_listener(listener)

    async def aclose(self, timeout: Optional[float] = None) -> List[str]:
        """Stop the service and release the runtime root.

        Runs still in flight are stopped the way a server shutdown stops
        them: their attempts stay recoverable and the next service on this
        root marks them interrupted. Their streams raise
        :class:`ClientClosedError`.

        Args:
            timeout: Seconds to wait for in-flight work to stop; the
                service's own default when omitted.

        Returns:
            Ids of work still running after the wait. While any remain the
            root stays claimed, so call ``aclose`` again before reusing it.
        """
        self._closed = True
        kwargs = {} if timeout is None else {"timeout": timeout}
        pending = await asyncio.to_thread(self._service.shutdown, **kwargs)
        for stream in list(self._listeners):
            stream._abort(ClientClosedError("the Client closed before the run ended"))
        if not pending:
            self._release()
        return pending

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _session_info(session: Any) -> SessionInfo:
    return SessionInfo(
        session_id=session.session_id,
        title=session.title,
        status=session.status.value,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_attempt_id=session.last_attempt_id,
    )


def _message_info(message: Any) -> MessageInfo:
    return MessageInfo(
        message_id=message.message_id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        attempt_id=message.linked_attempt_id,
        metadata=MappingProxyType(copy.deepcopy(dict(message.metadata or {}))),
    )


__all__ = [
    "Client",
    "ClientClosedError",
    "ClientSettings",
    "MessageInfo",
    "RuntimeRootInUseError",
    "SessionBusyError",
    "SessionInfo",
    "SessionNotFoundError",
    "Stream",
]
