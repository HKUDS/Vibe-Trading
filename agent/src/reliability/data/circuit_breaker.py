"""SQLite-backed source-level circuit breaker."""

from __future__ import annotations

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
        """Record a source failure and open if threshold is reached.

        Uses an atomic UPDATE to avoid the TOCTOU race where two concurrent
        failures both read the same count and under-increment.
        """
        error_class = type(error).__name__
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE circuit_state
                SET consecutive_failures = consecutive_failures + 1,
                    last_error_class = ?
                WHERE source = ?
                RETURNING consecutive_failures, state, opened_at
                """,
                (error_class, source),
            ).fetchone()
            if row is None:
                # Source not yet in table — insert with failures=1
                conn.execute(
                    """
                    INSERT INTO circuit_state (source, state, consecutive_failures, opened_at, last_error_class)
                    VALUES (?, 'CLOSED', 1, NULL, ?)
                    ON CONFLICT(source) DO UPDATE SET
                        consecutive_failures = circuit_state.consecutive_failures + 1,
                        last_error_class = excluded.last_error_class
                    """,
                    (source, error_class),
                )
                row = (1, "CLOSED", None)
                conn.commit()
                failures = 1
                state = "CLOSED"
                opened_at = None
            else:
                failures, state, opened_at = row
                failures = int(failures)
                conn.commit()

            if failures >= self.failure_threshold and state != "OPEN":
                conn.execute(
                    """
                    UPDATE circuit_state
                    SET state = 'OPEN', opened_at = ?
                    WHERE source = ?
                    """,
                    (now, source),
                )
                conn.commit()
                opened_at = now

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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _upsert_state(
        self,
        source: str,
        state: str,
        failures: int,
        error_class: str | None,
        opened_at: float | None,
    ) -> None:
        with self._connect() as conn:
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
