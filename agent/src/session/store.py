"""Filesystem-backed persistence for Session, Message, and Attempt records."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.session.models import Attempt, Message, Session
from src.session.replay import project_turn
from src.session.thread import THREAD_FILENAME, ThreadLog

logger = logging.getLogger(__name__)


class SessionStore:
    """Filesystem-backed persistent storage."""

    def __init__(self, base_dir: Path) -> None:
        """Initialize session storage."""
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def _session_file(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    def thread_path(self, session_id: str) -> Path:
        """Return the location of a session's conversation thread log."""
        return self._session_dir(session_id) / THREAD_FILENAME

    def thread_log(self, session_id: str) -> ThreadLog:
        """Open a session's conversation thread log."""
        self.ensure_migrated(session_id)
        return ThreadLog(self.thread_path(session_id))

    def ensure_migrated(self, session_id: str):
        """Migrate a pre-thread session before any thread read or write."""
        from src.session.migration import migrate_session

        return migrate_session(self._session_dir(session_id), session_id=session_id)

    def _attempt_dir(self, session_id: str, attempt_id: str) -> Path:
        return self._session_dir(session_id) / "attempts" / attempt_id

    def _attempt_file(self, session_id: str, attempt_id: str) -> Path:
        return self._attempt_dir(session_id, attempt_id) / "attempt.json"

    # Session CRUD

    def create_session(self, session: Session) -> Session:
        """Create and persist a session."""
        session_dir = self._session_dir(session.session_id)
        if session_dir.exists():
            raise ValueError(f"Session {session.session_id} already exists")
        session_dir.mkdir(parents=True)
        (session_dir / "attempts").mkdir()
        self._write_json(self._session_file(session.session_id), session.to_dict())
        self.ensure_migrated(session.session_id)
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Read a session."""
        path = self._session_file(session_id)
        data = self._read_json(path)
        if data is None:
            return None
        self.ensure_migrated(session_id)
        return Session.from_dict(data)

    def update_session(self, session: Session) -> None:
        """Update a session."""
        self._write_json(self._session_file(session.session_id), session.to_dict())

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all of its data."""
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return False
        import shutil

        shutil.rmtree(session_dir, ignore_errors=True)
        return True

    def list_sessions(self, limit: int = 50) -> List[Session]:
        """List all sessions in descending update-time order."""
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

    # Derived message views

    def get_messages(
        self, session_id: str, limit: Optional[int] = 100
    ) -> List[Message]:
        """Return display messages derived from the session thread."""
        if limit is not None and limit <= 0:
            self.ensure_migrated(session_id)
            return []
        items = self.thread_log(session_id).read()
        starts = [item for item in items if item.type == "turn_start"]
        rows: List[Message] = []
        for start in starts:
            turn_items = [item for item in items if item.turn_id == start.turn_id]
            user_items = [item for item in turn_items if item.type == "user"]
            if user_items:
                for item in user_items:
                    metadata = {}
                    input_id = item.get("input_id")
                    if isinstance(input_id, str) and input_id:
                        metadata["queued_input_id"] = input_id
                    rows.append(Message(
                        message_id=f"{session_id}:{item.seq}",
                        session_id=session_id,
                        role="user",
                        content=item.get("content") or "",
                        created_at=datetime.fromtimestamp(item.ts, timezone.utc).isoformat(),
                        metadata=metadata,
                    ))
            else:
                prompt = start.get("prompt")
                if isinstance(prompt, str) and prompt:
                    rows.append(Message(
                        session_id=session_id,
                        role="user",
                        content=prompt,
                        created_at=datetime.fromtimestamp(start.ts, timezone.utc).isoformat(),
                    ))
            for item in turn_items:
                if item.type == "inject" and item.get("role") == "system":
                    rows.append(Message(message_id=f"{session_id}:{item.seq}", session_id=session_id,
                                        role="system", content=item.get("content") or ""))
            projection = project_turn(turn_items, start.turn_id)
            if projection.status is None or projection.content is None:
                continue
            rows.append(Message(
                message_id=f"{session_id}:{start.turn_id}:reply",
                session_id=session_id,
                role="assistant",
                content=projection.content or "",
                linked_attempt_id=start.turn_id,
                created_at=datetime.fromtimestamp(start.ts, timezone.utc).isoformat(),
                metadata={**projection.metadata, "status": projection.status},
            ))
        if not starts:
            # Show the durable prompt while the accepted attempt still lacks a terminal projection.
            for attempt in self.list_attempts():
                if attempt.session_id != session_id:
                    continue
                if attempt.status.value in {"pending", "running", "waiting_user"}:
                    rows.append(Message(
                        session_id=session_id,
                        role="user",
                        content=attempt.prompt,
                    ))
        return rows if limit is None else rows[-limit:]

    # Attempt CRUD

    def create_attempt(self, attempt: Attempt) -> Attempt:
        """Create an execution attempt."""
        attempt_dir = self._attempt_dir(attempt.session_id, attempt.attempt_id)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(
            self._attempt_file(attempt.session_id, attempt.attempt_id),
            attempt.to_dict(),
        )
        return attempt

    def get_attempt(self, session_id: str, attempt_id: str) -> Optional[Attempt]:
        """Read an execution attempt."""
        path = self._attempt_file(session_id, attempt_id)
        data = self._read_json(path)
        if data is None:
            return None
        return Attempt.from_dict(data)

    def update_attempt(self, attempt: Attempt) -> None:
        """Update an execution attempt."""
        self._write_json(
            self._attempt_file(attempt.session_id, attempt.attempt_id),
            attempt.to_dict(),
        )

    def list_attempts(self) -> List[Attempt]:
        """Read every valid persisted attempt."""
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
        """Return the persisted assistant message linked to an attempt."""
        items = self.thread_log(session_id).read()
        projection = project_turn(items, attempt_id)
        if projection.status is None:
            return None
        return Message(
            session_id=session_id,
            role="assistant",
            content=projection.content or "",
            linked_attempt_id=attempt_id,
            metadata={**projection.metadata, "status": projection.status},
        )

    # IO Helpers

    @staticmethod
    def _write_json(path: Path, data: Dict[str, Any], *, indent: Optional[int] = 2) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8")
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
