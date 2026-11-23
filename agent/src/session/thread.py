"""Append-only, fsynced conversation storage with per-session sequence numbers."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]

from src.session.thread_schema import ThreadItem, ThreadItemError, _is_int, _validate_payload

logger = logging.getLogger(__name__)
THREAD_FILENAME = "thread.jsonl"


class _PathState:
    """Writer state shared by every ThreadLog open on one file in this process."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_seq = 0
        # File size after this process's last append; a different size means
        # the file changed outside this state, so ``last_seq`` is re-derived.
        self.known_size: Optional[int] = None


_PATH_STATES: Dict[str, _PathState] = {}
_PATH_STATES_LOCK = threading.Lock()


def _path_state(path: Path) -> _PathState:
    key = os.path.normcase(os.path.abspath(path))
    with _PATH_STATES_LOCK:
        state = _PATH_STATES.get(key)
        if state is None:
            state = _PATH_STATES[key] = _PathState()
        return state


def _encode_record(record: Mapping[str, Any]) -> bytes:
    try:
        return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate cannot be UTF-8 encoded; ASCII escapes keep the
        # exact string (it decodes back to the same code points).
        return (json.dumps(record, ensure_ascii=True) + "\n").encode("ascii")


class ThreadLog:
    """Append-only, fsynced ``thread.jsonl`` for one session.

    ``seq`` is assigned under a lock shared by every instance open on the same
    path in this process and an advisory file lock for writers in other
    processes. It is recovered from the file whenever the file is not the size
    this process last left it (first use, reopen, external append).

    Attributes:
        path: Location of ``thread.jsonl``.
    """

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        """Open a thread log.

        Args:
            path: Location of ``thread.jsonl``; created on first append.
            clock: Source of item timestamps (epoch seconds).
        """
        self.path = Path(path)
        self._clock = clock
        self._state = _path_state(self.path)

    # ---- Writing ----

    def append(self, item_type: str, turn_id: str, **payload: Any) -> ThreadItem:
        """Validate, number and durably append one item.

        Args:
            item_type: One of :data:`src.session.thread_schema.ITEM_TYPES`.
            turn_id: Turn (attempt id) the item belongs to.
            **payload: Type-specific fields.

        Returns:
            The item as written, with its assigned ``seq`` and ``ts``.

        Raises:
            ThreadItemError: The item does not match the schema.
            OSError: The write or fsync failed; ``seq`` is not consumed.
        """
        if not isinstance(turn_id, str) or not turn_id:
            raise ThreadItemError("turn_id must be a non-empty string")
        data = _validate_payload(item_type, payload)
        state = self._state
        with state.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._writer_lock() as log:
                needs_separator = self._sync_seq(state)
                item = ThreadItem(
                    seq=state.last_seq + 1,
                    ts=float(self._clock()),
                    turn_id=turn_id,
                    type=item_type,
                    data=data,
                )
                encoded = _encode_record(item.to_dict())
                if needs_separator:
                    # A torn last line (crash mid-write) must stay its own
                    # corrupt line, not swallow this record.
                    log.write(b"\n")
                log.seek(0, os.SEEK_END)
                log.write(encoded)
                log.flush()
                os.fsync(log.fileno())
                state.known_size = log.tell()
                state.last_seq = item.seq
        return item

    @contextmanager
    def _writer_lock(self):
        """Open the log and serialize appends across processes when supported."""
        created = not self.path.exists()
        with self.path.open("a+b") as log:
            if fcntl is not None:
                fcntl.flock(log.fileno(), fcntl.LOCK_EX)
            try:
                if created and os.name != "nt":
                    directory_fd = os.open(self.path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                yield log
            finally:
                if fcntl is not None:
                    fcntl.flock(log.fileno(), fcntl.LOCK_UN)

    def _sync_seq(self, state: _PathState) -> bool:
        """Re-derive ``last_seq`` when the file is not as this process left it.

        Args:
            state: Shared writer state (lock held by the caller).

        Returns:
            Whether the file ends without a newline and needs one first.
        """
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            state.known_size = None
            return False
        if size == state.known_size:
            return False
        last_seq = 0
        ends_with_newline = True
        with self.path.open("rb") as log:
            for raw_line in log:
                ends_with_newline = raw_line.endswith(b"\n")
                seq = _peek_seq(raw_line)
                if seq is not None and seq > last_seq:
                    last_seq = seq
        # Never move backwards: a truncated or replaced file must not reuse a
        # seq this process already handed out.
        state.last_seq = max(state.last_seq, last_seq)
        state.known_size = size
        return size > 0 and not ends_with_newline

    # ---- Reading ----

    def read(self, *, strict: bool = False) -> List[ThreadItem]:
        """Read every valid item in file order.

        A line that is not valid UTF-8, not JSON, not an object or does not
        match the schema is skipped with a warning; its neighbours are kept.

        Args:
            strict: Refuse unreadable records when callers rely on tool outcomes.

        Returns:
            Items in write order.
        """
        if not self.path.exists():
            return []
        items: List[ThreadItem] = []
        with self.path.open("rb") as log:
            for line_number, raw_line in enumerate(log, start=1):
                if not raw_line.strip():
                    continue
                try:
                    items.append(ThreadItem.from_line(raw_line))
                except (json.JSONDecodeError, UnicodeDecodeError, ThreadItemError) as exc:
                    if strict:
                        raise ThreadItemError(f"Corrupted thread record {line_number}") from exc
                    logger.warning(
                        "Skipping corrupted thread record %d in %s (%s)",
                        line_number,
                        self.path,
                        type(exc).__name__,
                    )
        return items

    def items_after(self, seq: int) -> List[ThreadItem]:
        """Return items whose ``seq`` is greater than ``seq``.

        Args:
            seq: Exclusive lower bound.

        Returns:
            Matching items in write order.
        """
        return [item for item in self.read() if item.seq > seq]

    def last_compaction(self) -> Optional[ThreadItem]:
        """Return the most recent ``compaction`` item, if any.

        Returns:
            The compaction item or None.
        """
        return last_compaction(self.read())

    def open_turns(self) -> List[str]:
        """Return turns that started but have no ``turn_end``.

        Returns:
            Turn ids in the order they started.
        """
        return open_turns(self.read())

    def turn_items(self, turn_id: str) -> List[ThreadItem]:
        """Return the items of one turn.

        Args:
            turn_id: Turn id.

        Returns:
            That turn's items in write order.
        """
        return [item for item in self.read() if item.turn_id == turn_id]


def _peek_seq(raw_line: bytes) -> Optional[int]:
    try:
        record = json.loads(raw_line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    seq = record.get("seq")
    return seq if _is_int(seq) else None


def last_compaction(items: Iterable[ThreadItem]) -> Optional[ThreadItem]:
    """Return the most recent ``compaction`` item.

    Args:
        items: Thread items in write order.

    Returns:
        The last compaction item or None.
    """
    found = None
    for item in items:
        if item.type == "compaction" and item.get("layer", 3) == 3:
            found = item
    return found


def open_turns(items: Iterable[ThreadItem]) -> List[str]:
    """Return turns that have a ``turn_start`` but no ``turn_end``.

    Args:
        items: Thread items in write order.

    Returns:
        Turn ids in start order.
    """
    started: List[str] = []
    ended = set()
    for item in items:
        if item.type == "turn_start" and item.turn_id not in started:
            started.append(item.turn_id)
        elif item.type == "turn_end":
            ended.add(item.turn_id)
    return [turn_id for turn_id in started if turn_id not in ended]
