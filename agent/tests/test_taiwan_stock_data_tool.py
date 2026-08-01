from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.agent.loop import TOOL_RESULT_LIMIT
from src.tools.taiwan_stock_data_tool import (
    MAX_QUERY_STOCKS,
    MAX_RESULT_ROWS,
    RESPONSE_CHAR_BUDGET,
    TaiwanStockDataTool,
)

SCHEMA_SQL = """
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

NEWEST_DATE = "2026-07-24"


def _create_test_database(
    tmp_path: Path,
) -> Path:
    db_path = tmp_path / "tw_stock_test.db"

    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SQL)

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


def _create_bulk_database(
    tmp_path: Path,
    *,
    stocks: int,
    rows: int,
) -> Path:
    """Build a snapshot wide enough to overflow the response budget."""
    db_path = tmp_path / "tw_stock_bulk.db"
    newest = date.fromisoformat(NEWEST_DATE)

    masters = []
    universe = []
    prices = []
    features = []

    for offset in range(stocks):
        stock_id = f"{2330 + offset:04d}"

        masters.append(
            (
                stock_id,
                "台積電測試",
                "twse",
                "半導體業",
                1,
            )
        )
        universe.append(
            (
                stock_id,
                "台積電測試",
                "twse",
                "半導體業",
                1,
                "active",
                rows,
                NEWEST_DATE,
                NEWEST_DATE,
                0,
                101.25,
                "2026-07-25T00:00:00+00:00",
            )
        )

        for step in range(rows):
            bar_date = (
                newest - timedelta(days=step)
            ).isoformat()

            prices.append(
                (
                    bar_date,
                    stock_id,
                    100.5,
                    103.25,
                    99.75,
                    101.25,
                    1234567.0,
                    123456789.0,
                    12345.0,
                    1.25,
                )
            )
            features.append(
                (
                    bar_date,
                    stock_id,
                    101.25,
                    99.123456,
                    96.654321,
                    91.987654,
                    98.111111,
                    95.222222,
                    3.333333,
                    2.444444,
                    0.555555,
                    62.666666,
                )
            )

    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SQL)
        connection.executemany(
            "INSERT INTO stock_master VALUES (?, ?, ?, ?, ?)",
            masters,
        )
        connection.executemany(
            """
            INSERT INTO analysis_universe
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            universe,
        )
        connection.executemany(
            """
            INSERT INTO daily_price
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            prices,
        )
        connection.executemany(
            """
            INSERT INTO stock_feature
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            features,
        )

    db_path.chmod(0o444)
    return db_path


def _create_stale_feature_database(
    tmp_path: Path,
) -> Path:
    """Build a snapshot whose newest indicators lag the newest price bar."""
    db_path = tmp_path / "tw_stock_stale.db"

    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SQL)

        connection.execute(
            "INSERT INTO stock_master VALUES (?, ?, ?, ?, ?)",
            (
                "2330",
                "台積電",
                "twse",
                "半導體業",
                1,
            ),
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
                    NEWEST_DATE,
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
            ],
        )
        # Features stop one trading day before the price series.
        connection.execute(
            """
            INSERT INTO stock_feature
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
        )
        connection.execute(
            """
            INSERT INTO analysis_universe
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2330",
                "台積電",
                "twse",
                "半導體業",
                1,
                "active",
                2,
                NEWEST_DATE,
                "2026-07-23",
                0,
                101.0,
                "2026-07-25T00:00:00+00:00",
            ),
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
    assert record["price_date"] == NEWEST_DATE
    assert record["feature_date"] == NEWEST_DATE
    assert record["stale_features"] is False
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


def test_small_history_response_reports_no_truncation(
    tmp_path: Path,
) -> None:
    db_path = _create_test_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    data = json.loads(
        tool.execute(
            action="history",
            stock_ids=["2330"],
        )
    )["data"]

    assert data["total_rows"] == 2
    assert data["returned_rows"] == 2
    assert data["truncated"] is False
    assert "hint" not in data


def test_default_history_response_stays_parseable_after_agent_truncation(
    tmp_path: Path,
) -> None:
    """The default request must survive the agent loop's hard result cut."""
    db_path = _create_bulk_database(
        tmp_path,
        stocks=1,
        rows=MAX_RESULT_ROWS,
    )
    tool = TaiwanStockDataTool(db_path)

    raw = tool.execute(
        action="history",
        stock_ids=["2330"],
    )

    assert len(raw) <= RESPONSE_CHAR_BUDGET
    assert len(raw) < TOOL_RESULT_LIMIT

    # The agent sees exactly raw[:TOOL_RESULT_LIMIT]; both must parse.
    payload = json.loads(raw)
    assert json.loads(raw[:TOOL_RESULT_LIMIT]) == payload

    data = payload["data"]

    assert data["truncated"] is True
    assert data["total_rows"] == 60
    assert 0 < data["returned_rows"] < data["total_rows"]
    assert len(data["records"]) == data["returned_rows"]
    assert data["hint"]

    # Oldest rows go first, so the newest bar must still be there.
    assert NEWEST_DATE in {
        record["date"] for record in data["records"]
    }


def test_max_boundary_history_response_stays_parseable_after_agent_truncation(
    tmp_path: Path,
) -> None:
    """200 rows x 50 stocks is the widest request the schema allows."""
    db_path = _create_bulk_database(
        tmp_path,
        stocks=MAX_QUERY_STOCKS,
        rows=MAX_RESULT_ROWS,
    )
    tool = TaiwanStockDataTool(db_path)

    raw = tool.execute(
        action="history",
        stock_ids=[
            f"{2330 + offset:04d}"
            for offset in range(MAX_QUERY_STOCKS)
        ],
        limit=MAX_RESULT_ROWS,
    )

    assert len(raw) <= RESPONSE_CHAR_BUDGET
    assert len(raw) < TOOL_RESULT_LIMIT

    payload = json.loads(raw)
    assert json.loads(raw[:TOOL_RESULT_LIMIT]) == payload

    data = payload["data"]

    assert data["truncated"] is True
    assert (
        data["total_rows"]
        == MAX_QUERY_STOCKS * MAX_RESULT_ROWS
    )
    assert 0 < data["returned_rows"] < data["total_rows"]
    assert len(data["records"]) == data["returned_rows"]
    assert data["hint"]

    assert NEWEST_DATE in {
        record["date"] for record in data["records"]
    }


def test_universe_response_stays_within_budget(
    tmp_path: Path,
) -> None:
    db_path = _create_bulk_database(
        tmp_path,
        stocks=MAX_QUERY_STOCKS,
        rows=2,
    )
    tool = TaiwanStockDataTool(db_path)

    raw = tool.execute(
        action="universe",
        limit=MAX_RESULT_ROWS,
    )

    assert len(raw) <= RESPONSE_CHAR_BUDGET

    data = json.loads(raw)["data"]

    assert data["truncated"] is True
    assert data["total_rows"] == MAX_QUERY_STOCKS
    assert NEWEST_DATE in {
        record["price_date"]
        for record in data["records"]
    }


def test_latest_separates_price_and_feature_dates(
    tmp_path: Path,
) -> None:
    """Indicators from an older date must not be dated as today's bar."""
    db_path = _create_stale_feature_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    record = json.loads(
        tool.execute(
            action="latest",
            stock_ids=["2330"],
        )
    )["data"]["records"][0]

    assert record["price_date"] == NEWEST_DATE
    assert record["feature_date"] == "2026-07-23"
    assert record["stale_features"] is True

    # The returned indicators are the 2026-07-23 values.
    assert record["close"] == 101.0
    assert record["rsi14"] == 60.0
    assert record["ma60"] == 90.0


def test_universe_separates_price_and_feature_dates(
    tmp_path: Path,
) -> None:
    db_path = _create_stale_feature_database(tmp_path)
    tool = TaiwanStockDataTool(db_path)

    record = json.loads(
        tool.execute(
            action="universe",
            limit=10,
        )
    )["data"]["records"][0]

    assert record["price_date"] == NEWEST_DATE
    assert record["feature_date"] == "2026-07-23"
    assert record["stale_features"] is True
    assert record["rsi14"] == 60.0


def test_wrong_schema_database_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A readable SQLite file with the wrong tables must not register."""
    db_path = tmp_path / "unrelated.db"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)"
        )

    monkeypatch.setenv(
        "VIBE_TW_STOCK_DB",
        str(db_path),
    )

    assert not TaiwanStockDataTool.check_available()

    with pytest.raises(
        ValueError,
        match="missing table 'stock_master'",
    ):
        TaiwanStockDataTool(db_path).execute(
            action="status"
        )


def test_missing_column_is_named_in_the_error(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "partial.db"

    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            SCHEMA_SQL.replace(
                "    rsi14 REAL,\n",
                "",
            )
        )

    with pytest.raises(
        ValueError,
        match="'stock_feature' is missing columns 'rsi14'",
    ):
        TaiwanStockDataTool(db_path).execute(
            action="status"
        )


def test_non_sqlite_file_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "not_a_database.db"
    db_path.write_text("plain text, not a snapshot")

    monkeypatch.setenv(
        "VIBE_TW_STOCK_DB",
        str(db_path),
    )

    assert not TaiwanStockDataTool.check_available()

    with pytest.raises(
        ValueError,
        match="not a readable SQLite database",
    ):
        TaiwanStockDataTool(db_path).execute(
            action="status"
        )
