"""SQLite-backed local artifact store for IRR-AGL Phase 1."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from src.reliability.artifacts.hashing import sha256_bytes
from src.reliability.artifacts.model import ArtifactRecord
from src.reliability.config import artifact_root, reliability_enabled
from src.reliability.errors import ArtifactPathError, ArtifactStoreError
from src.reliability.schema import ARTIFACT_SCHEMA_VERSION, ArtifactType

_INDEX_FILENAME = "artifact_index.sqlite"
_MAX_INSERT_ATTEMPTS = 6


def resolve_under_root(root: Path, relative_path: Path | str) -> Path:
    """Resolve a relative path and ensure it stays inside root."""
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ArtifactPathError(f"absolute paths are not allowed: {relative}")
    resolved_root = Path(root).resolve(strict=False)
    candidate = (resolved_root / relative).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ArtifactPathError(f"path escapes artifact root: {relative}") from exc
    return candidate


class ArtifactStore:
    """Content-addressed local artifact store with a SQLite metadata index."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else artifact_root()
        self._init_lock = Lock()
        self._initialized = False

    @property
    def index_path(self) -> Path:
        """Return the SQLite metadata index path."""
        return self.root / _INDEX_FILENAME

    def write_bytes(
        self,
        data: bytes,
        *,
        artifact_type: ArtifactType,
        generated_by: str,
        metadata: dict[str, Any] | None = None,
        parent_artifacts: list[str] | None = None,
        schema_version: str = ARTIFACT_SCHEMA_VERSION,
        artifact_id: str | None = None,
    ) -> ArtifactRecord | None:
        """Persist bytes and index their artifact metadata."""
        if not reliability_enabled():
            return None

        self._ensure_initialized()
        digest = sha256_bytes(data)
        payload_path = resolve_under_root(self.root, Path("objects") / digest[:2] / f"{digest}.bin")
        _atomic_write_bytes(payload_path, data)

        record = ArtifactRecord(
            artifact_id=artifact_id or f"art_{uuid.uuid4().hex}",
            artifact_type=artifact_type,
            schema_version=schema_version,
            sha256=digest,
            uri=f"artifact://sha256/{digest}",
            path=str(payload_path),
            parent_artifacts=list(parent_artifacts or []),
            generated_by=generated_by,
            metadata=dict(metadata or {}),
        )
        self._insert_record(record)
        return record

    def write_json(
        self,
        payload: dict[str, Any],
        *,
        artifact_type: ArtifactType,
        generated_by: str,
        metadata: dict[str, Any] | None = None,
        parent_artifacts: list[str] | None = None,
        schema_version: str = ARTIFACT_SCHEMA_VERSION,
        artifact_id: str | None = None,
    ) -> ArtifactRecord | None:
        """Persist a JSON payload using strict, deterministic serialization."""
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.write_bytes(
            data,
            artifact_type=artifact_type,
            generated_by=generated_by,
            metadata=metadata,
            parent_artifacts=parent_artifacts,
            schema_version=schema_version,
            artifact_id=artifact_id,
        )

    def get_record(self, artifact_id: str) -> ArtifactRecord | None:
        """Return an indexed artifact record by ID, or ``None`` if absent."""
        if not reliability_enabled() or not self.index_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    artifact_id,
                    artifact_type,
                    schema_version,
                    sha256,
                    uri,
                    path,
                    inline_ref,
                    parent_artifacts_json,
                    created_at,
                    generated_by,
                    metadata_json
                FROM artifacts
                WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return ArtifactRecord(
            artifact_id=row[0],
            artifact_type=row[1],
            schema_version=row[2],
            sha256=row[3],
            uri=row[4],
            path=row[5],
            inline_ref=row[6],
            parent_artifacts=json.loads(row[7]),
            created_at=row[8],
            generated_by=row[9],
            metadata=json.loads(row[10]),
        )

    def list_records(
        self,
        *,
        run_id: str | None = None,
        artifact_type: ArtifactType | None = None,
    ) -> list[ArtifactRecord]:
        """Return indexed artifact records, optionally filtered by metadata."""
        if not reliability_enabled() or not self.index_path.exists():
            return []
        query = """
            SELECT
                artifact_id,
                artifact_type,
                schema_version,
                sha256,
                uri,
                path,
                inline_ref,
                parent_artifacts_json,
                created_at,
                generated_by,
                metadata_json
            FROM artifacts
        """
        params: list[str] = []
        conditions: list[str] = []
        if artifact_type is not None:
            conditions.append("artifact_type = ?")
            params.append(artifact_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        records = [self._record_from_row(row) for row in rows]
        if run_id is not None:
            records = [record for record in records if record.metadata.get("run_id") == run_id]
        return records

    def read_json(self, artifact_id: str) -> dict[str, Any] | None:
        """Read a JSON artifact payload by artifact ID."""
        record = self.get_record(artifact_id)
        if record is None or record.path is None:
            return None
        try:
            payload = json.loads(Path(record.path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _record_from_row(row: tuple[Any, ...]) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=row[0],
            artifact_type=row[1],
            schema_version=row[2],
            sha256=row[3],
            uri=row[4],
            path=row[5],
            inline_ref=row[6],
            parent_artifacts=json.loads(row[7]),
            created_at=row[8],
            generated_by=row[9],
            metadata=json.loads(row[10]),
        )

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        artifact_type TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        uri TEXT NOT NULL,
                        path TEXT,
                        inline_ref TEXT,
                        parent_artifacts_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        generated_by TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.index_path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _insert_record(self, record: ArtifactRecord) -> None:
        dumped = record.model_dump(mode="json")
        parent_artifacts_json = json.dumps(dumped["parent_artifacts"], ensure_ascii=False, sort_keys=True)
        metadata_json = json.dumps(dumped["metadata"], ensure_ascii=False, sort_keys=True)
        params = (
            dumped["artifact_id"],
            dumped["artifact_type"],
            dumped["schema_version"],
            dumped["sha256"],
            dumped["uri"],
            dumped.get("path"),
            dumped.get("inline_ref"),
            parent_artifacts_json,
            dumped["created_at"],
            dumped["generated_by"],
            metadata_json,
        )
        for attempt in range(_MAX_INSERT_ATTEMPTS):
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        """
                        INSERT INTO artifacts (
                            artifact_id,
                            artifact_type,
                            schema_version,
                            sha256,
                            uri,
                            path,
                            inline_ref,
                            parent_artifacts_json,
                            created_at,
                            generated_by,
                            metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        params,
                    )
                    conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == _MAX_INSERT_ATTEMPTS - 1:
                    raise ArtifactStoreError(str(exc)) from exc
                time.sleep(0.02 * (2**attempt))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically with a same-directory temp file."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
