from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.tools.taiwan_stock_data_tool import (
    TaiwanStockDataTool,
)


def _create_test_database(
    tmp_path: Path,
) -> Path:
    db_path = tmp_path / "tw_stock_test.db"

    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE stock_master (
                stock_id TEXT PRIMARY KEY,
                stock_name TEXT NOT NULL,
                market TEXT,
                industry TEXT,
                enable INTEGER NOT NULL
            );

            CREATE TABLE daily_price (
                date TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                open REAL,
                max REAL,
                min REAL,
                close REAL,
                Trading_Volume REAL,
                Trading_money REAL,
                Trading_turnover REAL,
                spread REAL,
                UNIQUE(stock_id, date)
            );

            CREATE TABLE stock_feature (
                date TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                close REAL,
                ma5 REAL,
                ma20 REAL,
                ma60 REAL,
                ema12 REAL,
                ema26 REAL,
                macd REAL,
                macd_signal REAL,
                macd_hist REAL,
                rsi14 REAL,
                UNIQUE(stock_id, date)
            );

            CREATE TABLE analysis_universe (
                stock_id TEXT PRIMARY KEY,
                stock_name TEXT NOT NULL,
                market TEXT,
                industry TEXT,
                active INTEGER NOT NULL,
                reason TEXT NOT NULL,
                price_rows INTEGER NOT NULL,
                last_price_date TEXT,
                last_feature_date TEXT,
                trading_day_lag INTEGER,
                latest_close REAL,
                updated_at TEXT NOT NULL
            );
            """
        )

        connection.executemany(
            """
            INSERT INTO stock_master (
                stock_id,
                stock_name,
                market,
                industry,
                enable
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "2330",
                    "台積電",
                    "twse",
                    "半導體業",
                    1,
                ),
                (
                    "0054",
                    "元大台商50",
                    "twse",
                    "ETF",
                    1,
                ),
            ],
        )

        connection.executemany(
            """
            INSERT INTO daily_price
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2026-07-23",
                    "2330",
                    99.0,
                    102.0,
                    98.0,
                    100.0,
                    1000.0,
                    100000.0,
                    100.0,
                    1.0,
                ),
                (
                    "2026-07-24",
                    "2330",
                    100.0,
                    103.0,
                    99.0,
                    101.0,
                    1200.0,
                    121200.0,
                    120.0,
                    1.0,
                ),
                (
                    "2026-07-08",
                    "0054",
                    23.4,
                    23.5,
                    23.4,
                    23.5,
                    11000.0,
                    258400.0,
                    2.0,
                    0.1,
                ),
            ],
        )

        connection.executemany(
            """
            INSERT INTO stock_feature
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2026-07-23",
                    "2330",
                    100.0,
                    98.0,
                    95.0,
                    90.0,
                    97.0,
                    94.0,
                    3.0,
                    2.5,
                    0.5,
                    60.0,
                ),
                (
                    "2026-07-24",
                    "2330",
                    101.0,
                    99.0,
                    96.0,
                    91.0,
                    98.0,
                    95.0,
                    3.0,
                    2.6,
                    0.4,
                    62.0,
                ),
                (
                    "2026-07-08",
                    "0054",
                    23.5,
                    None,
                    None,
                    None,
                    23.5,
                    23.5,
                    0.0,
                    0.0,
                    0.0,
                    None,
                ),
            ],
        )

        connection.executemany(
            """
            INSERT INTO analysis_universe
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2330",
                    "台積電",
                    "twse",
                    "半導體業",
                    1,
                    "active",
                    618,
                    "2026-07-24",
                    "2026-07-24",
                    0,
                    101.0,
                    "2026-07-25T00:00:00+00:00",
                ),
                (
                    "0054",
                    "元大台商50",
                    "twse",
                    "ETF",
                    0,
                    "stale_price",
                    5,
                    "2026-07-08",
                    "2026-07-08",
                    11,
                    23.5,
                    "2026-07-25T00:00:00+00:00",
                ),
            ],
        )

    db_path.chmod(0o444)
    return db_path


def test_check_available_uses_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _create_test_database(tmp_path)

    monkeypatch.setenv(
        "VIBE_TW_STOCK_DB",
        str(db_path),
    )

    assert TaiwanStockDataTool.check_available()


def test_status_returns_snapshot_summary(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    payload = json.loads(
        tool.execute(action="status")
    )

    assert payload["status"] == "success"
    assert (
        payload["data"]["latest_market_date"]
        == "2026-07-24"
    )
    assert (
        payload["data"]["active_analysis_stocks"]
        == 1
    )
    assert payload["data"]["integrity"] == "ok"


def test_latest_returns_price_and_features(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    payload = json.loads(
        tool.execute(
            action="latest",
            stock_ids=["2330"],
        )
    )

    record = payload["data"]["records"][0]

    assert record["stock_id"] == "2330"
    assert record["date"] == "2026-07-24"
    assert record["close"] == 101.0
    assert record["ma60"] == 91.0
    assert record["rsi14"] == 62.0
    assert record["active"] == 1


def test_history_limit_is_applied_per_stock(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    payload = json.loads(
        tool.execute(
            action="history",
            stock_ids=["2330"],
            limit=1,
        )
    )

    records = payload["data"]["records"]

    assert len(records) == 1
    assert records[0]["date"] == "2026-07-24"


def test_universe_defaults_to_active_only(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    payload = json.loads(
        tool.execute(
            action="universe",
            limit=20,
        )
    )

    records = payload["data"]["records"]

    assert [row["stock_id"] for row in records] == [
        "2330"
    ]


def test_lookup_reports_unknown_stock_ids(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    payload = json.loads(
        tool.execute(
            action="lookup",
            stock_ids=["2330", "9999"],
        )
    )

    assert payload["data"]["not_found"] == ["9999"]


def test_invalid_stock_id_is_rejected(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    with pytest.raises(
        ValueError,
        match="Invalid Taiwan stock ID",
    ):
        tool.execute(
            action="latest",
            stock_ids=["TSMC"],
        )
