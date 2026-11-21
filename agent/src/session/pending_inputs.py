"""User messages sent while a session's turn is running.

A message sent to a busy session is not refused: it waits in the session's
durable ``pending_inputs.json`` and joins the conversation at the first point
where the model can take it without losing work:

* the running turn takes it after its current tool batch finished and before
  its next model call (:class:`QueuedInputDelivery`, called by ``AgentLoop``);
* if that turn ends first, the oldest input starts the next turn.

Each input leaves the queue exactly once. Before an input is written into the
conversation it is *claimed* for that turn, together with the thread's highest
seq at that moment, and it is removed only after the write. A process that dies
in between leaves the claim on disk, and :meth:`PendingInputQueue.reconcile`
settles it on the next start: the input was delivered when the claimed turn
holds a ``user`` item with its text after that seq (or, for an input that
started a turn, when that turn's attempt exists with it as its prompt);
otherwise it is pending again.

A queued input carries the shell-tool entitlement of the request that sent it.
It can only join a running turn whose tools it was entitled to: an input sent
without shell tools waits for a turn of its own rather than steering a model
that has them. Joining a turn never changes the turn's tools, its identity
ledger or its budgets.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

#: File, inside a session directory, that holds its pending inputs.
PENDING_INPUTS_FILENAME = "pending_inputs.json"

#: Most inputs one session may hold waiting. A client that keeps sending into a
#: busy session is told so instead of growing the queue without bound.
MAX_PENDING_INPUTS = 20

_SCHEMA_VERSION = 1


class PendingInputLimitError(RuntimeError):
    """Raised when a session already holds :data:`MAX_PENDING_INPUTS` inputs."""


@dataclass(frozen=True)
class PendingInput:
    """One user message waiting to join the conversation.

    Attributes:
        input_id: Unique id.
        content: The message text, as the user sent it.
        queued_at: Epoch seconds when it was accepted.
        queued_during: The turn that was running when it was accepted.
        include_shell_tools: Whether the sending request may use shell tools.
        claimed_by: Turn the input is being written into, while that write is
            in progress (None while it waits).
        claimed_after_seq: Highest thread seq when the claim was taken.
    """

    input_id: str
    content: str
    queued_at: float
    queued_during: Optional[str]
    include_shell_tools: bool
    claimed_by: Optional[str] = None
    claimed_after_seq: Optional[int] = None

    def public(self) -> Dict[str, Any]:
        """Return the client view of the input.

        Returns:
            ``input_id``, ``content``, ``queued_at``, ``queued_during`` and
            ``status`` (``queued`` or ``delivering``).
        """
        return {
            "input_id": self.input_id,
            "content": self.content,
            "queued_at": self.queued_at,
            "queued_during": self.queued_during,
            "status": "delivering" if self.claimed_by else "queued",
        }

    @classmethod
    def from_dict(cls, record: Dict[str, Any]) -> Optional["PendingInput"]:
        """Parse one stored record.

        Args:
            record: Decoded JSON object.

        Returns:
            The input, or None for a record that is not a valid input.
        """
        input_id = record.get("input_id")
        content = record.get("content")
        queued_at = record.get("queued_at")
        if not isinstance(input_id, str) or not input_id or not isinstance(content, str):
            return None
        if not isinstance(queued_at, (int, float)) or isinstance(queued_at, bool):
            return None
        claimed_by = record.get("claimed_by")
        claimed_after_seq = record.get("claimed_after_seq")
        queued_during = record.get("queued_during")
        return cls(
            input_id=input_id,
            content=content,
            queued_at=float(queued_at),
            queued_during=queued_during if isinstance(queued_during, str) else None,
            include_shell_tools=record.get("include_shell_tools") is True,
            claimed_by=claimed_by if isinstance(claimed_by, str) and claimed_by else None,
            claimed_after_seq=(
                claimed_after_seq
                if isinstance(claimed_after_seq, int) and not isinstance(claimed_after_seq, bool)
                else None
            ),
        )


class PendingInputQueue:
    """Durable FIFO of pending inputs, one file per session.

    Every change rewrites the session's file atomically (temporary file,
    fsync, ``os.replace``) under a per-session lock, so a reader never sees a
    half-written queue and a crash keeps either the old or the new one.
    """

    def __init__(self, path_for: Callable[[str], Path], *, clock: Callable[[], float] = time.time) -> None:
        """Create the queue.

        Args:
            path_for: Maps a session id to its ``pending_inputs.json``.
            clock: Source of ``queued_at`` (epoch seconds).
        """
        self._path_for = path_for
        self._clock = clock
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    # ---- Reading ----

    def list(self, session_id: str) -> List[PendingInput]:
        """Return a session's pending inputs, oldest first.

        Args:
            session_id: Session id.

        Returns:
            The inputs, claimed ones included.
        """
        with self._lock(session_id):
            return self._read(session_id)

    def waiting(self, session_id: str) -> List[PendingInput]:
        """Return the inputs no turn has claimed, oldest first.

        Args:
            session_id: Session id.

        Returns:
            Unclaimed inputs.
        """
        return [item for item in self.list(session_id) if item.claimed_by is None]

    # ---- Writing ----

    def add(self, session_id: str, content: str, *, queued_during: Optional[str], include_shell_tools: bool) -> PendingInput:
        """Accept one input at the end of the queue.

        Args:
            session_id: Session id.
            content: Message text.
            queued_during: The turn running now.
            include_shell_tools: The sending request's shell-tool entitlement.

        Returns:
            The stored input.

        Raises:
            PendingInputLimitError: The session already holds the maximum.
            OSError: The queue could not be written; nothing was accepted.
        """
        with self._lock(session_id):
            items = self._read(session_id)
            if len(items) >= MAX_PENDING_INPUTS:
                raise PendingInputLimitError(
                    f"Session {session_id} already has {len(items)} messages waiting"
                )
            item = PendingInput(
                input_id=uuid.uuid4().hex[:12],
                content=content,
                queued_at=float(self._clock()),
                queued_during=queued_during,
                include_shell_tools=include_shell_tools,
            )
            self._write(session_id, [*items, item])
            return item

    def claim_next(
        self,
        session_id: str,
        turn_id: str,
        *,
        after_seq: int,
        shell_tools: Optional[bool] = None,
    ) -> Optional[PendingInput]:
        """Claim the oldest waiting input for one turn.

        Only the head of the queue is ever claimed, so inputs join in the
        order they were sent.

        Args:
            session_id: Session id.
            turn_id: The turn the input is about to be written into.
            after_seq: Highest thread seq before that write.
            shell_tools: The running turn's shell-tool set, when the input is
                to join it. The head is not claimed when the turn has shell
                tools and the input was not entitled to them. None claims
                for a new turn, which takes the input's own entitlement.

        Returns:
            The claimed input, or None when nothing may be claimed now.
        """
        with self._lock(session_id):
            items = self._read(session_id)
            if not items or any(item.claimed_by for item in items):
                return None
            head = items[0]
            if shell_tools and not head.include_shell_tools:
                return None
            claimed = replace(head, claimed_by=turn_id, claimed_after_seq=after_seq)
            self._write(session_id, [claimed, *items[1:]])
            return claimed

    def complete(self, session_id: str, input_id: str) -> None:
        """Remove an input whose write into the conversation finished.

        Args:
            session_id: Session id.
            input_id: The delivered input.
        """
        with self._lock(session_id):
            items = self._read(session_id)
            kept = [item for item in items if item.input_id != input_id]
            if len(kept) != len(items):
                self._write(session_id, kept)

    def release(self, session_id: str, input_id: str) -> None:
        """Return a claimed input to the queue, at its old position.

        Args:
            session_id: Session id.
            input_id: The input whose write did not happen.
        """
        with self._lock(session_id):
            items = self._read(session_id)
            released = [
                replace(item, claimed_by=None, claimed_after_seq=None)
                if item.input_id == input_id else item
                for item in items
            ]
            if released != items:
                self._write(session_id, released)

    def discard(self, session_id: str, input_id: str) -> Optional[PendingInput]:
        """Remove a waiting input at the user's request.

        Args:
            session_id: Session id.
            input_id: Input to remove.

        Returns:
            The removed input, or None when it is not waiting (unknown, or
            claimed by a turn that is writing it now).
        """
        with self._lock(session_id):
            items = self._read(session_id)
            target = next((item for item in items if item.input_id == input_id), None)
            if target is None or target.claimed_by is not None:
                return None
            self._write(session_id, [item for item in items if item.input_id != input_id])
            return target

    def reconcile(
        self,
        session_id: str,
        thread_items: Iterable[Any],
        *,
        turn_prompt: Callable[[str], Optional[str]],
    ) -> List[PendingInput]:
        """Settle claims a previous process left behind.

        Args:
            session_id: Session id.
            thread_items: The session's thread items.
            turn_prompt: Maps a turn id to its attempt's prompt, or None when
                no such attempt exists.

        Returns:
            The inputs found delivered and removed.
        """
        with self._lock(session_id):
            items = self._read(session_id)
            if not any(item.claimed_by for item in items):
                return []
            thread_items = list(thread_items)
            delivered: List[PendingInput] = []
            kept: List[PendingInput] = []
            for item in items:
                if item.claimed_by is None:
                    kept.append(item)
                elif _was_delivered(item, thread_items, turn_prompt):
                    delivered.append(item)
                else:
                    kept.append(replace(item, claimed_by=None, claimed_after_seq=None))
            self._write(session_id, kept)
            return delivered

    # ---- Internals ----

    def _lock(self, session_id: str) -> threading.Lock:
        with self._locks_lock:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = self._locks[session_id] = threading.Lock()
            return lock

    def _read(self, session_id: str) -> List[PendingInput]:
        path = self._path_for(session_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Could not read pending inputs %s (%s)", path, type(exc).__name__)
            return []
        raw = record.get("inputs") if isinstance(record, dict) else None
        if not isinstance(raw, list):
            return []
        parsed = [PendingInput.from_dict(entry) for entry in raw if isinstance(entry, dict)]
        return [item for item in parsed if item is not None]

    def _write(self, session_id: str, items: List[PendingInput]) -> None:
        path = self._path_for(session_id)
        if not items:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            {"schema_version": _SCHEMA_VERSION, "inputs": [asdict(item) for item in items]},
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


def _was_delivered(
    item: PendingInput,
    thread_items: List[Any],
    turn_prompt: Callable[[str], Optional[str]],
) -> bool:
    after = item.claimed_after_seq if item.claimed_after_seq is not None else 0
    for thread_item in thread_items:
        if (
            thread_item.type == "user"
            and thread_item.turn_id == item.claimed_by
            and thread_item.seq > after
            and thread_item.get("content") == item.content
        ):
            return True
    return turn_prompt(item.claimed_by) == item.content


class QueuedInputDelivery:
    """Hands a running turn the inputs queued for its session.

    ``AgentLoop`` calls :meth:`deliver` at its one injection point, after a
    tool batch finished and before the next model call. Each input is claimed,
    written into the thread as a ``user`` item through the turn's recorder,
    announced, and only then removed from the queue. A write the recorder drops (the turn
    already finished) or fails returns the input to the queue.
    """

    def __init__(
        self,
        queue: PendingInputQueue,
        *,
        session_id: str,
        turn_id: str,
        recorder: Any,
        shell_tools: bool,
        on_delivered: Callable[[PendingInput, Any], None],
    ) -> None:
        """Bind the delivery to one turn.

        Args:
            queue: The service's pending-input queue.
            session_id: Session id.
            turn_id: The running turn.
            recorder: The turn's ``TurnRecorder``; its ``max_seq`` is at
                least the seq of the turn's own first user item, which is all
                a claim's ``after_seq`` has to separate.
            shell_tools: Whether the running turn has shell tools.
            on_delivered: Called after each input was recorded and before it
                leaves the queue, with the input and its thread item (display
                row, events).
        """
        self._queue = queue
        self._session_id = session_id
        self._turn_id = turn_id
        self._recorder = recorder
        self._shell_tools = shell_tools
        self._on_delivered = on_delivered

    def deliver(self) -> List[Dict[str, Any]]:
        """Write every input that may join the turn now into the thread.

        Returns:
            The user messages to append to the model input, in order. Each is
            the object the recorder mapped to its thread item.
        """
        delivered: List[Dict[str, Any]] = []
        while True:
            try:
                claimed = self._queue.claim_next(
                    self._session_id,
                    self._turn_id,
                    after_seq=self._recorder.max_seq,
                    shell_tools=self._shell_tools,
                )
            except OSError as exc:
                logger.warning("Could not claim a queued input for turn %s: %s", self._turn_id, exc)
                return delivered
            if claimed is None:
                return delivered
            message = {"role": "user", "content": claimed.content}
            try:
                item = self._recorder.user(
                    message, content=claimed.content, input_id=claimed.input_id
                )
            except Exception:  # noqa: BLE001 - the input must go back, not vanish
                logger.warning("Could not record queued input %s", claimed.input_id, exc_info=True)
                item = None
            if item is None:
                self._settle(self._queue.release, claimed)
                return delivered
            delivered.append(message)
            try:
                self._on_delivered(claimed, item)
            except Exception:  # noqa: BLE001 - the input is in the thread already
                logger.warning("Delivered input %s but could not publish it", claimed.input_id, exc_info=True)
            if not self._settle(self._queue.complete, claimed):
                # The claim stays on disk and blocks further claims; the next
                # start's reconcile finds the item and removes the input.
                return delivered

    def _settle(self, action: Callable[[str, str], None], claimed: PendingInput) -> bool:
        try:
            action(self._session_id, claimed.input_id)
        except OSError as exc:
            logger.warning("Could not settle queued input %s: %s", claimed.input_id, exc)
            return False
        return True
