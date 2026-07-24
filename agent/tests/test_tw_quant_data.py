"""Importer, snapshot, verifier, and loader integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import duckdb

from src.tw_quant.data.importers import import_dataset, stable_row_hash
from src.tw_quant.data.loader import SnapshotLoadError, TaiwanSnapshotLoader
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
