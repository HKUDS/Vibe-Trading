"""SQLite persistence for personal portfolio ledgers."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root

from .models import Portfolio, PortfolioTransaction, TransactionType

_TRANSACTION_TYPES = {"buy", "sell", "fee", "dividend", "deposit", "withdrawal", "adjustment"}
_MARKETS = {"a_share", "us", "commodity", "other"}
_ASSET_TYPES = {"equity", "etf", "commodity", "future", "bank_gold", "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value: Any, *, required: bool = False, name: str = "value") -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{name} is required")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a valid number") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


class PortfolioStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_runtime_root() / "portfolio.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolios (
                    id TEXT PRIMARY KEY,
                    profile_scope TEXT NOT NULL,
                    name TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_portfolios_scope ON portfolios(profile_scope, archived, updated_at);
                CREATE TABLE IF NOT EXISTS portfolio_transactions (
                    id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
                    type TEXT NOT NULL,
                    asset_type TEXT NOT NULL DEFAULT 'equity',
                    symbol TEXT,
                    market TEXT,
                    quantity TEXT,
                    price TEXT,
                    amount TEXT,
                    fee TEXT NOT NULL DEFAULT '0',
                    tax TEXT NOT NULL DEFAULT '0',
                    currency TEXT NOT NULL,
                    trade_at TEXT NOT NULL,
                    external_ref TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    reversed_transaction_id TEXT REFERENCES portfolio_transactions(id),
                    UNIQUE(portfolio_id, external_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_tx_portfolio_date
                    ON portfolio_transactions(portfolio_id, trade_at DESC, created_at DESC);
                CREATE TABLE IF NOT EXISTS reconciliation_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
                    broker_profile_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT,
                    broker_quantity TEXT,
                    broker_avg_cost TEXT,
                    broker_market_value TEXT,
                    status TEXT NOT NULL,
                    UNIQUE(portfolio_id, broker_profile_id, observed_at, symbol)
                );
                CREATE TABLE IF NOT EXISTS portfolio_price_overrides (
                    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    price TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(portfolio_id, symbol, market, currency)
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(portfolio_transactions)")}
            if "asset_type" not in columns:
                conn.execute("ALTER TABLE portfolio_transactions ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'equity'")

    @staticmethod
    def _scope(scope: str) -> str:
        value = str(scope).strip()
        if not value:
            raise ValueError("profile scope must not be empty")
        return value

    def list_portfolios(self, scope: str, *, include_archived: bool = False) -> list[Portfolio]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolios WHERE profile_scope = ? AND (? OR archived = 0) ORDER BY archived, name, created_at",
                (self._scope(scope), int(include_archived)),
            ).fetchall()
        return [self._portfolio(row) for row in rows]

    def create_portfolio(self, scope: str, name: str, base_currency: str = "CNY") -> Portfolio:
        name = str(name).strip()
        currency = str(base_currency).strip().upper()
        if not name or len(name) > 100:
            raise ValueError("portfolio name must be between 1 and 100 characters")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("base_currency must be a three-letter currency code")
        now = _now()
        item = (uuid.uuid4().hex, self._scope(scope), name, currency, 0, now, now)
        with self._connect() as conn:
            conn.execute("INSERT INTO portfolios VALUES (?, ?, ?, ?, ?, ?, ?)", item)
        return self.get_portfolio(scope, item[0])

    def update_portfolio(self, scope: str, portfolio_id: str, *, name: str | None = None, archived: bool | None = None) -> Portfolio:
        portfolio = self.get_portfolio(scope, portfolio_id)
        next_name = str(name).strip() if name is not None else portfolio.name
        if not next_name or len(next_name) > 100:
            raise ValueError("portfolio name must be between 1 and 100 characters")
        next_archived = portfolio.archived if archived is None else bool(archived)
        with self._connect() as conn:
            conn.execute(
                "UPDATE portfolios SET name = ?, archived = ?, updated_at = ? WHERE id = ? AND profile_scope = ?",
                (next_name, int(next_archived), _now(), portfolio_id, self._scope(scope)),
            )
        return self.get_portfolio(scope, portfolio_id)

    def get_portfolio(self, scope: str, portfolio_id: str) -> Portfolio:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM portfolios WHERE id = ? AND profile_scope = ?", (portfolio_id, self._scope(scope))).fetchone()
        if row is None:
            raise KeyError("portfolio not found")
        return self._portfolio(row)

    def list_transactions(self, scope: str, portfolio_id: str, **filters: Any) -> list[PortfolioTransaction]:
        self.get_portfolio(scope, portfolio_id)
        clauses = ["portfolio_id = ?"]
        args: list[Any] = [portfolio_id]
        if filters.get("symbol"):
            clauses.append("symbol = ?")
            args.append(str(filters["symbol"]).strip().upper())
        if filters.get("type"):
            clauses.append("type = ?")
            args.append(filters["type"])
        if filters.get("start_date"):
            clauses.append("trade_at >= ?")
            args.append(filters["start_date"])
        if filters.get("end_date"):
            clauses.append("trade_at <= ?")
            args.append(filters["end_date"])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM portfolio_transactions WHERE {' AND '.join(clauses)} ORDER BY trade_at DESC, created_at DESC",
                args,
            ).fetchall()
        return [self._transaction(row) for row in rows]

    def all_transactions(self, scope: str, portfolio_id: str | None = None) -> list[PortfolioTransaction]:
        if portfolio_id and portfolio_id != "all":
            return self.list_transactions(scope, portfolio_id)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT t.* FROM portfolio_transactions t
                   JOIN portfolios p ON p.id = t.portfolio_id
                   WHERE p.profile_scope = ? AND p.archived = 0
                   ORDER BY t.trade_at, t.created_at, t.id""",
                (self._scope(scope),),
            ).fetchall()
        return [self._transaction(row) for row in rows]

    def add_transaction(self, scope: str, portfolio_id: str, payload: dict[str, Any]) -> PortfolioTransaction:
        self.get_portfolio(scope, portfolio_id)
        tx_type = str(payload.get("type", "")).strip().lower()
        if tx_type not in _TRANSACTION_TYPES:
            raise ValueError(f"unsupported transaction type: {tx_type}")
        currency = str(payload.get("currency") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter currency code")
        symbol = str(payload.get("symbol") or "").strip().upper() or None
        market = str(payload.get("market") or "").strip().lower() or None
        if market and market not in _MARKETS:
            raise ValueError("market must be a_share, us, commodity or other")
        asset_type = str(payload.get("asset_type") or ("commodity" if market == "commodity" else "equity")).strip().lower()
        if market == "commodity" and asset_type == "equity":
            asset_type = "commodity"
        elif market == "other" and asset_type == "equity":
            asset_type = "other"
        if asset_type not in _ASSET_TYPES:
            raise ValueError("asset_type must be equity, etf, commodity, future, bank_gold or other")
        quantity = _money(payload.get("quantity"), name="quantity")
        price = _money(payload.get("price"), name="price")
        amount = _money(payload.get("amount"), name="amount")
        fee = _money(payload.get("fee"), name="fee") or Decimal("0")
        tax = _money(payload.get("tax"), name="tax") or Decimal("0")
        if fee < 0 or tax < 0:
            raise ValueError("fee and tax must be non-negative")
        if tx_type in {"buy", "sell"} and (not symbol or not market or quantity is None or price is None or quantity <= 0 or price <= 0):
            raise ValueError("buy and sell require positive symbol, market, quantity and price")
        if tx_type in {"deposit", "withdrawal", "fee", "dividend"} and (amount is None or amount <= 0):
            raise ValueError(f"{tx_type} requires a positive amount")
        if tx_type == "adjustment" and (not symbol or not market or quantity is None or quantity == 0):
            raise ValueError("adjustment requires symbol, market and non-zero quantity")
        if tx_type == "adjustment" and amount is not None and amount < 0:
            raise ValueError("adjustment amount must be non-negative")
        if tx_type in {"buy", "sell", "adjustment"} and not symbol:
            raise ValueError(f"{tx_type} requires a symbol")
        trade_at = str(payload.get("trade_at") or _now()).strip()
        external_ref = str(payload.get("external_ref") or "").strip() or None
        now = _now()
        tx_id = uuid.uuid4().hex
        values = (tx_id, portfolio_id, tx_type, asset_type, symbol, market, str(quantity) if quantity is not None else None,
                  str(price) if price is not None else None, str(amount) if amount is not None else None,
                  str(fee), str(tax), currency, trade_at, external_ref, str(payload.get("note") or "").strip() or None, now, None)
        try:
            with self._connect() as conn:
                if tx_type == "sell":
                    self._assert_can_sell(conn, portfolio_id, symbol or "", market or "", currency, quantity or Decimal("0"), trade_at)
                conn.execute(
                    """INSERT INTO portfolio_transactions
                       (id, portfolio_id, type, asset_type, symbol, market, quantity,
                        price, amount, fee, tax, currency, trade_at, external_ref,
                        note, created_at, reversed_transaction_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            if external_ref:
                raise ValueError("external_ref already exists for this portfolio") from exc
            raise
        return self.get_transaction(scope, portfolio_id, tx_id)

    def reverse_transaction(self, scope: str, portfolio_id: str, transaction_id: str) -> PortfolioTransaction:
        original = self.get_transaction(scope, portfolio_id, transaction_id)
        if original.reversed_transaction_id:
            raise ValueError("transaction has already been reversed")
        if original.type in {"buy", "sell", "adjustment"}:
            with self._connect() as conn:
                later = conn.execute(
                    """SELECT 1 FROM portfolio_transactions
                       WHERE portfolio_id = ? AND symbol = ? AND market = ? AND currency = ?
                         AND type IN ('buy', 'sell', 'adjustment')
                         AND (trade_at > ? OR (trade_at = ? AND created_at > ?))
                       LIMIT 1""",
                    (portfolio_id, original.symbol, original.market, original.currency,
                     original.trade_at, original.trade_at, original.created_at),
                ).fetchone()
            if later is not None:
                raise ValueError("cannot reverse a historical trade after later position changes; use an adjustment")
        inverse = {
            "buy": "sell", "sell": "buy", "deposit": "withdrawal", "withdrawal": "deposit",
            "fee": "deposit", "dividend": "withdrawal", "adjustment": "adjustment",
        }[original.type]
        quantity = -original.quantity if original.type == "adjustment" and original.quantity is not None else original.quantity
        payload = {"type": inverse, "asset_type": original.asset_type, "symbol": original.symbol, "market": original.market, "quantity": quantity,
                   "price": original.price, "amount": original.amount, "fee": original.fee, "tax": original.tax,
                   "currency": original.currency, "trade_at": _now(), "external_ref": f"reversal:{original.id}",
                   "note": f"Reversal of {original.id}"}
        if inverse == "deposit":
            payload["amount"] = original.amount
        reversed_tx = self.add_transaction(scope, portfolio_id, payload)
        with self._connect() as conn:
            conn.execute("UPDATE portfolio_transactions SET reversed_transaction_id = ? WHERE id = ?", (reversed_tx.id, original.id))
        return reversed_tx

    def get_transaction(self, scope: str, portfolio_id: str, transaction_id: str) -> PortfolioTransaction:
        self.get_portfolio(scope, portfolio_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM portfolio_transactions WHERE id = ? AND portfolio_id = ?", (transaction_id, portfolio_id)).fetchone()
        if row is None:
            raise KeyError("transaction not found")
        return self._transaction(row)

    def save_reconciliation(self, scope: str, portfolio_id: str, broker_profile_id: str, rows: list[dict[str, Any]], observed_at: str | None = None) -> dict[str, Any]:
        self.get_portfolio(scope, portfolio_id)
        observed = observed_at or _now()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM reconciliation_snapshots WHERE portfolio_id = ? AND broker_profile_id = ?",
                (portfolio_id, broker_profile_id),
            )
            conn.executemany(
                """INSERT INTO reconciliation_snapshots
                   (portfolio_id, broker_profile_id, observed_at, symbol, market,
                    broker_quantity, broker_avg_cost, broker_market_value, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (portfolio_id, broker_profile_id, observed, str(row["symbol"]), row.get("market"),
                     row.get("quantity"), row.get("avg_cost"), row.get("market_value"), row.get("status", "observed"))
                    for row in rows
                ],
            )
        return {"portfolio_id": portfolio_id, "broker_profile_id": broker_profile_id, "observed_at": observed, "items": rows}

    def latest_reconciliation(self, scope: str, portfolio_id: str, broker_profile_id: str | None = None) -> dict[str, Any] | None:
        self.get_portfolio(scope, portfolio_id)
        clauses = ["portfolio_id = ?"]
        args: list[Any] = [portfolio_id]
        if broker_profile_id:
            clauses.append("broker_profile_id = ?")
            args.append(broker_profile_id)
        with self._connect() as conn:
            latest = conn.execute(
                f"SELECT portfolio_id, broker_profile_id, observed_at FROM reconciliation_snapshots WHERE {' AND '.join(clauses)} ORDER BY observed_at DESC LIMIT 1",
                args,
            ).fetchone()
            if latest is None:
                return None
            rows = conn.execute(
                """SELECT symbol, market, broker_quantity AS quantity,
                          broker_avg_cost AS avg_cost, broker_market_value AS market_value, status
                   FROM reconciliation_snapshots
                   WHERE portfolio_id = ? AND broker_profile_id = ? AND observed_at = ?
                   ORDER BY symbol""",
                (portfolio_id, latest["broker_profile_id"], latest["observed_at"]),
            ).fetchall()
        return {"portfolio_id": latest["portfolio_id"], "broker_profile_id": latest["broker_profile_id"], "observed_at": latest["observed_at"], "items": [dict(row) for row in rows]}

    def save_price_override(self, scope: str, portfolio_id: str, *, symbol: str, market: str, currency: str, price: Any) -> dict[str, Any]:
        self.get_portfolio(scope, portfolio_id)
        normalized_symbol = str(symbol).strip().upper()
        normalized_market = str(market).strip().lower()
        normalized_currency = str(currency).strip().upper()
        normalized_price = _money(price, required=True, name="price")
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if normalized_market not in _MARKETS:
            raise ValueError("market must be a_share, us, commodity or other")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ValueError("currency must be a three-letter currency code")
        if normalized_price is None or normalized_price <= 0:
            raise ValueError("price must be positive")
        updated_at = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO portfolio_price_overrides
                   (portfolio_id, symbol, market, currency, price, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(portfolio_id, symbol, market, currency)
                   DO UPDATE SET price = excluded.price, updated_at = excluded.updated_at""",
                (portfolio_id, normalized_symbol, normalized_market, normalized_currency, str(normalized_price), updated_at),
            )
        return {"portfolio_id": portfolio_id, "symbol": normalized_symbol, "market": normalized_market, "currency": normalized_currency, "price": format(normalized_price, "f"), "updated_at": updated_at}

    def list_price_overrides(self, scope: str, portfolio_id: str) -> dict[str, dict[str, Any]]:
        self.get_portfolio(scope, portfolio_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, market, currency, price, updated_at FROM portfolio_price_overrides WHERE portfolio_id = ?",
                (portfolio_id,),
            ).fetchall()
        return {
            f"{row['market'].lower()}:{row['symbol'].upper()}:{row['currency'].upper()}": {
                "symbol": row["symbol"], "market": row["market"], "currency": row["currency"],
                "price": row["price"], "updated_at": row["updated_at"],
            }
            for row in rows
        }

    @staticmethod
    def _assert_can_sell(conn: sqlite3.Connection, portfolio_id: str, symbol: str, market: str, currency: str, quantity: Decimal, trade_at: str) -> None:
        rows = conn.execute("SELECT * FROM portfolio_transactions WHERE portfolio_id = ? AND trade_at <= ? ORDER BY trade_at, created_at, id", (portfolio_id, trade_at)).fetchall()
        reversed_ids = {row["id"] for row in rows if row["reversed_transaction_id"]}
        reversed_ids.update(row["reversed_transaction_id"] for row in rows if row["reversed_transaction_id"])
        qty = Decimal("0")
        for row in rows:
            if row["id"] in reversed_ids:
                continue
            if row["symbol"] != symbol or row["market"] != market or row["currency"] != currency:
                continue
            if row["type"] in {"buy", "adjustment"}:
                qty += Decimal(row["quantity"] or "0")
            elif row["type"] == "sell":
                qty -= Decimal(row["quantity"] or "0")
        if quantity > qty:
            raise ValueError(f"cannot sell {quantity}; available quantity is {qty}")

    @staticmethod
    def _portfolio(row: sqlite3.Row) -> Portfolio:
        return Portfolio(id=row["id"], profile_scope=row["profile_scope"], name=row["name"], base_currency=row["base_currency"], archived=bool(row["archived"]), created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _transaction(row: sqlite3.Row) -> PortfolioTransaction:
        return PortfolioTransaction(id=row["id"], portfolio_id=row["portfolio_id"], type=row["type"], asset_type=row["asset_type"] or "equity", symbol=row["symbol"], market=row["market"], quantity=_money(row["quantity"]), price=_money(row["price"]), amount=_money(row["amount"]), fee=_money(row["fee"]) or Decimal("0"), tax=_money(row["tax"]) or Decimal("0"), currency=row["currency"], trade_at=row["trade_at"], external_ref=row["external_ref"], note=row["note"], created_at=row["created_at"], reversed_transaction_id=row["reversed_transaction_id"])
