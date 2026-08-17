"""SQLite cache for the overview page's database-first market snapshots."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root


_DEFAULT_DB_NAME = "market_overview.db"
_CACHE_LOCK = threading.RLock()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


class MarketOverviewStore:
    """Persist independent A-share, US, and watchlist overview payloads."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_runtime_root() / _DEFAULT_DB_NAME
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _CACHE_LOCK
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_overview_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )

    def get(self, cache_key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM market_overview_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def age_seconds(self, cache_key: str) -> float | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT fetched_at FROM market_overview_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            fetched_at = datetime.fromisoformat(str(row["fetched_at"]))
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None

    def save(self, cache_key: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False)
        fetched_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_overview_cache (cache_key, payload_json, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at
                """,
                (cache_key, encoded, fetched_at),
            )


__all__ = ["MarketOverviewStore"]
