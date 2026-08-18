"""Typed domain objects for the personal portfolio ledger."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

TransactionType = Literal[
    "buy", "sell", "fee", "dividend", "deposit", "withdrawal", "adjustment"
]
AssetType = Literal["equity", "etf", "commodity", "future", "bank_gold", "other"]


@dataclass(frozen=True)
class Portfolio:
    id: str
    profile_scope: str
    name: str
    base_currency: str
    archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PortfolioTransaction:
    id: str
    portfolio_id: str
    type: TransactionType
    asset_type: AssetType
    symbol: str | None
    market: str | None
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal | None
    fee: Decimal
    tax: Decimal
    currency: str
    trade_at: str
    external_ref: str | None
    note: str | None
    created_at: str
    reversed_transaction_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        def number(value: Decimal | None) -> str | None:
            return format(value, "f") if value is not None else None

        return {
            "id": self.id,
            "portfolio_id": self.portfolio_id,
            "type": self.type,
            "asset_type": self.asset_type,
            "symbol": self.symbol,
            "market": self.market,
            "quantity": number(self.quantity),
            "price": number(self.price),
            "amount": number(self.amount),
            "fee": number(self.fee),
            "tax": number(self.tax),
            "currency": self.currency,
            "trade_at": self.trade_at,
            "external_ref": self.external_ref,
            "note": self.note,
            "created_at": self.created_at,
            "reversed_transaction_id": self.reversed_transaction_id,
        }
