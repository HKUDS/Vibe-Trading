"""SQLite persistence for immutable portfolio snapshots and FX cache."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root


def _all_positions_priced(payload: dict[str, Any]) -> bool:
    """Exclude older snapshots that were marked complete despite missing prices."""
    return all(bool(row.get("priced")) for row in payload.get("positions", []))


class PortfolioStore:
    """SQLite-backed history of immutable portfolio snapshots plus an FX cache."""

    def __init__(self, path: Path | None = None) -> None:
        """Open (and create when missing) the snapshot database.

        Args:
            path: Database file path. Defaults to
                ``portfolio/portfolio.sqlite3`` under the runtime root
                (``~/.vibe-trading``).
        """
        self.path = path or (get_runtime_root() / "portfolio" / "portfolio.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    complete INTEGER NOT NULL,
                    total_usd TEXT NOT NULL,
                    total_cny TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_created
                    ON portfolio_snapshots(created_at DESC);
                CREATE TABLE IF NOT EXISTS portfolio_fx_cache (
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    rate TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (base, quote)
                );
                """)

    def save_snapshot(self, payload: dict[str, Any]) -> None:
        """Append one immutable snapshot.

        Args:
            payload: The full snapshot envelope produced by
                :meth:`src.portfolio.service.PortfolioService.refresh`.
        """
        totals = payload["totals"]
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO portfolio_snapshots
                    (id, created_at, complete, total_usd, total_cny, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["snapshot_id"],
                    payload["created_at"],
                    int(payload["complete"]),
                    str(totals["usd"]),
                    str(totals["cny"]),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )

    def latest(self, *, complete_only: bool = False) -> dict[str, Any] | None:
        """Return the most recent stored snapshot.

        Args:
            complete_only: Restrict the lookup to snapshots in which every
                enabled source refreshed successfully.

        Returns:
            The snapshot envelope, or ``None`` when nothing matches.
        """
        where = "WHERE complete = 1" if complete_only else ""
        limit = 2000 if complete_only else 1
        with self._connect() as db:
            rows = db.execute(
                f"SELECT payload FROM portfolio_snapshots {where} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            if not complete_only or _all_positions_priced(payload):
                return payload
        return None

    def history(
        self,
        limit: int = 180,
        *,
        complete_only: bool = True,
        valuation_version: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return snapshot totals over time, oldest first.

        Args:
            limit: Maximum number of snapshots to read, clamped to 1..2000.
            complete_only: Restrict the series to snapshots in which every
                enabled source refreshed successfully. Charting a mix of
                complete and partial snapshots would draw a value drop that
                never happened.
            valuation_version: Restrict the series to snapshots produced by
                one valuation methodology. Legacy rows are retained but cannot
                create false changes beside a newer methodology.

        Returns:
            One row per snapshot with id, timestamp, completeness and totals.
        """
        row_limit = max(1, min(int(limit), 2000))
        where = "WHERE complete = 1" if complete_only else ""
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT id, created_at, complete, total_usd, total_cny, payload
                FROM portfolio_snapshots
                {where}
                ORDER BY created_at DESC LIMIT ?
                """,
                (2000 if valuation_version is not None or complete_only else row_limit,),
            ).fetchall()
        history = []
        for row in rows:
            if valuation_version is not None or complete_only:
                payload = json.loads(row["payload"])
                if valuation_version is not None and payload.get("valuation_version") != valuation_version:
                    continue
                if complete_only and not _all_positions_priced(payload):
                    continue
            history.append(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "complete": row["complete"],
                    "total_usd": row["total_usd"],
                    "total_cny": row["total_cny"],
                }
            )
            if len(history) >= row_limit:
                break
        return list(reversed(history))

    def latest_successful_source(self, source_id: str) -> dict[str, Any] | None:
        """Return the newest successfully read payload for one configured source.

        Only accounts with status ``ok`` qualify, so a run of failed refreshes
        keeps pointing back at the original successful observation and its real
        ``last_success_at`` timestamp. The payload is used to report *when* a
        failed source was last healthy; it is never added back into a snapshot's
        totals.

        Args:
            source_id: The configured source id (the local connection id).

        Returns:
            A dict with ``created_at``, ``account`` and ``positions`` for the
            newest successful observation, or ``None`` if there is none.
        """
        with self._connect() as db:
            rows = db.execute("""
                SELECT created_at, payload
                FROM portfolio_snapshots
                ORDER BY created_at DESC LIMIT 2000
                """).fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            account = next(
                (
                    item
                    for item in payload.get("accounts", [])
                    if (item.get("source_id") or item.get("broker")) == source_id
                    and item.get("status") == "ok"
                ),
                None,
            )
            if account is None:
                continue
            return {
                "created_at": str(account.get("last_success_at") or row["created_at"]),
                "account": account,
                "positions": [
                    item
                    for item in payload.get("positions", [])
                    if (item.get("source_id") or item.get("broker")) == source_id
                ],
            }
        return None

    def save_fx(self, base: str, quote: str, rate: str, fetched_at: str) -> None:
        """Cache one FX rate so a later outage still has a usable number.

        Args:
            base: Base currency code, e.g. ``USD``.
            quote: Quote currency code, e.g. ``CNY``.
            rate: The rate, stored as text to avoid binary float drift.
            fetched_at: ISO-8601 timestamp of the successful fetch.
        """
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO portfolio_fx_cache (base, quote, rate, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(base, quote) DO UPDATE SET
                    rate = excluded.rate, fetched_at = excluded.fetched_at
                """,
                (base, quote, rate, fetched_at),
            )

    def load_fx(self, base: str, quote: str) -> tuple[str, str] | None:
        """Read the last cached rate for one currency pair.

        Args:
            base: Base currency code, e.g. ``USD``.
            quote: Quote currency code, e.g. ``CNY``.

        Returns:
            ``(rate, fetched_at)`` or ``None`` when the pair was never cached.
        """
        with self._connect() as db:
            row = db.execute(
                "SELECT rate, fetched_at FROM portfolio_fx_cache WHERE base = ? AND quote = ?",
                (base, quote),
            ).fetchone()
        return (str(row["rate"]), str(row["fetched_at"])) if row else None
