"""Protocol review ledger events for confirmation records."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.governance.evidence_identity import canonical_json

SCHEMA_VERSION = "1.2.1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProtocolLedgerEvent(BaseModel):
    """Hash-addressed protocol confirmation event."""

    schema_version: str = SCHEMA_VERSION
    event_type: str = "protocol_field_confirmed"
    protocol_id: str
    field_path: str
    confirmed_by: str
    value_hash: str
    event_hash: str
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


def record_protocol_field_confirmation(
    *,
    protocol_id: str,
    field_path: str,
    value: Any,
    confirmed_by: str,
) -> ProtocolLedgerEvent:
    """Create a deterministic confirmation event suitable for ledger/artifact storage."""
    value_hash = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    envelope = {
        "event_type": "protocol_field_confirmed",
        "protocol_id": protocol_id,
        "field_path": field_path,
        "confirmed_by": confirmed_by,
        "value_hash": value_hash,
    }
    event_hash = hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()
    return ProtocolLedgerEvent(
        protocol_id=protocol_id,
        field_path=field_path,
        confirmed_by=confirmed_by,
        value_hash=value_hash,
        event_hash=event_hash,
    )


class TrialLedger:
    """SQLite-backed trial event ledger with retry-safe connection lifecycle."""

    def __init__(self, path: str | Path, *, max_attempts: int = 3, sleep_seconds: float = 0.02) -> None:
        self.path = Path(path)
        self.max_attempts = max(1, max_attempts)
        self.sleep_seconds = sleep_seconds

    def append(self, payload: dict[str, Any]) -> str:
        """Append a payload to the hash chain and return the event hash."""
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(self.max_attempts):
            conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=1000")
                self._ensure_schema(conn)
                conn.execute("BEGIN IMMEDIATE")
                previous_hash = self._latest_hash(conn)
                event_hash = self._event_hash(previous_hash, payload)
                conn.execute(
                    """
                    INSERT INTO trial_ledger(previous_hash, event_hash, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (previous_hash, event_hash, canonical_json(payload)),
                )
                conn.commit()
                return event_hash
            except sqlite3.OperationalError as exc:
                last_error = exc
                self._rollback_quietly(conn)
                if "locked" not in str(exc).lower() or attempt == self.max_attempts - 1:
                    raise
            except BaseException:
                self._rollback_quietly(conn)
                raise
            finally:
                conn.close()

            time.sleep(self.sleep_seconds)

        if last_error is not None:
            raise last_error
        raise RuntimeError("trial ledger append exhausted without an error")

    def list_events(self) -> list[dict[str, Any]]:
        """Return ledger events in append order."""
        conn = sqlite3.connect(self.path)
        try:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT previous_hash, event_hash, payload_json
                FROM trial_ledger
                ORDER BY seq ASC
                """
            ).fetchall()
        finally:
            conn.close()

        events: list[dict[str, Any]] = []
        for previous_hash, event_hash, payload_json in rows:
            payload = json.loads(payload_json)
            if isinstance(payload, dict):
                event = dict(payload)
            else:
                event = {"payload": payload}
            event["previous_hash"] = previous_hash
            event["event_hash"] = event_hash
            events.append(event)
        return events

    @staticmethod
    def _ensure_schema(conn: Any) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trial_ledger (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                previous_hash TEXT,
                event_hash TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _latest_hash(conn: Any) -> str | None:
        row = conn.execute("SELECT event_hash FROM trial_ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else None

    @staticmethod
    def _event_hash(previous_hash: str | None, payload: dict[str, Any]) -> str:
        envelope = {"previous_hash": previous_hash, "payload": payload}
        return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()

    @staticmethod
    def _rollback_quietly(conn: Any) -> None:
        try:
            conn.rollback()
        except Exception:
            pass
