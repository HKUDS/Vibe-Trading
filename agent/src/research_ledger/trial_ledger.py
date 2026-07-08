from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal

from src.research_ledger.hash_utils import (
    canonical_json_hash,
    json_safe,
    redact_secrets,
    utc_now_iso,
)


class TrialLedgerMutationError(RuntimeError):
    """Raised when callers attempt to update/delete append-only records."""


class TrialLedgerAppendError(RuntimeError):
    """Raised when the ledger cannot append a record safely."""


@dataclass(frozen=True)
class TrialLedgerEntry:
    trial_id: str
    trial_group_id: str
    parent_trial_id: str | None
    candidate_id: str
    parent_seed_id: str | None
    formula: str
    formula_hash: str
    data_snapshot_hash: str
    universe_hash: str
    split_id: str
    data_scope: Literal["train", "train_valid", "final_test", "demo_fixture"]
    search_space_hash: str
    objective: str
    random_seed: int | None
    n_candidates_seen_so_far: int
    status: Literal["success", "reject", "skip", "error"]
    decision: Literal[
        "reject",
        "research_only",
        "candidate_zoo",
        "paper_candidate",
        "forward_track",
        "none",
    ]
    reason_codes: list[str]
    metrics_summary: dict[str, float | int | str | bool | None]
    previous_entry_hash: str | None
    entry_hash: str
    created_at: str
    schema_version: Literal["trial_ledger_entry.v1"] = "trial_ledger_entry.v1"
    parameter_variant: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrialLedgerEntry":
        return cls(**payload)

    def sanitized(self) -> "TrialLedgerEntry":
        return replace(
            self,
            parameter_variant=redact_secrets(self.parameter_variant or {}),
            metrics_summary=redact_secrets(self.metrics_summary),
            created_at=self.created_at or utc_now_iso(),
        )

    def with_hashes(
        self, previous_entry_hash: str | None
    ) -> "TrialLedgerEntry":
        prepared = replace(
            self.sanitized(),
            previous_entry_hash=previous_entry_hash,
            entry_hash="",
        )
        digest = canonical_json_hash(prepared.to_dict(), exclude_keys=("entry_hash",))
        return replace(prepared, entry_hash=digest)


class TrialLedger:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trial_entries (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    trial_id TEXT NOT NULL UNIQUE,
                    trial_group_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    previous_entry_hash TEXT,
                    entry_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trial_entries_candidate ON trial_entries(candidate_id)"
            )

    def append(self, entry: TrialLedgerEntry) -> TrialLedgerEntry:
        last_error: Exception | None = None
        for attempt in range(8):
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    previous = self._tail_hash(conn)
                    prepared = entry.with_hashes(previous)
                    payload = json.dumps(
                        prepared.to_dict(),
                        sort_keys=True,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                    conn.execute(
                        """
                        INSERT INTO trial_entries (
                            trial_id, trial_group_id, candidate_id,
                            previous_entry_hash, entry_hash, created_at, payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            prepared.trial_id,
                            prepared.trial_group_id,
                            prepared.candidate_id,
                            prepared.previous_entry_hash,
                            prepared.entry_hash,
                            prepared.created_at,
                            payload,
                        ),
                    )
                    conn.execute("COMMIT")
                    return prepared
            except sqlite3.OperationalError as exc:
                last_error = exc
                time.sleep(0.02 * (attempt + 1))
            except sqlite3.IntegrityError as exc:
                raise TrialLedgerAppendError(str(exc)) from exc
            except Exception:
                try:
                    with self._connect() as conn:
                        conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        raise TrialLedgerAppendError(f"append failed after retries: {last_error}")

    def _tail_hash(self, conn: sqlite3.Connection) -> str | None:
        row = conn.execute(
            "SELECT entry_hash FROM trial_entries ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return None if row is None else str(row["entry_hash"])

    def query(self, *, candidate_id: str | None = None) -> list[TrialLedgerEntry]:
        sql = "SELECT payload FROM trial_entries"
        params: tuple[str, ...] = ()
        if candidate_id is not None:
            sql += " WHERE candidate_id = ?"
            params = (candidate_id,)
        sql += " ORDER BY seq ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [TrialLedgerEntry.from_dict(json.loads(row["payload"])) for row in rows]

    def verify_hash_chain(self) -> bool:
        previous: str | None = None
        for entry in self.query():
            if entry.previous_entry_hash != previous:
                return False
            expected = entry.with_hashes(entry.previous_entry_hash)
            if expected.entry_hash != entry.entry_hash:
                return False
            previous = entry.entry_hash
        return True

    def update(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        raise TrialLedgerMutationError("trial ledger is append-only")

    def delete(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        raise TrialLedgerMutationError("trial ledger is append-only")
