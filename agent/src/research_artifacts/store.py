"""SQLite index for immutable, versioned research artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from src.config.accessor import get_env_config
from src.config.paths import get_runtime_root

from .models import ResearchArtifactRevision, ResearchArtifactSaveResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _default_db_path() -> Path:
    paths = get_env_config().paths
    override = paths.vibe_trading_research_artifact_db_path.strip()
    if override:
        return Path(override).expanduser()
    goal_path = paths.vibe_trading_goal_db_path.strip()
    if goal_path:
        return Path(goal_path).expanduser()
    return get_runtime_root() / "sessions.db"


def _required(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required (string)")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


F = TypeVar("F", bound=Callable)


def _synchronized(method: F) -> F:
    @wraps(method)
    def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class ResearchArtifactStore:
    """Persist research revisions without modifying GoalStore or SDM records."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS research_artifact_revisions (
                    revision_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    previous_revision_id TEXT,
                    subject TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    provenance_hash TEXT NOT NULL,
                    identity_hash TEXT NOT NULL UNIQUE,
                    data_as_of TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    hypothesis_id TEXT,
                    goal_id TEXT,
                    session_id TEXT,
                    run_id TEXT,
                    UNIQUE(artifact_id, revision_number),
                    FOREIGN KEY(previous_revision_id)
                        REFERENCES research_artifact_revisions(revision_id)
                );

                CREATE INDEX IF NOT EXISTS idx_research_artifact_series
                    ON research_artifact_revisions(artifact_id, revision_number);
                CREATE INDEX IF NOT EXISTS idx_research_artifact_subject
                    ON research_artifact_revisions(subject, universe);
                CREATE INDEX IF NOT EXISTS idx_research_artifact_goal
                    ON research_artifact_revisions(goal_id);
                CREATE INDEX IF NOT EXISTS idx_research_artifact_hypothesis
                    ON research_artifact_revisions(hypothesis_id);
                CREATE INDEX IF NOT EXISTS idx_research_artifact_run
                    ON research_artifact_revisions(run_id);
                """)
            self._conn.commit()

    def close(self) -> None:
        """Close the SQLite connection, primarily for isolated test cleanup."""
        with self._lock:
            self._conn.close()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ResearchArtifactRevision:
        return ResearchArtifactRevision(
            revision_id=row["revision_id"],
            artifact_id=row["artifact_id"],
            revision_number=row["revision_number"],
            previous_revision_id=row["previous_revision_id"],
            subject=row["subject"],
            universe=row["universe"],
            content=row["content"],
            content_hash=row["content_hash"],
            provenance_hash=row["provenance_hash"],
            identity_hash=row["identity_hash"],
            data_as_of=row["data_as_of"],
            created_at=row["created_at"],
            evidence=tuple(json.loads(row["evidence_json"])),
            verification_status=row["verification_status"],
            completeness=row["completeness"],
            hypothesis_id=row["hypothesis_id"],
            goal_id=row["goal_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
        )

    def _latest(self, artifact_id: str) -> ResearchArtifactRevision | None:
        row = self._conn.execute(
            """
            SELECT * FROM research_artifact_revisions
            WHERE artifact_id = ?
            ORDER BY revision_number DESC LIMIT 1
            """,
            (artifact_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def _by_fingerprint(
        self, content_hash: str, provenance_hash: str, artifact_id: str | None
    ) -> ResearchArtifactRevision | None:
        row = self._conn.execute(
            "SELECT * FROM research_artifact_revisions WHERE content_hash = ? AND provenance_hash = ?"
            + (" AND artifact_id = ?" if artifact_id else "")
            + " ORDER BY created_at DESC LIMIT 1",
            (
                (content_hash, provenance_hash, artifact_id)
                if artifact_id
                else (content_hash, provenance_hash)
            ),
        ).fetchone()
        return self._from_row(row) if row else None

    @_synchronized
    def save(
        self,
        *,
        content: str,
        data_as_of: str,
        artifact_id: str | None = None,
        subject: str | None = None,
        universe: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        verification_status: str | None = None,
        completeness: str | None = None,
        hypothesis_id: str | None = None,
        goal_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> ResearchArtifactSaveResult:
        """Append a revision, or return the identical existing revision."""
        self._conn.execute("BEGIN IMMEDIATE")
        with self._conn:
            content = _required(content, "content")
            data_as_of = _required(data_as_of, "data_as_of")
            latest = self._latest(artifact_id) if artifact_id else None
            if artifact_id and latest is None:
                raise KeyError(f"research artifact not found: {artifact_id}")

            if latest is None:
                subject = _required(subject or "", "subject")
                universe = (universe or "").strip()
                evidence = list(evidence or [])
                verification_status = verification_status or "unverified"
                completeness = completeness or "complete"
            else:
                subject = _required(
                    subject if subject is not None else latest.subject, "subject"
                )
                universe = latest.universe if universe is None else universe.strip()
                if subject != latest.subject or universe != latest.universe:
                    raise ValueError(
                        "a revision must preserve the artifact subject and universe"
                    )
                evidence = list(latest.evidence) if evidence is None else list(evidence)
                unchanged = (
                    content == latest.content
                    and data_as_of == latest.data_as_of
                    and evidence == list(latest.evidence)
                    and all(
                        value is None or value == getattr(latest, key)
                        for key, value in (
                            ("hypothesis_id", hypothesis_id),
                            ("goal_id", goal_id),
                            ("session_id", session_id),
                            ("run_id", run_id),
                        )
                    )
                )
                verification_status = verification_status or (
                    latest.verification_status if unchanged else "unverified"
                )
                completeness = completeness or latest.completeness
                hypothesis_id = hypothesis_id or latest.hypothesis_id
                goal_id = goal_id or latest.goal_id
                session_id = session_id or latest.session_id
                run_id = run_id or latest.run_id

            if any(not isinstance(item, dict) for item in evidence):
                raise ValueError("evidence must contain JSON objects")
            evidence_json = _canonical_json(evidence)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            provenance_hash = hashlib.sha256(
                _canonical_json(
                    {
                        "subject": subject,
                        "universe": universe,
                        "data_as_of": data_as_of,
                        "evidence": evidence,
                        "verification_status": verification_status,
                        "completeness": completeness,
                        "hypothesis_id": hypothesis_id,
                        "goal_id": goal_id,
                        "session_id": session_id,
                        "run_id": run_id,
                    }
                ).encode("utf-8")
            ).hexdigest()
            existing = self._by_fingerprint(content_hash, provenance_hash, artifact_id)
            if existing is not None:
                return ResearchArtifactSaveResult(existing, created=False)

            if latest is None:
                artifact_id = f"ra_{uuid.uuid4().hex[:12]}"
                revision_number = 1
                previous_revision_id = None
            else:
                revision_number = latest.revision_number + 1
                previous_revision_id = latest.revision_id
            revision_id = f"{artifact_id}_r{revision_number}"
            identity_hash = hashlib.sha256(
                f"{artifact_id}:{content_hash}:{provenance_hash}".encode("ascii")
            ).hexdigest()
            created_at = _utc_now()

            self._conn.execute(
                """
                INSERT INTO research_artifact_revisions (
                    revision_id, artifact_id, revision_number, previous_revision_id,
                    subject, universe, content, content_hash, provenance_hash,
                    identity_hash, data_as_of, created_at, evidence_json,
                    verification_status, completeness, hypothesis_id, goal_id,
                    session_id, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    artifact_id,
                    revision_number,
                    previous_revision_id,
                    subject,
                    universe,
                    content,
                    content_hash,
                    provenance_hash,
                    identity_hash,
                    data_as_of,
                    created_at,
                    evidence_json,
                    verification_status,
                    completeness,
                    hypothesis_id,
                    goal_id,
                    session_id,
                    run_id,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM research_artifact_revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
            return ResearchArtifactSaveResult(self._from_row(row), created=True)

    @_synchronized
    def get_latest(self, artifact_id: str) -> ResearchArtifactRevision | None:
        """Return the newest revision in one series."""
        return self._latest(artifact_id)

    @_synchronized
    def get_revision(self, revision_id: str) -> ResearchArtifactRevision | None:
        """Return one immutable revision by its stable ID."""
        row = self._conn.execute(
            "SELECT * FROM research_artifact_revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    @_synchronized
    def list_revisions(self, artifact_id: str) -> list[ResearchArtifactRevision]:
        """Return a series newest first, including every linked revision."""
        rows = self._conn.execute(
            """
            SELECT * FROM research_artifact_revisions
            WHERE artifact_id = ? ORDER BY revision_number DESC
            """,
            (artifact_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @_synchronized
    def search(
        self,
        *,
        query: str = "",
        subject: str = "",
        universe: str = "",
        hypothesis_id: str = "",
        goal_id: str = "",
        session_id: str = "",
        run_id: str = "",
        limit: int = 50,
    ) -> list[ResearchArtifactRevision]:
        """Search the latest revision of each series with optional provenance filters."""
        limit = max(1, min(int(limit), 200))
        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip()}%"
            clauses.append("(subject LIKE ? OR universe LIKE ? OR content LIKE ?)")
            params.extend([needle, needle, needle])
        for column, value in (
            ("subject", subject.strip()),
            ("universe", universe.strip()),
            ("hypothesis_id", hypothesis_id.strip()),
            ("goal_id", goal_id.strip()),
            ("session_id", session_id.strip()),
            ("run_id", run_id.strip()),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT r.* FROM research_artifact_revisions AS r
            JOIN (
                SELECT artifact_id, MAX(revision_number) AS latest_revision
                FROM research_artifact_revisions
                GROUP BY artifact_id
            ) AS latest
            ON r.artifact_id = latest.artifact_id
            AND r.revision_number = latest.latest_revision
            {where}
            ORDER BY r.created_at DESC, r.revision_id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [self._from_row(row) for row in rows]
