"""Filesystem-backed persistence for Session, Message, and Attempt records."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.session.models import Attempt, Message, Session

logger = logging.getLogger(__name__)


class SessionStore:
    """Filesystem-backed persistent storage.

    Directory structure::

        sessions/
        ├── {session_id}/
        │   ├── session.json
        │   ├── messages.jsonl
        │   └── attempts/
        │       └── {attempt_id}/
        │           └── attempt.json

    Attributes:
        base_dir: Root directory for session storage.
    """

    def __init__(self, base_dir: Path) -> None:
        """Initialize session storage.

        Args:
            base_dir: Root directory for session storage.
        """
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def _session_file(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    def _messages_file(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "messages.jsonl"

    def _attempt_dir(self, session_id: str, attempt_id: str) -> Path:
        return self._session_dir(session_id) / "attempts" / attempt_id

    def _attempt_file(self, session_id: str, attempt_id: str) -> Path:
        return self._attempt_dir(session_id, attempt_id) / "attempt.json"

    def _partial_response_file(self, session_id: str, attempt_id: str) -> Path:
        return self._attempt_dir(session_id, attempt_id) / "partial_response.json"

    # ---- Session CRUD ----

    def create_session(self, session: Session) -> Session:
        """Create and persist a session.

        Args:
            session: Session instance to create.

        Returns:
            The persisted Session.

        Raises:
            ValueError: Raised when the session already exists.
        """
        session_dir = self._session_dir(session.session_id)
        if session_dir.exists():
            raise ValueError(f"Session {session.session_id} already exists")
        session_dir.mkdir(parents=True)
        (session_dir / "attempts").mkdir()
        self._write_json(self._session_file(session.session_id), session.to_dict())
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Read a session.

        Args:
            session_id: Session ID.

        Returns:
            The Session instance, or None when it does not exist.
        """
        path = self._session_file(session_id)
        data = self._read_json(path)
        if data is None:
            return None
        return Session.from_dict(data)

    def update_session(self, session: Session) -> None:
        """Update a session.

        Args:
            session: Modified Session instance.
        """
        self._write_json(self._session_file(session.session_id), session.to_dict())

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all of its data.

        Args:
            session_id: Session ID.

        Returns:
            Whether the delete succeeded.
        """
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return False
        import shutil
        shutil.rmtree(session_dir, ignore_errors=True)
        return True

    def list_sessions(self, limit: int = 50) -> List[Session]:
        """List all sessions in descending update-time order.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of Session objects.
        """
        sessions: List[Session] = []
        if not self.base_dir.exists():
            return sessions
        for session_dir in self.base_dir.iterdir():
            if not session_dir.is_dir():
                continue
            session_file = session_dir / "session.json"
            data = self._read_json(session_file)
            if not isinstance(data, dict):
                continue
            try:
                sessions.append(Session.from_dict(data))
            except (TypeError, ValueError, KeyError) as exc:
                # One bad session.json must not abort listing siblings.
                logger.warning(
                    "Skipping corrupt session.json in %s: %s",
                    session_dir.name,
                    exc,
                )
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    # ---- Message Append-Only Log ----

    def append_message(self, message: Message) -> None:
        """Append a message to the session JSONL log.

        Args:
            message: Message to append.
        """
        path = self._messages_file(message.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def get_messages(self, session_id: str, limit: int = 100) -> List[Message]:
        """Read all messages for a session.

        Args:
            session_id: Session ID.
            limit: Maximum number of messages to return.

        Returns:
            List of Message objects in chronological order.
        """
        path = self._messages_file(session_id)
        if not path.exists():
            return []
        messages: List[Message] = []
        # Decode physical JSONL records separately: one unreadable byte must
        # cost one record, never the intact messages on either side of it.
        with path.open("rb") as log:
            for line_number, raw_line in enumerate(log, start=1):
                if not raw_line.strip():
                    continue
                try:
                    line = raw_line.decode("utf-8")
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise TypeError(
                            f"message line must be a JSON object, got {type(payload).__name__}"
                        )
                    messages.append(Message.from_dict(payload))
                except (
                    json.JSONDecodeError,
                    UnicodeDecodeError,
                    TypeError,
                    ValueError,
                    KeyError,
                ) as exc:
                    logger.warning(
                        "Skipping corrupted message record %d in session %s (%s)",
                        line_number,
                        session_id,
                        type(exc).__name__,
                    )
        return messages[-limit:]

    # ---- Attempt CRUD ----

    def create_attempt(self, attempt: Attempt) -> Attempt:
        """Create an execution attempt.

        Args:
            attempt: Attempt to create.

        Returns:
            The persisted Attempt.
        """
        attempt_dir = self._attempt_dir(attempt.session_id, attempt.attempt_id)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(
            self._attempt_file(attempt.session_id, attempt.attempt_id),
            attempt.to_dict(),
        )
        return attempt

    def get_attempt(self, session_id: str, attempt_id: str) -> Optional[Attempt]:
        """Read an execution attempt.

        Args:
            session_id: Session ID.
            attempt_id: Attempt ID.

        Returns:
            The Attempt instance, or None when it does not exist.
        """
        path = self._attempt_file(session_id, attempt_id)
        data = self._read_json(path)
        if data is None:
            return None
        return Attempt.from_dict(data)

    def update_attempt(self, attempt: Attempt) -> None:
        """Update an execution attempt.

        Args:
            attempt: Modified Attempt.
        """
        self._write_json(
            self._attempt_file(attempt.session_id, attempt.attempt_id),
            attempt.to_dict(),
        )

    def list_attempts(self) -> List[Attempt]:
        """Read every valid persisted attempt.

        Returns:
            Attempts found below the session storage root.
        """
        attempts: List[Attempt] = []
        for path in self.base_dir.glob("*/attempts/*/attempt.json"):
            data = self._read_json(path)
            if not isinstance(data, dict):
                continue
            try:
                attempts.append(Attempt.from_dict(data))
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("Skipping corrupt attempt file %s: %s", path, exc)
        return attempts

    def get_message_for_attempt(
        self, session_id: str, attempt_id: str
    ) -> Optional[Message]:
        """Return the persisted assistant message linked to an attempt.

        Args:
            session_id: Session ID.
            attempt_id: Attempt ID.

        Returns:
            The linked message, or None when the reply is not in the log.
        """
        for message in reversed(self.get_messages(session_id, limit=1_000_000)):
            if message.linked_attempt_id == attempt_id:
                return message
        return None

    # ---- Streaming Response Checkpoints ----

    def save_partial_response(
        self, session_id: str, attempt_id: str, content: str
    ) -> None:
        """Atomically persist the current streamed assistant text.

        Args:
            session_id: Session ID.
            attempt_id: Attempt ID.
            content: Assistant text accumulated so far.
        """
        self._write_json(
            self._partial_response_file(session_id, attempt_id),
            {"content": content},
        )

    def get_partial_response(self, session_id: str, attempt_id: str) -> Optional[str]:
        """Read a streamed assistant response checkpoint.

        Args:
            session_id: Session ID.
            attempt_id: Attempt ID.

        Returns:
            Saved response text, or None when no checkpoint exists.
        """
        data = self._read_json(self._partial_response_file(session_id, attempt_id))
        if not isinstance(data, dict):
            return None
        content = data.get("content")
        return content if isinstance(content, str) else None

    def delete_partial_response(self, session_id: str, attempt_id: str) -> None:
        """Remove a response checkpoint after the attempt becomes terminal.

        Args:
            session_id: Session ID.
            attempt_id: Attempt ID.
        """
        self._partial_response_file(session_id, attempt_id).unlink(missing_ok=True)

    # ---- IO Helpers ----

    @staticmethod
    def _write_json(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as temporary_file:
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "Skipping corrupt JSON file %s (%s)", path.name, type(exc).__name__
            )
            return None
        except OSError:
            return None
