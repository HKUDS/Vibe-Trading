"""Importer, snapshot, verifier, and loader integration tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import duckdb

from src.tw_quant.data.importers import (
    import_dataset,
    read_input,
    stable_row_hash,
    validate_dataset,
)
from src.tw_quant.data.loader import (
    SnapshotLoadError,
    SnapshotRequiredError,
    TaiwanSnapshotLoader,
)
from src.tw_quant.data.snapshots import create_snapshot
from src.tw_quant.data.verifier import verify_snapshot
from src.tw_quant.db.migrations import migrate


def _security_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "symbol": "2330.TW", "local_code": "2330", "market": "TWSE",
            "security_type": "common_stock", "name": "Synthetic Semiconductor",
            "listed_at": "2020-01-01T00:00:00+08:00", "delisted_at": None,
            "industry_code": "24", "effective_at": "2020-01-01T00:00:00+00:00",
            "available_at": "2020-01-01T00:00:00+00:00",
        },
        {
            "symbol": "6488.TWO", "local_code": "6488", "market": "TPEX",
            "security_type": "common_stock", "name": "Synthetic TPEX",
            "listed_at": "2020-01-01T00:00:00+08:00", "delisted_at": None,
            "industry_code": "24", "effective_at": "2020-01-01T00:00:00+00:00",
            "available_at": "2020-01-01T00:00:00+00:00",
        },
    ])


def _price_frame() -> pd.DataFrame:
    rows = []
    for symbol, base in (("2330.TW", 100.0), ("6488.TWO", 50.0)):
        for offset, day in enumerate(("2026-01-02", "2026-01-05", "2026-01-06")):
            close = base + offset
            rows.append({
                "symbol": symbol, "trade_date": day, "open": close - 0.5,
                "high": close + 1.0, "low": close - 1.0, "close": close,
                "volume": 1000.0, "turnover": 100000.0, "trades": 10.0,
                "reference_price": close - 0.5, "price_limit_up": close * 1.1,
                "price_limit_down": close * 0.9, "is_suspended": False,
                "is_disposition": False, "is_full_delivery": False,
                "adjustment_factor": 1.0, "effective_at": f"{day}T00:00:00+00:00",
                "available_at": f"{day}T09:00:00+00:00",
                "ingested_at": "2026-01-07T00:00:00+00:00",
            })
    return pd.DataFrame(rows)


def _revenue_frame() -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": "2330.TW", "revenue_month": "2025-12-01", "revenue": 1000.0,
        "revenue_yoy": 0.1, "revenue_mom": 0.02,
        "announced_at": "2026-01-10T06:00:00+00:00",
        "effective_at": "2025-12-01T00:00:00+00:00",
        "available_at": "2026-01-10T06:00:00+00:00",
        "ingested_at": "2026-01-11T00:00:00+00:00",
    }])


def _write_csvs(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for dataset, frame in (
        ("security_master", _security_frame()),
        ("daily_price", _price_frame()),
        ("monthly_revenue", _revenue_frame()),
    ):
        path = tmp_path / f"{dataset}.csv"
        frame.to_csv(path, index=False)
        paths[dataset] = path
    return paths


def test_row_hash_is_stable_and_excludes_ingest_time() -> None:
    row = {"symbol": "2330.TW", "close": 100.0, "ingested_at": "2026-01-01T00:00:00Z"}
    changed_ingest = {**row, "ingested_at": "2027-01-01T00:00:00Z"}
    assert stable_row_hash(row) == stable_row_hash(changed_ingest)


def test_validate_only_does_not_write_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    path = _write_csvs(tmp_path)["daily_price"]
    result = import_dataset(
        path, "daily_price", source="fixture", source_dataset="synthetic",
        mode="validate_only",
    )
    assert result.report.ok
    assert result.inserted_rows == 0
    assert not (tmp_path / "tw_quant.duckdb").exists()


def test_validate_only_accepts_duckdb_written_parquet_input(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    parquet_path = tmp_path / "daily_price.parquet"
    frame = _price_frame()
    with duckdb.connect(database=":memory:") as conn:
        conn.register("price_frame", frame)
        conn.execute(f"COPY price_frame TO '{parquet_path}' (FORMAT PARQUET)")
    result = import_dataset(
        parquet_path, "daily_price", source="fixture", source_dataset="synthetic",
        mode="validate_only",
    )
    assert result.report.ok
    assert result.report.rows == len(frame)


def test_csv_path_with_spaces_is_supported(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    data_dir = tmp_path / "fixture data with spaces"
    data_dir.mkdir()
    path = data_dir / "daily price.csv"
    _price_frame().to_csv(path, index=False)
    result = import_dataset(
        path, "daily_price", source="fixture", source_dataset="synthetic",
        mode="validate_only",
    )
    assert result.report.ok


def test_append_rolls_back_on_duplicate_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "tw_quant.duckdb"
    frame = _price_frame()
    path = tmp_path / "daily_price.csv"
    frame.to_csv(path, index=False)
    first = import_dataset(
        path, "daily_price", source="fixture", source_dataset="synthetic",
        mode="append", db_path=db_path, revision_id="r1",
    )
    assert first.inserted_rows == len(frame)
    with pytest.raises(Exception, match="Constraint|constraint|duplicate|Duplicate"):
        import_dataset(
            path, "daily_price", source="fixture", source_dataset="synthetic",
            mode="append", db_path=db_path, revision_id="r1",
        )
    with duckdb.connect(str(db_path), read_only=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM daily_price").fetchone()[0]
    assert count == len(frame)


def test_fixture_to_snapshot_to_loader_and_offline_tamper_detection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "tw_quant.duckdb"
    snapshot_dir = tmp_path / "snapshots"
    paths = _write_csvs(tmp_path)
    migrate(db_path)
    for dataset, path in paths.items():
        result = import_dataset(
            path, dataset, source="fixture", source_dataset="synthetic",
            mode="append", db_path=db_path, revision_id="r1",
        )
        assert result.report.ok
        assert result.inserted_rows > 0

    manifest = create_snapshot(
        db_path, snapshot_root=snapshot_dir, snapshot_id="twq-fixture-r1"
    )
    report = verify_snapshot("twq-fixture-r1", snapshot_dir)
    assert report.ok
    loader = TaiwanSnapshotLoader(snapshot_id="twq-fixture-r1", snapshot_root=snapshot_dir)
    data = loader.fetch(["2330.TW"], "2026-01-01", "2026-01-31")
    assert list(data) == ["2330.TW"]
    assert list(data["2330.TW"]["close"]) == [100.0, 101.0, 102.0]
    assert loader.provenance["snapshot_id"] == manifest["snapshot_id"]
    with pytest.raises(SnapshotLoadError, match="absent"):
        loader.fetch(["9999.TW"], "2026-01-01", "2026-01-31")
    with pytest.raises(SnapshotLoadError, match="no rows"):
        loader.fetch(["2330.TW"], "2030-01-01", "2030-01-31")

    data_path = snapshot_dir / "twq-fixture-r1" / "data" / "daily_price.parquet"
    with data_path.open("ab") as stream:
        stream.write(b"tampered")
    tampered = verify_snapshot("twq-fixture-r1", snapshot_dir)
    assert not tampered.ok
    assert any("SHA-256" in error for error in tampered.errors)
    with pytest.raises(SnapshotLoadError, match="verification failed"):
        loader.fetch(["2330.TW"], "2026-01-01", "2026-01-31")


def test_verify_snapshot_reports_missing_manifest(tmp_path: Path) -> None:
    report = verify_snapshot(tmp_path / "missing-snapshot")

    assert not report.ok
    assert report.snapshot_id is None
    assert "manifest.json is missing" in report.errors


def test_verify_snapshot_rejects_malformed_or_incomplete_manifest(tmp_path: Path) -> None:
    snapshot = tmp_path / "staging"
    snapshot.mkdir()
    manifest_path = snapshot / "manifest.json"
    manifest_path.write_text("[]", encoding="utf-8")

    malformed = verify_snapshot(snapshot, _allow_staging=True)
    assert not malformed.ok
    assert any("JSON object" in error for error in malformed.errors)

    manifest_path.write_text(
        json.dumps({"snapshot_id": "staging", "quality_report": "quality.json"}),
        encoding="utf-8",
    )
    (snapshot / "quality.json").write_text("{}", encoding="utf-8")
    incomplete = verify_snapshot(snapshot, _allow_staging=True)
    assert not incomplete.ok
    assert any("manifest field is missing" in error for error in incomplete.errors)
    assert any("manifest tables are incomplete" in error for error in incomplete.errors)


def _seed_snapshot(tmp_path: Path, monkeypatch, snapshot_id: str = "twq-verifier") -> tuple[Path, Path]:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "tw_quant.duckdb"
    snapshot_root = tmp_path / "snapshots"
    for dataset, path in _write_csvs(tmp_path).items():
        import_dataset(
            path,
            dataset,
            source="fixture",
            source_dataset="synthetic",
            mode="append",
            db_path=db_path,
            revision_id="r1",
        )
    create_snapshot(db_path, snapshot_root=snapshot_root, snapshot_id=snapshot_id)
    return snapshot_root, snapshot_root / snapshot_id


def test_verify_snapshot_rejects_manifest_row_and_time_metadata_drift(tmp_path, monkeypatch) -> None:
    snapshot_root, snapshot = _seed_snapshot(tmp_path, monkeypatch)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tables"]["daily_price"]["rows"] += 1
    manifest["tables"]["daily_price"]["min_event_time"] = "1900-01-01"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = verify_snapshot("twq-verifier", snapshot_root)

    assert not report.ok
    assert any("row count mismatch" in error for error in report.errors)
    assert any("event time range mismatch" in error for error in report.errors)


def test_verify_snapshot_warns_about_unlisted_files_and_directory_mismatch(tmp_path, monkeypatch) -> None:
    snapshot_root, snapshot = _seed_snapshot(tmp_path, monkeypatch, "twq-warning")
    (snapshot / "data" / "unlisted-note.txt").write_text("ignored", encoding="utf-8")

    report = verify_snapshot("twq-warning", snapshot_root)
    assert report.ok
    assert any("unlisted snapshot file ignored" in warning for warning in report.warnings)

    copied = snapshot_root / "different-directory"
    shutil.copytree(snapshot, copied)
    mismatch = verify_snapshot(copied)
    assert not mismatch.ok
    assert any("does not match snapshot directory" in error for error in mismatch.errors)


def test_verify_snapshot_checks_physical_column_types(tmp_path, monkeypatch) -> None:
    snapshot_root, snapshot = _seed_snapshot(tmp_path, monkeypatch, "twq-types")
    data_path = snapshot / "data" / "daily_price.parquet"
    replacement = tmp_path / "daily_price-wrong-type.parquet"
    with duckdb.connect(database=":memory:") as conn:
        conn.execute(
            "COPY (SELECT * EXCLUDE(is_suspended), "
            "CAST(is_suspended AS VARCHAR) AS is_suspended "
            f"FROM read_parquet('{data_path}')) TO '{replacement}' (FORMAT PARQUET)"
        )
    replacement.replace(data_path)

    report = verify_snapshot("twq-types", snapshot_root)

    assert not report.ok
    assert any("expected BOOLEAN" in error for error in report.errors)


def test_verify_snapshot_rejects_symlinked_data_file(tmp_path, monkeypatch) -> None:
    snapshot_root, snapshot = _seed_snapshot(tmp_path, monkeypatch, "twq-symlink")
    data_path = snapshot / "data" / "daily_price.parquet"
    original_is_symlink = Path.is_symlink

    def pretend_symlink(path: Path) -> bool:
        return path == data_path or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", pretend_symlink)
    report = verify_snapshot("twq-symlink", snapshot_root)

    assert not report.ok
    assert any("symlinked data files are not allowed" in error for error in report.errors)


def test_snapshot_loader_rejects_explicit_empty_field_list(tmp_path, monkeypatch) -> None:
    snapshot_root, _ = _seed_snapshot(tmp_path, monkeypatch, "twq-empty-fields")
    loader = TaiwanSnapshotLoader(snapshot_id="twq-empty-fields", snapshot_root=snapshot_root)

    with pytest.raises(SnapshotLoadError, match="at least one daily_price field"):
        loader.load(["2330.TW"], "2026-01-01", "2026-01-31", fields=[])


def test_duplicate_snapshot_refuses_overwrite(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "tw_quant.duckdb"
    paths = _write_csvs(tmp_path)
    for dataset, path in paths.items():
        import_dataset(
            path, dataset, source="fixture", source_dataset="synthetic",
            mode="append", db_path=db_path, revision_id="r1",
        )
    first = create_snapshot(db_path, snapshot_root=tmp_path / "snapshots", snapshot_id="twq-fixed")
    second = create_snapshot(db_path, snapshot_root=tmp_path / "snapshots", snapshot_id="twq-fixed-copy")
    assert first["tables"]["daily_price"]["sha256"] == second["tables"]["daily_price"]["sha256"]
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        create_snapshot(db_path, snapshot_root=tmp_path / "snapshots", snapshot_id="twq-fixed")


def test_manifest_path_traversal_is_rejected(tmp_path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "quality.json").write_text("{}", encoding="utf-8")
    (snapshot / "manifest.json").write_text(json.dumps({
        "snapshot_id": "twq-path",
        "created_at": "2026-01-01T00:00:00Z",
        "schema_version": 1,
        "code_commit": "unknown",
        "timezone": "Asia/Taipei",
        "tables": {"daily_price": {"path": "../outside.parquet", "rows": 0, "sha256": ""}},
        "quality_report": "quality.json",
    }), encoding="utf-8")
    report = verify_snapshot(snapshot, _allow_staging=True)
    assert not report.ok
    assert any("escapes" in error for error in report.errors)


def test_validate_dataset_fills_provider_metadata_and_canonicalizes_values() -> None:
    frame = _price_frame().iloc[:1].copy()
    frame["symbol"] = "2330.tw"
    frame["is_suspended"] = "1"
    frame["is_disposition"] = "false"
    frame["is_full_delivery"] = 0
    frame["quality_flags"] = '{"z": 2, "a": 1}'
    frame = frame.drop(columns=["ingested_at"])

    canonical, report = validate_dataset(
        frame,
        "daily_price",
        source="fixture",
        source_dataset="synthetic",
        revision_id="r-canonical",
        ingested_at="2026-01-07T00:00:00Z",
    )

    assert report.ok
    assert canonical is not None
    assert canonical.loc[0, "symbol"] == "2330.TW"
    assert canonical.loc[0, "source"] == "fixture"
    assert canonical.loc[0, "source_dataset"] == "synthetic"
    assert canonical.loc[0, "revision_id"] == "r-canonical"
    assert canonical.loc[0, "quality_flags"] == '{"a":1,"z":2}'
    assert bool(canonical.loc[0, "is_suspended"]) is True
    assert bool(canonical.loc[0, "is_disposition"]) is False
    assert bool(canonical.loc[0, "is_full_delivery"]) is False


def test_validate_dataset_rejects_missing_and_unknown_columns() -> None:
    frame = _price_frame().drop(columns=["close"]).assign(unexpected="no")

    canonical, report = validate_dataset(
        frame,
        "daily_price",
        source="fixture",
        source_dataset="synthetic",
    )

    assert canonical is None
    assert not report.ok
    assert any("missing required columns" in error for error in report.errors)
    assert any("unknown columns" in error for error in report.errors)


def test_validate_dataset_rejects_bad_values_and_business_invariants() -> None:
    frame = _price_frame().iloc[:1].copy()
    frame["is_suspended"] = frame["is_suspended"].astype(object)
    frame.loc[0, "available_at"] = None
    frame.loc[0, "close"] = 0
    frame.loc[0, "volume"] = -1
    frame.loc[0, "adjustment_factor"] = 0
    frame.loc[0, "is_suspended"] = "maybe"
    frame.loc[0, "quality_flags"] = "not-json"

    canonical, report = validate_dataset(
        frame,
        "daily_price",
        source="fixture",
        source_dataset="synthetic",
    )

    assert canonical is not None
    assert not report.ok
    expected_errors = (
        "available_at must not be empty",
        "violate OHLC invariants",
        "volume must not be negative",
        "adjustment_factor must be positive",
        "invalid boolean in is_suspended",
        "quality_flags is not valid JSON",
    )
    for expected in expected_errors:
        assert any(expected in error for error in report.errors), report.errors


def test_validate_dataset_rejects_security_identity_mismatch() -> None:
    frame = _security_frame().iloc[:1].copy()
    frame.loc[0, "local_code"] = "9999"
    frame.loc[0, "market"] = "TPEX"

    canonical, report = validate_dataset(
        frame,
        "security_master",
        source="fixture",
        source_dataset="synthetic",
    )

    assert canonical is not None
    assert not report.ok
    assert any("local_code does not match" in error for error in report.errors)
    assert any("market does not match" in error for error in report.errors)


def test_validate_dataset_rejects_negative_revenue_and_duplicate_business_key() -> None:
    revenue = _revenue_frame()
    revenue.loc[0, "revenue"] = -1
    _, revenue_report = validate_dataset(
        revenue,
        "monthly_revenue",
        source="fixture",
        source_dataset="synthetic",
        revision_id="r1",
    )
    assert any("revenue must not be negative" in error for error in revenue_report.errors)

    duplicate = pd.concat([_price_frame().iloc[:1], _price_frame().iloc[:1]], ignore_index=True)
    _, duplicate_report = validate_dataset(
        duplicate,
        "daily_price",
        source="fixture",
        source_dataset="synthetic",
        revision_id="r1",
    )
    assert any("duplicate business key" in error for error in duplicate_report.errors)


def test_read_input_rejects_unsupported_file_type(tmp_path: Path) -> None:
    path = tmp_path / "daily_price.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported import file type"):
        read_input(path)


def test_import_dataset_rejects_invalid_options(tmp_path: Path) -> None:
    path = tmp_path / "daily_price.csv"
    _price_frame().to_csv(path, index=False)

    with pytest.raises(ValueError, match="unsupported Taiwan schema_version"):
        import_dataset(path, "daily_price", source="fixture", source_dataset="synthetic", schema_version=2)
    with pytest.raises(ValueError, match="mode must be"):
        import_dataset(path, "daily_price", source="fixture", source_dataset="synthetic", mode="replace")
    with pytest.raises(ValueError, match="db_path is required"):
        import_dataset(
            path,
            "daily_price",
            source="fixture",
            source_dataset="synthetic",
            mode="append",
        )


def test_create_snapshot_honors_event_date_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "tw_quant.duckdb"
    snapshot_root = tmp_path / "snapshots"
    paths = _write_csvs(tmp_path)
    for dataset, path in paths.items():
        import_dataset(
            path,
            dataset,
            source="fixture",
            source_dataset="synthetic",
            mode="append",
            db_path=db_path,
            revision_id="r1",
        )

    manifest = create_snapshot(
        db_path,
        snapshot_root=snapshot_root,
        snapshot_id="twq-date-filter",
        start="2026-01-05",
        end="2026-01-05",
    )

    assert manifest["tables"]["daily_price"]["rows"] == 2
    assert manifest["tables"]["daily_price"]["min_event_time"] == "2026-01-05"
    assert manifest["tables"]["daily_price"]["max_event_time"] == "2026-01-05"
    assert manifest["tables"]["security_master"]["rows"] == 0
    assert manifest["tables"]["monthly_revenue"]["rows"] == 0
    assert verify_snapshot("twq-date-filter", snapshot_root).ok


def test_snapshot_loader_fails_closed_for_invalid_requests(tmp_path: Path) -> None:
    loader = TaiwanSnapshotLoader(snapshot_root=tmp_path)

    assert not loader.is_available()
    with pytest.raises(SnapshotRequiredError, match="snapshot_id is required"):
        loader.load(["2330.TW"], "2026-01-01", "2026-01-02")
    with pytest.raises(SnapshotLoadError, match="daily bars only"):
        loader.fetch(["2330.TW"], "2026-01-01", "2026-01-02", interval="1H")


def test_snapshot_loader_reads_environment_defaults(tmp_path: Path, monkeypatch) -> None:
    snapshot_root = tmp_path / "snapshots"
    monkeypatch.setenv("TW_QUANT_SNAPSHOT_ID", "from-env")
    monkeypatch.setenv("TW_QUANT_SNAPSHOT_ROOT", str(snapshot_root))

    loader = TaiwanSnapshotLoader()

    assert loader.snapshot_id == "from-env"
    assert loader.snapshot_root == snapshot_root


def test_snapshot_loader_supports_selected_fields_and_bare_codes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db_path = tmp_path / "tw_quant.duckdb"
    snapshot_root = tmp_path / "snapshots"
    paths = _write_csvs(tmp_path)
    for dataset, path in paths.items():
        import_dataset(
            path,
            dataset,
            source="fixture",
            source_dataset="synthetic",
            mode="append",
            db_path=db_path,
            revision_id="r1",
        )
    create_snapshot(db_path, snapshot_root=snapshot_root, snapshot_id="twq-fields")
    loader = TaiwanSnapshotLoader(snapshot_id="twq-fields", snapshot_root=snapshot_root)

    result = loader.load(
        ["2330"],
        "2026-01-02",
        "2026-01-05",
        fields=["close", "volume"],
        market_hint="TWSE",
    )

    assert list(result) == ["2330.TW"]
    assert list(result["2330.TW"].columns) == ["close", "volume"]
    assert list(result["2330.TW"]["close"]) == [100.0, 101.0]
    assert loader.provenance["table"] == "daily_price"

    with pytest.raises(SnapshotLoadError, match="unsupported adjustment_mode"):
        loader.load(["2330.TW"], "2026-01-01", "2026-01-02", adjustment_mode="adjusted")
    with pytest.raises(SnapshotLoadError, match="start date"):
        loader.load(["2330.TW"], "2026-01-03", "2026-01-02")
    with pytest.raises(SnapshotLoadError, match="invalid Taiwan load date range"):
        loader.load(["2330.TW"], "not-a-date", "2026-01-02")
    with pytest.raises(SnapshotLoadError, match="unavailable"):
        loader.load(["2330.TW"], "2026-01-01", "2026-01-02", fields=["not_a_field"])
    with pytest.raises(SnapshotLoadError, match="unknown Taiwan market suffix"):
        loader.load(["2330.US"], "2026-01-01", "2026-01-02")
