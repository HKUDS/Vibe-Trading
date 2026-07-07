"""SQLite circuit-breaker failure counters with atomic updates."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class CircuitBreakerStore:
    """Persist per-source failure counters without leaked SQLite connections."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record_failure(self, source: str) -> int:
        """Atomically increment and return the failure count for ``source``."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO circuit_breaker_failures(source, failure_count)
                VALUES (?, 1)
                ON CONFLICT(source)
                DO UPDATE SET failure_count = failure_count + 1
                """,
                (source,),
            )
            row = conn.execute(
                "SELECT failure_count FROM circuit_breaker_failures WHERE source = ?",
                (source,),
            ).fetchone()
            conn.commit()
            count = int(row[0]) if row else 0
        except BaseException:
            try:
                conn.rollback()
            finally:
                conn.close()
            raise
        else:
            conn.close()
            return count

    def get_failure_count(self, source: str) -> int:
        """Return the recorded failure count for ``source``."""
        conn = self._connect()
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT failure_count FROM circuit_breaker_failures WHERE source = ?",
                (source,),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None, check_same_thread=False)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS circuit_breaker_failures (
                source TEXT PRIMARY KEY,
                failure_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
