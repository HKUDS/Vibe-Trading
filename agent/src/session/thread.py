"""Append-only conversation thread log and its replay into model input.

``sessions/<id>/thread.jsonl`` is the source of truth for a conversation: every
user message, model response, tool result, loop injection, compaction marker,
state snapshot and turn boundary, one JSON object per line. The model input of
a later turn is *derived* from it by :func:`replay`; nothing derived is ever
written back, so a repair made for one provider request (a synthetic result for
an interrupted call, a dropped orphan result) never becomes history.

``messages.jsonl`` keeps one display row per turn. :func:`project_turn` builds
that row's content and ``tool_trail`` from the thread, so the thread is the only
place a turn is recorded in full.

Replayed history is conversation text only. It never grants tool permission or
instrument authorization: those are restored from their own persisted records,
never parsed out of what the model said or saw.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

THREAD_FILENAME = "thread.jsonl"

ASSISTANT_PHASES = frozenset({"commentary", "final"})
TOOL_RESULT_STATUSES = frozenset({"ok", "error"})
TURN_END_STATUSES = frozenset({"completed", "cancelled", "failed", "interrupted"})
STOPPED_TURN_STATUSES = frozenset({"cancelled", "failed", "interrupted"})

# Tool-trail display limits, matching the live ``tool_call`` / ``tool_result``
# event payloads the legacy trail was built from (``tool_lifecycle.py``).
TRAIL_ARGUMENT_CHARS = 200
TRAIL_PREVIEW_CHARS = 200

# Content of the result replay supplies, in the request only, for a call the
# thread has no result for. JSON like every other tool error envelope.
INTERRUPTED_RESULT_CONTENT = json.dumps(
    {
        "status": "error",
        "error": (
            "interrupted: this tool call did not finish and no result was "
            "recorded. It may have partly run."
        ),
    },
    ensure_ascii=False,
)

# One note per stopped turn, after that turn's last item. Wrapped in
# ``<system>`` like the loop's other user-role injections.
STOPPED_TURN_NOTES: Dict[str, str] = {
    "cancelled": (
        "<system>The user stopped the previous turn before it finished. Tool "
        "results recorded above for that turn are still valid and can be used. "
        "A tool call marked interrupted may have partly run; check its effect "
        "before repeating anything it could have changed.</system>"
    ),
    "interrupted": (
        "<system>The previous turn was interrupted (the service stopped) before "
        "it finished. Tool results recorded above for that turn are still valid "
        "and can be used. A tool call marked interrupted may have partly run; "
        "check its effect before repeating anything it could have changed."
        "</system>"
    ),
    "failed": (
        "<system>The previous turn ended with an error before it finished. Tool "
        "results recorded above for that turn are still valid and can be used. "
        "A tool call marked interrupted may have partly run; check its effect "
        "before repeating anything it could have changed.</system>"
    ),
}

_COMMON_FIELDS = ("seq", "ts", "turn_id", "type")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _optional(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda value: value is None or check(value)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_message_content(value: Any) -> bool:
    # OpenAI message content: a string or a list of content parts.
    return isinstance(value, (str, list))


def _is_tool_calls(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for call in value:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str):
            return False
        function = call.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            return False
    return True


@dataclass(frozen=True)
class _Field:
    check: Callable[[Any], bool]
    required: bool = False
    default: Any = None


# Per-type payload schema. ``state`` is open: its keys (identity records,
# loaded tool names, workspace) are owned by the session runtime.
_SCHEMA: Dict[str, Optional[Dict[str, _Field]]] = {
    "turn_start": {
        "prompt": _Field(_is_message_content, required=True),
        "model": _Field(_optional(_is_str)),
        "provider": _Field(_optional(_is_str)),
    },
    "user": {
        "content": _Field(_is_message_content, required=True),
        "llm_content": _Field(_is_message_content, required=True),
        "input_id": _Field(_optional(_is_str)),
    },
    "assistant": {
        "content": _Field(_optional(_is_message_content)),
        "tool_calls": _Field(_is_tool_calls, default=[]),
        "reasoning_content": _Field(_optional(_is_str)),
        "provider_items": _Field(_optional(_is_list)),
        "provider": _Field(_optional(_is_str)),
        "model": _Field(_optional(_is_str)),
        "phase": _Field(_optional(lambda v: v in ASSISTANT_PHASES)),
    },
    "tool_result": {
        "tool_call_id": _Field(lambda v: isinstance(v, str) and bool(v), required=True),
        "name": _Field(_is_str, required=True),
        "content": _Field(_is_str, required=True),
        "status": _Field(lambda v: v in TOOL_RESULT_STATUSES, required=True),
        "elapsed_ms": _Field(_optional(_is_number)),
        # Display-only: the report link the live event carried. Never replayed.
        "artifact": _Field(_optional(_is_dict)),
    },
    "inject": {
        "content": _Field(_is_message_content, required=True),
        "role": _Field(lambda v: v in {"user", "system"}, default="user"),
    },
    "checkpoint": {
        "content": _Field(_is_str, required=True),
    },
    "compaction": {
        "summary": _Field(_is_str, default=""),
        "replaces_through_seq": _Field(_is_int, default=0),
        "layer": _Field(lambda v: _is_int(v) and v in {1, 2, 3}, default=3),
        # Layer 1 and 2 preserve raw items and record the exact message
        # replacements that the model saw after an in-memory compaction.
        "changes": _Field(_is_list, default=[]),
    },
    "state": None,
    "turn_end": {
        "status": _Field(lambda v: v in TURN_END_STATUSES, required=True),
        "usage": _Field(_optional(_is_dict)),
        "elapsed_ms": _Field(_optional(_is_number)),
        "summary": _Field(_optional(_is_str)),
        "error": _Field(_optional(_is_str)),
        "run_dir": _Field(_optional(_is_str)),
        "provider": _Field(_optional(_is_str)),
        "model": _Field(_optional(_is_str)),
        "pending_inputs": _Field(_optional(_is_list)),
    },
}

ITEM_TYPES = frozenset(_SCHEMA)


class ThreadItemError(ValueError):
    """Raised when an item does not match the thread schema."""


def _validate_payload(item_type: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Check one item's payload against its type schema and fill defaults.

    Args:
        item_type: Item type name.
        payload: Type-specific fields (common fields excluded).

    Returns:
        A new payload dict with defaults filled in.

    Raises:
        ThreadItemError: The type is unknown or a field is missing, unknown
            or of the wrong shape.
    """
    if item_type not in _SCHEMA:
        raise ThreadItemError(f"unknown thread item type {item_type!r}")
    for name in _COMMON_FIELDS:
        if name in payload:
            raise ThreadItemError(f"{name!r} is assigned by the log, not the caller")
    schema = _SCHEMA[item_type]
    if schema is None:
        return copy.deepcopy(dict(payload))
    unknown = set(payload) - set(schema)
    if unknown:
        raise ThreadItemError(
            f"{item_type} item has unknown fields: {', '.join(sorted(unknown))}"
        )
    result: Dict[str, Any] = {}
    for name, spec in schema.items():
        if name not in payload:
            if spec.required:
                raise ThreadItemError(f"{item_type} item is missing {name!r}")
            result[name] = copy.deepcopy(spec.default)
            continue
        value = payload[name]
        if not spec.check(value):
            raise ThreadItemError(f"{item_type} item has an invalid {name!r}")
        result[name] = copy.deepcopy(value)
    if item_type == "compaction":
        # Keep the legacy on-disk shape byte-for-byte for summary-only
        # records. New layer events carry these fields explicitly.
        if "layer" not in payload:
            result.pop("layer", None)
        if "changes" not in payload:
            result.pop("changes", None)
    if item_type == "user" and result.get("input_id") is None:
        # Preserve the legacy user-item shape. Queued inputs carry a real id.
        result.pop("input_id", None)
    if item_type == "assistant":
        # Older thread records did not identify the provider/model. Keep their
        # on-disk shape stable while new responses record both fields.
        for name in ("provider", "model"):
            if name not in payload:
                result.pop(name, None)
    return result


@dataclass(frozen=True)
class ThreadItem:
    """One record of ``thread.jsonl``.

    Attributes:
        seq: Position in the session, strictly increasing in write order.
        ts: Wall-clock write time, epoch seconds.
        turn_id: Turn the item belongs to (the attempt id).
        type: One of :data:`ITEM_TYPES`.
        data: Type-specific payload.
    """

    seq: int
    ts: float
    turn_id: str
    type: str
    data: Dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        """Return one payload field.

        Args:
            name: Field name.
            default: Value when the field is absent.

        Returns:
            The field value or ``default``.
        """
        return self.data.get(name, default)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the flat on-disk shape.

        Returns:
            Common fields followed by the payload fields.
        """
        return {
            "seq": self.seq,
            "ts": self.ts,
            "turn_id": self.turn_id,
            "type": self.type,
            **copy.deepcopy(self.data),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "ThreadItem":
        """Parse one on-disk record.

        Args:
            record: Decoded JSON object.

        Returns:
            The item.

        Raises:
            ThreadItemError: A common field is missing or the payload does not
                match its type schema.
        """
        seq = record.get("seq")
        ts = record.get("ts")
        turn_id = record.get("turn_id")
        item_type = record.get("type")
        if not _is_int(seq) or seq < 1:
            raise ThreadItemError("seq must be a positive integer")
        if not _is_number(ts):
            raise ThreadItemError("ts must be a number")
        if not isinstance(turn_id, str) or not turn_id:
            raise ThreadItemError("turn_id must be a non-empty string")
        if not isinstance(item_type, str):
            raise ThreadItemError("type must be a string")
        payload = {k: v for k, v in record.items() if k not in _COMMON_FIELDS}
        return cls(
            seq=seq,
            ts=float(ts),
            turn_id=turn_id,
            type=item_type,
            data=_validate_payload(item_type, payload),
        )


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
_FILE_LOCKS: Dict[str, threading.Lock] = {}
_FILE_LOCKS_LOCK = threading.Lock()


def _path_state(path: Path) -> _PathState:
    key = os.path.normcase(os.path.abspath(path))
    with _PATH_STATES_LOCK:
        state = _PATH_STATES.get(key)
        if state is None:
            state = _PATH_STATES[key] = _PathState()
        return state


def _file_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _FILE_LOCKS_LOCK:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = _FILE_LOCKS[key] = threading.Lock()
        return lock


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
            item_type: One of :data:`ITEM_TYPES`.
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
        process_lock = _file_lock(self.path)
        with process_lock:
            with self.path.open("a+b") as log:
                if fcntl is not None:
                    fcntl.flock(log.fileno(), fcntl.LOCK_EX)
                try:
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

    def read(self) -> List[ThreadItem]:
        """Read every valid item in file order.

        A line that is not valid UTF-8, not JSON, not an object or does not
        match the schema is skipped with a warning; its neighbours are kept.

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
                    record = json.loads(raw_line.decode("utf-8"))
                    if not isinstance(record, dict):
                        raise ThreadItemError(
                            f"thread line must be a JSON object, got {type(record).__name__}"
                        )
                    items.append(ThreadItem.from_dict(record))
                except (json.JSONDecodeError, UnicodeDecodeError, ThreadItemError) as exc:
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


# ---- Replay ----


def _assistant_message(
    item: ThreadItem,
    *,
    target_provider: Optional[str] = None,
    target_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Rebuild the assistant message the loop sent, in the loop's key order.

    Mirrors ``ContextBuilder.format_assistant_tool_calls`` for a tool-call
    response and the loop's plain ``{"role", "content"}`` for a final answer.
    """
    message: Dict[str, Any] = {"role": "assistant", "content": copy.deepcopy(item.get("content"))}
    tool_calls = item.get("tool_calls") or []
    if tool_calls:
        message["tool_calls"] = copy.deepcopy(tool_calls)
        if any(call.get("extra_content") for call in tool_calls):
            message["additional_kwargs"] = {"tool_calls": copy.deepcopy(tool_calls)}
    source_provider = item.get("provider")
    source_model = item.get("model")
    same_runtime = (
        target_provider is None and target_model is None
    ) or (
        isinstance(source_provider, str)
        and isinstance(source_model, str)
        and source_provider == target_provider
        and source_model == target_model
    )
    if same_runtime and item.get("reasoning_content") is not None:
        message["reasoning_content"] = item.get("reasoning_content")
    if same_runtime and item.get("provider_items"):
        message["provider_items"] = copy.deepcopy(item.get("provider_items"))
    return message


class _Replayer:
    """Single pass over thread items that keeps every tool block well-formed.

    A tool block is an assistant message with tool calls plus the results that
    must follow it directly. While a block is open, results for its calls are
    appended and anything else is held back; the block closes at the next
    assistant message, turn boundary or end of input, where calls without a
    result get :data:`INTERRUPTED_RESULT_CONTENT` and the held messages follow.
    A result for a call outside the open block is dropped.

    Pairing is positional, not by a session-wide id set: providers that derive
    call ids from a per-response counter reuse them across turns.
    """

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self._pending: Dict[str, str] = {}
        self._answered: set = set()
        self._held: List[Dict[str, Any]] = []

    def assistant(self, item: ThreadItem) -> None:
        self.close_block()
        message = _assistant_message(item)
        self.assistant_message(message)

    def assistant_message(self, message: Dict[str, Any]) -> None:
        """Append an already reconstructed assistant message."""
        self.close_block()
        self.messages.append(message)
        for call in message.get("tool_calls", []):
            self._pending[call["id"]] = call["function"]["name"]

    def tool_result(self, item: ThreadItem) -> None:
        self.tool_result_message({
            "role": "tool",
            "tool_call_id": item.get("tool_call_id"),
            "name": item.get("name"),
            "content": item.get("content"),
        })

    def tool_result_message(self, message: Dict[str, Any]) -> None:
        """Append an already reconstructed tool result."""
        call_id = message.get("tool_call_id")
        if call_id not in self._pending or call_id in self._answered:
            logger.debug("Replay dropped a tool result without an open call: %s", call_id)
            return
        self._answered.add(call_id)
        self.messages.append(copy.deepcopy(message))

    def other(self, message: Dict[str, Any]) -> None:
        if self._pending:
            self._held.append(message)
        else:
            self.messages.append(message)

    def close_block(self) -> None:
        for call_id, name in self._pending.items():
            if call_id not in self._answered:
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": INTERRUPTED_RESULT_CONTENT,
                    }
                )
        self._pending = {}
        self._answered = set()
        self.messages.extend(self._held)
        self._held = []


def _item_message(
    item: ThreadItem,
    *,
    target_provider: Optional[str] = None,
    target_model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build the provider message represented by one thread item."""
    if item.type == "user":
        return {"role": "user", "content": copy.deepcopy(item.get("llm_content"))}
    if item.type == "assistant":
        return _assistant_message(
            item, target_provider=target_provider, target_model=target_model
        )
    if item.type == "tool_result":
        return {
            "role": "tool",
            "tool_call_id": item.get("tool_call_id"),
            "name": item.get("name"),
            "content": item.get("content"),
        }
    if item.type == "inject":
        return {"role": item.get("role"), "content": copy.deepcopy(item.get("content"))}
    return None


def replay(
    items: Iterable[ThreadItem],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build the OpenAI-format history a new turn sends to the model.

    1. Start after the last ``compaction``'s ``replaces_through_seq``, with
       its summary first as a user message.
    2. ``user`` becomes its ``llm_content`` verbatim; ``assistant``,
       ``tool_result`` and ``inject`` are rebuilt verbatim; ``state``,
       ``turn_start`` and ``turn_end`` are not model input.
    3. Tool-call pairing is repaired in the returned list only (see
       :class:`_Replayer`); the items are not modified.
    4. A turn that ended ``cancelled`` / ``interrupted`` / ``failed``, or has
       no ``turn_end`` when another turn starts, gets one note after its last
       item, unless the compaction summary already covers all of it.

    Replay assumes no turn is in flight: a trailing turn without ``turn_end``
    is replayed as it stands, with its unanswered calls marked interrupted.

    Args:
        items: Thread items in write order.

    Returns:
        A fresh list of message dicts; mutating it does not touch ``items``.
    """
    items = list(items)
    compaction = last_compaction(items)
    replayer = _Replayer()
    start_after = compaction.get("replaces_through_seq") if compaction is not None else 0

    # Apply the recorded view changes in write order. Raw user, assistant and
    # tool items remain untouched in the log. Layer 1 and 2 events replace the
    # exact message that was sent after the in-memory mutation, while layer 3
    # starts a new replay view at its summary boundary.
    message_by_seq: Dict[int, Dict[str, Any]] = {}
    source_by_seq: Dict[int, ThreadItem] = {}
    for item in items:
        message = _item_message(item, target_provider=provider, target_model=model)
        if message is not None:
            message_by_seq[item.seq] = message
            source_by_seq[item.seq] = item
    for event in items:
        if event.type != "compaction":
            continue
        layer = event.get("layer", 3)
        if layer in {1, 2}:
            for change in event.get("changes") or []:
                if not isinstance(change, dict):
                    continue
                seq = change.get("seq")
                message = change.get("message")
                if _is_int(seq) and isinstance(message, dict) and seq in message_by_seq:
                    message_by_seq[seq] = copy.deepcopy(message)

    if compaction is not None:
        replayer.messages.append({"role": "user", "content": compaction.get("summary")})

    open_turn: Optional[str] = None
    finished: set = set()
    # Turns with an item after the start point. A turn the summary already
    # covers gets no note of its own.
    visible: set = set()

    def finish_turn(turn_id: str, status: Optional[str]) -> None:
        finished.add(turn_id)
        replayer.close_block()
        note = STOPPED_TURN_NOTES.get(status or "")
        if note is not None and turn_id in visible:
            replayer.messages.append({"role": "user", "content": note})

    for item in items:
        if item.seq > start_after:
            visible.add(item.turn_id)
        if item.type == "turn_start":
            if open_turn is not None and open_turn != item.turn_id:
                # The open turn never recorded an end and another turn
                # started: the process died under it.
                finish_turn(open_turn, "interrupted")
            open_turn = item.turn_id
            continue
        if item.type == "turn_end":
            if item.turn_id not in finished:
                finish_turn(item.turn_id, item.get("status"))
            if item.turn_id == open_turn:
                open_turn = None
            continue
        if item.seq <= start_after or item.type in {"compaction", "state"}:
            continue
        effective = message_by_seq.get(item.seq)
        if effective is not None:
            if effective.get("role") == "assistant":
                source = source_by_seq.get(item.seq)
                if source is not None:
                    effective = _assistant_message(
                        source, target_provider=provider, target_model=model
                    )
                replayer.assistant_message(copy.deepcopy(effective))
            elif effective.get("role") == "tool":
                replayer.tool_result_message(copy.deepcopy(effective))
            elif effective.get("role") in {"user", "system"}:
                replayer.other(copy.deepcopy(effective))
            continue
        if item.type == "user":
            replayer.other({"role": "user", "content": copy.deepcopy(item.get("llm_content"))})
        elif item.type == "assistant":
            replayer.assistant_message(
                _assistant_message(
                    item, target_provider=provider, target_model=model
                )
            )
        elif item.type == "tool_result":
            replayer.tool_result(item)
        elif item.type == "inject":
            replayer.other({"role": item.get("role"), "content": copy.deepcopy(item.get("content"))})
    replayer.close_block()
    return replayer.messages


# ---- Display projection ----


@dataclass
class TurnProjection:
    """The legacy ``messages.jsonl`` row fields for one finished turn.

    Attributes:
        turn_id: Turn id.
        status: ``turn_end`` status, or None when the turn has not ended.
        content: Final answer text, or None when the turn produced none.
        tool_trail: Compact tool records in the ``Message.tool_trail`` shape.
        usage: ``turn_end`` usage, if recorded.
        elapsed_ms: ``turn_end`` elapsed time, if recorded.
    """

    turn_id: str
    status: Optional[str]
    content: Optional[str]
    tool_trail: List[Dict[str, Any]]
    usage: Optional[Dict[str, Any]] = None
    elapsed_ms: Optional[float] = None


def _trail_arguments(raw: Any, run_dir: Optional[str]) -> Dict[str, Any]:
    from src.agent.tool_results import _normalize_tool_run_dir
    from src.tools.redaction import redact_payload

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = None
    if not isinstance(parsed, dict):
        return {}
    redacted = redact_payload(_normalize_tool_run_dir(parsed, run_dir))
    return {key: str(value)[:TRAIL_ARGUMENT_CHARS] for key, value in redacted.items()}


def project_turn(
    items: Iterable[ThreadItem],
    turn_id: str,
    *,
    run_dir: Optional[str] = None,
) -> TurnProjection:
    """Project one turn's items onto the legacy display row.

    The trail follows ``SessionService._record_tool_trail_event``: one entry
    per call in call order with ``tool`` / ``status`` / ``arguments`` /
    ``timestamp`` / ``call_id``, completed by its result with ``status``
    (``ok`` / ``error``), ``elapsed_ms``, ``preview`` and an ``ok`` result's
    ``artifact``; a result with no recorded call gets an entry of its own.
    A call that never got a result in a turn that has ended is shown as
    ``error`` with the interrupted preview rather than ``running`` forever.

    Args:
        items: Thread items (any superset of the turn's).
        turn_id: Turn to project.
        run_dir: The turn's run directory, used to show ``run_dir`` arguments
            as the live ``tool_call`` event did.

    Returns:
        The projection.
    """
    turn = [item for item in items if item.turn_id == turn_id]
    trail: List[Dict[str, Any]] = []
    final_content: Optional[str] = None
    fallback_content: Optional[str] = None
    status: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    elapsed_ms: Optional[float] = None

    for item in turn:
        if item.type == "assistant":
            tool_calls = item.get("tool_calls") or []
            content = item.get("content")
            if item.get("phase") == "final" and isinstance(content, str):
                final_content = content
            elif not tool_calls and isinstance(content, str) and content.strip():
                fallback_content = content
            for call in tool_calls:
                function = call.get("function") or {}
                trail.append(
                    {
                        "tool": function.get("name") or "",
                        "status": "running",
                        "arguments": _trail_arguments(function.get("arguments"), run_dir),
                        "timestamp": int(item.ts * 1000),
                        "call_id": call.get("id"),
                    }
                )
        elif item.type == "tool_result":
            call_id = item.get("tool_call_id")
            name = item.get("name") or ""
            match = next(
                (e for e in trail if e.get("call_id") == call_id and e["status"] == "running"),
                None,
            )
            if match is None:
                match = next(
                    (e for e in trail if e["tool"] == name and e["status"] == "running"),
                    None,
                )
            if match is None:
                match = {"tool": name, "arguments": {}, "timestamp": int(item.ts * 1000)}
                trail.append(match)
            match["status"] = "ok" if item.get("status") == "ok" else "error"
            elapsed = item.get("elapsed_ms")
            if _is_number(elapsed):
                match["elapsed_ms"] = max(0, int(elapsed))
            match["preview"] = str(item.get("content") or "")[:TRAIL_PREVIEW_CHARS]
            if match["status"] == "ok" and isinstance(item.get("artifact"), dict):
                match["artifact"] = dict(item.get("artifact"))
            match["call_id"] = call_id
        elif item.type == "turn_end":
            status = item.get("status")
            usage = copy.deepcopy(item.get("usage"))
            elapsed_ms = item.get("elapsed_ms")

    if status is not None:
        for entry in trail:
            if entry["status"] == "running":
                entry["status"] = "error"
                entry["preview"] = INTERRUPTED_RESULT_CONTENT[:TRAIL_PREVIEW_CHARS]

    return TurnProjection(
        turn_id=turn_id,
        status=status,
        content=final_content if final_content is not None else fallback_content,
        tool_trail=trail,
        usage=usage,
        elapsed_ms=elapsed_ms,
    )
