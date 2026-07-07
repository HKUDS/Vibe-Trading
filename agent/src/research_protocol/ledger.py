"""SQLite WAL trial ledger with confirmation-event helpers."""

from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from src.governance.evidence_identity import canonical_json
from src.reliability.artifacts.hashing import sha256_json
from src.research_protocol.trial import LedgerVerificationResult, TrialEvent, TrialEventType

SCHEMA_VERSION = "1.2.1"
WRITE_RETRY_COUNT = 5
WRITE_RETRY_DELAY_MS = 100
_LEDGER_ENV = "VIBE_TRADING_RESEARCH_LEDGER_PATH"


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


def default_ledger_path() -> Path:
    override = os.getenv(_LEDGER_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".vibe-trading" / "research-ledger" / "ledger.sqlite"


class TrialLedger:
    """Append-only trial ledger using BEGIN IMMEDIATE and hash chaining."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        write_retry_count: int = WRITE_RETRY_COUNT,
        write_retry_delay_ms: int = WRITE_RETRY_DELAY_MS,
        max_attempts: int | None = None,
        sleep_seconds: float | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else default_ledger_path()
        self.write_retry_count = int(max_attempts if max_attempts is not None else write_retry_count)
        self.write_retry_delay_ms = int(write_retry_delay_ms)
        self.legacy_max_attempts = max(1, int(max_attempts if max_attempts is not None else write_retry_count))
        self.legacy_sleep_seconds = (
            float(sleep_seconds)
            if sleep_seconds is not None
            else max(0.0, float(write_retry_delay_ms) / 1000.0)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, *args: Any, **kwargs: Any) -> TrialEvent | str:
        """Append either a formal trial event or a legacy payload dict."""
        if args and isinstance(args[0], dict) and not kwargs:
            return self._append_legacy(args[0])
        return self._append_trial_event(**kwargs)

    def _append_trial_event(
        self,
        *,
        protocol_hash: str,
        event_type: TrialEventType | str,
        payload: dict[str, Any] | None = None,
        artifact_refs: list[str] | None = None,
    ) -> TrialEvent:
        """Append one event, assigning sequence and previous hash inside the transaction."""
        self._init_db()
        last_error: Exception | None = None
        for attempt in range(max(1, self.write_retry_count)):
            conn = self._connect(timeout=0.1)
            try:
                conn.execute("BEGIN IMMEDIATE")
                sequence, previous = self._next_sequence(conn)
                created_at = datetime.now(timezone.utc)
                event_id = f"te_{uuid4().hex}"
                event_type_value = TrialEventType(event_type).value
                payload_dict = dict(payload or {})
                refs = list(artifact_refs or [])
                event_hash = _event_hash(
                    event_id=event_id,
                    event_type=event_type_value,
                    schema_version="1.0.0",
                    protocol_hash=protocol_hash,
                    sequence_number=sequence,
                    previous_event_hash=previous,
                    created_at=created_at.isoformat(),
                    payload=payload_dict,
                    artifact_refs=refs,
                )
                conn.execute(
                    """
                    INSERT INTO trial_events (
                        event_id, event_type, schema_version, protocol_hash,
                        sequence_number, previous_event_hash, event_hash,
                        created_at, payload_json, artifact_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type_value,
                        "1.0.0",
                        protocol_hash,
                        sequence,
                        previous,
                        event_hash,
                        created_at.isoformat(),
                        _json_dump(payload_dict),
                        _json_dump(refs),
                    ),
                )
                conn.commit()
                return TrialEvent(
                    event_id=event_id,
                    event_type=TrialEventType(event_type_value),
                    schema_version="1.0.0",
                    protocol_hash=protocol_hash,
                    sequence_number=sequence,
                    previous_event_hash=previous,
                    event_hash=event_hash,
                    created_at=created_at,
                    payload=payload_dict,
                    artifact_refs=refs,
                )
            except sqlite3.OperationalError as exc:
                conn.rollback()
                last_error = exc
                if "locked" not in str(exc).lower() or attempt >= self.write_retry_count - 1:
                    raise
                delay = (self.write_retry_delay_ms / 1000.0) * (2**attempt)
                delay += random.uniform(0, self.write_retry_delay_ms / 1000.0)
                time.sleep(delay)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        if last_error is not None:
            raise last_error
        raise RuntimeError("failed to append trial event")

    def _append_legacy(self, payload: dict[str, Any]) -> str:
        """Append a v1.2.1 compatibility payload to the legacy hash-chain table."""
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(self.legacy_max_attempts):
            conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=1000")
                self._ensure_legacy_schema(conn)
                conn.execute("BEGIN IMMEDIATE")
                previous_hash = self._latest_legacy_hash(conn)
                event_hash = self._legacy_event_hash(previous_hash, payload)
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
                if "locked" not in str(exc).lower() or attempt == self.legacy_max_attempts - 1:
                    raise
            except BaseException:
                self._rollback_quietly(conn)
                raise
            finally:
                conn.close()

            time.sleep(self.legacy_sleep_seconds)

        if last_error is not None:
            raise last_error
        raise RuntimeError("trial ledger append exhausted without an error")

    def list_events(self) -> list[dict[str, Any]]:
        """Return legacy compatibility events in append order."""
        conn = sqlite3.connect(str(self.path))
        try:
            self._ensure_legacy_schema(conn)
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
            event = dict(payload) if isinstance(payload, dict) else {"payload": payload}
            event["previous_hash"] = previous_hash
            event["event_hash"] = event_hash
            events.append(event)
        return events

    def verify(self) -> LedgerVerificationResult:
        """Verify sequence, previous hash, event hash, protocol hash, and schema version."""
        self._init_db()
        errors: list[str] = []
        previous_hash: str | None = None
        expected_sequence = 1
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, event_type, schema_version, protocol_hash,
                       sequence_number, previous_event_hash, event_hash,
                       created_at, payload_json, artifact_refs_json
                FROM trial_events
                ORDER BY sequence_number ASC
                """
            ).fetchall()
        for row in rows:
            sequence = int(row["sequence_number"])
            if sequence != expected_sequence:
                errors.append(f"sequence gap at {row['event_id']}: expected {expected_sequence}, got {sequence}")
            if row["previous_event_hash"] != previous_hash:
                errors.append(f"previous hash mismatch at sequence {sequence}")
            if row["schema_version"] != "1.0.0":
                errors.append(f"schema_version mismatch at sequence {sequence}")
            if not str(row["protocol_hash"] or "").strip():
                errors.append(f"protocol hash missing at sequence {sequence}")
            try:
                TrialEventType(row["event_type"])
            except ValueError:
                errors.append(f"unknown event_type at sequence {sequence}: {row['event_type']}")
            payload = _json_load(row["payload_json"], {})
            refs = _json_load(row["artifact_refs_json"], [])
            expected_hash = _event_hash(
                event_id=row["event_id"],
                event_type=row["event_type"],
                schema_version=row["schema_version"],
                protocol_hash=row["protocol_hash"],
                sequence_number=sequence,
                previous_event_hash=row["previous_event_hash"],
                created_at=row["created_at"],
                payload=payload,
                artifact_refs=refs,
            )
            if expected_hash != row["event_hash"]:
                errors.append(f"event_hash mismatch at sequence {sequence}")
            previous_hash = row["event_hash"]
            expected_sequence += 1
        return LedgerVerificationResult(valid=not errors, event_count=len(rows), errors=errors)

    def _init_db(self) -> None:
        for attempt in range(max(1, self.write_retry_count)):
            try:
                with self._connect(timeout=0.1) as conn:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS trial_events (
                            event_id TEXT PRIMARY KEY,
                            event_type TEXT NOT NULL,
                            schema_version TEXT NOT NULL,
                            protocol_hash TEXT NOT NULL,
                            sequence_number INTEGER NOT NULL UNIQUE,
                            previous_event_hash TEXT,
                            event_hash TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            artifact_refs_json TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_trial_events_protocol ON trial_events(protocol_hash)")
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt >= self.write_retry_count - 1:
                    raise
                delay = (self.write_retry_delay_ms / 1000.0) * (2**attempt)
                delay += random.uniform(0, self.write_retry_delay_ms / 1000.0)
                time.sleep(delay)

    def _connect(self, *, timeout: float = 30.0) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=timeout, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _next_sequence(conn: sqlite3.Connection) -> tuple[int, str | None]:
        row = conn.execute(
            "SELECT sequence_number, event_hash FROM trial_events ORDER BY sequence_number DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 1, None
        return int(row["sequence_number"]) + 1, str(row["event_hash"])

    @staticmethod
    def _ensure_legacy_schema(conn: Any) -> None:
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
    def _latest_legacy_hash(conn: Any) -> str | None:
        row = conn.execute("SELECT event_hash FROM trial_ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else None

    @staticmethod
    def _legacy_event_hash(previous_hash: str | None, payload: dict[str, Any]) -> str:
        envelope = {"previous_hash": previous_hash, "payload": payload}
        return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()

    @staticmethod
    def _rollback_quietly(conn: Any) -> None:
        try:
            conn.rollback()
        except Exception:
            pass


def _event_hash(
    *,
    event_id: str,
    event_type: str,
    schema_version: str,
    protocol_hash: str,
    sequence_number: int,
    previous_event_hash: str | None,
    created_at: str,
    payload: dict[str, Any],
    artifact_refs: list[str],
) -> str:
    return sha256_json(
        {
            "event_id": event_id,
            "event_type": event_type,
            "schema_version": schema_version,
            "protocol_hash": protocol_hash,
            "sequence_number": sequence_number,
            "previous_event_hash": previous_event_hash,
            "created_at": created_at,
            "payload": payload,
            "artifact_refs": artifact_refs,
        }
    )


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _json_load(value: str, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)
