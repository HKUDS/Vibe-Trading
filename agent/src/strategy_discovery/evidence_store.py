"""SQLite persistence for per-regime strategy evidence.

``EvidenceStore`` is a deliberately small key/value-style store keyed on
``(strategy_id, regime)``. It exists so the discovery facade can answer
evidence-gated questions from durable, reproducible harness output — never
from invented numbers. The table starts empty and is only populated by
``evidence_harness.rebuild_evidence`` (or explicit ``upsert_rows`` calls).

Connection discipline: one short-lived ``sqlite3`` connection per operation
(context-managed), matching the read-mostly, multi-process-friendly access
pattern of the rest of the agent. Non-finite floats (NaN/Inf) are rejected
before they ever reach the database.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

from src.strategy_discovery.models import (
    EVIDENCE_STAGES,
    QUALITY_INSUFFICIENT,
    REGIMES,
    EvidenceRow,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_FILENAME = "strategy_discovery.db"

_FLOAT_FIELDS = (
    "position_size",
    "return_in_regime",
    "benchmark_in_regime",
    "excess_in_regime",
    "sharpe_in_regime",
    "max_drawdown_in_regime",
    "breakeven_fee_bps",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_regime_evidence (
    strategy_id            TEXT NOT NULL,
    regime                 TEXT NOT NULL,
    trades_in_regime       INTEGER NOT NULL,
    position_size          REAL,
    return_in_regime       REAL,
    benchmark_in_regime    REAL,
    excess_in_regime       REAL,
    sharpe_in_regime       REAL,
    max_drawdown_in_regime REAL,
    date_ranges            TEXT NOT NULL,
    breakeven_fee_bps      REAL,
    cost_sensitive         INTEGER NOT NULL DEFAULT 0,
    evidence_quality       TEXT NOT NULL,
    warnings               TEXT NOT NULL,
    last_verified          TEXT NOT NULL DEFAULT '',
    evidence_stage         TEXT NOT NULL DEFAULT 'backtest',
    provenance             TEXT NOT NULL DEFAULT '',
    regime_definition      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (strategy_id, regime)
)
"""

#: Columns that must exist; a cache DB missing any of them predates the
#: provenance/stage contract and is dropped + recreated (the cache is
#: disposable — rows only ever come from a harness rebuild).
_REQUIRED_COLUMNS = (
    "strategy_id",
    "regime",
    "trades_in_regime",
    "position_size",
    "return_in_regime",
    "benchmark_in_regime",
    "excess_in_regime",
    "sharpe_in_regime",
    "max_drawdown_in_regime",
    "date_ranges",
    "breakeven_fee_bps",
    "cost_sensitive",
    "evidence_quality",
    "warnings",
    "last_verified",
    "evidence_stage",
    "provenance",
    "regime_definition",
)

_INSERT_SQL = """
INSERT OR REPLACE INTO strategy_regime_evidence (
    strategy_id, regime, trades_in_regime, position_size,
    return_in_regime, benchmark_in_regime, excess_in_regime,
    sharpe_in_regime, max_drawdown_in_regime, date_ranges,
    breakeven_fee_bps, cost_sensitive, evidence_quality, warnings,
    last_verified, evidence_stage, provenance, regime_definition
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _env_override_db_path() -> Path | None:
    """Resolve the ``vibe_trading_strategy_discovery_db_path`` EnvConfig field.

    The field is defined on the env schema (``src.config.env_schema``); a
    sibling change adds it, so access happens lazily and defensively: any
    import/resolution problem simply yields ``None`` and the caller falls back
    to the default location. Never raises, never reads ``os.environ``
    directly (the repository's AST CI gate forbids that here).
    """
    try:
        from src.config.accessor import get_env_config

        paths = get_env_config().paths
        raw = getattr(paths, "vibe_trading_strategy_discovery_db_path", "") or ""
    except Exception:  # noqa: BLE001 — degrade to default path, never crash
        logger.debug("strategy_discovery env override unavailable", exc_info=True)
        return None
    raw = raw.strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _default_db_path() -> Path:
    """Default database location: ``<runtime-root>/strategy_discovery.db``.

    Uses the shared runtime root helper (which honours ``VIBE_TRADING_HOME``)
    when available, falling back to ``~/.vibe-trading`` otherwise.
    """
    try:
        from src.config.paths import get_runtime_root

        return get_runtime_root() / _DEFAULT_DB_FILENAME
    except Exception:  # noqa: BLE001 — config layer optional for this package
        return Path.home() / ".vibe-trading" / _DEFAULT_DB_FILENAME


def _validate_row_for_write(row: EvidenceRow) -> None:
    """Reject rows containing NaN/Inf or otherwise unwritable values."""
    if not isinstance(row.trades_in_regime, int) or not math.isfinite(
        row.trades_in_regime
    ):
        raise ValueError(
            f"evidence row {row.strategy_id}/{row.regime}: trades_in_regime must be a finite int"
        )
    for field_name in _FLOAT_FIELDS:
        value = getattr(row, field_name)
        if value is not None and not math.isfinite(value):
            raise ValueError(
                f"evidence row {row.strategy_id}/{row.regime}: "
                f"{field_name} is non-finite ({value!r}); refusing to persist"
            )


class EvidenceStore:
    """Persistent store of (strategy, regime) evidence rows.

    Starts empty — no seed data ships with the package. Rows only ever come
    from the evidence harness computing over real backtest run artifacts.
    """

    TABLE = "strategy_regime_evidence"

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Open (and initialize) the evidence database.

        Args:
            db_path: Explicit database file. When ``None``, an env override
                (``vibe_trading_strategy_discovery_db_path`` on ``EnvConfig``)
                is consulted lazily; absent that, the default runtime-root
                location is used. Parent directories are created.
        """
        if db_path is not None:
            resolved = Path(db_path).expanduser()
        else:
            override = _env_override_db_path()
            resolved = override if override is not None else _default_db_path()
        self.db_path = resolved
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            self._migrate_stale_schema(conn)

    @staticmethod
    def _migrate_stale_schema(conn) -> None:
        """Drop and recreate a cache DB that predates the current schema.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so a
        DB written before the provenance/stage columns existed would keep
        serving rows without them. The cache is disposable by contract, so
        the honest response is to drop it (a rebuild regenerates every row).
        """
        present = {
            record["name"]
            for record in conn.execute(
                f"PRAGMA table_info({EvidenceStore.TABLE})"
            ).fetchall()
        }
        missing = [c for c in _REQUIRED_COLUMNS if c not in present]
        if not missing:
            return
        logger.warning(
            "strategy_discovery cache %s predates columns %s; dropping the "
            "disposable cache so a harness rebuild can repopulate it",
            EvidenceStore.TABLE,
            ", ".join(missing),
        )
        conn.execute(f"DROP TABLE {EvidenceStore.TABLE}")
        conn.execute(_SCHEMA)

    # -- connection helpers --------------------------------------------------

    @contextmanager
    def _connect(self):
        """Yield one short-lived connection; commit on success, rollback on error."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    # -- writes --------------------------------------------------------------

    def upsert_rows(self, rows: Sequence[EvidenceRow]) -> int:
        """Insert or replace evidence rows. Returns the number of rows written.

        Raises:
            ValueError: When any row carries a NaN/Inf numeric field.
        """
        count = 0
        with self._connect() as conn:
            for row in rows:
                _validate_row_for_write(row)
                conn.execute(
                    _INSERT_SQL,
                    (
                        row.strategy_id,
                        row.regime,
                        row.trades_in_regime,
                        row.position_size,
                        row.return_in_regime,
                        row.benchmark_in_regime,
                        row.excess_in_regime,
                        row.sharpe_in_regime,
                        row.max_drawdown_in_regime,
                        json.dumps(list(row.date_ranges), ensure_ascii=False),
                        row.breakeven_fee_bps,
                        1 if row.cost_sensitive else 0,
                        row.evidence_quality,
                        json.dumps(list(row.warnings), ensure_ascii=False),
                        row.last_verified,
                        row.evidence_stage,
                        row.provenance,
                        row.regime_definition,
                    ),
                )
                count += 1
        return count

    def replace_rows(self, rows: Sequence[EvidenceRow]) -> int:
        """Atomically replace ALL evidence rows with ``rows``.

        DELETE-all + INSERT-all inside ONE ``_connect()`` context — a single
        transaction, so a failure anywhere leaves the previous contents
        intact (rollback) instead of the clear-then-upsert window where a
        crash could leave the store empty (plan D5). Per-row validation is
        identical to :meth:`upsert_rows` and runs before the DELETE, so an
        invalid row set never touches the table. Returns rows written.

        Raises:
            ValueError: When any row carries a NaN/Inf numeric field.
        """
        materialized = list(rows)
        for row in materialized:
            _validate_row_for_write(row)
        count = 0
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.TABLE}")
            for row in materialized:
                conn.execute(
                    _INSERT_SQL,
                    (
                        row.strategy_id,
                        row.regime,
                        row.trades_in_regime,
                        row.position_size,
                        row.return_in_regime,
                        row.benchmark_in_regime,
                        row.excess_in_regime,
                        row.sharpe_in_regime,
                        row.max_drawdown_in_regime,
                        json.dumps(list(row.date_ranges), ensure_ascii=False),
                        row.breakeven_fee_bps,
                        1 if row.cost_sensitive else 0,
                        row.evidence_quality,
                        json.dumps(list(row.warnings), ensure_ascii=False),
                        row.last_verified,
                        row.evidence_stage,
                        row.provenance,
                        row.regime_definition,
                    ),
                )
                count += 1
        return count

    def clear(self) -> None:
        """Delete every evidence row (used by harness rebuilds)."""
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.TABLE}")

    # -- reads ---------------------------------------------------------------

    def get_rows(
        self,
        strategy_id: str | None = None,
        regime: str | None = None,
    ) -> list[EvidenceRow]:
        """Read evidence rows, optionally filtered, ordered by (strategy_id, regime)."""
        clauses: list[str] = []
        params: list[object] = []
        if strategy_id is not None:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if regime is not None:
            clauses.append("regime = ?")
            params.append(regime)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM {self.TABLE} {where} " "ORDER BY strategy_id, regime"
        ).strip()
        rows: list[EvidenceRow] = []
        with self._connect() as conn:
            for record in conn.execute(sql, params).fetchall():
                row = self._row_from_record(record)
                if row is None:
                    continue
                rows.append(row)
        return rows

    def strategy_ids(self) -> list[str]:
        """Distinct strategy ids that have evidence, sorted."""
        sql = f"SELECT DISTINCT strategy_id FROM {self.TABLE} ORDER BY strategy_id"
        with self._connect() as conn:
            return [record["strategy_id"] for record in conn.execute(sql).fetchall()]

    def row_count(self) -> int:
        """Total number of stored evidence rows."""
        with self._connect() as conn:
            record = conn.execute(f"SELECT COUNT(*) AS n FROM {self.TABLE}").fetchone()
        return int(record["n"])

    # -- conversion ----------------------------------------------------------

    @staticmethod
    def _row_from_record(record: sqlite3.Row) -> EvidenceRow | None:
        """Convert a database record back into an ``EvidenceRow``.

        Returns ``None`` for records whose regime is outside ``REGIMES``.
        Such rows can only reach the store through external tampering (the
        write path validates regimes via ``EvidenceRow``); the honest
        behaviour for a never-invent store is to drop them from reads rather
        than remap onto a documented regime and present fabricated state.
        """
        regime = record["regime"]
        if regime not in REGIMES:
            logger.warning(
                "evidence row %s carries unknown regime %r; skipping it "
                "(possible externally tampered evidence database)",
                record["strategy_id"],
                regime,
            )
            return None
        keys = set(record.keys())
        stage = record["evidence_stage"] if "evidence_stage" in keys else "backtest"
        if stage not in EVIDENCE_STAGES:
            logger.warning(
                "evidence row %s carries unknown evidence_stage %r; "
                "skipping it (possible externally tampered evidence database)",
                record["strategy_id"],
                stage,
            )
            return None
        return EvidenceRow(
            strategy_id=record["strategy_id"],
            regime=regime,
            trades_in_regime=int(record["trades_in_regime"]),
            position_size=record["position_size"],
            return_in_regime=record["return_in_regime"],
            benchmark_in_regime=record["benchmark_in_regime"],
            excess_in_regime=record["excess_in_regime"],
            sharpe_in_regime=record["sharpe_in_regime"],
            max_drawdown_in_regime=record["max_drawdown_in_regime"],
            date_ranges=tuple(json.loads(record["date_ranges"] or "[]")),
            breakeven_fee_bps=record["breakeven_fee_bps"],
            cost_sensitive=bool(record["cost_sensitive"]),
            evidence_quality=record["evidence_quality"] or QUALITY_INSUFFICIENT,
            warnings=tuple(json.loads(record["warnings"] or "[]")),
            last_verified=record["last_verified"] or "",
            evidence_stage=stage,
            provenance=(record["provenance"] if "provenance" in keys else "") or "",
            regime_definition=(
                record["regime_definition"] if "regime_definition" in keys else ""
            )
            or "",
        )
