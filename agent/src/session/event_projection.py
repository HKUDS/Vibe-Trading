"""Project canonical thread items into the client view and resumable live stream."""
from __future__ import annotations

import asyncio
import copy
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from src.kernel import events as vocabulary
from src.session.events import (
    EventBus, SSEEvent, SubscriberQueue, _COMPLETED, _RUN, _STARTED,
    _event_key, cursor_from_event_id, durable_event_id, select_buffered_live, select_replay,
)
from src.session.thread import ThreadLog
from src.session.thread_display import display_item
from src.session.thread_schema import ThreadItem, ThreadItemError

# Seq -> live id of items this process streamed live, so a client resuming
# from disk can still match its in-progress item to the completed one.
_LIVE_ID_MEMORY = 4096


def _type_kinds(item_type: str, status: Optional[str]) -> Tuple[str, str]:
    if item_type == "tool_result":
        return vocabulary.TOOL_STARTED, vocabulary.TOOL_COMPLETED if status == "ok" else vocabulary.TOOL_FAILED
    return vocabulary.ITEM_STARTED, vocabulary.ITEM_COMPLETED


@dataclass
class _LiveItem:
    live_id: str
    type: str
    turn_id: str


@dataclass
class _Tail:
    """Read position and live-item state of one session's thread."""

    path: Path
    offset: int = 0
    last_seq: int = 0
    assistant: Optional[_LiveItem] = None
    tools: Dict[Tuple[str, str], List[_LiveItem]] = field(default_factory=dict)
    interactions: Dict[Tuple[str, str], List[_LiveItem]] = field(default_factory=dict)
    # Queued user inputs, oldest first: (input_id, content, live item). Each
    # stays until its ``user`` item is recorded or it is discarded; it
    # outlives the turn it was sent during.
    inputs: List[Tuple[str, str, _LiveItem]] = field(default_factory=list)
    completed_tools: set[Tuple[str, str]] = field(default_factory=set)
    counter: int = 0
    live_by_seq: "OrderedDict[int, str]" = field(default_factory=OrderedDict)


def _take_live(pending: Dict[Tuple[str, str], List[_LiveItem]], key: Tuple[str, str]) -> Optional[_LiveItem]:
    queue = pending.get(key)
    if not queue:
        return None
    live = queue.pop(0)
    if not queue:
        del pending[key]
    return live


def _parse_line(raw_line: bytes) -> Optional[ThreadItem]:
    if not raw_line.strip():
        return None
    try:
        return ThreadItem.from_line(raw_line)
    except (json.JSONDecodeError, UnicodeDecodeError, ThreadItemError):
        return None


class ThreadEvents:
    """Project durable thread items and correlate transient live events."""

    def __init__(self, bus: EventBus, thread_path: Callable[[str], Path]) -> None:
        """Create the stream."""
        self.bus = bus
        self._thread_path = thread_path
        # Re-entrant: a bus listener may publish through this object from
        # inside a publish this object made.
        self._lock = threading.RLock()
        self._tails: Dict[str, _Tail] = {}

    # ---- Publishing ----

    def emit(self, session_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> Optional[SSEEvent]:
        """Publish durable items and a canonical live event from a callback."""
        payload = data if data is not None else {}
        with self._lock:
            tail = self._tail(session_id)
            self._pump(session_id, tail)
            if event_type in {"goal.created", "goal.updated", "goal.evidence", "swarm.started", "swarm.event"}:
                return self.bus.emit(session_id, event_type, payload)
            if event_type not in vocabulary.ITEM_EVENT_TYPES and event_type not in vocabulary.RUN_EVENT_TYPES:
                return None
            item = payload.get("item") or {}
            if event_type == vocabulary.ITEM_COMPLETED and item.get("type") == "tool_result" and (
                payload.get("attempt_id") or payload.get("turn_id"), item.get("tool_call_id")
            ) in tail.completed_tools:
                return None
            # A tool callback follows its durable result. Publish it only when
            # no recorder completed the same live item (standalone callers).
            if event_type == vocabulary.ITEM_COMPLETED and payload.get("live_id") in tail.live_by_seq.values():
                return None
            event = self._canonical_live_event(session_id, tail, event_type, payload)
            if event is not None:
                self.bus.publish(event)
            return event

    def sync(self, session_id: str) -> int:
        """Publish the events of items recorded since the last read."""
        with self._lock:
            tail = self._tail(session_id)
            self._pump(session_id, tail)
            return tail.last_seq

    # ---- Subscribing ----

    async def stream(
        self,
        session_id: str,
        *,
        cursor: Optional[int] = None,
        last_event_id: Optional[str] = None,
        replay_all: bool = False,
        active_turn_id: Optional[str] = None,
    ) -> AsyncIterator[SSEEvent]:
        """Subscribe to a session, resuming durable items from disk."""
        if cursor is None:
            cursor = cursor_from_event_id(last_event_id)
        with self._lock:
            tail = self._tail(session_id)
            self._pump(session_id, tail)
            high = tail.last_seq
            live_ids = dict(tail.live_by_seq)
            queue, buffer = self.bus.attach(session_id)
        try:
            durable = cursor is not None or (replay_all and bool(active_turn_id))
            last_key: Tuple[int, int] = (-1, _RUN)
            if durable:
                items = await asyncio.to_thread(self._read, session_id)
                if cursor is not None:
                    chosen = [item for item in items if cursor < item.seq <= high]
                    last_key = (cursor, _RUN)
                else:
                    chosen = [
                        item for item in items
                        if item.turn_id == active_turn_id and item.seq <= high
                    ]
                for item in chosen:
                    for event in self._recorded_events(session_id, item, live_ids.get(item.seq)):
                        yield event
                replayed = select_buffered_live(
                    buffer, cursor, last_event_id, finished_live_ids=set(live_ids.values())
                )
            else:
                replayed = select_replay(buffer, last_event_id, replay_all=replay_all)
            for event in replayed:
                yield event
            last_key = max(last_key, (high, _RUN))

            async for event in self.bus.listen(session_id, queue):
                if isinstance(queue, SubscriberQueue) and queue.overflowed:
                    queue.overflowed = False
                    async for missed in self._recover(session_id, last_key):
                        last_key = _event_key(missed)
                        yield missed
                if event.seq is not None:
                    key = _event_key(event)
                    if key <= last_key:
                        continue
                    last_key = key
                yield event
        finally:
            self.bus.detach(session_id, queue)

    async def _recover(self, session_id: str, last_key: Tuple[int, int]) -> AsyncIterator[SSEEvent]:
        """Re-read recorded items a full subscriber queue dropped."""
        with self._lock:
            tail = self._tail(session_id)
            self._pump(session_id, tail)
            high = tail.last_seq
            live_ids = dict(tail.live_by_seq)
        items = await asyncio.to_thread(self._read, session_id)
        for item in items:
            if item.seq < last_key[0] or item.seq > high:
                continue
            for event in self._recorded_events(session_id, item, live_ids.get(item.seq)):
                if _event_key(event) > last_key:
                    yield event

    # ---- Reading the thread ----

    def _read(self, session_id: str) -> List[ThreadItem]:
        from src.session.migration import migrate_session

        path = self._thread_path(session_id)
        migrate_session(path.parent, session_id=session_id)
        return ThreadLog(path).read()

    def _tail(self, session_id: str) -> _Tail:
        tail = self._tails.get(session_id)
        if tail is None:
            # First touch in this process: items already on disk are history
            # (served from disk), not news, so reading starts at the end.
            self._read(session_id)
            tail = _Tail(path=Path(self._thread_path(session_id)))
            for item in self._read_new(tail):
                tail.last_seq = max(tail.last_seq, item.seq)
            self._tails[session_id] = tail
        return tail

    @staticmethod
    def _read_new(tail: _Tail) -> List[ThreadItem]:
        """Read complete lines appended since the last read."""
        try:
            size = tail.path.stat().st_size
        except FileNotFoundError:
            tail.offset = 0
            return []
        if size < tail.offset:
            tail.offset = 0  # Replaced file; seqs below last_seq are skipped.
        if size == tail.offset:
            return []
        with tail.path.open("rb") as log:
            log.seek(tail.offset)
            chunk = log.read(size - tail.offset)
        end = chunk.rfind(b"\n")
        if end < 0:
            return []  # A line still being written.
        tail.offset += end + 1
        return [item for item in map(_parse_line, chunk[: end + 1].split(b"\n")) if item is not None]

    def _pump(self, session_id: str, tail: _Tail) -> None:
        for item in self._read_new(tail):
            if item.seq <= tail.last_seq:
                continue
            tail.last_seq = item.seq
            self._publish_item(session_id, tail, item)

    # ---- Event construction ----

    def _publish(
        self,
        session_id: str,
        event_type: str,
        data: Dict[str, Any],
        *,
        seq: Optional[int] = None,
        rank: int = _COMPLETED,
    ) -> None:
        event = SSEEvent(event_type=event_type, data=data, session_id=session_id, seq=seq)
        if seq is not None:
            event.event_id = durable_event_id(seq, rank)
        self.bus.publish(event)

    def _recorded_events(
        self, session_id: str, item: ThreadItem, live_id: Optional[str],
        *, view: Optional[Dict[str, Any]] = None,
    ) -> List[SSEEvent]:
        """The completion (and run) events of one recorded item."""
        if view is None:
            view = display_item(item)
            if view is None:
                return []
        _, completed_kind = _type_kinds(item.type, item.get("status"))
        data: Dict[str, Any] = {
            "kind": completed_kind,
            "seq": item.seq,
            "turn_id": item.turn_id,
            "item": view,
            "cursor": item.seq,
        }
        if live_id:
            data["live_id"] = live_id
        events = [
            SSEEvent(
                event_id=durable_event_id(item.seq, _COMPLETED),
                event_type=vocabulary.ITEM_COMPLETED,
                data=data,
                session_id=session_id,
                seq=item.seq,
            )
        ]
        run_type = None
        run: Dict[str, Any] = {"turn_id": item.turn_id, "seq": item.seq, "cursor": item.seq}
        if item.type == "turn_start":
            run_type = vocabulary.RUN_STARTED
            run.update(
                status="running",
                started_at=item.ts,
                model=view["model"],
                provider=view["provider"],
            )
        elif item.type == "turn_end":
            status = item.get("status")
            run_type = vocabulary.RUN_TERMINAL_EVENTS.get(status, vocabulary.RUN_FAILED)
            started_at = next(
                (candidate.ts for candidate in self._read(session_id)
                 if candidate.turn_id == item.turn_id and candidate.type == "turn_start"),
                None,
            )
            run.update(
                status=status,
                started_at=started_at,
                ended_at=item.ts,
                **{key: value for key, value in view.items()
                   if key not in {"seq", "ts", "turn_id", "type", "status"}},
            )
        if run_type is not None:
            events.append(
                SSEEvent(
                    event_id=durable_event_id(item.seq, _RUN),
                    event_type=run_type,
                    data=run,
                    session_id=session_id,
                    seq=item.seq,
                )
            )
        return events

    def _publish_item(self, session_id: str, tail: _Tail, item: ThreadItem) -> None:
        view = display_item(item)
        if view is None:
            return
        live: Optional[_LiveItem] = None
        if item.type == "turn_start":
            tail.completed_tools.clear()
            self._discard_live(session_id, tail, None)
        elif item.type == "assistant":
            if tail.assistant is not None and tail.assistant.turn_id == item.turn_id:
                live, tail.assistant = tail.assistant, None
        elif item.type == "tool_result":
            key = (item.turn_id, item.get("tool_call_id"))
            tail.completed_tools.add(key)
            live = _take_live(tail.tools, key)
        elif item.type in {"plan", "question"}:
            live = _take_live(tail.interactions, (item.turn_id, item.type))
        elif item.type == "user":
            content = item.get("content")
            for index, (input_id, queued_content, queued) in enumerate(tail.inputs):
                if (item.get("input_id") == input_id if item.get("input_id") else queued_content == content):
                    live = queued
                    del tail.inputs[index]
                    break
        elif item.type == "turn_end":
            self._discard_live(session_id, tail, item.turn_id)

        if live is None:
            started_kind, _ = _type_kinds(item.type, item.get("status"))
            self._publish(
                session_id,
                vocabulary.ITEM_STARTED,
                {
                    "kind": started_kind,
                    "seq": item.seq,
                    "turn_id": item.turn_id,
                    "item": copy.deepcopy(view),
                    "cursor": item.seq,
                },
                seq=item.seq,
                rank=_STARTED,
            )
        else:
            tail.live_by_seq[item.seq] = live.live_id
            while len(tail.live_by_seq) > _LIVE_ID_MEMORY:
                tail.live_by_seq.popitem(last=False)
        for event in self._recorded_events(session_id, item, live.live_id if live else None, view=view):
            self.bus.publish(event)

    def _discard(self, session_id: str, tail: _Tail, live: _LiveItem) -> None:
        self._publish(
            session_id,
            vocabulary.ITEM_COMPLETED,
            {
                "kind": vocabulary.DISCARDED_KIND,
                "live_id": live.live_id,
                "turn_id": live.turn_id,
                "item": {"type": live.type, "turn_id": live.turn_id, "status": "discarded"},
                "cursor": tail.last_seq,
            },
        )

    def _discard_live(self, session_id: str, tail: _Tail, turn_id: Optional[str]) -> None:
        """Close the live items of a turn (or all) that were never recorded."""
        if tail.assistant is not None and turn_id in (None, tail.assistant.turn_id):
            self._discard(session_id, tail, tail.assistant)
            tail.assistant = None
        for pending in (tail.tools, tail.interactions):
            for key in [key for key in pending if turn_id in (None, key[0])]:
                for live in pending.pop(key):
                    self._discard(session_id, tail, live)

    def _canonical_live_event(
        self, session_id: str, tail: _Tail, event_type: str, data: Dict[str, Any]
    ) -> Optional[SSEEvent]:
        """Attach cursor and correlation metadata to a canonical live event."""
        turn_id = data.get("attempt_id") or data.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            return None
        payload = dict(data)
        payload["turn_id"] = turn_id
        payload.setdefault("cursor", tail.last_seq)
        kind = payload.get("kind")
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        live_id = payload.get("live_id")
        if event_type == vocabulary.ITEM_STARTED and not isinstance(live_id, str):
            tail.counter += 1
            live_id = f"{turn_id}:live:{tail.counter}"
            payload["live_id"] = live_id
        if isinstance(live_id, str) and event_type == vocabulary.ITEM_STARTED:
            item_type = item.get("type") or ("tool_result" if kind == vocabulary.TOOL_STARTED else "assistant")
            live = _LiveItem(live_id, str(item_type), turn_id)
            if item_type == "assistant":
                if tail.assistant is not None:
                    self._discard(session_id, tail, tail.assistant)
                tail.assistant = live
            elif kind == vocabulary.TOOL_STARTED:
                call_id = item.get("tool_call_id") or payload.get("call_id")
                if isinstance(call_id, str):
                    tail.completed_tools.discard((turn_id, call_id))
                    tail.tools.setdefault((turn_id, call_id), []).append(live)
            elif item_type in {"plan", "question"}:
                tail.interactions.setdefault((turn_id, item_type), []).append(live)
            elif item_type == "user" and item.get("status") == "queued":
                input_id = item.get("input_id")
                content = item.get("content")
                if isinstance(input_id, str) and isinstance(content, str):
                    tail.inputs.append((input_id, content, live))
            payload["item"] = {"type": item_type, "turn_id": turn_id, "status": "in_progress", **item}
        if event_type == vocabulary.ITEM_COMPLETED and kind == vocabulary.DISCARDED_KIND:
            tail.inputs = [entry for entry in tail.inputs if entry[2].live_id != live_id]
        return SSEEvent(event_type=event_type, data=payload, session_id=session_id)
