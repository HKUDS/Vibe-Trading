"""Agent tool for recording paper trades in a personal portfolio ledger.

This tool is deliberately separate from the broker connector tools.  A call
only records a filled virtual trade in the local portfolio ledger; it never
contacts a broker and cannot place a live or paper-broker order.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.agent.tools import BaseTool
from src.portfolio.store import PortfolioStore


_SCOPE = "shared-key-holder"
_MARKETS = {"a_share", "us", "commodity", "other"}
_ASSET_TYPES = {"equity", "etf", "commodity", "future", "bank_gold", "other"}
_BROKER_ARGUMENTS = frozenset(
    {
        "connection",
        "host",
        "port",
        "client_id",
        "account",
        "order_type",
        "limit_price",
        "time_in_force",
        "notional",
    }
)


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a valid number") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _resolve_portfolio(store: PortfolioStore, portfolio_ref: str):
    """Resolve a portfolio id or an exact active portfolio name."""
    reference = str(portfolio_ref or "").strip()
    if not reference:
        raise ValueError("portfolio is required and must be a portfolio id or exact name")

    try:
        return store.get_portfolio(_SCOPE, reference)
    except KeyError:
        matches = [
            item
            for item in store.list_portfolios(_SCOPE)
            if item.name == reference
        ]
        if not matches:
            raise ValueError(f"portfolio not found: {reference}")
        if len(matches) > 1:
            raise ValueError(f"portfolio name is ambiguous: {reference}")
        return matches[0]


class VirtualPortfolioTradeTool(BaseTool):
    """Record one filled buy or sell in a local paper portfolio."""

    name = "virtual_portfolio_trade"
    execution_domain = "virtual_portfolio"
    description = (
        "Record a filled virtual buy or sell in a personal portfolio ledger. "
        "This is paper trading only: it never contacts a broker or places a "
        "real order. portfolio accepts a portfolio id or exact portfolio name "
        "such as '量化A'. price must be the simulated fill price. Use a stable "
        "external_ref for idempotency when a strategy retries a trade."
    )
    parameters = {
        "type": "object",
        "properties": {
            "portfolio": {
                "type": "string",
                "description": "Portfolio id or exact portfolio name, e.g. '量化A'.",
            },
            "symbol": {
                "type": "string",
                "description": "Canonical symbol, e.g. 600519.SH or AAPL.US.",
            },
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {
                "type": "number",
                "description": "Positive filled units/shares/contracts.",
            },
            "price": {
                "type": "number",
                "description": "Positive simulated fill price.",
            },
            "market": {
                "type": "string",
                "enum": sorted(_MARKETS),
                "default": "a_share",
            },
            "asset_type": {
                "type": "string",
                "enum": sorted(_ASSET_TYPES),
                "default": "equity",
            },
            "currency": {
                "type": "string",
                "description": "Three-letter settlement currency; defaults to CNY.",
                "default": "CNY",
            },
            "fee": {"type": "number", "default": 0},
            "tax": {"type": "number", "default": 0},
            "trade_at": {
                "type": "string",
                "description": "Optional ISO timestamp or date; defaults to now.",
            },
            "external_ref": {
                "type": "string",
                "description": "Stable strategy/order id used to prevent duplicate fills.",
            },
            "note": {"type": "string", "description": "Optional strategy note."},
        },
        "required": ["portfolio", "symbol", "side", "quantity", "price", "external_ref"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        try:
            broker_arguments = sorted(
                key for key in _BROKER_ARGUMENTS if kwargs.get(key) is not None
            )
            if broker_arguments:
                raise ValueError(
                    "virtual_portfolio_trade accepts no broker/order-routing "
                    f"arguments: {', '.join(broker_arguments)}"
                )

            side = str(kwargs.get("side") or "").strip().lower()
            if side not in {"buy", "sell"}:
                raise ValueError("side must be buy or sell")

            quantity = _positive_decimal(kwargs.get("quantity"), "quantity")
            price = _positive_decimal(kwargs.get("price"), "price")

            market = str(kwargs.get("market") or "a_share").strip().lower()
            if market not in _MARKETS:
                raise ValueError(f"market must be one of {sorted(_MARKETS)}")
            asset_type = str(kwargs.get("asset_type") or "equity").strip().lower()
            if asset_type not in _ASSET_TYPES:
                raise ValueError(f"asset_type must be one of {sorted(_ASSET_TYPES)}")

            symbol = str(kwargs.get("symbol") or "").strip().upper()
            if not symbol:
                raise ValueError("symbol is required")

            external_ref = str(kwargs.get("external_ref") or "").strip()
            if not external_ref:
                raise ValueError("external_ref is required for idempotent virtual fills")

            store = PortfolioStore()
            portfolio = _resolve_portfolio(store, str(kwargs.get("portfolio") or ""))
            transaction = store.add_transaction(
                _SCOPE,
                portfolio.id,
                {
                    "type": side,
                    "asset_type": asset_type,
                    "symbol": symbol,
                    "market": market,
                    "quantity": quantity,
                    "price": price,
                    "currency": str(kwargs.get("currency") or "CNY").strip().upper(),
                    "fee": kwargs.get("fee", 0),
                    "tax": kwargs.get("tax", 0),
                    "trade_at": str(kwargs.get("trade_at") or datetime.now(timezone.utc).isoformat()),
                    "external_ref": external_ref,
                    "note": kwargs.get("note"),
                },
            )
            return json.dumps(
                {
                    "status": "ok",
                    "mode": "virtual",
                    "portfolio": {
                        "id": portfolio.id,
                        "name": portfolio.name,
                        "base_currency": portfolio.base_currency,
                    },
                    "transaction": transaction.to_dict(),
                },
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001 - tools return structured errors
            return json.dumps(
                {"status": "error", "mode": "virtual", "error": str(exc)},
                ensure_ascii=False,
            )
