"""SQLite-backed RunEvidenceIndex derived view for v1.2.1 evidence."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


SCHEMA_VERSION = "1.2.1"
_INDEX_FILENAME = "evidence_index.sqlite"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunEvidenceIndex(BaseModel):
    """Derived evidence refs for one run, with IDs and artifact refs separated."""

    schema_version: str = SCHEMA_VERSION
    run_id: str
    session_id: str | None = None
    protocol_hash: str | None = None
    policy_decision_ids: list[str] = Field(default_factory=list)
    policy_decision_artifact_refs: list[str] = Field(default_factory=list)
    trace_event_refs: list[str] = Field(default_factory=list)
    ledger_event_hashes: list[str] = Field(default_factory=list)
    data_audit_artifact_refs: list[str] = Field(default_factory=list)
    backtest_artifact_refs: list[str] = Field(default_factory=list)
    alpha_bench_artifact_refs: list[str] = Field(default_factory=list)
    scorecard_artifact_refs: list[str] = Field(default_factory=list)
    research_card_artifact_refs: list[str] = Field(default_factory=list)
    claim_set_artifact_refs: list[str] = Field(default_factory=list)
    methodology_fact_artifact_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _datetime_must_be_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(timezone.utc)


class EvidenceIndexStore:
    """SQLite WAL persistence for RunEvidenceIndex records."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_index_path()
        self._initialized = False

    def get_or_create(self, run_id: str) -> RunEvidenceIndex:
        existing = self.get(run_id)
        return existing if existing is not None else RunEvidenceIndex(run_id=run_id)

    def get(self, run_id: str) -> RunEvidenceIndex | None:
        if not self.path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM run_evidence_index WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RunEvidenceIndex.model_validate(json.loads(row[0]))

    def write(self, index: RunEvidenceIndex) -> RunEvidenceIndex:
        self._ensure_initialized()
        index.updated_at = _utc_now()
        payload = json.dumps(index.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO run_evidence_index (run_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (index.run_id, payload, index.updated_at.isoformat()),
            )
            conn.commit()
        return index

    def record_policy_decision(self, envelope: object) -> RunEvidenceIndex | None:
        run_id = getattr(envelope, "run_id", None)
        if not run_id or not evidence_index_enabled():
            return None
        index = self.get_or_create(run_id)
        index.session_id = index.session_id or getattr(envelope, "session_id", None)
        index.protocol_hash = index.protocol_hash or getattr(envelope, "protocol_hash", None)
        _append_unique(index.policy_decision_ids, getattr(envelope, "decision_id", None))
        identity = getattr(envelope, "evidence_identity", None)
        if identity is not None:
            _append_unique(index.policy_decision_artifact_refs, getattr(identity, "policy_decision_artifact_id", None))
            _append_unique(index.trace_event_refs, getattr(identity, "trace_event_id", None))
            _append_unique(index.ledger_event_hashes, getattr(identity, "ledger_event_hash", None))
        return self.write(index)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_evidence_index (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn


def evidence_index_enabled() -> bool:
    return os.getenv("VIBE_TRADING_EVIDENCE_INDEX_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}


def _default_index_path() -> Path:
    raw = os.getenv("VIBE_TRADING_EVIDENCE_INDEX_PATH")
    if raw:
        return Path(os.path.expandvars(os.path.expanduser(raw))).resolve(strict=False)
    return (Path.home() / ".vibe-trading" / "evidence_index.sqlite").resolve(strict=False)


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)

