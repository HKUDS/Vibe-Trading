"""Session-level runtime: the conversation, not the run, is the kernel's unit.

One :class:`SessionRuntime` lives per session for as long as the process does
and is rebuilt from the thread's ``state`` items after a restart. It owns what
used to be thrown away at the end of every attempt:

* the model input of the next turn, replayed from ``thread.jsonl``;
* the instrument-identity ledger's own records;
* the tool schemas the conversation has loaded;
* the tool-result files earlier turns offloaded, so a later turn's
  ``read_file`` reaches them by the relative path their receipt names.

Each turn gets a :class:`TurnRecorder`, the sink ``AgentLoop`` writes thread
items through. The loop stays usable without one (CLI, tests).

Replayed history is conversation text only. Identity authorization is restored
from the ledger's persisted records in ``state`` items, never parsed out of
what the model said or saw.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.session.thread import (
    ThreadItem,
    ThreadItemError,
    ThreadLog,
    TurnProjection,
    _assistant_message,
    last_compaction,
    open_turns,
    project_turn,
    replay,
)

logger = logging.getLogger(__name__)

#: Directory, inside a run directory, that ``deliver_tool_result`` and
#: ``persist_calculation_result`` offload complete tool results into.
TOOL_RESULTS_DIRNAME = "tool-results"

_RUN_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,80}")
_RUN_DIRECTORY_RE = re.compile(r"Run directory:\s*\S+")


# ---- History ----


def legacy_history(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Text-only history for messages a session recorded before its thread log.

    Sessions created before ``thread.jsonl`` existed have only
    ``messages.jsonl``: one user row and one assistant reply per turn. Their
    text is all there is to replay. A trailing user row is the turn being
    answered now, so it is left out. Size is not capped here; the loop's
    context budget compacts replayed history like any other.

    The run id of a reply lives only in its metadata, so it is written into
    the reply as ``[prev_run: <id>]`` for a later turn to find that run.

    Args:
        rows: ``Message`` objects or dicts in chronological order.

    Returns:
        OpenAI-format user/assistant messages.
    """
    rows = list(rows)
    if rows and _field(rows[-1], "role") == "user":
        rows = rows[:-1]

    def _shorten_run_dir(match: re.Match) -> str:
        path_str = match.group(0).replace("Run directory:", "").strip()
        run_id = Path(path_str).name if path_str else ""
        return f"[prev_run: {run_id}]" if run_id else ""

    history: List[Dict[str, Any]] = []
    for row in rows:
        role = _field(row, "role") or "user"
        content = _field(row, "content") or ""
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        content = _RUN_DIRECTORY_RE.sub(_shorten_run_dir, content).strip()
        metadata = _field(row, "metadata")
        run_id = metadata.get("run_id") if isinstance(metadata, Mapping) else None
        marker = f"[prev_run: {run_id}]"
        if (
            role == "assistant"
            and content
            and isinstance(run_id, str)
            and _RUN_ID_RE.fullmatch(run_id)
            and marker not in content
        ):
            content = f"{marker}\n{content}"
        if content:
            history.append({"role": role, "content": content})
    return history


def _field(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _created_ts(row: Any) -> Optional[float]:
    value = _field(row, "created_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _rows_before_thread(rows: Sequence[Any], items: Sequence[ThreadItem]) -> List[Any]:
    """Return the ``messages.jsonl`` rows the thread log does not cover.

    With no thread yet, every row is legacy. Otherwise a row is legacy when it
    was written before the thread's first item.
    """
    if not items:
        return list(rows)
    first_ts = items[0].ts
    return [row for row in rows if (_created_ts(row) or float("inf")) < first_ts]


def _message_key(message: Mapping[str, Any]) -> str:
    return json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)


def _item_message(item: ThreadItem) -> Optional[Dict[str, Any]]:
    """The message replay builds from one item, or None for non-model items."""
    if item.type == "user":
        return {"role": "user", "content": item.get("llm_content")}
    if item.type == "assistant":
        return _assistant_message(item)
    if item.type == "tool_result":
        return {
            "role": "tool",
            "tool_call_id": item.get("tool_call_id"),
            "name": item.get("name"),
            "content": item.get("content"),
        }
    if item.type == "inject":
        return {"role": item.get("role"), "content": item.get("content")}
    return None


def replay_with_seqs(items: Sequence[ThreadItem]) -> Tuple[List[Dict[str, Any]], List[Optional[int]]]:
    """Replay the thread and name the item each replayed message came from.

    A compaction recorded mid-turn has to say which items its summary
    replaces, and the messages it folds include replayed history. Messages
    replay synthesised (the compaction summary, interrupted-call stubs,
    stopped-turn notes) have no item and map to None.

    Args:
        items: Thread items in write order.

    Returns:
        ``(messages, seqs)`` of equal length.
    """
    messages = replay(items)
    compaction = last_compaction(items)
    start_after = compaction.get("replaces_through_seq") if compaction is not None else 0
    pool: Dict[str, List[int]] = {}
    for item in items:
        if item.seq <= start_after:
            continue
        message = _item_message(item)
        if message is not None:
            pool.setdefault(_message_key(message), []).append(item.seq)
    seqs: List[Optional[int]] = []
    for message in messages:
        queue = pool.get(_message_key(message))
        seqs.append(queue.pop(0) if queue else None)
    return messages, seqs


# ---- Workspace ----


def carry_tool_results(previous_run_dir: Optional[str], run_dir: Path) -> int:
    """Make earlier turns' offloaded tool results readable from this turn.

    A tool-result receipt tells the model to read ``tool-results/...`` relative
    to its current workspace, and ``read_file`` only reads the active run
    directory. Each turn still gets its own run directory (its id is the turn's
    public identity for run cards, ``state.json`` and ``/runs/{id}``), so the
    files are hard-linked forward: content-addressed and written once, they are
    safe to share. A filesystem without hard links gets a copy.

    The previous turn's directory already carries everything before it, so
    linking from it alone is enough.

    Args:
        previous_run_dir: Run directory of the session's previous turn.
        run_dir: This turn's run directory.

    Returns:
        Number of files made available.
    """
    if not previous_run_dir:
        return 0
    from src.tools.path_utils import safe_run_dir

    try:
        previous = safe_run_dir(str(previous_run_dir))
    except ValueError:
        logger.warning("Not carrying tool results from %s: outside the run roots", previous_run_dir)
        return 0
    source = previous / TOOL_RESULTS_DIRNAME
    if not source.is_dir() or previous == Path(run_dir).resolve():
        return 0
    target_root = Path(run_dir) / TOOL_RESULTS_DIRNAME
    carried = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        target = target_root / path.relative_to(source)
        if target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, target)
            except OSError:
                shutil.copy2(path, target)
            carried += 1
        except OSError as exc:
            logger.warning("Could not carry tool result %s forward: %s", path, exc)
    return carried


# ---- Recorder ----


class TurnRecorder:
    """Thread sink for one turn.

    ``AgentLoop`` writes every item of the turn through this object: the user
    message as sent, each model response, each delivered tool result, loop
    injections, compactions and state snapshots. A write failure is logged and
    the turn continues, as a failed trace or checkpoint write does; the
    recorder then reports ``degraded``.

    After :meth:`close` (the service finished the turn) further writes are
    dropped, so a loop thread that outlives its turn cannot interleave items
    into the next one.

    Attributes:
        turn_id: The turn (attempt) id.
        history: Replayed model input for this turn, without the system prompt.
        user_history: Earlier user-authored text, for resolver constraints.
        identity_state: Identity ledger records restored from ``state``.
        loaded_tools: Tool names exposed so far, or None for a new session.
        previous_workspace: Run directory of the previous turn.
        usage: Token usage the loop reports at the end of the turn.
        degraded: Whether any write failed.
    """

    def __init__(
        self,
        runtime: "SessionRuntime",
        turn_id: str,
        history: List[Dict[str, Any]],
        history_seqs: List[Optional[int]],
        user_history: List[Dict[str, Any]],
    ) -> None:
        """Create a recorder for one turn.

        Args:
            runtime: Owning session runtime.
            turn_id: The turn (attempt) id.
            history: Replayed history messages.
            history_seqs: Source item seq per history message.
            user_history: Earlier user-authored messages.
        """
        self._runtime = runtime
        self.turn_id = turn_id
        self.history = history
        self.user_history = user_history
        state = runtime.state
        self.identity_state = copy.deepcopy(state.get("identity"))
        loaded = state.get("loaded_tools")
        self.loaded_tools = list(loaded) if isinstance(loaded, list) else None
        workspace = state.get("workspace")
        self.previous_workspace = workspace if isinstance(workspace, str) else None
        self.usage: Optional[Dict[str, Any]] = None
        self.degraded = False
        self.started = False
        self.max_seq = 0
        self._closed = False
        self._lock = threading.Lock()
        # id(message) -> (seq, message); the message is held so its id is
        # never reused by another object while it is mapped.
        self._seqs: Dict[int, Tuple[int, Dict[str, Any]]] = {}
        for message, seq in zip(history, history_seqs):
            if seq is not None:
                self._remember(message, seq)
        self._last_state: Optional[Dict[str, Any]] = None

    # ---- Writing ----

    def start(
        self,
        *,
        prompt: str,
        message: Dict[str, Any],
        model: Optional[str],
        provider: Optional[str],
    ) -> None:
        """Record the turn's start and the user message exactly as sent.

        Args:
            prompt: The user's text as typed.
            message: The user message the model receives (with envelopes).
            model: Configured model name.
            provider: Provider name.
        """
        if self.started:
            return
        self.started = True
        self._write("turn_start", None, prompt=prompt, model=model, provider=provider)
        self._write("user", message, content=prompt, llm_content=message.get("content"))

    def user(self, message: Dict[str, Any], *, content: str) -> Optional[ThreadItem]:
        """Record a user message that joined the turn after it started.

        A message sent while the turn was running (``src.session.pending_inputs``)
        enters the model input between a tool batch and the next model call.

        Args:
            message: The user message the model receives.
            content: The user's text as typed.

        Returns:
            The recorded item, or None when the write failed or the turn has
            already finished; the caller must then keep the input pending.
        """
        return self._write("user", message, content=content, llm_content=message.get("content"))

    def assistant(self, message: Dict[str, Any], *, phase: str) -> None:
        """Record one model response as it enters the model's messages.

        Args:
            message: OpenAI-format assistant message.
            phase: ``commentary`` (more steps follow) or ``final``.
        """
        self._write(
            "assistant",
            message,
            content=message.get("content"),
            tool_calls=list(message.get("tool_calls") or []),
            reasoning_content=message.get("reasoning_content"),
            provider_items=message.get("provider_items") or None,
            phase=phase,
        )

    def tool_result(
        self,
        message: Dict[str, Any],
        *,
        status: str,
        elapsed_ms: Optional[float] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one delivered (redacted, size-capped) tool result.

        Args:
            message: The ``role: tool`` message the model receives.
            status: ``ok`` or ``error``.
            elapsed_ms: Execution time.
            artifact: Display-only report link.
        """
        self._write(
            "tool_result",
            message,
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name") or "",
            content=message.get("content"),
            status=status,
            elapsed_ms=elapsed_ms,
            artifact=artifact,
        )

    def inject(self, message: Dict[str, Any]) -> None:
        """Record a message the loop added on its own (``<system>`` notes).

        Args:
            message: The injected message.
        """
        self._write("inject", message, content=message.get("content"), role=message.get("role") or "user")

    def compaction(self, message: Dict[str, Any], kept: Iterable[Dict[str, Any]]) -> None:
        """Record a layer-3 summary so the next replay starts from it.

        The items the summary folded stay in the file; only replay skips them.

        Args:
            message: The summary message that replaced the folded head.
            kept: Messages the compaction preserved after the summary.
        """
        kept_seqs = [seq for seq in (self.seq_of(m) for m in kept) if seq is not None]
        through = min(kept_seqs) - 1 if kept_seqs else self.max_seq
        if through < 0:
            return
        item = self._write(
            "compaction", None, summary=message.get("content"), replaces_through_seq=through,
        )
        if item is not None:
            self._remember(message, item.seq)

    def state(self, snapshot: Dict[str, Any]) -> None:
        """Record a state snapshot when it differs from the last one.

        Args:
            snapshot: JSON-serialisable session state.
        """
        if snapshot == self._last_state:
            return
        item = self._write("state", None, **snapshot)
        if item is not None:
            self._last_state = copy.deepcopy(snapshot)
            self._runtime.update_state(snapshot)

    def prepare_workspace(self, run_dir: Path) -> None:
        """Bring earlier turns' offloaded tool results into this run directory.

        Args:
            run_dir: This turn's run directory.
        """
        carry_tool_results(self.previous_workspace, Path(run_dir))

    def close(self) -> None:
        """Stop recording; later writes are dropped."""
        with self._lock:
            self._closed = True

    # ---- Reading ----

    def seq_of(self, message: Mapping[str, Any]) -> Optional[int]:
        """Return the seq of the item a message was recorded as.

        Args:
            message: A message object from the loop's message list.

        Returns:
            The item seq, or None for a message the thread does not hold.
        """
        entry = self._seqs.get(id(message))
        if entry is None or entry[1] is not message:
            return None
        return entry[0]

    # ---- Internals ----

    def _remember(self, message: Dict[str, Any], seq: int) -> None:
        self._seqs[id(message)] = (seq, message)
        self.max_seq = max(self.max_seq, seq)

    def _write(self, item_type: str, message: Optional[Dict[str, Any]], **payload: Any) -> Optional[ThreadItem]:
        with self._lock:
            if self._closed:
                logger.info("Dropped a %s item for finished turn %s", item_type, self.turn_id)
                return None
            try:
                item = self._runtime.thread.append(item_type, self.turn_id, **payload)
            except (OSError, ThreadItemError) as exc:
                self.degraded = True
                logger.warning(
                    "Could not record %s item for turn %s: %s", item_type, self.turn_id, exc,
                    exc_info=True,
                )
                return None
            if message is not None:
                self._remember(message, item.seq)
            else:
                self.max_seq = max(self.max_seq, item.seq)
            return item


# ---- Runtime ----


class SessionRuntime:
    """Per-session state that outlives one turn.

    Attributes:
        session_id: Session id.
        thread: The session's thread log.
        state: Folded ``state`` items (identity, loaded_tools, workspace).
    """

    def __init__(self, thread: ThreadLog, session_id: str) -> None:
        """Open the runtime and rebuild its state from the thread.

        Args:
            thread: The session's thread log.
            session_id: Session id.
        """
        self.session_id = session_id
        self.thread = thread
        self.state: Dict[str, Any] = {}
        self._recorders: Dict[str, TurnRecorder] = {}
        self._lock = threading.Lock()
        for item in thread.read():
            if item.type == "state":
                self.state.update(copy.deepcopy(item.data))

    def update_state(self, snapshot: Mapping[str, Any]) -> None:
        """Fold a recorded snapshot into the live state.

        Args:
            snapshot: The snapshot just written.
        """
        with self._lock:
            self.state.update(copy.deepcopy(dict(snapshot)))

    def begin_turn(self, turn_id: str, rows: Sequence[Any]) -> TurnRecorder:
        """Prepare one turn: close stale turns, replay history, open a recorder.

        A turn that started in this thread and never ended belongs to a run the
        process lost (an event-loop shutdown it survived, for instance). It is
        closed as ``interrupted`` before this turn starts, so replay closes its
        tool block where it really ended.

        Args:
            turn_id: The new turn (attempt) id.
            rows: The session's ``messages.jsonl`` rows, for a session whose
                history began before its thread log.

        Returns:
            The turn's recorder, carrying its replayed history.
        """
        items = self.thread.read()
        for stale in open_turns(items):
            if stale != turn_id:
                self._append_safely("turn_end", stale, status="interrupted")
        items = self.thread.read()
        prefix_rows = [] if last_compaction(items) is not None else _rows_before_thread(rows, items)
        prefix = legacy_history(prefix_rows)
        replayed, seqs = replay_with_seqs(items)
        user_history = [m for m in prefix if m["role"] == "user"] + [
            {"role": "user", "content": item.get("content")}
            for item in items
            if item.type == "user" and isinstance(item.get("content"), str)
        ]
        recorder = TurnRecorder(
            self,
            turn_id,
            history=prefix + replayed,
            history_seqs=[None] * len(prefix) + seqs,
            user_history=user_history,
        )
        with self._lock:
            self._recorders[turn_id] = recorder
        return recorder

    def finish_turn(
        self,
        turn_id: str,
        *,
        prompt: str,
        status: str,
        usage: Optional[Dict[str, Any]] = None,
        elapsed_ms: Optional[float] = None,
        run_dir: Optional[str] = None,
        summary: Optional[str] = None,
        error: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        pending_inputs: Optional[list[Dict[str, Any]]] = None,
    ) -> TurnProjection:
        """Close a turn in the thread and project its display row.

        A turn that never reached the model (it failed or was cancelled while
        its tools were still being built) has no ``turn_start``; the user's
        message is recorded as typed so the next turn still sees what was
        asked. ``turn_end`` is written once.

        Args:
            turn_id: Turn (attempt) id.
            prompt: The user's message.
            status: ``completed`` / ``cancelled`` / ``failed`` / ``interrupted``.
            usage: Token usage totals.
            elapsed_ms: Turn duration.
            run_dir: The turn's run directory, for the trail's arguments.
            summary: Stored reply text for durable run events.
            error: Stored failure reason for durable run events.
            provider: Provider used by the turn.
            model: Model used by the turn.

        Returns:
            The turn's projection onto the legacy display row.
        """
        with self._lock:
            recorder = self._recorders.pop(turn_id, None)
        if recorder is not None:
            recorder.close()
        items = self.thread.read()
        turn_types = {item.type for item in items if item.turn_id == turn_id}
        if "turn_start" not in turn_types:
            self._append_safely("turn_start", turn_id, prompt=prompt)
            self._append_safely("user", turn_id, content=prompt, llm_content=prompt)
        if "turn_end" not in turn_types:
            self._append_safely(
                "turn_end", turn_id, status=status, usage=usage, elapsed_ms=elapsed_ms,
                summary=summary, error=error, run_dir=run_dir,
                provider=provider, model=model, pending_inputs=pending_inputs,
            )
        return project_turn(self.thread.read(), turn_id, run_dir=run_dir)

    def _append_safely(self, item_type: str, turn_id: str, **payload: Any) -> None:
        try:
            self.thread.append(item_type, turn_id, **payload)
        except (OSError, ThreadItemError) as exc:
            logger.warning("Could not record %s for turn %s: %s", item_type, turn_id, exc)
