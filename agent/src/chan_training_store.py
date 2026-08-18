"""SQLite persistence and accounting for Chan-theory training sessions."""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root
from src.chan_training_analysis import build_chan_analysis, filter_chan_analysis


ZERO = Decimal("0")
ONE = Decimal("1")
HALF = Decimal("0.5")
THIRD = Decimal("0.3333333333333333333333333333")
QUARTER = Decimal("0.25")
_LOCK = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any, *, name: str, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a valid number") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _ratio_value(value: str) -> Decimal:
    if value in {"1/2", "0.5"}:
        return HALF
    if value in {"1/3", "0.3333333333333333"}:
        return THIRD
    if value in {"1/4", "0.25"}:
        return QUARTER
    if value in {"1", "clear", "all"}:
        return ONE
    raise ValueError("ratio must be 1/2, 1/3, 1/4 or 1")


def _floor_lot(value: Decimal, lot: Decimal) -> Decimal:
    if lot <= ONE:
        return value.quantize(Decimal("1"), rounding=ROUND_DOWN)
    return (value / lot).to_integral_value(rounding=ROUND_DOWN) * lot


class ChanTrainingStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_runtime_root() / "chan_training.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS training_sessions (
                    id TEXT PRIMARY KEY,
                    profile_scope TEXT NOT NULL,
                    market TEXT NOT NULL,
                    period TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    initial_capital TEXT NOT NULL,
                    window_size INTEGER NOT NULL,
                    initial_cursor INTEGER NOT NULL,
                    current_cursor INTEGER NOT NULL,
                    cash TEXT NOT NULL,
                    position TEXT NOT NULL DEFAULT '0',
                    avg_cost TEXT NOT NULL DEFAULT '0',
                    realized_pnl TEXT NOT NULL DEFAULT '0',
                    total_fees TEXT NOT NULL DEFAULT '0',
                    commission_enabled INTEGER NOT NULL DEFAULT 0,
                    commission_rate TEXT NOT NULL,
                    stamp_enabled INTEGER NOT NULL DEFAULT 0,
                    stamp_rate TEXT NOT NULL,
                    transfer_enabled INTEGER NOT NULL DEFAULT 0,
                    transfer_rate TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_training_sessions_scope
                    ON training_sessions(profile_scope, created_at DESC);
                CREATE TABLE IF NOT EXISTS training_session_bars (
                    session_id TEXT NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
                    bar_index INTEGER NOT NULL,
                    time TEXT NOT NULL,
                    open TEXT NOT NULL,
                    high TEXT NOT NULL,
                    low TEXT NOT NULL,
                    close TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    indicators_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(session_id, bar_index)
                );
                CREATE TABLE IF NOT EXISTS training_trades (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    ratio TEXT NOT NULL,
                    bar_index INTEGER NOT NULL,
                    trade_time TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    gross_amount TEXT NOT NULL,
                    commission TEXT NOT NULL,
                    stamp_tax TEXT NOT NULL,
                    transfer_fee TEXT NOT NULL,
                    total_fees TEXT NOT NULL,
                    cash_after TEXT NOT NULL,
                    position_after TEXT NOT NULL,
                    avg_cost_after TEXT NOT NULL,
                    total_assets_after TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_training_trades_session
                    ON training_trades(session_id, sequence);
                CREATE TABLE IF NOT EXISTS training_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    bar_index INTEGER NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_training_events_session
                    ON training_events(session_id, sequence);
                CREATE TABLE IF NOT EXISTS training_chan_analysis (
                    session_id TEXT PRIMARY KEY REFERENCES training_sessions(id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS training_instruments (
                    market TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    exchange TEXT,
                    asset_type TEXT NOT NULL DEFAULT 'equity',
                    status TEXT NOT NULL DEFAULT 'active',
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(market, symbol)
                );
                CREATE INDEX IF NOT EXISTS idx_training_instruments_market
                    ON training_instruments(market, status, updated_at DESC);
                """
            )
            # The old table stored a versioned Chan contract. Since the current
            # contract is the only supported one, discard that table and rebuild
            # its payloads from the immutable session bars.
            chan_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(training_chan_analysis)").fetchall()}
            if "analysis_version" in chan_columns:
                conn.execute("DROP TABLE training_chan_analysis")
                conn.execute(
                    """CREATE TABLE training_chan_analysis (
                        session_id TEXT PRIMARY KEY REFERENCES training_sessions(id) ON DELETE CASCADE,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                )

            # Sessions created before the persisted analysis table was added,
            # or cleared by the migration above, are backfilled once.
            missing_sessions = conn.execute(
                """SELECT id FROM training_sessions
                   WHERE id NOT IN (SELECT session_id FROM training_chan_analysis)"""
            ).fetchall()
            for session in missing_sessions:
                rows = conn.execute(
                    "SELECT bar_index, time, open, high, low, close, volume, amount FROM training_session_bars WHERE session_id = ? ORDER BY bar_index",
                    (session["id"],),
                ).fetchall()
                if not rows:
                    continue
                analysis = build_chan_analysis([dict(row) for row in rows])
                now_analysis = _now()
                conn.execute(
                    "INSERT INTO training_chan_analysis (session_id, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session["id"], json.dumps(_json_safe(analysis), ensure_ascii=False), now_analysis, now_analysis),
                )

    def upsert_instruments(self, instruments: list[dict[str, Any]]) -> int:
        """Replace the active instrument snapshot for each supplied market.

        The universe is deliberately persisted separately from a training
        session.  A session can therefore record the exact instrument chosen
        from the latest successful synchronization without relying on a
        hard-coded application list.
        """
        now = _now()
        rows: list[tuple[str, str, str, str, str, str, str, str]] = []
        markets: set[str] = set()
        for item in instruments:
            market = str(item.get("market") or "").strip().lower()
            symbol = str(item.get("symbol") or "").strip().upper()
            name = str(item.get("name") or symbol).strip()
            if market not in {"a_share", "us"} or not symbol or not name:
                continue
            markets.add(market)
            rows.append((market, symbol, name, str(item.get("exchange") or ""), str(item.get("asset_type") or "equity"), "active", str(item.get("source") or "unknown"), now))
        if not rows:
            raise ValueError("instrument synchronization returned no valid instruments")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """INSERT INTO training_instruments
                   (market, symbol, name, exchange, asset_type, status, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(market, symbol) DO UPDATE SET
                     name = excluded.name, exchange = excluded.exchange,
                     asset_type = excluded.asset_type, status = excluded.status,
                     source = excluded.source, updated_at = excluded.updated_at""",
                rows,
            )
            for market in markets:
                symbols = {row[1] for row in rows if row[0] == market}
                if symbols:
                    placeholders = ",".join("?" for _ in symbols)
                    conn.execute(
                        f"UPDATE training_instruments SET status = 'inactive', updated_at = ? WHERE market = ? AND symbol NOT IN ({placeholders})",
                        (now, market, *symbols),
                    )
        return len(rows)

    def count_instruments(self, market: str | None = None) -> int | dict[str, int]:
        with self._connect() as conn:
            if market:
                row = conn.execute("SELECT COUNT(*) AS count FROM training_instruments WHERE market = ? AND status = 'active'", (market,)).fetchone()
                return int(row["count"])
            rows = conn.execute("SELECT market, COUNT(*) AS count FROM training_instruments WHERE status = 'active' GROUP BY market").fetchall()
        return {str(row["market"]): int(row["count"]) for row in rows}

    def list_instruments(self, market: str, *, limit: int = 50000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT market, symbol, name, exchange, asset_type, source, updated_at FROM training_instruments WHERE market = ? AND status = 'active' ORDER BY symbol LIMIT ?",
                (market, max(1, min(int(limit), 100000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def random_instrument(self, market: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT market, symbol, name, exchange, asset_type, source, updated_at FROM training_instruments WHERE market = ? AND status = 'active' ORDER BY RANDOM() LIMIT 1",
                (market,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _scope(scope: str) -> str:
        value = str(scope).strip()
        if not value:
            raise ValueError("profile scope must not be empty")
        return value

    @staticmethod
    def _bar_payload(item: dict[str, Any]) -> dict[str, Any]:
        def finite(value: Any, fallback: Decimal = ZERO) -> Decimal:
            parsed = _decimal(value, name="bar value", default=fallback)
            return parsed if parsed is not None else fallback

        open_ = finite(item.get("open"))
        high = finite(item.get("high"))
        low = finite(item.get("low"))
        close = finite(item.get("close"))
        volume = finite(item.get("volume"))
        amount = finite(item.get("amount"), volume * (open_ + high + low + close) / Decimal("4"))
        return {
            "time": str(item.get("time") or item.get("trade_date") or ""),
            "open": _number(open_),
            "high": _number(high),
            "low": _number(low),
            "close": _number(close),
            "volume": _number(volume),
            "amount": _number(amount),
            "indicators": item.get("indicators") or {},
        }

    def create_session(self, scope: str, config: dict[str, Any], bars: list[dict[str, Any]], chan_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = self._scope(scope)
        if not bars:
            raise ValueError("training session requires at least one bar")
        market = str(config.get("market") or "").strip().lower()
        period = str(config.get("period") or "").strip().lower()
        if market not in {"a_share", "us"} or period not in {"1d", "1w"}:
            raise ValueError("unsupported training market or period")
        capital = _decimal(config.get("initial_capital"), name="initial_capital", default=ZERO) or ZERO
        window_size = int(config.get("window_size") or 60)
        if capital <= ZERO or window_size < 2 or window_size > len(bars):
            raise ValueError("invalid training capital or window size")
        # Persist only the current analysis shape, even when a caller supplies
        # a stale or partial payload. The bar snapshot is the source of truth.
        if chan_analysis is not None:
            chan_analysis = build_chan_analysis(bars)
        initial_cursor = int(config.get("initial_cursor", max(window_size - 1, len(bars) // 2)))
        initial_cursor = max(window_size - 1, min(initial_cursor, len(bars) - 1))
        now = _now()
        session_id = uuid.uuid4().hex
        values = (
            session_id, scope, market, period, str(config.get("symbol") or ""), str(config.get("name") or config.get("symbol") or ""),
            str(config.get("currency") or ("CNY" if market == "a_share" else "USD")), _number(capital), window_size,
            initial_cursor, initial_cursor, _number(capital), "0", "0", "0", "0",
            int(bool(config.get("commission_enabled"))), _number(_decimal(config.get("commission_rate"), name="commission_rate", default=ZERO) or ZERO),
            int(bool(config.get("stamp_enabled"))), _number(_decimal(config.get("stamp_rate"), name="stamp_rate", default=ZERO) or ZERO),
            int(bool(config.get("transfer_enabled"))), _number(_decimal(config.get("transfer_rate"), name="transfer_rate", default=ZERO) or ZERO),
            "active", now, now, None,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO training_sessions
                   (id, profile_scope, market, period, symbol, name, currency, initial_capital,
                    window_size, initial_cursor, current_cursor, cash, position, avg_cost,
                    realized_pnl, total_fees, commission_enabled, commission_rate, stamp_enabled,
                    stamp_rate, transfer_enabled, transfer_rate, status, created_at, updated_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            for index, raw in enumerate(bars):
                bar = self._bar_payload(raw)
                if not bar["time"]:
                    continue
                conn.execute(
                    """INSERT INTO training_session_bars
                       (session_id, bar_index, time, open, high, low, close, volume, amount, indicators_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, index, bar["time"], bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"], bar["amount"], json.dumps(_json_safe(bar["indicators"]), ensure_ascii=False)),
                )
            if chan_analysis is not None:
                now_analysis = _now()
                conn.execute(
                    "INSERT INTO training_chan_analysis (session_id, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, json.dumps(_json_safe(chan_analysis), ensure_ascii=False), now_analysis, now_analysis),
                )
            self._insert_event(conn, session_id, 1, "start", initial_cursor, {"market": market, "period": period})
        return self.get_session(scope, session_id, include_hidden=True)

    def _insert_event(self, conn: sqlite3.Connection, session_id: str, sequence: int, event_type: str, bar_index: int, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO training_events (id, session_id, sequence, event_type, bar_index, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, session_id, sequence, event_type, bar_index, json.dumps(_json_safe(payload), ensure_ascii=False), _now()),
        )

    def _get_row(self, scope: str, session_id: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row:
        own = conn is None
        connection = conn or self._connect()
        try:
            row = connection.execute("SELECT * FROM training_sessions WHERE id = ? AND profile_scope = ?", (session_id, self._scope(scope))).fetchone()
            if row is None:
                raise KeyError("training session not found")
            return row
        finally:
            if own:
                connection.close()

    @staticmethod
    def _bar_dict(row: sqlite3.Row) -> dict[str, Any]:
        try:
            indicators = json.loads(row["indicators_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            indicators = {}
        return {"time": row["time"], "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "volume": float(row["volume"]), "amount": float(row["amount"]), "indicators": indicators}

    @staticmethod
    def _session_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "market": row["market"], "period": row["period"], "symbol": row["symbol"], "name": row["name"], "currency": row["currency"],
            "initial_capital": row["initial_capital"], "window_size": row["window_size"], "initial_cursor": row["initial_cursor"], "current_cursor": row["current_cursor"],
            "cash": row["cash"], "position": row["position"], "avg_cost": row["avg_cost"], "realized_pnl": row["realized_pnl"], "total_fees": row["total_fees"],
            "commission_enabled": bool(row["commission_enabled"]), "commission_rate": row["commission_rate"], "stamp_enabled": bool(row["stamp_enabled"]), "stamp_rate": row["stamp_rate"],
            "transfer_enabled": bool(row["transfer_enabled"]), "transfer_rate": row["transfer_rate"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"], "finished_at": row["finished_at"],
        }

    @staticmethod
    def _trade_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in ("id", "sequence", "side", "ratio", "bar_index", "trade_time", "price", "quantity", "gross_amount", "commission", "stamp_tax", "transfer_fee", "total_fees", "cash_after", "position_after", "avg_cost_after", "total_assets_after", "created_at")}

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return {"id": row["id"], "sequence": row["sequence"], "event_type": row["event_type"], "bar_index": row["bar_index"], "payload": payload, "created_at": row["created_at"]}

    def get_session(self, scope: str, session_id: str, *, include_hidden: bool = False) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._get_row(scope, session_id, conn)
            payload = self._session_dict(row)
            payload["bars"] = [self._bar_dict(item) for item in conn.execute("SELECT * FROM training_session_bars WHERE session_id = ? ORDER BY bar_index", (session_id,)).fetchall()]
            payload["trades"] = [self._trade_dict(item) for item in conn.execute("SELECT * FROM training_trades WHERE session_id = ? ORDER BY sequence", (session_id,)).fetchall()]
            payload["events"] = [self._event_dict(item) for item in conn.execute("SELECT * FROM training_events WHERE session_id = ? ORDER BY sequence", (session_id,)).fetchall()]
            analysis_row = conn.execute("SELECT payload_json FROM training_chan_analysis WHERE session_id = ?", (session_id,)).fetchone()
            if analysis_row:
                try:
                    payload["chan_analysis"] = json.loads(analysis_row["payload_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload["chan_analysis"] = None
            else:
                payload["chan_analysis"] = None
        if not include_hidden:
            payload["symbol"] = None
            payload["name"] = None
            payload["bars"] = [{**bar, "time": f"K{index + 1}"} for index, bar in enumerate(payload["bars"])]
            payload["trades"] = [{**trade, "trade_time": f"K{trade['bar_index'] + 1}"} for trade in payload["trades"]]
            if payload["chan_analysis"]:
                payload["chan_analysis"] = filter_chan_analysis(payload["chan_analysis"], int(payload["current_cursor"]))
        return payload

    def list_sessions(self, scope: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM training_sessions WHERE profile_scope = ? ORDER BY created_at DESC", (self._scope(scope),)).fetchall()
        return [self._session_dict(row) for row in rows]

    def delete_session(self, scope: str, session_id: str) -> None:
        """Delete one user's training session and all of its review snapshots."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._get_row(scope, session_id, conn)
            conn.execute("DELETE FROM training_sessions WHERE id = ?", (session_id,))

    def save_state(self, scope: str, session_id: str, cursor: int) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get_row(scope, session_id, conn)
            if row["status"] not in {"active", "finished"}:
                raise ValueError("training session is not navigable")
            bars_count = conn.execute("SELECT COUNT(*) AS count FROM training_session_bars WHERE session_id = ?", (session_id,)).fetchone()["count"]
            next_cursor = max(row["window_size"] - 1, min(int(cursor), bars_count - 1))
            sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM training_events WHERE session_id = ?", (session_id,)).fetchone()["sequence"]
            conn.execute("UPDATE training_sessions SET current_cursor = ?, updated_at = ? WHERE id = ?", (next_cursor, _now(), session_id))
            self._insert_event(conn, session_id, sequence, "move", next_cursor, {"cursor": next_cursor})
        return self.get_session(scope, session_id, include_hidden=False)

    def finish(self, scope: str, session_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get_row(scope, session_id, conn)
            if row["status"] == "active":
                sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM training_events WHERE session_id = ?", (session_id,)).fetchone()["sequence"]
                now = _now()
                conn.execute("UPDATE training_sessions SET status = 'finished', finished_at = ?, updated_at = ? WHERE id = ?", (now, now, session_id))
                self._insert_event(conn, session_id, sequence, "finish", row["current_cursor"], {})
        return self.get_session(scope, session_id, include_hidden=True)

    def execute_trade(self, scope: str, session_id: str, side: str, ratio: str) -> dict[str, Any]:
        side = str(side).strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        fraction = _ratio_value(str(ratio).strip())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get_row(scope, session_id, conn)
            if row["status"] != "active":
                raise ValueError("training session is not active")
            bar = conn.execute("SELECT * FROM training_session_bars WHERE session_id = ? AND bar_index = ?", (session_id, row["current_cursor"])).fetchone()
            if bar is None:
                raise ValueError("current training bar not found")
            price = Decimal(bar["close"])
            cash = Decimal(row["cash"])
            position = Decimal(row["position"])
            avg_cost = Decimal(row["avg_cost"])
            commission_rate = Decimal(row["commission_rate"]) if row["commission_enabled"] else ZERO
            stamp_rate = Decimal(row["stamp_rate"]) if row["stamp_enabled"] and side == "sell" and row["market"] == "a_share" else ZERO
            transfer_rate = Decimal(row["transfer_rate"]) if row["transfer_enabled"] and row["market"] == "a_share" else ZERO
            lot = Decimal("100") if row["market"] == "a_share" else ONE
            if side == "buy":
                denominator = price * (ONE + commission_rate + transfer_rate)
                quantity = _floor_lot(cash * fraction / denominator, lot) if denominator > ZERO else ZERO
                if quantity <= ZERO:
                    raise ValueError("available cash is insufficient for the minimum trading unit")
                gross = quantity * price
                commission = gross * commission_rate
                transfer = gross * transfer_rate
                stamp = ZERO
                fees = commission + transfer
                cash_after = cash - gross - fees
                position_after = position + quantity
                avg_after = ((position * avg_cost) + gross + fees) / position_after
                realized_after = Decimal(row["realized_pnl"])
            else:
                quantity = position if fraction == ONE else _floor_lot(position * fraction, lot)
                if quantity <= ZERO:
                    raise ValueError("position is insufficient for the minimum trading unit")
                gross = quantity * price
                commission = gross * commission_rate
                stamp = gross * stamp_rate
                transfer = gross * transfer_rate
                fees = commission + stamp + transfer
                cash_after = cash + gross - fees
                position_after = position - quantity
                avg_after = avg_cost if position_after > ZERO else ZERO
                realized_after = Decimal(row["realized_pnl"]) + gross - quantity * avg_cost - fees
            total_assets = cash_after + position_after * price
            total_fees = Decimal(row["total_fees"]) + fees
            sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM training_trades WHERE session_id = ?", (session_id,)).fetchone()["sequence"]
            trade_id = uuid.uuid4().hex
            now = _now()
            conn.execute(
                """INSERT INTO training_trades
                   (id, session_id, sequence, side, ratio, bar_index, trade_time, price, quantity, gross_amount,
                    commission, stamp_tax, transfer_fee, total_fees, cash_after, position_after, avg_cost_after,
                    total_assets_after, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, session_id, sequence, side, str(ratio), row["current_cursor"], bar["time"], _number(price), _number(quantity), _number(gross), _number(commission), _number(stamp), _number(transfer), _number(fees), _number(cash_after), _number(position_after), _number(avg_after), _number(total_assets), now),
            )
            event_sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM training_events WHERE session_id = ?", (session_id,)).fetchone()["sequence"]
            self._insert_event(conn, session_id, event_sequence, "trade", row["current_cursor"], {"trade_id": trade_id, "side": side, "ratio": str(ratio)})
            conn.execute("UPDATE training_sessions SET cash = ?, position = ?, avg_cost = ?, realized_pnl = ?, total_fees = ?, updated_at = ? WHERE id = ?", (_number(cash_after), _number(position_after), _number(avg_after), _number(realized_after), _number(total_fees), now, session_id))
        return self.get_session(scope, session_id, include_hidden=False)
