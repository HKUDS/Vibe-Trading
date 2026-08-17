"""SQLite persistence for the overview page's market watchlists."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root


_DEFAULT_DB_NAME = "market_watchlists.db"
_MARKETS = ("a_share", "us")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WatchlistStore:
    """Persist the overview watchlist in the active Vibe-Trading runtime."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_runtime_root() / _DEFAULT_DB_NAME
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS overview_watchlist_entries (
                    profile_scope TEXT NOT NULL,
                    market TEXT NOT NULL CHECK (market IN ('a_share', 'us')),
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    position INTEGER NOT NULL CHECK (position >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (profile_scope, market, symbol),
                    UNIQUE (profile_scope, market, position)
                )
                """
            )

    def load(self, profile_scope: str) -> dict[str, list[dict[str, str]]]:
        scope = self._require_scope(profile_scope)
        result: dict[str, list[dict[str, str]]] = {market: [] for market in _MARKETS}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT market, symbol, name
                FROM overview_watchlist_entries
                WHERE profile_scope = ?
                ORDER BY market, position
                """,
                (scope,),
            ).fetchall()
        for row in rows:
            result[row["market"]].append({"symbol": row["symbol"], "name": row["name"]})
        return result

    def save(
        self,
        profile_scope: str,
        watchlists: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, str]]]:
        scope = self._require_scope(profile_scope)
        normalized = self._normalize(watchlists)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM overview_watchlist_entries WHERE profile_scope = ?",
                (scope,),
            )
            connection.executemany(
                """
                INSERT INTO overview_watchlist_entries
                    (profile_scope, market, symbol, name, position, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (scope, market, entry["symbol"], entry["name"], position, now)
                    for market in _MARKETS
                    for position, entry in enumerate(normalized[market])
                ],
            )
        return normalized

    @staticmethod
    def _require_scope(profile_scope: str) -> str:
        scope = str(profile_scope).strip()
        if not scope:
            raise ValueError("profile scope must not be empty")
        return scope

    @staticmethod
    def _normalize(watchlists: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, str]]]:
        normalized: dict[str, list[dict[str, str]]] = {market: [] for market in _MARKETS}
        for market in _MARKETS:
            seen: set[str] = set()
            for raw_entry in watchlists.get(market, []):
                symbol = str(raw_entry.get("symbol", "")).strip().upper()
                name = str(raw_entry.get("name", "")).strip()
                if not symbol or not name or symbol in seen:
                    continue
                seen.add(symbol)
                normalized[market].append({"symbol": symbol, "name": name})
        return normalized
