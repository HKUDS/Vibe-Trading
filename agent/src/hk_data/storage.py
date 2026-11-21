"""Durable, deduplicated quote revisions and collector health."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.paths import get_runtime_root
from src.hk_data.service import iso_time, normalize_symbols, quote_age

UTC = timezone.utc


def default_db_path() -> Path:
    return get_runtime_root() / "data" / "hk_quotes.sqlite3"


class QuoteStore:
    """Store provider revisions once, including corrections at the same time."""

    def __init__(
        self, path: str | Path | None = None, *, readonly: bool = False
    ) -> None:
        self.path = Path(path).expanduser() if path is not None else default_db_path()
        self.readonly = readonly
        if readonly:
            if not self.path.is_file():
                raise FileNotFoundError(
                    "No HK quote store yet; run the collector first"
                )
            self.connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
            )
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path, timeout=10)
            self.connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    source TEXT NOT NULL,
                    provider_time TEXT NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS quote_latest
                    ON quotes(symbol, provider_time DESC, last_observed_at DESC);
                CREATE INDEX IF NOT EXISTS quote_retention ON quotes(last_observed_at);
                CREATE TABLE IF NOT EXISTS polls (
                    id INTEGER PRIMARY KEY,
                    observed_at_utc TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS poll_retention ON polls(observed_at_utc);
            """)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> QuoteStore:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def record_poll(self, result: dict) -> int:
        """Atomically persist quotes and poll health; return new revision count."""
        if self.readonly:
            raise ValueError("Store is read-only")
        inserted = 0
        with self.connection:
            for row in result.get("quotes", []):
                # Only changed provider values produce new revisions.
                stable = {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {"observed_at_utc", "age_seconds", "status", "session_state"}
                }
                payload = json.dumps(stable, sort_keys=True, allow_nan=False)
                fingerprint = hashlib.sha256(payload.encode()).hexdigest()
                seen = row["observed_at_utc"]
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO quotes (fingerprint,symbol,source,provider_time,first_observed_at,last_observed_at,payload) VALUES (?,?,?,?,?,?,?)",
                    (
                        fingerprint,
                        row["symbol"],
                        row["source"],
                        row["provider_time"],
                        seen,
                        seen,
                        payload,
                    ),
                )
                inserted += cursor.rowcount
                # Metadata such as session window may change without creating
                # another market observation. Keep its last observed value.
                stored = {
                    **stable,
                    "session_state": row.get("session_state", "unknown"),
                }
                self.connection.execute(
                    "UPDATE quotes SET first_observed_at=MIN(first_observed_at,?),last_observed_at=MAX(last_observed_at,?),payload=? WHERE fingerprint=?",
                    (
                        seen,
                        seen,
                        json.dumps(stored, sort_keys=True, allow_nan=False),
                        fingerprint,
                    ),
                )
            health = {key: value for key, value in result.items() if key != "quotes"}
            health["quote_count"] = len(result.get("quotes", []))
            health["new_revisions"] = inserted
            health["stale_count"] = sum(
                row.get("status") == "stale" for row in result.get("quotes", [])
            )
            self.connection.execute(
                "INSERT INTO polls (observed_at_utc,payload) VALUES (?,?)",
                (result["observed_at_utc"], json.dumps(health, allow_nan=False)),
            )
        return inserted

    def latest(
        self,
        symbols: list[str] | None = None,
        *,
        max_age_seconds: float = 1200,
        now: datetime | None = None,
    ) -> dict:
        """Read snapshots with current age and separate last-poll health."""
        now = now or datetime.now(UTC)
        requested = normalize_symbols(symbols) if symbols is not None else None
        where, params = "", []
        if requested is not None:
            where = "WHERE symbol IN (" + ",".join("?" for _ in requested) + ")"
            params = requested
        rows = self.connection.execute(
            "SELECT * FROM (SELECT *,ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY provider_time DESC,last_observed_at DESC,id DESC) AS rank FROM quotes "
            + where
            + ") WHERE rank=1 ORDER BY symbol",
            params,
        ).fetchall()
        quotes = []
        for row in rows:
            quote = json.loads(row["payload"])
            quote["observed_at_utc"] = row["last_observed_at"]
            quote["first_observed_at_utc"] = row["first_observed_at"]
            quotes.append(quote_age(quote, now, max_age_seconds))
        poll = self.connection.execute(
            "SELECT payload FROM polls ORDER BY id DESC LIMIT 1"
        ).fetchone()
        health = json.loads(poll["payload"]) if poll else None
        missing = [
            symbol
            for symbol in requested or []
            if symbol not in {row["symbol"] for row in quotes}
        ]
        status = "empty" if not quotes else "partial" if missing else "ok"
        if health and not health.get("ok"):
            status = "last_poll_failed"
        poll_age = (
            max(
                0.0,
                (
                    now - datetime.fromisoformat(health["observed_at_utc"])
                ).total_seconds(),
            )
            if health
            else None
        )
        return {
            "ok": bool(quotes),
            "status": status,
            "read_at_utc": iso_time(now),
            "quotes": quotes,
            "missing": missing,
            "latest_poll": health,
            "latest_poll_age_seconds": poll_age,
            "stored_revisions": self.connection.execute(
                "SELECT COUNT(*) FROM quotes"
            ).fetchone()[0],
        }

    def prune(self, retain_days: int, *, now: datetime | None = None) -> None:
        """Delete expired observations; reuse pages and bound the WAL size."""
        if retain_days < 0:
            raise ValueError("retain_days must be nonnegative")
        if self.readonly or retain_days == 0:
            return
        cutoff = iso_time((now or datetime.now(UTC)) - timedelta(days=retain_days))
        with self.connection:
            self.connection.execute(
                "DELETE FROM quotes WHERE last_observed_at < ?", (cutoff,)
            )
            self.connection.execute(
                "DELETE FROM polls WHERE observed_at_utc < ?", (cutoff,)
            )
        self.connection.execute("PRAGMA incremental_vacuum(200)")
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
