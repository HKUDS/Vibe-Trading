"""Tests for the config-driven local data loader."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest
import yaml

import backtest.loaders.local_loader as local_loader


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sources: list[dict]) -> None:
    """Point the local loader at a temp config file."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config_path)


def test_local_loader_fetches_csv_with_local_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Symbols prefixed with local: should resolve to the configured symbol."""
    csv_path = tmp_path / "aapl.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-01-01,10,11,9,10.5,1000",
                "2026-01-02,12,13,11,12.5,1500",
            ]
        ),
        encoding="utf-8",
    )
    _configure(
        monkeypatch,
        tmp_path,
        [
            {
                "symbol": "AAPL.US",
                "type": "csv",
                "path": str(csv_path),
                "columns": {
                    "date": "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
            }
        ],
    )

    frames = local_loader.DataLoader().fetch(
        ["local:AAPL.US"], "2026-01-01", "2026-01-02"
    )

    assert set(frames) == {"AAPL.US"}
    assert list(frames["AAPL.US"]["close"]) == [10.5, 12.5]


def _intraday_csv(tmp_path: Path) -> Path:
    """Write 8 hourly bars on 2026-01-01 (00:00..07:00)."""
    rows = ["Date,Open,High,Low,Close,Volume"]
    bars = [
        ("2026-01-01 00:00:00", 10, 12, 9, 11, 100),
        ("2026-01-01 01:00:00", 11, 13, 10, 12, 110),
        ("2026-01-01 02:00:00", 12, 14, 11, 13, 120),
        ("2026-01-01 03:00:00", 13, 15, 12, 14, 130),
        ("2026-01-01 04:00:00", 14, 16, 13, 15, 140),
        ("2026-01-01 05:00:00", 15, 17, 14, 16, 150),
        ("2026-01-01 06:00:00", 16, 18, 15, 17, 160),
        ("2026-01-01 07:00:00", 17, 19, 16, 18, 170),
    ]
    rows += [f"{d},{o},{h},{lo},{c},{v}" for d, o, h, lo, c, v in bars]
    path = tmp_path / "intraday.csv"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def _intraday_source(csv_path: Path) -> dict:
    return {
        "symbol": "AAA.US",
        "type": "csv",
        "path": str(csv_path),
        "columns": {
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
    }


def test_local_loader_resamples_intraday_to_coarser_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requesting 4H against hourly bars must aggregate, not silently return hourly."""
    csv_path = _intraday_csv(tmp_path)
    _configure(monkeypatch, tmp_path, [_intraday_source(csv_path)])

    frames = local_loader.DataLoader().fetch(
        ["AAA.US"], "2026-01-01", "2026-01-01", interval="4H"
    )

    df = frames["AAA.US"]
    assert len(df) == 2  # 00:00-03:59 and 04:00-07:59 buckets
    first, second = df.iloc[0], df.iloc[1]
    # First 4H bar aggregates hours 0-3.
    assert first["open"] == 10
    assert first["high"] == 15
    assert first["low"] == 9
    assert first["close"] == 14
    assert first["volume"] == 100 + 110 + 120 + 130
    # Second 4H bar aggregates hours 4-7.
    assert second["open"] == 14
    assert second["close"] == 18
    assert second["volume"] == 140 + 150 + 160 + 170


def test_local_loader_warns_and_keeps_source_when_upsampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Requesting a finer interval than the file holds cannot fabricate bars."""
    csv_path = tmp_path / "daily.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-01-01,10,11,9,10.5,1000",
                "2026-01-02,12,13,11,12.5,1500",
                "2026-01-03,13,14,12,13.5,1200",
            ]
        ),
        encoding="utf-8",
    )
    _configure(
        monkeypatch,
        tmp_path,
        [
            {
                "symbol": "AAA.US",
                "type": "csv",
                "path": str(csv_path),
                "columns": {
                    "date": "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
            }
        ],
    )

    with caplog.at_level(logging.WARNING, logger="backtest.loaders.local_loader"):
        frames = local_loader.DataLoader().fetch(
            ["AAA.US"], "2026-01-01", "2026-01-03", interval="4H"
        )

    df = frames["AAA.US"]
    assert len(df) == 3  # daily source bars returned unchanged
    assert list(df["close"]) == [10.5, 12.5, 13.5]
    assert any("upsample" in rec.message.lower() for rec in caplog.records)


def test_local_loader_fetches_duckdb_without_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DuckDB sources use db_path/query and should not require a path field."""
    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "market.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE prices AS
            SELECT '2026-01-01' AS date, 10.0 AS open, 11.0 AS high,
                   9.0 AS low, 10.5 AS close, 1000.0 AS volume
            UNION ALL
            SELECT '2026-01-02', 12.0, 13.0, 11.0, 12.5, 1500.0
            """
        )
    _configure(
        monkeypatch,
        tmp_path,
        [
            {
                "symbol": "MYINDEX",
                "type": "duckdb",
                "db_path": str(db_path),
                "query": "SELECT * FROM prices",
            }
        ],
    )

    frames = local_loader.DataLoader().fetch(["MYINDEX"], "2026-01-01", "2026-01-02")

    assert set(frames) == {"MYINDEX"}
    assert list(frames["MYINDEX"]["close"]) == [10.5, 12.5]


def test_local_loader_handles_timezone_aware_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tz-aware timestamps must not crash the date filter into an empty result.

    Regression: the date-range filter compared a tz-naive Timestamp against a
    tz-aware index, which raised TypeError that was swallowed into empty data.
    """
    csv_path = tmp_path / "tz_aapl.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-01-01T00:00:00+00:00,10,11,9,10.5,1000",
                "2026-01-02T00:00:00+00:00,12,13,11,12.5,1500",
            ]
        ),
        encoding="utf-8",
    )
    _configure(
        monkeypatch,
        tmp_path,
        [
            {
                "symbol": "AAPL.US",
                "type": "csv",
                "path": str(csv_path),
                "columns": {
                    "date": "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
            }
        ],
    )

    frames = local_loader.DataLoader().fetch(
        ["local:AAPL.US"], "2026-01-01", "2026-01-02"
    )

    assert set(frames) == {"AAPL.US"}
    assert list(frames["AAPL.US"]["close"]) == [10.5, 12.5]


def test_local_loader_normalizes_dst_offsets_to_naive_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "dst.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-01-15T09:30:00-05:00,10,11,9,10.5,1000",
                "2026-07-15T09:30:00-04:00,12,13,11,12.5,1500",
            ]
        ),
        encoding="utf-8",
    )
    _configure(
        monkeypatch,
        tmp_path,
        [
            {
                "symbol": "DST.US",
                "type": "csv",
                "path": str(csv_path),
                "columns": {
                    "date": "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
            }
        ],
    )

    frame = local_loader.DataLoader().fetch(
        ["local:DST.US"], "2026-01-01", "2026-07-31"
    )["DST.US"]

    assert frame.index.tz is None
    assert list(frame.index) == [
        pd.Timestamp("2026-01-15 14:30:00"),
        pd.Timestamp("2026-07-15 13:30:00"),
    ]
