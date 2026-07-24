"""Migration and importer contract tests for Phase 01."""

from __future__ import annotations

import pytest
import duckdb

from src.tw_quant.db import migrations
from src.tw_quant.db.migrations import migrate


def test_migration_is_idempotent_and_records_checksum(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "twq.duckdb"
    first = migrate(db_path)
    second = migrate(db_path)
    assert first["applied"] == [1]
    assert second["applied"] == []
    with duckdb.connect(str(db_path), read_only=True) as conn:
        version, checksum = conn.execute(
            "SELECT version, checksum FROM schema_migrations"
        ).fetchone()
    assert version == 1
    assert checksum == migrations.migration_checksum(migrations._MIGRATIONS[0][1])


def test_migration_rejects_checksum_drift(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "twq.duckdb"
    migrate(db_path)
    original = migrations._MIGRATIONS
    monkeypatch.setattr(migrations, "_MIGRATIONS", ((1, original[0][1] + "\n-- drift"),))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate(db_path)
