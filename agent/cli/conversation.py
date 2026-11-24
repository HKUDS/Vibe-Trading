"""CLI turns recorded through the session thread, the way a web turn is."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.tools.redaction import redact_text
from src.session.runtime import SessionRuntime, TurnRecorder
from src.session.attempts import STOPPED_MARKER
from src.session.store import SessionStore

logger = logging.getLogger(__name__)

_THREAD_STATUS = {"success": "completed", "cancelled": "cancelled", "waiting_user": "waiting_user"}
_EMPTY_REPLY = (
    "The run finished without producing any text output. "
    "Check the run artifacts, or rephrase the request and try again."
)


def index_message(session_id: str, role: str, content: str) -> None:
    """Refresh the optional FTS index from a thread-derived message."""
    try:
        from src.session.search import get_shared_index
        get_shared_index().index_message(session_id, role, content)
    except Exception:  # noqa: BLE001 - the search index is optional
        logger.debug("Could not index a %s message", role, exc_info=True)


def _reply_text(status: str, result: Dict[str, Any], streamed_text: str) -> str:
    """Return the assistant row's text, as the web service words it."""
    if status == "completed":
        return str(result.get("content") or "").strip() or _EMPTY_REPLY
    if status == "waiting_user":
        return str(result.get("content") or "").strip() or "Please answer the question above."
    if status == "cancelled":
        streamed = streamed_text.strip()
        return f"{streamed}\n\n{STOPPED_MARKER}" if streamed else STOPPED_MARKER
    return f"Execution failed: {result.get('reason') or 'unknown error'}"


class CliTurn:
    """One CLI turn in progress."""

    def __init__(
        self,
        store: SessionStore,
        runtime: SessionRuntime,
        recorder: TurnRecorder,
        session_id: str,
        prompt: str,
    ) -> None:
        """Create a turn; use :func:`open_turn`."""
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
        """Close the turn and write its display row."""
        if self._finished:
            return result
        self._finished = True
        status = _THREAD_STATUS.get(str(result.get("status")), "failed")
        if result.get("reason"):
            result["reason"] = redact_text(result["reason"])
        elapsed_ms = max(0, round((time.perf_counter() - self._started) * 1000))
        run_dir = result.get("run_dir")
        reply_text = _reply_text(status, result, streamed_text)
        metadata: Dict[str, Any] = {"status": status, "elapsed_ms": elapsed_ms}
        if run_dir:
            metadata["run_id"] = str(result.get("run_id") or Path(str(run_dir)).name)
        try:
            self._runtime.finish_turn(
                self.turn_id,
                prompt=self._prompt,
                status=status,
                usage=self.recorder.usage,
                elapsed_ms=elapsed_ms,
                run_dir=str(run_dir) if run_dir else None,
                summary=reply_text,
                error=result.get("reason"),
                metadata=metadata,
            )
        except Exception:  # noqa: BLE001 - the thread close still gets reported
            logger.warning("Could not close thread turn %s", self.turn_id, exc_info=True)
        index_message(self._session_id, "user", self._prompt)
        index_message(self._session_id, "assistant", reply_text)
        if self.recorder.usage:
            result["usage"] = dict(self.recorder.usage)
        return result

    def abort(self, status: str = "cancelled", reason: str = "Interrupted") -> None:
        """Close a turn whose run ended by an exception (a forced quit)."""
        self.finish({"status": status, "reason": reason})


def open_turn(
    store: SessionStore,
    session_id: str,
    prompt: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[CliTurn]:
    """Start a recorded turn in a session."""
    try:
        runtime = SessionRuntime(store.thread_log(session_id), session_id)
        recorder = runtime.begin_turn(
            uuid.uuid4().hex[:12],
            provider=provider, model=model,
        )
    except Exception:  # noqa: BLE001 - an unusable store must not block the turn
        logger.warning("Could not open a recorded turn for session %s", session_id, exc_info=True)
        return None
    return CliTurn(store, runtime, recorder, session_id, prompt)
