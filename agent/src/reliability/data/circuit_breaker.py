"""SQLite-backed source-level circuit breaker."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.reliability.data.contracts import CircuitBreakerSnapshot, StructuredWarning


@dataclass(frozen=True)
class CircuitDecision:
    """Decision before using one source."""

    source: str
    state: str
    allowed: bool
    warning: StructuredWarning | None = None


class CircuitBreaker:
    """Track source failures and skip OPEN providers."""

    def __init__(
        self,
        path: Path,
        *,
        failure_threshold: int = 3,
        open_seconds: int = 60,
    ) -> None:
        self.path = Path(path)
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_seconds = max(0, int(open_seconds))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def before_request(self, source: str) -> CircuitDecision:
        """Return whether source should be used now."""
        snapshot = self.snapshot(source)
        if snapshot.state == "OPEN":
            now = time.time()
            opened_at = snapshot.opened_at.timestamp() if snapshot.opened_at is not None else 0.0
            if now - opened_at >= self.open_seconds:
                self._upsert_state(source, "HALF_OPEN", snapshot.consecutive_failures, snapshot.last_error_class, opened_at)
                return CircuitDecision(source=source, state="HALF_OPEN", allowed=True)
            return CircuitDecision(
                source=source,
                state="OPEN",
                allowed=False,
                warning=StructuredWarning(
                    code="DATA_SOURCE_SKIPPED_BY_CIRCUIT",
                    severity="warning",
                    message="source skipped because circuit breaker is OPEN",
                    metadata={"source": source},
                ),
            )
        return CircuitDecision(source=source, state=snapshot.state, allowed=True)

    def record_success(self, source: str) -> None:
        """Close source circuit after a successful request."""
        self._upsert_state(source, "CLOSED", 0, None, None)

    def record_failure(self, source: str, error: BaseException) -> None:
        """Record a source failure and open if threshold is reached."""
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT state, consecutive_failures, opened_at, last_error_class
                    FROM circuit_state
                    WHERE source = ?
                    """,
                    (source,),
                ).fetchone()
                if row is None:
                    previous_state = "CLOSED"
                    failures = 1
                    previous_opened_at = None
                else:
                    previous_state = str(row[0])
                    failures = int(row[1]) + 1
                    previous_opened_at = row[2]

                state = previous_state
                opened_at = previous_opened_at
                if failures >= self.failure_threshold:
                    state = "OPEN"
                    opened_at = (
                        float(previous_opened_at)
                        if previous_state == "OPEN" and previous_opened_at is not None
                        else time.time()
                    )

                self._write_state(
                    conn,
                    source,
                    state,
                    failures,
                    type(error).__name__,
                    opened_at,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def snapshot(self, source: str) -> CircuitBreakerSnapshot:
        """Return a source state snapshot."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, consecutive_failures, opened_at, last_error_class FROM circuit_state WHERE source = ?",
                (source,),
            ).fetchone()
        if row is None:
            return CircuitBreakerSnapshot(source=source, state="CLOSED", consecutive_failures=0)
        state, failures, opened_at, error_class = row
        opened_dt = _from_epoch(opened_at)
        next_probe = (
            datetime.fromtimestamp(float(opened_at) + self.open_seconds, tz=timezone.utc)
            if opened_at is not None
            else None
        )
        return CircuitBreakerSnapshot(
            source=source,
            state=state,
            consecutive_failures=int(failures),
            opened_at=opened_dt,
            last_error_class=error_class,
            next_probe_after=next_probe,
        )

    def snapshots(self, sources: list[str]) -> list[CircuitBreakerSnapshot]:
        """Return snapshots for all requested sources."""
        return [self.snapshot(source) for source in sources]

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS circuit_state (
                    source TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL,
                    opened_at REAL,
                    last_error_class TEXT
                )
                """
            )
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            yield conn
        finally:
            conn.close()

    def _upsert_state(
        self,
        source: str,
        state: str,
        failures: int,
        error_class: str | None,
        opened_at: float | None,
    ) -> None:
        with self._connect() as conn:
            try:
                self._write_state(conn, source, state, failures, error_class, opened_at)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _write_state(
        conn: sqlite3.Connection,
        source: str,
        state: str,
        failures: int,
        error_class: str | None,
        opened_at: float | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO circuit_state (source, state, consecutive_failures, opened_at, last_error_class)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                state = excluded.state,
                consecutive_failures = excluded.consecutive_failures,
                opened_at = excluded.opened_at,
                last_error_class = excluded.last_error_class
            """,
            (source, state, failures, opened_at, error_class),
        )


def _from_epoch(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)
