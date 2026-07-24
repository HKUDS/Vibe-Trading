"""Versioned, idempotent DuckDB migrations for Phase 01."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from src.tw_quant.data.schemas import TABLE_DDL
from src.tw_quant.db.connection import connect_database


_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        "\n".join(
            [
                "CREATE TABLE IF NOT EXISTS schema_migrations (",
                "  version INTEGER PRIMARY KEY,",
                "  applied_at TIMESTAMPTZ NOT NULL,",
                "  checksum VARCHAR NOT NULL",
                ");",
                *[TABLE_DDL[name].strip() + ";" for name in TABLE_DDL],
            ]
        ),
    ),
)


def migration_checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def migrate(path: str | Path):
    """Apply all migrations and reject checksum drift.

    Returns a small machine-readable summary. The database transaction is
    rolled back if any DDL or checksum check fails.
    """
    conn = connect_database(path)
    applied: list[int] = []
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL, checksum VARCHAR NOT NULL)"
        )
        conn.execute("BEGIN TRANSACTION")
        for version, sql in _MIGRATIONS:
            checksum = migration_checksum(sql)
            row = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE version = ?", [version]
            ).fetchone()
            if row is not None:
                if str(row[0]) != checksum:
                    raise RuntimeError(
                        f"migration checksum mismatch for version {version}: "
                        f"database={row[0]}, code={checksum}"
                    )
                continue
            for statement in (part.strip() for part in sql.split(";")):
                if statement:
                    conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at, checksum) VALUES (?, ?, ?)",
                [version, datetime.now(timezone.utc), checksum],
            )
            applied.append(version)
        conn.execute("COMMIT")
        return {"applied": applied, "versions": [version for version, _ in _MIGRATIONS]}
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
