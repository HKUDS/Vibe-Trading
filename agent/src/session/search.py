"""SQLite FTS5 session search index for cross-session full-text search.

Stores an inverted index of all conversation messages. The primary data
remains in the file-based SessionStore; this module provides a fast search
layer on top.

Database location: ``sessions.db`` under the runtime root (default
``~/.vibe-trading``; WAL mode for concurrent reads).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading as _threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

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


def _search_snippet(content: str, query: str) -> str:
    """Highlight query terms in the original text, never in expanded tokens."""
    terms = sorted(set(_QUERY_TERM.findall(query)), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE) if terms else None
    first = pattern.search(content) if pattern else None
    start = max(0, first.start() - 100) if first else 0
    end = min(len(content), start + 400)
    excerpt = content[start:end]
    if pattern:
        excerpt = pattern.sub(lambda match: f">>>{match[0]}<<<", excerpt)
    return ("..." if start else "") + excerpt + ("..." if end < len(content) else "")


@dataclass(frozen=True)
class SearchMatch:
    """A single search result from the FTS5 index.

    Attributes:
        session_id: Session ID.
        title: Session title.
        started_at: Human-readable start time.
        message_count: Total messages in the session.
        snippet: FTS5 snippet with match highlights (>>> <<<).
        rank: FTS5 relevance rank (lower is better).
    """

    session_id: str
    title: str
    started_at: str
    message_count: int
    snippet: str
    rank: float

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "started_at": self.started_at,
            "message_count": self.message_count,
            "snippet": self.snippet,
        }


class SessionSearchIndex:
    """SQLite FTS5 index for cross-session search.

    Supports:
        - Indexing individual messages as they arrive
        - Full-text search with relevance ranking
        - Bulk reindex from the file-based SessionStore
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        """Initialize the search index.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
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
        # Serialize upgrade across processes. Keep original messages for readable
        # snippets; rebuild the derived index once, including historical rows.
        conn.create_function("prepare_session_text", 1, _prepare_search_text, deterministic=True)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            migrating = "search_content" not in columns
            if migrating:
                for name in ("messages_ai", "messages_ad", "messages_au"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {name}")
                conn.execute("ALTER TABLE messages ADD COLUMN search_content TEXT NOT NULL DEFAULT ''")
                conn.execute("UPDATE messages SET search_content = prepare_session_text(content)")
                conn.execute("DROP TABLE IF EXISTS messages_fts")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(search_content, content=messages, content_rowid=id)
            """)
            conn.execute("""CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, search_content) VALUES (new.id, new.search_content);
            END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, search_content)
                VALUES ('delete', old.id, old.search_content);
            END""")
            if migrating:
                conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")

    def index_session(
        self,
        session_id: str,
        title: str = "",
        ts: Optional[float] = None,
    ) -> None:
        """Upsert a session record.

        Args:
            session_id: Session ID.
            title: Session title.
            ts: Session start time as a Unix epoch. When ``None``, an
                existing row keeps its ``started_at`` and a new row is
                stamped with ``time.time()``. Passing an explicit value
                (e.g. parsed from the on-disk ``created_at``) overwrites
                the stored timestamp so that bulk reindex restores the
                true session start time rather than the reindex moment.
        """
        conn = self._get_conn()
        # Preserve the existing started_at when the caller does not supply
        # one — otherwise INSERT OR REPLACE would overwrite the original
        # session start time on every re-upsert, breaking date-sort/filter.
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

    def index_message(self, session_id: str, role: str, content: str,
                      tool_name: Optional[str] = None) -> None:
        """Index a single message.

        Args:
            session_id: Session ID.
            role: Message role (user/assistant/tool).
            content: Message text.
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

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a user query for FTS5 MATCH syntax.

        - Separates Unicode words and East Asian character runs; the latter
          become adjacent-token phrases, matching shorter text accurately
        - Joins with OR so any-word-matches (not all-words-required)
        - Quotes each token to prevent FTS5 operator interpretation

        Args:
            query: Raw user query string.

        Returns:
            FTS5-safe MATCH expression.
        """
        tokens = [_prepare_search_text(term).strip() for term in _QUERY_TERM.findall(query)]
        return " OR ".join(f'"{token}"' for token in tokens) if tokens else '""'

    def search(self, query: str, max_sessions: int = 3) -> List[SearchMatch]:
        """Full-text search across all sessions.

        Args:
            query: Search query (keywords or phrase).
            max_sessions: Maximum number of distinct sessions to return.

        Returns:
            List of SearchMatch results, grouped by session, ranked by relevance.
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
                    rank
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, max_sessions * 5),
            )
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 search failed: %s", exc)
            return []

        seen: dict[str, SearchMatch] = {}
        for row in cursor.fetchall():
            sid = row[0]
            if sid in seen:
                continue
            seen[sid] = SearchMatch(
                session_id=row[0],
                title=row[1] or "(untitled)",
                started_at=self._format_time(row[2]),
                message_count=row[3],
                snippet=_search_snippet(row[4] or "", query),
                rank=row[5],
            )
            if len(seen) >= max_sessions:
                break

        return list(seen.values())

    def reindex_from_store(self, store_base_dir: Path) -> int:
        """Rebuild the entire index from file-based session store.

        Args:
            store_base_dir: Root directory of the SessionStore (contains session subdirs).

        Returns:
            Number of messages indexed.
        """
        if not store_base_dir.exists():
            return 0

        conn = self._get_conn()
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
        try:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        except sqlite3.OperationalError:
            pass
        conn.commit()

        count = 0
        for session_dir in store_base_dir.iterdir():
            if not session_dir.is_dir():
                continue

            session_file = session_dir / "session.json"
            messages_file = session_dir / "messages.jsonl"

            if not session_file.exists():
                continue

            try:
                session_data = json.loads(session_file.read_text(encoding="utf-8"))
                sid = session_data.get("session_id", session_dir.name)
                title = session_data.get("title", "")

                try:
                    ts = datetime.fromisoformat(session_data.get("created_at", "")).timestamp()
                except (ValueError, TypeError):
                    ts = time.time()

                self.index_session(sid, title, ts=ts)

                if messages_file.exists():
                    for line in messages_file.read_text(encoding="utf-8").strip().splitlines():
                        if not line.strip():
                            continue
                        try:
                            msg = json.loads(line)
                            role = msg.get("role", "")
                            content = msg.get("content", "")
                            if content and role in ("user", "assistant"):
                                self.index_message(sid, role, content)
                                count += 1
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:
                logger.warning("Failed to index session %s: %s", session_dir.name, exc)

        return count

    @staticmethod
    def _format_time(epoch: float) -> str:
        """Format epoch timestamp to human-readable string."""
        try:
            return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "unknown"

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


_shared_index: Optional[SessionSearchIndex] = None
_shared_lock = _threading.Lock()


def get_shared_index() -> SessionSearchIndex:
    """Return a process-wide singleton SessionSearchIndex.

    Thread-safe via double-checked locking. Used by both
    SessionService (indexing) and SessionSearchTool (searching)
    so they share one SQLite connection.
    """
    global _shared_index
    if _shared_index is None:
        with _shared_lock:
            if _shared_index is None:
                _shared_index = SessionSearchIndex()
    return _shared_index
