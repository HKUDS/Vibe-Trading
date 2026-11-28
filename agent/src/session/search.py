"""Index session messages in a derived SQLite FTS5 database under the runtime root."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading as _threading
import time
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

_DB_PATH = get_runtime_root() / "sessions.db"

# Ideographs, kana (including half-width), Hangul syllables and jamo.
_EAST_ASIAN = "\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f\uac00-\ud7af\u1100-\u11ff\u3130-\u318f"
_EAST_ASIAN_CHAR = re.compile(f"[{_EAST_ASIAN}]")
_QUERY_TERM = re.compile(rf"[{_EAST_ASIAN}]+|[^\W_{_EAST_ASIAN}]+")


def _prepare_search_text(text: str) -> str:
    """Separate East Asian characters for FTS5 without changing display text."""
    return _EAST_ASIAN_CHAR.sub(lambda match: f" {match[0]} ", text)


def _search_snippet(
    conn: sqlite3.Connection, message_id: int, content: str, fts_query: str
) -> str:
    """Map native FTS match spans back to the original, bounded excerpt."""
    # Keep highlight markers distinct from literal text.
    opening, closing = "<\x01>", "<\x02>"
    while opening in content or closing in content:
        opening = "<" + opening[1:-1] * 2 + ">"
        closing = "<" + closing[1:-1] * 2 + ">"
    row = conn.execute(
        "SELECT highlight(messages_fts, 0, ?, ?) FROM messages_fts "
        "WHERE messages_fts MATCH ? AND rowid = ?",
        (opening, closing, fts_query, message_id),
    ).fetchone()
    highlighted = row[0] if row else ""

    # Only inserted spaces need offset bookkeeping.
    insertions = []
    for index, match in enumerate(_EAST_ASIAN_CHAR.finditer(content)):
        position = match.start() + 2 * index
        insertions.extend((position, position + 2))

    spans = []
    cursor = prepared_offset = 0
    while True:
        marker_start = highlighted.find(opening, cursor)
        if marker_start < 0:
            break
        prepared_offset += marker_start - cursor
        match_start = marker_start + len(opening)
        marker_end = highlighted.find(closing, match_start)
        if marker_end < 0:
            break
        prepared_end = prepared_offset + marker_end - match_start
        start = prepared_offset - bisect_left(insertions, prepared_offset)
        end = prepared_end - bisect_left(insertions, prepared_end)
        if start < end:
            spans.append((start, end))
        prepared_offset = prepared_end
        cursor = marker_end + len(closing)

    start = max(0, spans[0][0] - 100) if spans else 0
    end = min(len(content), start + 400)
    pieces = []
    cursor = start
    for match_start, match_end in spans:
        if match_start >= end:
            break
        match_start, match_end = max(match_start, start), min(match_end, end)
        if match_end <= cursor:
            continue
        pieces.extend(
            (content[cursor:match_start], ">>>", content[match_start:match_end], "<<<")
        )
        cursor = match_end
    pieces.append(content[cursor:end])
    return (
        ("..." if start else "")
        + "".join(pieces)
        + ("..." if end < len(content) else "")
    )


@dataclass(frozen=True)
class SearchMatch:
    """A single search result from the FTS5 index."""

    session_id: str
    title: str
    started_at: str
    message_count: int
    snippet: str
    rank: float

    def to_dict(self) -> dict:
        """Serialize the match for clients.

        Returns:
            Session ID, title, start time, message count, and matching snippet.
        """
        return {
            "session_id": self.session_id,
            "title": self.title,
            "started_at": self.started_at,
            "message_count": self.message_count,
            "snippet": self.snippet,
        }


def _serialized_operation(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Keep each shared-connection operation and its cursor consumption together."""

    @wraps(fn)
    def wrapped(self: SessionSearchIndex, *args: Any, **kwargs: Any) -> Any:
        with self._operation_lock:
            return fn(self, *args, **kwargs)

    return wrapped


class SessionSearchIndex:
    """SQLite FTS5 index for cross-session search.

    Args:
        db_path: Path to the SQLite index. Its parent directory is created when needed.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        """Initialize the search index."""
        self._operation_lock = _threading.RLock()
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create the SQLite connection (WAL mode)."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self) -> None:
        """Create tables and FTS5 virtual table if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                timestamp REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id);
        """)
        # Serialize upgrades across processes and preserve original text for snippets.
        conn.create_function(
            "prepare_session_text", 1, _prepare_search_text, deterministic=True
        )
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            migrating = "search_content" not in columns
            if migrating:
                for name in ("messages_ai", "messages_ad", "messages_au"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {name}")
                conn.execute(
                    "ALTER TABLE messages ADD COLUMN search_content TEXT NOT NULL DEFAULT ''"
                )
                conn.execute(
                    "UPDATE messages SET search_content = prepare_session_text(content)"
                )
                conn.execute("DROP TABLE IF EXISTS messages_fts")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(search_content, content=messages, content_rowid=id)
            """)
            conn.execute(
                """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, search_content) VALUES (new.id, new.search_content);
            END"""
            )
            conn.execute(
                """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, search_content)
                VALUES ('delete', old.id, old.search_content);
            END"""
            )
            if migrating:
                conn.execute(
                    "INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')"
                )

    @_serialized_operation
    def index_session(
        self,
        session_id: str,
        title: str = "",
        ts: float | None = None,
    ) -> None:
        """Upsert a session without resetting an existing message count.

        Args:
            session_id: Session ID.
            title: Session title.
            ts: Explicit Unix start time in seconds. None preserves an existing start time or uses
                the current time for a new session.
        """
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (id, title, started_at, message_count) "
            "VALUES ("
            "  ?, ?,"
            "  COALESCE(?, (SELECT started_at FROM sessions WHERE id = ?), ?),"
            "  COALESCE((SELECT message_count FROM sessions WHERE id = ?), 0)"
            ")",
            (session_id, title, ts, session_id, time.time(), session_id),
        )
        conn.commit()

    @_serialized_operation
    def index_message(
        self, session_id: str, role: str, content: str, tool_name: str | None = None
    ) -> None:
        """Index a single message.

        Args:
            session_id: Session ID.
            role: Message role such as user, assistant, or tool.
            content: Message text. Whitespace-only messages are skipped and long text is capped.
            tool_name: Tool name if this is a tool result.
        """
        if not content or not content.strip():
            return
        conn = self._get_conn()
        content = content[:50_000]
        prepared = _prepare_search_text(content)
        conn.execute(
            "INSERT INTO messages (session_id, role, content, search_content, tool_name, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, prepared, tool_name, time.time()),
        )
        conn.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
            (session_id,),
        )
        conn.commit()

    @_serialized_operation
    def remove_session(self, session_id: str) -> None:
        """Remove a session and all of its messages from the index.

        Args:
            session_id: Session ID whose indexed text should be removed.
        """
        conn = self._get_conn()
        with conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a user query for FTS5 MATCH syntax."""
        tokens = [
            _prepare_search_text(term).strip() for term in _QUERY_TERM.findall(query)
        ]
        return " OR ".join(f'"{token}"' for token in tokens) if tokens else '""'

    @_serialized_operation
    def search(self, query: str, max_sessions: int = 3) -> list[SearchMatch]:
        """Full-text search across all sessions.

        Args:
            query: Search query containing keywords or a phrase.
            max_sessions: Maximum number of distinct sessions to return.

        Returns:
            The best match per session ranked by relevance, or an empty list when the query fails.
        """
        conn = self._get_conn()
        fts_query = self._sanitize_fts_query(query)
        try:
            cursor = conn.execute(
                """
                SELECT
                    m.session_id,
                    s.title,
                    s.started_at,
                    s.message_count,
                    m.content,
                    rank,
                    m.id
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                """,
                (fts_query,),
            )
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 search failed: %s", exc)
            return []

        seen: dict[str, SearchMatch] = {}
        for row in cursor:
            sid = row[0]
            if sid in seen:
                continue
            seen[sid] = SearchMatch(
                session_id=row[0],
                title=row[1] or "(untitled)",
                started_at=self._format_time(row[2]),
                message_count=row[3],
                snippet=_search_snippet(conn, row[6], row[4] or "", fts_query),
                rank=row[5],
            )
            if len(seen) >= max_sessions:
                break

        return list(seen.values())

    @staticmethod
    def _format_time(epoch: float) -> str:
        """Format epoch timestamp to human-readable string."""
        try:
            return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "unknown"

    @_serialized_operation
    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


_shared_index: SessionSearchIndex | None = None
_shared_lock = _threading.Lock()


def get_shared_index() -> SessionSearchIndex:
    """Access the process-wide session search index.

    Returns:
        The shared SessionSearchIndex, created on first use.
    """
    global _shared_index
    if _shared_index is None:
        with _shared_lock:
            if _shared_index is None:
                _shared_index = SessionSearchIndex()
    return _shared_index
