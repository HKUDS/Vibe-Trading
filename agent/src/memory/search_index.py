"""SQLite FTS5 full-text search index for persistent memory (Tier 2).

Provides O(log n) search via inverted index, replacing the O(n) sequential
token-scan in PersistentMemory.find_relevant(). Falls back gracefully if
FTS5 is unavailable.

Feature flag: VT_MEMORY_FTS_INDEX (default off).
Database: ~/.vibe-trading/memory_index.db (separate from sessions.db).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".vibe-trading" / "memory_index.db"

# Body text truncation limit (chars)
_MAX_BODY_LEN = 50_000

# CJK Unicode range boundaries for ideograph detection
_CJK_RANGE_MAIN = (0x4E00, 0x9FFF)
_CJK_RANGE_EXT_A = (0x3400, 0x4DBF)


def _is_cjk_char(char: str) -> bool:
    """Check if character is a CJK ideograph."""
    cp = ord(char)
    return (
        _CJK_RANGE_MAIN[0] <= cp <= _CJK_RANGE_MAIN[1]
        or _CJK_RANGE_EXT_A[0] <= cp <= _CJK_RANGE_EXT_A[1]
    )


def _expand_cjk_buffer(chars: list[str]) -> str:
    """Expand a sequence of CJK chars into unigrams + bigrams.

    Example: ['\u8bb0', '\u5fc6', '\u7cfb', '\u7edf'] -> '\u8bb0 \u5fc6 \u7cfb \u7edf \u8bb0\u5fc6 \u5fc6\u7cfb \u7cfb\u7edf'
    """
    parts: list[str] = []
    # Unigrams
    parts.extend(chars)
    # Bigrams (overlapping pairs)
    for i in range(len(chars) - 1):
        parts.append(chars[i] + chars[i + 1])
    return " ".join(parts)


def _cjk_query_tokens(chars: list[str]) -> list[str]:
    """Generate unigram + bigram tokens from consecutive CJK chars for queries."""
    tokens: list[str] = list(chars)
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    return tokens


def _dedupe_cjk_runs(text: str) -> str:
    """Remove duplicate CJK substrings produced by bigram expansion during clean.

    After collapsing spaces, bigram tokens merge into the original run,
    creating duplicates like '\u8bb0\u5fc6\u7cfb\u7edf\u8bb0\u5fc6\u5fc6\u7cfb\u7cfb\u7edf'. This finds CJK runs and
    keeps only the longest non-repeating form.
    """
    _cjk_run_re = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]{2,}")

    def _shrink(match: re.Match) -> str:  # type: ignore[type-arg]
        run = match.group(0)
        # Try to find the minimal prefix whose repetition covers the run
        # But simpler: the original text was unigrams + bigrams concatenated.
        # The original run length N produces N unigrams + (N-1) bigrams
        # = N + 2*(N-1) = 3N-2 chars when concatenated. Solve for N.
        total = len(run)
        # 3N - 2 = total => N = (total + 2) / 3
        n = (total + 2) // 3
        if 3 * n - 2 == total and n >= 2:
            # Verify the prefix matches
            candidate = run[:n]
            # Rebuild what bigram expansion would produce concatenated
            expected = candidate + "".join(
                candidate[i] + candidate[i + 1] for i in range(n - 1)
            )
            if expected == run:
                return candidate
        return run

    return _cjk_run_re.sub(_shrink, text)


@dataclass(frozen=True)
class MemoryMatch:
    """A single FTS5 search result.

    Attributes:
        entry_id: 6-char hex identifier of the memory entry.
        title: Memory title.
        snippet: FTS5 snippet with match highlights (>>> <<<).
        rank: FTS5 relevance rank (lower is better).
    """

    entry_id: str
    title: str
    snippet: str
    rank: float


class MemorySearchIndex:
    """SQLite FTS5 index for memory full-text search.

    Supports:
        - Indexing individual memory entries as they are created/updated
        - Full-text search with relevance ranking
        - Bulk reindex from in-memory entry data
        - Graceful degradation when FTS5 is unavailable
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the search index.

        Args:
            db_path: Path to SQLite DB (default: ~/.vibe-trading/memory_index.db).
        """
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._fts_available: bool = True
        self._auto_rebuilt: bool = False
        self._op_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create SQLite connection with WAL mode."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self) -> None:
        """Create tables + FTS5 virtual table + auto-sync triggers."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                keywords TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT ''
            );
        """)

        # FTS5 virtual table — separate try/except for graceful degradation
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(
                    title, description, keywords, body,
                    content=memories, content_rowid=rowid
                )
            """)
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 unavailable, search disabled: %s", exc)
            self._fts_available = False
            conn.commit()
            return

        # Auto-sync triggers
        for trigger_sql in [
            """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, title, description, keywords, body)
                VALUES (new.rowid, new.title, new.description, new.keywords, new.body);
            END""",
            """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, description, keywords, body)
                VALUES ('delete', old.rowid, old.title, old.description, old.keywords, old.body);
            END""",
            """CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, description, keywords, body)
                VALUES ('delete', old.rowid, old.title, old.description, old.keywords, old.body);
                INSERT INTO memories_fts(rowid, title, description, keywords, body)
                VALUES (new.rowid, new.title, new.description, new.keywords, new.body);
            END""",
        ]:
            try:
                conn.execute(trigger_sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def _is_index_populated(self) -> bool:
        """Check if the FTS5 index has any entries."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0] > 0 if row else False
        except Exception:
            return False

    def index_entry(
        self,
        entry_id: str,
        title: str,
        description: str,
        keywords: str,
        body: str,
    ) -> None:
        """Upsert a memory entry into the index.

        Args:
            entry_id: 6-char hex identifier.
            title: Memory title.
            description: One-line description.
            keywords: Space-joined keywords.
            body: Full body text (truncated to 50k chars).
        """
        with self._op_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO memories (id, title, description, keywords, body) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        entry_id,
                        self._prepare_cjk(title),
                        self._prepare_cjk(description),
                        self._prepare_cjk(keywords),
                        self._prepare_cjk(body[:_MAX_BODY_LEN]),
                    ),
                )
                conn.commit()
            except sqlite3.OperationalError as exc:
                logger.debug("index_entry failed for %s: %s", entry_id, exc)

    def remove_entry(self, entry_id: str) -> None:
        """Remove an entry from the index by ID."""
        with self._op_lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM memories WHERE id = ?", (entry_id,))
                conn.commit()
            except sqlite3.OperationalError as exc:
                logger.debug("remove_entry failed for %s: %s", entry_id, exc)

    def search(self, query: str, max_results: int = 5) -> List[MemoryMatch]:
        """Full-text search with FTS5 MATCH.

        Args:
            query: User search query.
            max_results: Maximum results to return.

        Returns:
            List of MemoryMatch sorted by relevance. Empty list if FTS5
            unavailable or query produces no results.
        """
        if not self._fts_available:
            return []

        fts_query = self._sanitize_fts_query(query)
        if not fts_query or fts_query == '""':
            return []

        with self._op_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """
                    SELECT
                        m.id,
                        m.title,
                        snippet(memories_fts, 3, '>>>', '<<<', '...', 64) AS snippet,
                        rank
                    FROM memories_fts
                    JOIN memories m ON m.rowid = memories_fts.rowid
                    WHERE memories_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, max_results),
                )
            except sqlite3.OperationalError as exc:
                logger.warning("FTS5 search failed: %s", exc)
                return []

            results: List[MemoryMatch] = []
            for row in cursor.fetchall():
                results.append(
                    MemoryMatch(
                        entry_id=row[0],
                        title=self._clean_cjk(row[1] or ""),
                        snippet=self._clean_cjk(row[2] or ""),
                        rank=row[3],
                    )
                )
            return results

    def rebuild_all(self, entries_data: List[tuple]) -> int:
        """Full reindex from a list of (id, title, description, keywords, body) tuples.

        Clears existing data and re-inserts all entries. Use for bulk
        synchronization from the canonical PersistentMemory store.

        Args:
            entries_data: List of tuples (id, title, description, keywords, body).

        Returns:
            Number of entries indexed.
        """
        with self._op_lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM memories")
                if self._fts_available:
                    conn.execute(
                        "INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')"
                    )
            except sqlite3.OperationalError as exc:
                logger.debug("rebuild_all clear failed: %s", exc)
            conn.commit()

            count = 0
            for entry in entries_data:
                if len(entry) < 5:
                    continue
                entry_id, title, description, keywords, body = (
                    entry[0],
                    entry[1],
                    entry[2],
                    entry[3],
                    entry[4],
                )
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO memories "
                        "(id, title, description, keywords, body) VALUES (?, ?, ?, ?, ?)",
                        (
                            entry_id,
                            self._prepare_cjk(title or ""),
                            self._prepare_cjk(description or ""),
                            self._prepare_cjk(keywords or ""),
                            self._prepare_cjk((body or "")[:_MAX_BODY_LEN]),
                        ),
                    )
                    count += 1
                except sqlite3.OperationalError as exc:
                    logger.debug("rebuild_all entry %s failed: %s", entry_id, exc)
            conn.commit()
            return count

    @staticmethod
    def _prepare_cjk(text: str) -> str:
        """Insert spaces for CJK chars and generate bigrams for better matching.

        Example: "记忆系统" → "记 忆 系 统 记忆 忆系 系统"
        This allows both single-char and two-char phrase matching in FTS5.
        Non-CJK text is preserved as-is.
        """
        result: list[str] = []
        cjk_buffer: list[str] = []
        text_buffer: list[str] = []

        for char in text:
            if _is_cjk_char(char):
                if text_buffer:
                    result.append("".join(text_buffer))
                    text_buffer = []
                cjk_buffer.append(char)
            else:
                if cjk_buffer:
                    result.append(_expand_cjk_buffer(cjk_buffer))
                    cjk_buffer = []
                text_buffer.append(char)

        if cjk_buffer:
            result.append(_expand_cjk_buffer(cjk_buffer))
        if text_buffer:
            result.append("".join(text_buffer))

        return " ".join(result)

    @staticmethod
    def _clean_cjk(text: str) -> str:
        """Collapse extra whitespace and remove bigram duplicates from display text.

        Removes spaces between CJK characters and strips bigram tokens that
        are substrings of already-present CJK runs, normalizing whitespace.
        """
        # First remove bigram-only tokens (two adjacent CJK chars surrounded by spaces)
        # by collapsing all CJK-adjacent spacing.
        _cjk_space = re.compile(
            r"([\u4e00-\u9fff\u3400-\u4dbf])\s+([\u4e00-\u9fff\u3400-\u4dbf])"
        )
        prev = None
        while prev != text:
            prev = text
            text = _cjk_space.sub(r"\1\2", text)
        # Remove duplicate CJK runs that appear due to bigram expansion
        # e.g. "记忆系统记忆忆系系统" → keep longest contiguous run only
        text = _dedupe_cjk_runs(text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize user query for FTS5 MATCH syntax.
    
        Extracts alphanumeric tokens (2+ chars) and CJK characters,
        generates bigrams for consecutive CJK chars, quotes each token
        and joins with OR to prevent FTS5 operator injection.
    
        Args:
            query: Raw user query string.
    
        Returns:
            FTS5-safe MATCH expression, or empty-quoted string if no tokens.
        """
        tokens: list[str] = []
        cjk_buffer: list[str] = []
    
        # Walk through pre-extracted raw tokens
        raw_tokens = re.findall(
            r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff\u3400-\u4dbf]", query
        )
        for tok in raw_tokens:
            if len(tok) == 1 and _is_cjk_char(tok):
                cjk_buffer.append(tok)
            else:
                if cjk_buffer:
                    tokens.extend(_cjk_query_tokens(cjk_buffer))
                    cjk_buffer = []
                tokens.append(tok)
    
        if cjk_buffer:
            tokens.extend(_cjk_query_tokens(cjk_buffer))
    
        if not tokens:
            return '""'
        # Quote each token and join with OR for broader matching
        return " OR ".join(f'"{t}"' for t in tokens)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_shared_index: Optional[MemorySearchIndex] = None
_shared_lock = threading.Lock()


def get_shared_index(db_path: Optional[Path] = None) -> MemorySearchIndex:
    """Return a process-wide singleton MemorySearchIndex.

    Thread-safe via double-checked locking. Shared by memory indexing
    and search callers so they use one SQLite connection.

    Args:
        db_path: Optional override for the database path (only used on
                 first call when creating the singleton).

    Returns:
        The shared MemorySearchIndex instance.
    """
    global _shared_index
    if _shared_index is None:
        with _shared_lock:
            if _shared_index is None:
                _shared_index = MemorySearchIndex(db_path=db_path)
    return _shared_index
