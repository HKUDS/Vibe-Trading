"""SQLite-backed strategy/factor artifact store.

Satisfies ``StrategyStoreProtocol``.  Uses WAL mode for concurrent reads,
FK constraints for referential integrity, and ``PRAGMA user_version``
for schema migrations.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BenchCategory,
    BenchResult,
    DecaySignal,
    DecaySnapshot,
    ModelTier,
    ValidationStatus,
    validate_validation_status_transition,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path.home() / ".vibe-trading" / "strategy_store.db"

# Schema version introduced by the model-governance migration (adds the
# developer/owner/validator/approver/model_version/artifact_version/
# model_tier/intended_use/limitations/validation_status/validation_date
# columns to `artifacts`). Bumping PRAGMA user_version documents intent;
# the migration itself is idempotent via a column-existence check so it is
# safe to run unconditionally on every open regardless of the stamped
# version (covers DBs that were hand-edited or partially migrated).
_SCHEMA_VERSION_GOVERNANCE = 2

# column_name -> DDL type/default fragment used by ALTER TABLE ADD COLUMN.
_GOVERNANCE_COLUMNS: dict[str, str] = {
    "developer": "TEXT",
    "owner": "TEXT",
    "validator": "TEXT",
    "approver": "TEXT",
    "model_version": "TEXT",
    "artifact_version": "TEXT",
    "model_tier": "TEXT",
    "intended_use": "TEXT",
    "limitations": "TEXT",
    "validation_status": "TEXT DEFAULT 'unvalidated'",
    "validation_date": "TEXT",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_artifact_id() -> str:
    """Generate a unique artifact identifier."""
    return f"art_{uuid.uuid4().hex[:12]}"


def _json_dumps(value: object) -> str:
    """Serialize *value* to a compact JSON string."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None, default: object) -> object:
    """Deserialize a JSON string, returning *default* when empty."""
    if not value:
        return default
    return json.loads(value)


def _default_db_path() -> Path:
    """Return the configured strategy-store database path."""
    from src.config.accessor import get_env_config

    raw_path = get_env_config().paths.vibe_trading_strategy_store_db_path.strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return _DEFAULT_DB_PATH


F = TypeVar("F", bound=Callable)


def _synchronized(method: F) -> F:
    """Serialize access to the shared SQLite connection."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# SqliteStrategyStore
# ---------------------------------------------------------------------------


class SqliteStrategyStore:
    """SQLite-backed strategy/factor artifact store.

    Satisfies ``StrategyStoreProtocol``.  Uses WAL mode for concurrent reads,
    FK constraints for referential integrity, and ``PRAGMA user_version``
    for schema migrations.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize the strategy store.

        Args:
            db_path: SQLite database path.  When omitted,
                ``VIBE_TRADING_STRATEGY_STORE_DB_PATH`` can override the
                default ``~/.vibe-trading/strategy_store.db``.
        """
        self.db_path = (
            Path(db_path) if db_path is not None else _default_db_path()
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init_db()

    # -- Schema bootstrap ---------------------------------------------------

    def _init_db(self) -> None:
        """Create schema if needed, set PRAGMAs."""
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id              TEXT PRIMARY KEY,
                    type            TEXT NOT NULL CHECK(type IN ('factor', 'strategy')),
                    name            TEXT NOT NULL,
                    source_paper    TEXT,
                    source_url      TEXT,
                    formula_latex   TEXT,
                    theme           TEXT,
                    columns_required TEXT,
                    decay_horizon   INTEGER DEFAULT 20,
                    signal_definition TEXT,
                    entry_rules     TEXT,
                    exit_rules      TEXT,
                    position_sizing TEXT,
                    universe        TEXT NOT NULL,
                    signal_engine_path TEXT,
                    run_dir         TEXT,
                    hypothesis_id   TEXT,
                    status          TEXT NOT NULL DEFAULT 'created'
                                    CHECK(status IN (
                                        'created','benching','active',
                                        'monitoring','decayed','disabled')),
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    disabled_at     TEXT,
                    disabled_reason TEXT,
                    UNIQUE(name, universe)
                );

                CREATE TABLE IF NOT EXISTS bench_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_id     TEXT NOT NULL
                                    REFERENCES artifacts(id) ON DELETE CASCADE,
                    bench_type      TEXT NOT NULL
                                    CHECK(bench_type IN ('initial','periodic','manual')),
                    ic_mean         REAL,
                    ic_std          REAL,
                    ir              REAL,
                    ic_positive_ratio REAL,
                    t_stat          REAL,
                    sharpe          REAL,
                    annual_return   REAL,
                    max_drawdown    REAL,
                    calmar          REAL,
                    category        TEXT
                                    CHECK(category IN (
                                        'alive','reversed','dead',
                                        'confirmed_alive','noise')),
                    train_start     TEXT,
                    train_end       TEXT,
                    test_start      TEXT,
                    test_end        TEXT,
                    run_dir         TEXT,
                    created_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decay_snapshots (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_id     TEXT NOT NULL
                                    REFERENCES artifacts(id) ON DELETE CASCADE,
                    rolling_ic_mean     REAL,
                    rolling_ir          REAL,
                    baseline_ic_mean    REAL,
                    ic_ratio            REAL,
                    decay_signal    TEXT
                                    CHECK(decay_signal IN (
                                        'healthy','warning','decayed','critical')),
                    consecutive_warnings INTEGER DEFAULT 0,
                    detail          TEXT,
                    created_at      TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_status
                    ON artifacts(status);
                CREATE INDEX IF NOT EXISTS idx_artifacts_type
                    ON artifacts(type);
                CREATE INDEX IF NOT EXISTS idx_bench_artifact
                    ON bench_history(artifact_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_decay_artifact
                    ON decay_snapshots(artifact_id, created_at);
                """
            )
            if self._conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                self._conn.execute("PRAGMA user_version=1")
            self._migrate_governance_columns()
            if self._conn.execute("PRAGMA user_version").fetchone()[0] < _SCHEMA_VERSION_GOVERNANCE:
                self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION_GOVERNANCE}")
            self._conn.commit()

    def _migrate_governance_columns(self) -> None:
        """Add model-governance columns to ``artifacts`` if missing.

        Idempotent: checks ``PRAGMA table_info`` for each column before
        issuing ``ALTER TABLE ADD COLUMN``, so it is safe to call on every
        connection open — including against a pre-governance database that
        predates this migration (the primary backward-compatibility path)
        and against re-running this exact method twice in the same process.
        """
        existing_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(artifacts)")
        }
        for column, ddl in _GOVERNANCE_COLUMNS.items():
            if column not in existing_columns:
                self._conn.execute(f"ALTER TABLE artifacts ADD COLUMN {column} {ddl}")

    # -- Write transaction --------------------------------------------------

    @contextmanager
    def _write_transaction(self):
        """Open an immediate write transaction for cross-connection safety."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    # -- Row converters -----------------------------------------------------

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> Artifact:
        """Convert a database row to an ``Artifact`` dataclass."""
        return Artifact(
            id=row["id"],
            type=ArtifactType(row["type"]),
            name=row["name"],
            universe=row["universe"],
            source_paper=row["source_paper"],
            source_url=row["source_url"],
            formula_latex=row["formula_latex"],
            theme=tuple(_json_loads(row["theme"], [])),
            columns_required=tuple(_json_loads(row["columns_required"], [])),
            decay_horizon=row["decay_horizon"],
            signal_definition=row["signal_definition"],
            entry_rules=row["entry_rules"],
            exit_rules=row["exit_rules"],
            position_sizing=row["position_sizing"],
            signal_engine_path=row["signal_engine_path"],
            run_dir=row["run_dir"],
            hypothesis_id=row["hypothesis_id"],
            status=ArtifactStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            disabled_at=row["disabled_at"],
            disabled_reason=row["disabled_reason"],
            developer=row["developer"],
            owner=row["owner"],
            validator=row["validator"],
            approver=row["approver"],
            model_version=row["model_version"],
            artifact_version=row["artifact_version"],
            model_tier=ModelTier(row["model_tier"]) if row["model_tier"] else None,
            intended_use=row["intended_use"],
            limitations=row["limitations"],
            validation_status=(
                ValidationStatus(row["validation_status"])
                if row["validation_status"]
                else ValidationStatus.UNVALIDATED
            ),
            validation_date=row["validation_date"],
        )

    @staticmethod
    def _row_to_bench_result(row: sqlite3.Row) -> BenchResult:
        """Convert a database row to a ``BenchResult`` dataclass."""
        category = row["category"]
        return BenchResult(
            id=row["id"],
            artifact_id=row["artifact_id"],
            bench_type=row["bench_type"],
            ic_mean=row["ic_mean"],
            ic_std=row["ic_std"],
            ir=row["ir"],
            ic_positive_ratio=row["ic_positive_ratio"],
            t_stat=row["t_stat"],
            sharpe=row["sharpe"],
            annual_return=row["annual_return"],
            max_drawdown=row["max_drawdown"],
            calmar=row["calmar"],
            category=BenchCategory(category) if category else None,
            train_start=row["train_start"],
            train_end=row["train_end"],
            test_start=row["test_start"],
            test_end=row["test_end"],
            run_dir=row["run_dir"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_decay_snapshot(row: sqlite3.Row) -> DecaySnapshot:
        """Convert a database row to a ``DecaySnapshot`` dataclass."""
        signal = row["decay_signal"]
        return DecaySnapshot(
            id=row["id"],
            artifact_id=row["artifact_id"],
            rolling_ic_mean=row["rolling_ic_mean"],
            rolling_ir=row["rolling_ir"],
            baseline_ic_mean=row["baseline_ic_mean"],
            ic_ratio=row["ic_ratio"],
            decay_signal=DecaySignal(signal) if signal else None,
            consecutive_warnings=row["consecutive_warnings"],
            detail=row["detail"],
            created_at=row["created_at"],
        )

    # -- Artifact CRUD ------------------------------------------------------

    @_synchronized
    def register_artifact(self, artifact: Artifact) -> str:
        """Register a new artifact.  Returns the artifact_id."""
        # A brand-new record has no prior validation history, so its implicit
        # "current" state is UNVALIDATED — registering directly with
        # validation_status=APPROVED would skip the VALIDATED step.
        validate_validation_status_transition(
            ValidationStatus.UNVALIDATED, artifact.validation_status
        )

        now = _now_iso()
        artifact_id = artifact.id or _new_artifact_id()
        created_at = artifact.created_at or now

        try:
            with self._write_transaction():
                self._conn.execute(
                    """
                    INSERT INTO artifacts (
                        id, type, name, source_paper, source_url, formula_latex,
                        theme, columns_required, decay_horizon, signal_definition,
                        entry_rules, exit_rules, position_sizing, universe,
                        signal_engine_path, run_dir, hypothesis_id, status,
                        created_at, updated_at, disabled_at, disabled_reason,
                        developer, owner, validator, approver, model_version,
                        artifact_version, model_tier, intended_use, limitations,
                        validation_status, validation_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        artifact.type.value,
                        artifact.name,
                        artifact.source_paper,
                        artifact.source_url,
                        artifact.formula_latex,
                        _json_dumps(list(artifact.theme)),
                        _json_dumps(list(artifact.columns_required)),
                        artifact.decay_horizon,
                        artifact.signal_definition,
                        artifact.entry_rules,
                        artifact.exit_rules,
                        artifact.position_sizing,
                        artifact.universe,
                        artifact.signal_engine_path,
                        artifact.run_dir,
                        artifact.hypothesis_id,
                        artifact.status.value,
                        created_at,
                        now,
                        artifact.disabled_at,
                        artifact.disabled_reason,
                        artifact.developer,
                        artifact.owner,
                        artifact.validator,
                        artifact.approver,
                        artifact.model_version,
                        artifact.artifact_version,
                        artifact.model_tier.value if artifact.model_tier else None,
                        artifact.intended_use,
                        artifact.limitations,
                        artifact.validation_status.value,
                        artifact.validation_date,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "artifacts.name" in str(exc):
                raise ValueError(
                    f"artifact '{artifact.name}' already exists in "
                    f"universe '{artifact.universe}'"
                ) from exc
            raise
        return artifact_id

    @_synchronized
    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Get a single artifact by ID.  Returns ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return self._row_to_artifact(row) if row else None

    @_synchronized
    def list_artifacts(
        self,
        *,
        type: ArtifactType | None = None,
        status: ArtifactStatus | None = None,
        universe: str | None = None,
        limit: int = 100,
    ) -> Sequence[Artifact]:
        """List artifacts with optional filters, newest first."""
        clauses: list[str] = []
        params: list[object] = []

        if type is not None:
            clauses.append("type = ?")
            params.append(type.value)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if universe is not None:
            clauses.append("universe = ?")
            params.append(universe)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        rows = self._conn.execute(
            f"SELECT * FROM artifacts {where} ORDER BY created_at DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    @_synchronized
    def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        *,
        reason: str | None = None,
    ) -> Artifact | None:
        """Transition an artifact to a new status.

        Sets ``disabled_at`` when transitioning to ``DISABLED``.
        Clears it when transitioning away.
        Returns the updated artifact, or ``None`` if not found.
        """
        existing = self.get_artifact(artifact_id)
        if existing is None:
            return None

        now = _now_iso()
        disabled_at: str | None = None
        disabled_reason: str | None = None

        if status is ArtifactStatus.DISABLED:
            disabled_at = now
            disabled_reason = reason if reason is not None else existing.disabled_reason
        elif existing.status is ArtifactStatus.DISABLED:
            # Clear disabled fields when moving out of DISABLED.
            disabled_at = None
            disabled_reason = None
        else:
            # Preserve existing disabled fields.
            disabled_at = existing.disabled_at
            disabled_reason = existing.disabled_reason

        with self._write_transaction():
            self._conn.execute(
                """
                UPDATE artifacts
                SET status = ?, updated_at = ?, disabled_at = ?, disabled_reason = ?
                WHERE id = ?
                """,
                (status.value, now, disabled_at, disabled_reason, artifact_id),
            )
        return self.get_artifact(artifact_id)

    @_synchronized
    def update_artifact(self, artifact: Artifact) -> Artifact | None:
        """Replace an artifact record.  Returns updated artifact or ``None``."""
        existing = self.get_artifact(artifact.id)
        if existing is None:
            return None

        # Structural enforcement of the validation state machine: an
        # unvalidated model can never be updated straight into APPROVED.
        validate_validation_status_transition(
            existing.validation_status, artifact.validation_status
        )

        now = _now_iso()
        with self._write_transaction():
            self._conn.execute(
                """
                UPDATE artifacts
                SET type = ?, name = ?, source_paper = ?, source_url = ?,
                    formula_latex = ?, theme = ?, columns_required = ?,
                    decay_horizon = ?, signal_definition = ?,
                    entry_rules = ?, exit_rules = ?, position_sizing = ?,
                    universe = ?, signal_engine_path = ?, run_dir = ?,
                    hypothesis_id = ?, status = ?, updated_at = ?,
                    disabled_at = ?, disabled_reason = ?,
                    developer = ?, owner = ?, validator = ?, approver = ?,
                    model_version = ?, artifact_version = ?, model_tier = ?,
                    intended_use = ?, limitations = ?, validation_status = ?,
                    validation_date = ?
                WHERE id = ?
                """,
                (
                    artifact.type.value,
                    artifact.name,
                    artifact.source_paper,
                    artifact.source_url,
                    artifact.formula_latex,
                    _json_dumps(list(artifact.theme)),
                    _json_dumps(list(artifact.columns_required)),
                    artifact.decay_horizon,
                    artifact.signal_definition,
                    artifact.entry_rules,
                    artifact.exit_rules,
                    artifact.position_sizing,
                    artifact.universe,
                    artifact.signal_engine_path,
                    artifact.run_dir,
                    artifact.hypothesis_id,
                    artifact.status.value,
                    now,
                    artifact.disabled_at,
                    artifact.disabled_reason,
                    artifact.developer,
                    artifact.owner,
                    artifact.validator,
                    artifact.approver,
                    artifact.model_version,
                    artifact.artifact_version,
                    artifact.model_tier.value if artifact.model_tier else None,
                    artifact.intended_use,
                    artifact.limitations,
                    artifact.validation_status.value,
                    artifact.validation_date,
                    artifact.id,
                ),
            )
        return self.get_artifact(artifact.id)

    # -- Bench history ------------------------------------------------------

    @_synchronized
    def record_bench(self, result: BenchResult) -> int:
        """Record a bench result.  Returns the result ID."""
        now = _now_iso()
        created_at = result.created_at or now
        category_value = result.category.value if result.category else None

        with self._write_transaction():
            cursor = self._conn.execute(
                """
                INSERT INTO bench_history (
                    artifact_id, bench_type, ic_mean, ic_std, ir,
                    ic_positive_ratio, t_stat, sharpe, annual_return,
                    max_drawdown, calmar, category,
                    train_start, train_end, test_start, test_end,
                    run_dir, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.artifact_id,
                    result.bench_type,
                    result.ic_mean,
                    result.ic_std,
                    result.ir,
                    result.ic_positive_ratio,
                    result.t_stat,
                    result.sharpe,
                    result.annual_return,
                    result.max_drawdown,
                    result.calmar,
                    category_value,
                    result.train_start,
                    result.train_end,
                    result.test_start,
                    result.test_end,
                    result.run_dir,
                    created_at,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    @_synchronized
    def get_bench_history(
        self, artifact_id: str, *, limit: int = 50
    ) -> Sequence[BenchResult]:
        """Get bench history for an artifact, newest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM bench_history
            WHERE artifact_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (artifact_id, limit),
        ).fetchall()
        return [self._row_to_bench_result(row) for row in rows]

    # -- Decay snapshots ----------------------------------------------------

    @_synchronized
    def record_decay_snapshot(self, snapshot: DecaySnapshot) -> int:
        """Record a decay monitoring snapshot.  Returns the snapshot ID."""
        now = _now_iso()
        created_at = snapshot.created_at or now
        signal_value = snapshot.decay_signal.value if snapshot.decay_signal else None

        with self._write_transaction():
            cursor = self._conn.execute(
                """
                INSERT INTO decay_snapshots (
                    artifact_id, rolling_ic_mean, rolling_ir,
                    baseline_ic_mean, ic_ratio, decay_signal,
                    consecutive_warnings, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.artifact_id,
                    snapshot.rolling_ic_mean,
                    snapshot.rolling_ir,
                    snapshot.baseline_ic_mean,
                    snapshot.ic_ratio,
                    signal_value,
                    snapshot.consecutive_warnings,
                    snapshot.detail,
                    created_at,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    @_synchronized
    def get_decay_history(
        self, artifact_id: str, *, limit: int = 20
    ) -> Sequence[DecaySnapshot]:
        """Get decay snapshots for an artifact, newest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM decay_snapshots
            WHERE artifact_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (artifact_id, limit),
        ).fetchall()
        return [self._row_to_decay_snapshot(row) for row in rows]
