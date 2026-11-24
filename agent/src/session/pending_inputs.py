"""Persist FIFO input claims and reconcile them after a process restart."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.session.store import SessionStore

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
    """One queued message and its request's shell entitlement.

    Attributes:
        claimed_by: Turn currently writing the input.
        claimed_after_seq: Highest thread seq when the claim was persisted.
    """

    input_id: str
    content: str
    queued_at: float
    queued_during: Optional[str]
    include_shell_tools: bool
    claimed_by: Optional[str] = None
    claimed_after_seq: Optional[int] = None

    def unclaimed(self) -> "PendingInput":
        """Clear both fields of this input's durable claim."""
        return replace(self, claimed_by=None, claimed_after_seq=None)

    def public(self) -> Dict[str, Any]:
        """Return the client view of the input."""
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
    """Durable FIFO of pending inputs, one file per session."""

    def __init__(self, path_for: Callable[[str], Path], *, clock: Callable[[], float] = time.time) -> None:
        """Create the queue."""
        self._path_for = path_for
        self._clock = clock
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    # ---- Reading ----

    def list(self, session_id: str) -> List[PendingInput]:
        """Return a session's pending inputs, oldest first."""
        with self._lock(session_id):
            return self._read(session_id)

    def public_items(self, session_id: str) -> list[dict[str, Any]]:
        """Return the client view of the durable queue in delivery order."""
        return [item.public() for item in self.list(session_id)]

    def waiting(self, session_id: str) -> List[PendingInput]:
        """Return the inputs no turn has claimed, oldest first."""
        return [item for item in self.list(session_id) if item.claimed_by is None]

    # ---- Writing ----

    def add(self, session_id: str, content: str, *, queued_during: Optional[str], include_shell_tools: bool) -> PendingInput:
        """Accept one input at the end of the queue."""
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
        """Claim the head of the queue for a turn.

        Args:
            after_seq: Highest thread seq before delivery.
            shell_tools: True requires the input's shell entitlement. None starts
                a new turn with the input's own entitlement.
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
        """Remove an input whose write into the conversation finished."""
        self._remove(session_id, input_id, waiting_only=False)

    def release(self, session_id: str, input_id: str) -> None:
        """Return a claimed input to the queue, at its old position."""
        with self._lock(session_id):
            items = self._read(session_id)
            released = [
                item.unclaimed()
                if item.input_id == input_id else item
                for item in items
            ]
            if released != items:
                self._write(session_id, released)

    def discard(self, session_id: str, input_id: str) -> Optional[PendingInput]:
        """Remove a waiting input at the user's request."""
        return self._remove(session_id, input_id, waiting_only=True)

    def _remove(self, session_id: str, input_id: str, *, waiting_only: bool) -> Optional[PendingInput]:
        with self._lock(session_id):
            items = self._read(session_id)
            target = next((item for item in items if item.input_id == input_id), None)
            if target is None or (waiting_only and target.claimed_by is not None):
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
        """Settle claims a previous process left behind."""
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
                    kept.append(item.unclaimed())
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
        SessionStore._write_json(path, {
            "schema_version": _SCHEMA_VERSION,
            "inputs": [asdict(item) for item in items],
        })


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

    ``AgentRuntime`` calls :meth:`deliver` at its one injection point, after a
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
        """Bind the delivery to one turn."""
        self._queue = queue
        self._session_id = session_id
        self._turn_id = turn_id
        self._recorder = recorder
        self._shell_tools = shell_tools
        self._on_delivered = on_delivered

    def deliver(self) -> List[Dict[str, Any]]:
        """Write every input that may join the turn now into the thread."""
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
