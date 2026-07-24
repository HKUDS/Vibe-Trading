"""Immutable DuckDB-to-Parquet snapshot builder."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.tw_quant.config import ensure_snapshot_id, ensure_within_root, snapshot_root as default_snapshot_root
from src.tw_quant.data.manifest import sha256_file, write_json
from src.tw_quant.data.schemas import schema_for
from src.tw_quant.data.verifier import verify_snapshot
from src.tw_quant.db.connection import connect_database
from src.tw_quant.db.migrations import migrate


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _git_provenance(repo_root: str | Path | None) -> tuple[str, bool]:
    cwd = Path(repo_root or Path.cwd())
    try:
        commit = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(cwd), "diff", "--quiet"],
            check=False,
        ).returncode != 0
        return commit or "unknown", dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def _source_metadata(conn: Any, dataset: str) -> dict[str, Any]:
    rows = conn.execute(
        f"SELECT DISTINCT source, source_dataset, revision_id FROM {dataset} "
        "ORDER BY source, source_dataset, revision_id"
    ).fetchall()
    return {
        "sources": sorted({str(row[0]) for row in rows}),
        "datasets": sorted({str(row[1]) for row in rows}),
        "revisions": sorted({str(row[2]) for row in rows}),
    }


def create_snapshot(
    db_path: str | Path,
    *,
    snapshot_root: str | Path | None = None,
    snapshot_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Create, verify, and atomically seal an immutable snapshot."""
    migrate(db_path)
    root = Path(snapshot_root or default_snapshot_root()).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    staging = ensure_within_root(root / f".staging-{uuid.uuid4().hex}", root)
    created_at = datetime.now(timezone.utc)
    code_commit, dirty = _git_provenance(repo_root)
    conn = connect_database(db_path, read_only=True)
    try:
        staging.mkdir(parents=True, exist_ok=False)
        data_dir = staging / "data"
        data_dir.mkdir()
        tables: dict[str, dict[str, Any]] = {}
        for dataset in ("security_master", "daily_price", "monthly_revenue"):
            schema = schema_for(dataset)
            output = data_dir / f"{dataset}.parquet"
            predicates: list[str] = []
            if start:
                start_value = pd.Timestamp(start).date().isoformat()
                predicates.append(f"{schema.event_column} >= DATE {_sql_literal(start_value)}")
            if end:
                end_value = pd.Timestamp(end).date().isoformat()
                predicates.append(f"{schema.event_column} <= DATE {_sql_literal(end_value)}")
            where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
            conn.execute(
                f"COPY (SELECT * FROM {dataset}{where}) TO {_sql_literal(output)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            count, min_time, max_time = conn.execute(
                f"SELECT COUNT(*), MIN({schema.event_column}), MAX({schema.event_column}) FROM {dataset}{where}"
            ).fetchone()
            source_meta = _source_metadata(conn, dataset)
            tables[dataset] = {
                "path": f"data/{dataset}.parquet",
                "rows": int(count),
                "sha256": sha256_file(output),
                "min_event_time": str(min_time) if min_time is not None else None,
                "max_event_time": str(max_time) if max_time is not None else None,
                "sources": source_meta["sources"],
                "source_datasets": source_meta["datasets"],
                "revision_ids": source_meta["revisions"],
            }

        quality = {
            "status": "ok",
            "tables": {name: {"rows": entry["rows"], "errors": []} for name, entry in tables.items()},
        }
        write_json(staging / "quality.json", quality)
        content_hash = hashlib.sha256(
            "".join(tables[name]["sha256"] for name in sorted(tables)).encode("ascii")
        ).hexdigest()[:12]
        final_id = ensure_snapshot_id(snapshot_id or f"twq-{created_at.strftime('%Y%m%d')}-{content_hash}")
        target = ensure_within_root(root / final_id, root)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"snapshot already exists and will not be overwritten: {target}")
        manifest = {
            "snapshot_id": final_id,
            "created_at": created_at.isoformat(),
            "schema_version": 1,
            "code_commit": code_commit,
            "dirty": dirty,
            "timezone": "Asia/Taipei",
            "tables": tables,
            "sources": {name: {"primary": entry["sources"], "revisions": entry["revision_ids"]} for name, entry in tables.items()},
            "rule_profile": "TW_EQUITY_PHASE01_PLACEHOLDER",
            "quality_report": "quality.json",
            "license_policy": "metadata-only-or-redistributable",
            "builder_version": "tw_quant.phase01",
        }
        write_json(staging / "manifest.json", manifest)
        report = verify_snapshot(staging, _allow_staging=True)
        if not report.ok:
            raise RuntimeError("new snapshot failed self-verification: " + "; ".join(report.errors))
        staging.replace(target)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    finally:
        conn.close()
