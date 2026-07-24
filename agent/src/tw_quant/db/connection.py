"""Safe DuckDB connection factory."""

from __future__ import annotations

from pathlib import Path

from src.tw_quant.config import ensure_data_path


def connect_database(path: str | Path, *, read_only: bool = False):
    """Open the Phase 01 DuckDB database after validating its path."""
    import duckdb

    db_path = ensure_data_path(Path(path))
    if not read_only:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)
