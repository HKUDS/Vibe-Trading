"""Durable SQLite outbox for failed or partial evidence writes."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.reliability.redaction import redact_secrets

_OUTBOX_FILENAME = "evidence_outbox.sqlite"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceOutboxEntry(BaseModel):
    """One pending/reconciled evidence write fallback row."""

    schema_version: str = "1.2.1"
    idempotency_key: str
    decision_id: str
    run_id: str | None = None
    status: Literal["pending", "reconciled"] = "pending"
    payload: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvidenceOutbox:
    """SQLite WAL outbox for evidence writes that need reconciliation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_outbox_path()
        self._initialized = False

    def append(self, envelope: Any, *, errors: list[str] | None = None) -> EvidenceOutboxEntry:
        self._ensure_initialized()
        now = _utc_now()
        payload = redact_secrets(envelope.model_dump(mode="json") if hasattr(envelope, "model_dump") else dict(envelope))
        idempotency_key = envelope.evidence_identity.idempotency_key
        entry = EvidenceOutboxEntry(
            idempotency_key=idempotency_key,
            decision_id=envelope.decision_id,
            run_id=envelope.run_id,
            payload=payload,
            errors=list(errors or []),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO evidence_outbox (
                    idempotency_key,
                    decision_id,
                    run_id,
                    status,
                    payload_json,
                    errors_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    decision_id = excluded.decision_id,
                    run_id = excluded.run_id,
                    status = 'pending',
                    payload_json = excluded.payload_json,
                    errors_json = excluded.errors_json,
                    updated_at = excluded.updated_at
                """,
                (
                    entry.idempotency_key,
                    entry.decision_id,
                    entry.run_id,
                    entry.status,
                    json.dumps(entry.payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(entry.errors, ensure_ascii=False, sort_keys=True),
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                ),
            )
            conn.commit()
        return entry

    def list_pending(self, *, run_id: str | None = None) -> list[EvidenceOutboxEntry]:
        if not self.path.exists():
            return []
        query = (
            "SELECT idempotency_key, decision_id, run_id, status, payload_json, errors_json, created_at, updated_at "
            "FROM evidence_outbox WHERE status = 'pending'"
        )
        params: tuple[str, ...] = ()
        if run_id is not None:
            query += " AND run_id = ?"
            params = (run_id,)
        query += " ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def mark_reconciled(self, idempotency_key: str) -> None:
        if not self.path.exists():
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE evidence_outbox SET status = 'reconciled', updated_at = ? WHERE idempotency_key = ?",
                (_utc_now().isoformat(), idempotency_key),
            )

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_outbox (
                    idempotency_key TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    run_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _row_to_entry(row: tuple[Any, ...]) -> EvidenceOutboxEntry:
        return EvidenceOutboxEntry(
            idempotency_key=row[0],
            decision_id=row[1],
            run_id=row[2],
            status=row[3],
            payload=json.loads(row[4]),
            errors=json.loads(row[5]),
            created_at=datetime.fromisoformat(row[6]),
            updated_at=datetime.fromisoformat(row[7]),
        )


def evidence_outbox_enabled() -> bool:
    return os.getenv("VIBE_TRADING_EVIDENCE_OUTBOX_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}


def _default_outbox_path() -> Path:
    raw = os.getenv("VIBE_TRADING_EVIDENCE_OUTBOX_PATH")
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw))).resolve(strict=False)
    return (Path.home() / ".vibe-trading" / _OUTBOX_FILENAME).resolve(strict=False)

