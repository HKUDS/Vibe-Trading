"""SQLite cache for stock-detail data, including period-specific K-lines."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.config.paths import get_runtime_root
from src.chan_training_analysis import ANALYSIS_VERSION, build_chan_analysis


_DEFAULT_DB_NAME = "market_stock_details.db"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_STORE_LOCK = threading.RLock()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


class StockDetailStore:
    """Persist static stock details and per-period refreshed historical bars."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_runtime_root() / _DEFAULT_DB_NAME
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # All route-level store instances share one process lock because the
        # independent info/industry/report requests may update one symbol at
        # the same time.
        self._lock = _STORE_LOCK
        self._initialize()

    @staticmethod
    def today() -> str:
        return datetime.now(_SHANGHAI).date().isoformat()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS stock_detail_static_cache (
                    symbol TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    refreshed_date TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stock_detail_bars_cache (
                    symbol TEXT NOT NULL,
                    period TEXT NOT NULL,
                    bars_json TEXT NOT NULL,
                    chan_analysis_json TEXT,
                    fetched_at TEXT NOT NULL,
                    refreshed_date TEXT NOT NULL,
                    PRIMARY KEY (symbol, period)
                );
                """
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(stock_detail_bars_cache)").fetchall()}
            if "chan_analysis_json" not in columns:
                connection.execute("ALTER TABLE stock_detail_bars_cache ADD COLUMN chan_analysis_json TEXT")
            rows = connection.execute(
                "SELECT symbol, period, bars_json, chan_analysis_json FROM stock_detail_bars_cache WHERE period IN ('1d', '1w', '1mo')"
            ).fetchall()
            for row in rows:
                try:
                    bars = json.loads(row["bars_json"] or "[]")
                    cached_analysis = json.loads(row["chan_analysis_json"] or "") if row["chan_analysis_json"] else None
                    needs_refresh = not isinstance(cached_analysis, dict) or cached_analysis.get("version") != ANALYSIS_VERSION
                    analysis = build_chan_analysis(bars) if isinstance(bars, list) and needs_refresh else None
                except (TypeError, ValueError, json.JSONDecodeError):
                    analysis = None
                if analysis is not None:
                    connection.execute(
                        "UPDATE stock_detail_bars_cache SET chan_analysis_json = ? WHERE symbol = ? AND period = ?",
                        (json.dumps(_json_safe(analysis), ensure_ascii=False, allow_nan=False), row["symbol"], row["period"]),
                    )

    def get_static(self, symbol: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM stock_detail_static_cache WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def get_static_with_meta(self, symbol: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, fetched_at, refreshed_date
                FROM stock_detail_static_cache
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return {
            "payload": payload,
            "fetched_at": row["fetched_at"],
            "refreshed_date": row["refreshed_date"],
        }

    def save_static(self, symbol: str, payload: dict[str, Any]) -> None:
        now = datetime.now(_SHANGHAI).isoformat()
        encoded = json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO stock_detail_static_cache
                    (symbol, payload_json, fetched_at, refreshed_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    refreshed_date = excluded.refreshed_date
                """,
                (symbol, encoded, now, self.today()),
            )

    def update_static(self, symbol: str, updates: dict[str, Any]) -> None:
        """Merge one independently fetched static section into the cache."""
        with self._lock:
            payload = self.get_static(symbol) or {}
            payload.update(updates)
            self.save_static(symbol, payload)

    def get_bars(self, symbol: str, period: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT bars_json, chan_analysis_json, fetched_at, refreshed_date
                FROM stock_detail_bars_cache
                WHERE symbol = ? AND period = ?
                """,
                (symbol, period),
            ).fetchone()
        if row is None:
            return None
        try:
            bars = json.loads(row["bars_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(bars, list):
            return None
        try:
            chan_analysis = json.loads(row["chan_analysis_json"] or "") if row["chan_analysis_json"] else None
        except (TypeError, ValueError, json.JSONDecodeError):
            chan_analysis = None
        return {
            "bars": bars,
            "chan_analysis": chan_analysis if isinstance(chan_analysis, dict) else None,
            "fetched_at": row["fetched_at"],
            "refreshed_date": row["refreshed_date"],
        }

    def save_bars(self, symbol: str, period: str, bars: list[dict[str, Any]]) -> dict[str, Any] | None:
        now = datetime.now(_SHANGHAI).isoformat()
        encoded = json.dumps(_json_safe(bars), ensure_ascii=False, allow_nan=False)
        chan_analysis = build_chan_analysis(bars) if period in {"1d", "1w", "1mo"} else None
        chan_encoded = json.dumps(_json_safe(chan_analysis), ensure_ascii=False, allow_nan=False) if chan_analysis is not None else None
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO stock_detail_bars_cache
                    (symbol, period, bars_json, chan_analysis_json, fetched_at, refreshed_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, period) DO UPDATE SET
                    bars_json = excluded.bars_json,
                    chan_analysis_json = excluded.chan_analysis_json,
                    fetched_at = excluded.fetched_at,
                    refreshed_date = excluded.refreshed_date
                """,
                (symbol, period, encoded, chan_encoded, now, self.today()),
            )
        return chan_analysis

    def save_chan_analysis(self, symbol: str, period: str, analysis: dict[str, Any]) -> None:
        """Persist a backfilled Chan snapshot without changing bar freshness."""
        encoded = json.dumps(_json_safe(analysis), ensure_ascii=False, allow_nan=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE stock_detail_bars_cache
                SET chan_analysis_json = ?
                WHERE symbol = ? AND period = ?
                """,
                (encoded, symbol, period),
            )

__all__ = ["StockDetailStore"]
