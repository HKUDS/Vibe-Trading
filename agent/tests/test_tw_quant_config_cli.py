"""Configuration and command-line contract tests for Phase 01."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.tw_quant.cli import main
from src.tw_quant.config import (
    PathSafetyError,
    data_root,
    db_path,
    ensure_data_path,
    ensure_snapshot_id,
    ensure_within_root,
    snapshot_root,
)


def _security_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "2330.TW",
                "local_code": "2330",
                "market": "TWSE",
                "security_type": "common_stock",
                "name": "Synthetic Semiconductor",
                "listed_at": "2020-01-01T00:00:00+08:00",
                "delisted_at": None,
                "industry_code": "24",
                "effective_at": "2020-01-01T00:00:00+00:00",
                "available_at": "2020-01-01T00:00:00+00:00",
            }
        ]
    )


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "2330.TW",
                "trade_date": "2026-01-02",
                "open": 99.5,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
                "turnover": 100000.0,
                "trades": 10.0,
                "reference_price": 99.5,
                "price_limit_up": 110.0,
                "price_limit_down": 90.0,
                "is_suspended": False,
                "is_disposition": False,
                "is_full_delivery": False,
                "adjustment_factor": 1.0,
                "effective_at": "2026-01-02T00:00:00+00:00",
                "available_at": "2026-01-02T09:00:00+00:00",
                "ingested_at": "2026-01-03T00:00:00+00:00",
            }
        ]
    )


def _revenue_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "2330.TW",
                "revenue_month": "2025-12-01",
                "revenue": 1000.0,
                "revenue_yoy": 0.1,
                "revenue_mom": 0.02,
                "announced_at": "2026-01-10T06:00:00+00:00",
                "effective_at": "2025-12-01T00:00:00+00:00",
                "available_at": "2026-01-10T06:00:00+00:00",
                "ingested_at": "2026-01-11T00:00:00+00:00",
            }
        ]
    )


def _write_input_files(tmp_path: Path) -> dict[str, Path]:
    frames = {
        "security_master": _security_frame(),
        "daily_price": _price_frame(),
        "monthly_revenue": _revenue_frame(),
    }
    paths: dict[str, Path] = {}
    for dataset, frame in frames.items():
        path = tmp_path / f"{dataset}.csv"
        frame.to_csv(path, index=False)
        paths[dataset] = path
    return paths


def test_config_uses_data_root_for_relative_paths(tmp_path: Path, monkeypatch) -> None:
    configured_root = tmp_path / "state"
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(configured_root))
    monkeypatch.setenv("TW_QUANT_DB_PATH", "db/research.duckdb")
    monkeypatch.setenv("TW_QUANT_SNAPSHOT_ROOT", "sealed-snapshots")

    assert data_root() == configured_root.resolve()
    assert db_path() == (configured_root / "db" / "research.duckdb").resolve()
    assert snapshot_root() == (configured_root / "sealed-snapshots").resolve()


def test_config_rejects_paths_outside_root_and_missing_required_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(PathSafetyError, match="escapes allowed root"):
        ensure_within_root(root / ".." / "outside", root)
    with pytest.raises(FileNotFoundError):
        ensure_within_root(root / "not-created", root, allow_missing=False)


@pytest.mark.parametrize("snapshot_id", ["", ".", "..", "../escape", "bad id", "-bad", "bad\\id"])
def test_snapshot_id_must_be_one_safe_path_segment(snapshot_id: str) -> None:
    with pytest.raises(PathSafetyError, match="invalid snapshot_id"):
        ensure_snapshot_id(snapshot_id)


def test_ensure_data_path_uses_configured_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))

    valid = ensure_data_path(tmp_path / "nested" / "file.parquet")
    assert valid == (tmp_path / "nested" / "file.parquet").resolve()
    with pytest.raises(PathSafetyError):
        ensure_data_path(tmp_path.parent / "outside.parquet")


def test_cli_migrate_and_validate_import(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db = tmp_path / "tw_quant.duckdb"
    csv_path = tmp_path / "daily_price.csv"
    _price_frame().to_csv(csv_path, index=False)

    assert main(["migrate", "--db-path", str(db)]) == 0
    migration_output = json.loads(capsys.readouterr().out)
    assert migration_output["applied"] == [1]

    assert main(
        [
            "import",
            "--dataset",
            "daily_price",
            "--input",
            str(csv_path),
            "--source",
            "fixture",
            "--source-dataset",
            "synthetic",
            "--mode",
            "validate_only",
        ]
    ) == 0
    import_output = json.loads(capsys.readouterr().out)
    assert import_output["ok"] is True
    assert import_output["mode"] == "validate_only"
    assert import_output["inserted_rows"] == 0


def test_cli_import_create_and_verify_snapshot(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TW_QUANT_DATA_ROOT", str(tmp_path))
    db = tmp_path / "tw_quant.duckdb"
    snapshot_root = tmp_path / "snapshots"
    paths = _write_input_files(tmp_path)

    for dataset, path in paths.items():
        assert main(
            [
                "import",
                "--dataset",
                dataset,
                "--input",
                str(path),
                "--source",
                "fixture",
                "--source-dataset",
                "synthetic",
                "--revision-id",
                "cli-r1",
                "--mode",
                "append",
                "--db-path",
                str(db),
            ]
        ) == 0
        assert json.loads(capsys.readouterr().out)["inserted_rows"] == 1

    assert main(
        [
            "snapshot",
            "create",
            "--db-path",
            str(db),
            "--snapshot-root",
            str(snapshot_root),
            "--snapshot-id",
            "cli-r1",
        ]
    ) == 0
    create_output = json.loads(capsys.readouterr().out)
    assert create_output["snapshot_id"] == "cli-r1"

    assert main(["snapshot", "verify", "cli-r1", "--snapshot-root", str(snapshot_root)]) == 0
    verify_output = json.loads(capsys.readouterr().out)
    assert verify_output["ok"] is True
    assert verify_output["snapshot_id"] == "cli-r1"


def test_cli_reports_invalid_input_as_json_error(tmp_path: Path, capsys) -> None:
    path = tmp_path / "not-supported.json"
    path.write_text("{}", encoding="utf-8")

    assert main(
        [
            "import",
            "--dataset",
            "daily_price",
            "--input",
            str(path),
            "--source",
            "fixture",
            "--source-dataset",
            "synthetic",
        ]
    ) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert "unsupported import file type" in output["error"]
