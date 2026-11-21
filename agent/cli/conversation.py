"""CLI turns recorded through the session thread, the way a web turn is.

Every CLI entry that runs the agent inside a session (interactive REPL,
``run``, ``continue``, ``session`` chat) goes through :func:`open_turn`:

* the user's message is appended to ``messages.jsonl`` first, as the web
  service does when it accepts a message;
* :meth:`SessionRuntime.begin_turn` replays ``thread.jsonl`` (or, for a session
  recorded before it, the text rows of ``messages.jsonl``) into the model's
  history, and hands the loop a recorder that writes the turn's items;
* :meth:`CliTurn.finish` closes the turn in the thread and projects the
  display row (reply text and tool trail) into ``messages.jsonl``.

So a session started in the terminal resumes in the web UI, and the other way
round, with the same tool calls and results in the model's history.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.session.models import Message
from src.session.runtime import SessionRuntime, TurnRecorder
from src.session.service import STOPPED_MARKER
from src.session.store import SessionStore

logger = logging.getLogger(__name__)

_THREAD_STATUS = {"success": "completed", "cancelled": "cancelled"}
_EMPTY_REPLY = (
    "The run finished without producing any text output. "
    "Check the run artifacts, or rephrase the request and try again."
)


def record_message(store: SessionStore, message: Message) -> None:
    """Append a message to ``messages.jsonl`` and the FTS5 search index.

    Persistence is best effort: a failed write must not stop the turn. The two
    writes sit in separate ``try`` blocks so a search-index failure does not
    retry a JSONL write that succeeded.

    Args:
        store: Session store.
        message: Message to record.
    """
    try:
        store.append_message(message)
    except Exception:  # noqa: BLE001 - never block a turn on persistence
        logger.warning("Could not record a %s message", message.role, exc_info=True)
    try:
        from src.session.search import get_shared_index

        get_shared_index().index_message(message.session_id, message.role, message.content)
    except Exception:  # noqa: BLE001 - the search index is optional
        logger.debug("Could not index a %s message", message.role, exc_info=True)


def _reply_text(status: str, result: Dict[str, Any], streamed_text: str) -> str:
    """Return the assistant row's text, as the web service words it.

    Args:
        status: ``completed`` / ``cancelled`` / ``failed``.
        result: The loop's result dict.
        streamed_text: Text streamed to the user during the turn.

    Returns:
        The reply text shown in the transcript.
    """
    if status == "completed":
        return str(result.get("content") or "").strip() or _EMPTY_REPLY
    if status == "cancelled":
        streamed = streamed_text.strip()
        return f"{streamed}\n\n{STOPPED_MARKER}" if streamed else STOPPED_MARKER
    return f"Execution failed: {result.get('reason') or 'unknown error'}"


class CliTurn:
    """One CLI turn in progress.

    Attributes:
        turn_id: The turn (attempt) id written on every thread item.
        recorder: Sink the agent loop writes thread items through.
    """

    def __init__(
        self,
        store: SessionStore,
        runtime: SessionRuntime,
        recorder: TurnRecorder,
        session_id: str,
        prompt: str,
    ) -> None:
        """Create a turn; use :func:`open_turn`.

        Args:
            store: Session store.
            runtime: The session's runtime.
            recorder: The turn's recorder.
            session_id: Session id.
            prompt: The user's message.
        """
        self._store = store
        self._runtime = runtime
        self.recorder = recorder
        self.turn_id = recorder.turn_id
        self._session_id = session_id
        self._prompt = prompt
        self._started = time.perf_counter()
        self._finished = False

    @property
    def history(self) -> List[Dict[str, Any]]:
        """The replayed model history for this turn (no system prompt)."""
        return self.recorder.history

    def finish(self, result: Dict[str, Any], streamed_text: str = "") -> Dict[str, Any]:
        """Close the turn and write its display row.

        Args:
            result: The loop's result dict; ``usage`` is added to it.
            streamed_text: Text streamed to the user, kept in a stopped reply.

        Returns:
            ``result``, with the turn's token usage under ``usage``.
        """
        if self._finished:
            return result
        self._finished = True
        status = _THREAD_STATUS.get(str(result.get("status")), "failed")
        elapsed_ms = max(0, round((time.perf_counter() - self._started) * 1000))
        run_dir = result.get("run_dir")
        projection = None
        try:
            projection = self._runtime.finish_turn(
                self.turn_id,
                prompt=self._prompt,
                status=status,
                usage=self.recorder.usage,
                elapsed_ms=elapsed_ms,
                run_dir=str(run_dir) if run_dir else None,
            )
        except Exception:  # noqa: BLE001 - the reply below still gets written
            logger.warning("Could not close thread turn %s", self.turn_id, exc_info=True)
        metadata: Dict[str, Any] = {"status": status, "elapsed_ms": elapsed_ms}
        if run_dir:
            metadata["run_id"] = str(result.get("run_id") or Path(str(run_dir)).name)
        record_message(
            self._store,
            Message(
                session_id=self._session_id,
                role="user",
                content=self._prompt,
            )
        )
        record_message(
            self._store,
            Message(
                session_id=self._session_id,
                role="assistant",
                content=_reply_text(status, result, streamed_text),
                metadata=metadata,
                tool_trail=projection.tool_trail if projection is not None else [],
            ),
        )
        if self.recorder.usage:
            result["usage"] = dict(self.recorder.usage)
        return result

    def abort(self, status: str = "cancelled", reason: str = "Interrupted") -> None:
        """Close a turn whose run ended by an exception (a forced quit).

        Args:
            status: Loop status to close the turn with (``cancelled``/``failed``).
            reason: Why it ended, shown in a failed turn's reply.
        """
        self.finish({"status": status, "reason": reason})


def open_turn(store: SessionStore, session_id: str, prompt: str) -> Optional[CliTurn]:
    """Start a recorded turn in a session.

    Replays the session's history and opens the turn's recorder. A new session id gets a thread on
    its first turn; a session recorded before the thread existed keeps working
    through the text-only fallback of :meth:`SessionRuntime.begin_turn`.

    Args:
        store: Session store rooted at the user-level sessions directory.
        session_id: Session id.
        prompt: The user's message.

    Returns:
        The turn, or None when the session store cannot be used; the caller
        then runs the loop without history, as a store failure always did.
    """
    try:
        runtime = SessionRuntime(store.thread_log(session_id), session_id)
        recorder = runtime.begin_turn(
            uuid.uuid4().hex[:12], store.get_messages(session_id, limit=None)
        )
    except Exception:  # noqa: BLE001 - an unusable store must not block the turn
        logger.warning("Could not open a recorded turn for session %s", session_id, exc_info=True)
        return None
    return CliTurn(store, runtime, recorder, session_id, prompt)
