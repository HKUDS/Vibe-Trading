"""Restore session state and record each turn in the canonical thread."""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from src.session.replay import durable_tool_calls, replay_with_seqs
from src.session.thread import ThreadLog, open_turns
from src.session.thread_schema import ThreadItem, ThreadItemError

logger = logging.getLogger(__name__)

class TurnRecorder:
    """Append turn items and reject late worker writes after closing.

    Args:
        runtime: Runtime that owns the thread and folded session state.
        turn_id: The turn or attempt ID.
        history: Replayed model input for this turn, without the system prompt.
        history_seqs: Source sequences parallel to history, with None for synthetic messages.
        user_history: Earlier user-authored text used by the agent.
        queued_input_id: Queued input ID if delivery started this turn.
        provider: Provider label recorded on assistant items.
        model: Model label recorded on assistant items.
    """

    def __init__(
        self,
        runtime: "SessionRuntime",
        turn_id: str,
        history: List[Dict[str, Any]],
        history_seqs: List[Optional[int]],
        user_history: List[Dict[str, Any]],
        *,
        queued_input_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Create a recorder for one turn."""
        self._runtime = runtime
        self.turn_id = turn_id
        self.history = history
        self.user_history = user_history
        self.provider = provider
        self.model = model
        self.answer_to_question_id = runtime.pending_question_id()
        self.queued_input_id = queued_input_id
        state = runtime.state
        self.identity_state = copy.deepcopy(state.get("identity"))
        loaded = state.get("loaded_tools")
        self.loaded_tools = list(loaded) if isinstance(loaded, list) else None
        workspace = state.get("workspace_dir")
        self.session_workspace = workspace if isinstance(workspace, str) else None
        self.usage: Optional[Dict[str, Any]] = None
        self.degraded = False
        self.started = False
        self.max_seq = 0
        self._closed = False
        self._lock = threading.Lock()
        # Hold each message so its ID cannot be reused while indexed.
        self._seqs: Dict[int, Tuple[int, Dict[str, Any]]] = {}
        for message, seq in zip(history, history_seqs):
            if seq is not None:
                self._remember(message, seq)
        self._last_state: Optional[Dict[str, Any]] = None

    # Writing

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
            message: The user message the model receives, including any envelopes.
            model: Configured model name.
            provider: Provider name.
        """
        if self.started:
            return
        self.started = True
        self._write("turn_start", None, prompt=prompt, model=model, provider=provider)
        self._write_user(message, prompt, self.queued_input_id, self.answer_to_question_id)

    def user(
        self, message: Dict[str, Any], *, content: str, input_id: Optional[str] = None
    ) -> Optional[ThreadItem]:
        """Record a user message that joined the turn after it started.

        Args:
            message: The user message the model receives.
            content: The user's text as typed.
            input_id: Queue entry ID, when the message came from the pending-input queue.

        Returns:
            The recorded item, or None when the write failed or the turn has already finished.
        """
        return self._write_user(message, content, input_id, self._runtime.pending_question_id())

    def _write_user(
        self, message: Dict[str, Any], content: str, input_id: Optional[str], question_id: Optional[str],
    ) -> Optional[ThreadItem]:
        return self._write(
            "user", message, content=content, llm_content=message.get("content"),
            input_id=input_id, answer_to_question_id=question_id,
        )

    def assistant(self, message: Dict[str, Any], *, phase: str) -> None:
        """Record one model response as it enters the model's messages.

        Args:
            message: OpenAI-format assistant message.
            phase: Commentary when more steps follow, or final for the answer.
        """
        self._write(
            "assistant",
            message,
            content=message.get("content"),
            tool_calls=durable_tool_calls(message),
            reasoning_content=message.get("reasoning_content"),
            provider_items=message.get("provider_items") or None,
            provider=self.provider,
            model=self.model,
            phase=phase,
        )

    def tool_result(
        self,
        message: Dict[str, Any],
        *,
        status: str,
        elapsed_ms: Optional[float] = None,
        artifact: Optional[Dict[str, Any]] = None,
        images: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        """Record one delivered (redacted, size-capped) tool result.

        Args:
            message: The tool-role message the model receives.
            status: Result status, ok or error.
            elapsed_ms: Execution time in milliseconds, when available.
            artifact: Display-only artifact metadata.
            images: Image metadata to store alongside the textual result.
        """
        durable_content = message.get("content")
        if not isinstance(durable_content, str):
            parts = []
            for part in durable_content if isinstance(durable_content, list) else [durable_content]:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    parts.append(f"[image artifact: {(part.get('image_url') or {}).get('url', '')}]")
            durable_content = "\n".join(parts)
        self._write(
            "tool_result",
            message,
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name") or "",
            content=durable_content,
            status=status,
            elapsed_ms=elapsed_ms,
            artifact=artifact,
            images=images,
        )

    def hook(self, decision: Dict[str, Any]) -> None:
        """Record a redacted command-hook decision in the thread audit.

        Args:
            decision: Fields describing the command-hook decision.
        """
        self._write("hook_decision", None, **dict(decision))

    def write(self, event: Dict[str, Any]) -> None:
        """Record a diagnostic event in the conversation thread.

        Args:
            event: Diagnostic mapping whose type becomes the event name, defaulting to event.
        """
        if not isinstance(event, dict):
            return
        payload = copy.deepcopy(event)
        name = payload.pop("type", "event")
        if not isinstance(name, str) or not name:
            name = "event"
        self._write("event", None, name=name, data=payload)

    def plan(self, plan_id: str, steps: list[dict[str, Any]]) -> None:
        """Record a structured plan in the turn's thread.

        Args:
            plan_id: Identifier of the plan being recorded.
            steps: Plan steps in display order.
        """
        self._write("plan", None, plan_id=plan_id, steps=steps)

    def question(self, question_id: str, prompt: str, options: list[str], allow_free_text: bool = True) -> None:
        """Record a structured question for the user.

        Args:
            question_id: Identifier used to associate an answer with the question.
            prompt: Question shown to the user.
            options: Selectable answers.
            allow_free_text: Whether to accept an answer outside the listed options.
        """
        self._write("question", None, question_id=question_id, prompt=prompt, options=options, allow_free_text=allow_free_text)

    def inject(self, message: Dict[str, Any]) -> None:
        """Record a message the loop added on its own (``<system>`` notes).

        Args:
            message: Injected message containing content and an optional role, which defaults to
                user.
        """
        self._write("inject", message, content=message.get("content"), role=message.get("role") or "user")

    def compaction(self, message: Dict[str, Any], kept: Iterable[Dict[str, Any]]) -> None:
        """Record a layer-3 summary so the next replay starts from it.

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

    def compaction_layer(self, layer: int, messages: Iterable[Dict[str, Any]]) -> None:
        """Record L1/L2 message replacements keyed by original seq for exact replay.

        Args:
            layer: Compaction layer, either 1 or 2.
            messages: Replacement messages with original thread sequences known to this recorder.
        """
        changes = []
        for message in messages:
            seq = self.seq_of(message)
            if seq is not None:
                durable = copy.deepcopy(message)
                if durable.get("role") == "assistant" and durable.get("tool_calls"):
                    durable["tool_calls"] = durable_tool_calls(message)
                    if "tool_calls" in (durable.get("additional_kwargs") or {}):
                        durable["additional_kwargs"]["tool_calls"] = durable["tool_calls"]
                changes.append({"seq": seq, "message": durable})
        if not changes:
            return
        payload: Dict[str, Any] = {
            "summary": "",
            "replaces_through_seq": 0,
            "layer": layer,
            "changes": changes,
        }
        self._write("compaction", None, **payload)

    def state(self, snapshot: Dict[str, Any]) -> None:
        """Record a state snapshot when it differs from the last one.

        Args:
            snapshot: JSON-serializable session state to persist and fold into the runtime.
        """
        if snapshot == self._last_state:
            return
        item = self._write("state", None, **snapshot)
        if item is not None:
            self._last_state = copy.deepcopy(snapshot)
            self._runtime.update_state(snapshot)

    def record_checkpoint(self, content: str) -> None:
        """Record the latest streamed text in the conversation log.

        Args:
            content: Latest accumulated assistant response text.
        """
        self._write("checkpoint", None, content=content)

    def prepare_workspace(self, run_dir: Path) -> None:
        """Ensure the shared artifact workspace exists before tool execution.

        Args:
            run_dir: This turn's run directory, accepted by the recorder interface. The workspace
                path comes from session state.
        """
        if self.session_workspace:
            Path(self.session_workspace).mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """Stop recording; later writes are dropped."""
        with self._lock:
            self._closed = True

    # Reading

    def seq_of(self, message: Mapping[str, Any]) -> Optional[int]:
        """Return the seq of the item a message was recorded as.

        Args:
            message: A message object from the loop's message list.

        Returns:
            The source sequence, or None if this object has no recorded item.
        """
        entry = self._seqs.get(id(message))
        if entry is not None and entry[1] is message:
            return entry[0]
        return None

    # Internals

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
                if self._runtime.require_durable_items:
                    raise
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


# Runtime


class SessionRuntime:
    """Keep the thread and folded state across turns.

    Args:
        thread: The session's thread log, used to restore state and locate the workspace.
        session_id: Session ID.
        require_durable_items: Whether failures to write durable items should propagate.
    """

    def __init__(self, thread: ThreadLog, session_id: str, *, require_durable_items: bool = False) -> None:
        """Open the runtime and rebuild its state from the thread."""
        self.session_id = session_id
        self.thread = thread
        self.require_durable_items = require_durable_items
        self.workspace_path = thread.path.parent / "workspace"
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Any] = {}
        self._recorders: Dict[str, TurnRecorder] = {}
        self._lock = threading.Lock()
        for item in thread.read():
            if item.type == "state":
                self.state.update(copy.deepcopy(item.data))
        self.state.setdefault("workspace_dir", str(self.workspace_path))

    def update_state(self, snapshot: Mapping[str, Any]) -> None:
        """Fold a recorded snapshot into the live state.

        Args:
            snapshot: The snapshot just written to the thread.
        """
        with self._lock:
            self.state.update(copy.deepcopy(dict(snapshot)))

    def replay_history(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Optional[int]], List[Dict[str, Any]]]:
        """Return replayed messages, source seqs, and earlier user messages.

        Args:
            provider: Target provider for filtering provider-native assistant metadata.
            model: Target model for filtering provider-native assistant metadata.

        Returns:
            Replayed model messages, their parallel source sequences, and all recorded user
            messages.
        """
        items = self.thread.read()
        replayed, seqs = replay_with_seqs(items, provider=provider, model=model)
        user_history = [
            {"role": "user", "content": item.get("content")}
            for item in items
            if item.type == "user" and isinstance(item.get("content"), str)
        ]
        return replayed, seqs, user_history

    def pending_question_id(self) -> Optional[str]:
        """Return the latest unanswered structured question.

        Returns:
            The latest question ID without a recorded answer, or None.
        """
        items = self.thread.read()
        answered = {item.get("answer_to_question_id") for item in items if item.type == "user"}
        for item in reversed(items):
            if item.type == "question" and item.get("question_id") not in answered:
                return item.get("question_id")
        return None

    def begin_turn(
        self,
        turn_id: str,
        *,
        queued_input_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> TurnRecorder:
        """Close stale turns as interrupted before replay and return the new recorder.

        Args:
            turn_id: The new turn or attempt ID.
            queued_input_id: Queued input ID if delivery started this turn.
            provider: Target provider used to replay history and label assistant items.
            model: Target model used to replay history and label assistant items.

        Returns:
            The turn's recorder, carrying its replayed history.
        """
        items = self.thread.read()
        for stale in open_turns(items):
            if stale != turn_id:
                self._append_safely("turn_end", stale, status="interrupted")
        history, history_seqs, user_history = self.replay_history(provider=provider, model=model)
        recorder = TurnRecorder(
            self,
            turn_id,
            history=history,
            history_seqs=history_seqs,
            queued_input_id=queued_input_id,
            user_history=user_history,
            provider=provider,
            model=model,
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
        metadata: Optional[Dict[str, Any]] = None,
        display: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Close a turn once, recording the prompt if execution never opened it.

        Args:
            turn_id: Turn or attempt ID.
            prompt: The user's message, recorded if the turn never opened.
            status: Terminal turn status to persist.
            usage: Token usage totals, when available.
            elapsed_ms: Turn duration in milliseconds.
            run_dir: The turn's run directory, used by the tool trail.
            summary: Reply text for reconnect and history.
            error: Failure reason for the durable turn event.
            provider: Provider used by the turn.
            model: Model used by the turn.
            pending_inputs: Client-facing snapshot of the pending input queue, when available.
            metadata: Derived reply metadata for transcript readers.
            display: Client-facing turn facts carried on the terminal event, when any.
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
                metadata=metadata, display=display,
            )

    def partial_response(self, turn_id: str) -> Optional[str]:
        """Return the latest durable streaming checkpoint for a turn.

        Args:
            turn_id: Turn ID whose streaming checkpoints to inspect.

        Returns:
            Text from the latest checkpoint, or None if no checkpoint exists.
        """
        return next(
            (item.get("content") for item in reversed(self.thread.read())
             if item.turn_id == turn_id and item.type == "checkpoint"),
            None,
        )

    def record_checkpoint(self, turn_id: str, content: str) -> None:
        """Append a streamed-text checkpoint to the session thread.

        Args:
            turn_id: Turn ID for the item. Its active recorder is used when available.
            content: Latest accumulated assistant response text.
        """
        with self._lock:
            recorder = self._recorders.get(turn_id)
        if recorder is not None:
            recorder.record_checkpoint(content)
        else:
            self._append_safely("checkpoint", turn_id, content=content)

    def _append_safely(self, item_type: str, turn_id: str, **payload: Any) -> None:
        try:
            self.thread.append(item_type, turn_id, **payload)
        except (OSError, ThreadItemError) as exc:
            logger.warning("Could not record %s for turn %s: %s", item_type, turn_id, exc)


class SessionRuntimes:
    """Own this service's per-conversation runtimes, shared by maintenance and attempts.

    Args:
        thread_log: Callable resolving a session ID to its durable thread log.
    """

    def __init__(self, thread_log: Callable[[str], ThreadLog]) -> None:
        self._thread_log = thread_log
        self._sessions: dict[str, SessionRuntime] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> SessionRuntime:
        """Rebuild a conversation from its thread on first use.

        Args:
            session_id: Session ID.

        Returns:
            The cached session runtime, created from its thread on first use.
        """
        with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                runtime = SessionRuntime(self._thread_log(session_id), session_id)
                self._sessions[session_id] = runtime
            return runtime

    def discard(self, session_id: str) -> None:
        """Release the cached runtime after its session has been deleted.

        Args:
            session_id: Session ID whose cached runtime should be removed.
        """
        with self._lock:
            self._sessions.pop(session_id, None)
