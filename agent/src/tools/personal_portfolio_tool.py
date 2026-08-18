"""Read-only Agent access to the personal portfolio ledger."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.portfolio.calculator import calculate_snapshot
from src.portfolio.store import PortfolioStore


_DEFAULT_SCOPE = "shared-key-holder"


class GetPersonalPortfolioTool(BaseTool):
    name = "get_personal_portfolio"
    description = "Read the user's personal portfolio summary and current holdings. This tool is read-only and never changes ledger entries."
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_id": {"type": "string", "description": "Portfolio id, or 'all' for all active portfolios."},
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            scope = _DEFAULT_SCOPE
            portfolio_id = str(kwargs.get("portfolio_id") or "all")
            store = PortfolioStore()
            transactions = store.all_transactions(scope, portfolio_id)
            quotes: dict[str, dict[str, Any]] = {}
            if transactions:
                try:
                    from src.api.portfolio_routes import _fetch_quotes

                    seeds = [
                        {
                            "market": tx.market,
                            "symbol": tx.symbol,
                            "asset_type": tx.asset_type,
                            "quote_symbol": "GC=F" if tx.market == "commodity" and tx.symbol in {"XAUUSD", "XAU", "GOLD"} else tx.symbol,
                        }
                        for tx in transactions
                        if tx.symbol and tx.market and tx.type in {"buy", "adjustment"}
                    ]
                    quotes = _fetch_quotes(seeds)
                except Exception:
                    # A quote outage must not hide the ledger or its cost basis.
                    quotes = {}
            snapshot = calculate_snapshot(transactions, quotes)
            snapshot["portfolio_id"] = portfolio_id
            snapshot["portfolios"] = [
                {"id": item.id, "name": item.name, "base_currency": item.base_currency}
                for item in store.list_portfolios(scope)
            ]
            return json.dumps({"status": "ok", "data": snapshot}, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


class GetPortfolioTransactionsTool(BaseTool):
    name = "get_portfolio_transactions"
    description = "Read personal portfolio transaction history. This tool is read-only and cannot add, edit, or delete transactions."
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_id": {"type": "string", "description": "Portfolio id."},
            "symbol": {"type": "string"},
            "type": {"type": "string", "enum": ["buy", "sell", "fee", "dividend", "deposit", "withdrawal", "adjustment"]},
        },
        "required": ["portfolio_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            scope = _DEFAULT_SCOPE
            portfolio_id = str(kwargs["portfolio_id"])
            items = PortfolioStore().list_transactions(scope, portfolio_id, symbol=kwargs.get("symbol"), type=kwargs.get("type"))
            return json.dumps({"status": "ok", "items": [item.to_dict() for item in items]}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
