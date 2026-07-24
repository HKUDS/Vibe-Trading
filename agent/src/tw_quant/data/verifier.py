"""Independent immutable snapshot verifier."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.tw_quant.config import PathSafetyError, ensure_snapshot_id, ensure_within_root
from src.tw_quant.data.manifest import read_manifest, sha256_file
from src.tw_quant.data.schemas import schema_for


@dataclass(frozen=True)
class VerificationReport:
    snapshot_id: str | None
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    tables: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "tables": list(self.tables),
        }


def _sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _snapshot_path(snapshot: str | Path, snapshot_root: str | Path | None) -> Path:
    value = Path(snapshot).expanduser()
    if value.exists() or value.is_absolute() or len(value.parts) > 1:
        return value.resolve(strict=False)
    if snapshot_root is None:
        raise ValueError("snapshot_root is required when snapshot is an ID")
    snapshot_id = ensure_snapshot_id(str(snapshot))
    root = Path(snapshot_root).expanduser().resolve(strict=False)
    return ensure_within_root(root / snapshot_id, root)


def _validate_physical_types(dataset: str, columns: list[tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    actual = {name: dtype.upper() for name, dtype in columns}
    expected = schema_for(dataset)
    missing = set(expected.columns) - set(actual)
    extra = set(actual) - set(expected.columns)
    if missing:
        errors.append(f"{dataset}: missing Parquet columns: {sorted(missing)}")
    if extra:
        errors.append(f"{dataset}: unexpected Parquet columns: {sorted(extra)}")
    for name in expected.columns:
        if name not in actual:
            continue
        dtype = actual[name]
        if name in {"is_suspended", "is_disposition", "is_full_delivery"} and "BOOL" not in dtype:
            errors.append(f"{dataset}.{name}: expected BOOLEAN, got {dtype}")
        if name in {"symbol", "local_code", "market", "security_type", "name", "industry_code", "source", "source_dataset", "revision_id", "quality_flags", "row_hash"}:
            if not any(token in dtype for token in ("VARCHAR", "TEXT", "STRING")):
                errors.append(f"{dataset}.{name}: expected string, got {dtype}")
    return errors


def verify_snapshot(
    snapshot: str | Path,
    snapshot_root: str | Path | None = None,
    *,
    _allow_staging: bool = False,
) -> VerificationReport:
    """Verify manifest, paths, hashes, row counts, columns, and types."""
    errors: list[str] = []
    warnings: list[str] = []
    tables_report: list[dict[str, Any]] = []
    try:
        snapshot_path = _snapshot_path(snapshot, snapshot_root)
        manifest_path = snapshot_path / "manifest.json"
        if not manifest_path.is_file():
            return VerificationReport(None, False, ("manifest.json is missing",))
        manifest = read_manifest(manifest_path)
        snapshot_id = str(manifest.get("snapshot_id", "")).strip() or None
        if snapshot_id is None:
            errors.append("manifest snapshot_id is missing")
        else:
            try:
                ensure_snapshot_id(snapshot_id)
            except PathSafetyError as exc:
                errors.append(str(exc))
            if not _allow_staging and snapshot_path.name != snapshot_id:
                errors.append("snapshot ID does not match snapshot directory")
        for field in ("created_at", "schema_version", "code_commit", "timezone", "tables", "quality_report"):
            if field not in manifest:
                errors.append(f"manifest field is missing: {field}")
        quality_relative = Path(str(manifest.get("quality_report", "quality.json")))
        if quality_relative.is_absolute() or ".." in quality_relative.parts:
            errors.append("quality report path escapes snapshot")
        else:
            try:
                quality_path = ensure_within_root(
                    snapshot_path / quality_relative, snapshot_path, allow_missing=False
                )
                if not quality_path.is_file():
                    errors.append("quality report is missing")
            except (PathSafetyError, FileNotFoundError) as exc:
                errors.append(f"quality report: {exc}")

        table_entries = manifest.get("tables")
        if not isinstance(table_entries, dict) or not table_entries:
            errors.append("manifest tables must be a non-empty object")
            table_entries = {}
        missing_datasets = {"security_master", "daily_price", "monthly_revenue"} - set(table_entries)
        if missing_datasets:
            errors.append(f"manifest tables are incomplete: {sorted(missing_datasets)}")

        import duckdb

        conn = duckdb.connect(database=":memory:")
        try:
            for dataset, entry in table_entries.items():
                try:
                    schema_for(dataset)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                if not isinstance(entry, dict):
                    errors.append(f"manifest table entry is not an object: {dataset}")
                    continue
                relative = entry.get("path")
                if not isinstance(relative, str) or not relative.strip():
                    errors.append(f"manifest path is missing: {dataset}")
                    continue
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    errors.append(f"manifest path escapes snapshot: {relative}")
                    continue
                try:
                    data_path = ensure_within_root(snapshot_path / relative_path, snapshot_path, allow_missing=False)
                except (PathSafetyError, FileNotFoundError) as exc:
                    errors.append(f"{dataset}: {exc}")
                    continue
                if data_path.is_symlink():
                    errors.append(f"{dataset}: symlinked data files are not allowed")
                    continue
                actual_hash = sha256_file(data_path)
                if actual_hash != str(entry.get("sha256", "")):
                    errors.append(f"{dataset}: SHA-256 mismatch")
                try:
                    described = conn.execute(f"DESCRIBE SELECT * FROM read_parquet({_sql_literal(data_path)})").fetchall()
                    type_errors = _validate_physical_types(dataset, [(row[0], row[1]) for row in described])
                    errors.extend(type_errors)
                    count, min_time, max_time = conn.execute(
                        f"SELECT COUNT(*), MIN({schema_for(dataset).event_column}), MAX({schema_for(dataset).event_column}) "
                        f"FROM read_parquet({_sql_literal(data_path)})"
                    ).fetchone()
                except Exception as exc:
                    errors.append(f"{dataset}: Parquet read failed: {exc}")
                    continue
                if int(count) != int(entry.get("rows", -1)):
                    errors.append(f"{dataset}: row count mismatch")
                expected_min = entry.get("min_event_time")
                expected_max = entry.get("max_event_time")
                if (expected_min is None) != (min_time is None) or (expected_max is None) != (max_time is None):
                    errors.append(f"{dataset}: event time range mismatch")
                tables_report.append({
                    "dataset": dataset,
                    "path": relative,
                    "rows": int(count),
                    "sha256": actual_hash,
                    "min_event_time": str(min_time) if min_time is not None else None,
                    "max_event_time": str(max_time) if max_time is not None else None,
                })
        finally:
            conn.close()

        data_dir = snapshot_path / "data"
        listed = {str(entry.get("path")) for entry in table_entries.values() if isinstance(entry, dict)}
        if data_dir.is_dir():
            for candidate in data_dir.rglob("*"):
                if candidate.is_file() and candidate.relative_to(snapshot_path).as_posix() not in listed:
                    warnings.append(f"unlisted snapshot file ignored: {candidate.relative_to(snapshot_path)}")
    except (OSError, ValueError, json.JSONDecodeError, PathSafetyError) as exc:
        errors.append(str(exc))
        snapshot_id = locals().get("snapshot_id")
    return VerificationReport(snapshot_id, not errors, tuple(dict.fromkeys(errors)), tuple(warnings), tuple(tables_report))
