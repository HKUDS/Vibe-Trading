"""Pure portfolio accounting using Decimal arithmetic."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .models import PortfolioTransaction

ZERO = Decimal("0")


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None or value == "":
        return default
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _quote_key(market: str | None, symbol: str | None, currency: str | None = None) -> str:
    base = f"{(market or '').lower()}:{(symbol or '').upper()}"
    return f"{base}:{currency.upper()}" if currency else base


def calculate_snapshot(
    transactions: Iterable[PortfolioTransaction],
    quotes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate cash, positions, and P&L from an immutable transaction stream.

    ``quotes`` is keyed by ``"market:SYMBOL"`` and may contain ``price``,
    ``name``, ``source``, ``updated_at`` and ``status``. Missing quotes never
    remove a holding; they only make its market value unavailable.
    """
    quote_map = quotes or {}
    materialized = list(transactions)
    reversed_ids = {item.id for item in materialized if item.reversed_transaction_id}
    reversed_ids.update(item.reversed_transaction_id for item in materialized if item.reversed_transaction_id)
    ordered = sorted(
        (item for item in materialized if item.id not in reversed_ids),
        key=lambda item: (item.trade_at, item.created_at, item.id),
    )
    positions: dict[tuple[str, str, str], dict[str, Decimal | str]] = {}
    cash: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    currencies = {item.currency.upper() for item in materialized if item.currency}
    net_contributed: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    realized: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    dividends: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    fees: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    taxes: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    other_expenses: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)

    for tx in ordered:
        currency = tx.currency.upper()
        qty = tx.quantity or ZERO
        price = tx.price or ZERO
        amount = tx.amount or ZERO
        fee = tx.fee or ZERO
        tax = tx.tax or ZERO
        fees[currency] += fee
        taxes[currency] += tax

        if tx.type == "deposit":
            cash[currency] += amount - fee - tax
            net_contributed[currency] += amount
            other_expenses[currency] += fee + tax
        elif tx.type == "withdrawal":
            cash[currency] -= amount + fee + tax
            net_contributed[currency] -= amount
            other_expenses[currency] += fee + tax
        elif tx.type == "fee":
            cash[currency] -= amount + fee + tax
            fees[currency] += amount
            other_expenses[currency] += amount + fee + tax
        elif tx.type == "dividend":
            cash[currency] += amount - fee - tax
            dividends[currency] += amount
            other_expenses[currency] += fee + tax
        elif tx.type in {"buy", "sell", "adjustment"}:
            if not tx.symbol or not tx.market:
                continue
            key = (tx.market.lower(), tx.symbol.upper(), currency)
            position = positions.setdefault(
                key,
                {"quantity": ZERO, "cost_basis": ZERO, "realized_pnl": ZERO, "asset_type": tx.asset_type},
            )
            current_qty = _decimal(position["quantity"])
            current_cost = _decimal(position["cost_basis"])
            avg_cost = current_cost / current_qty if current_qty else ZERO

            if tx.type == "buy":
                gross = qty * price
                position["quantity"] = current_qty + qty
                position["cost_basis"] = current_cost + gross + fee + tax
                cash[currency] -= gross + fee + tax
            elif tx.type == "sell":
                proceeds = qty * price
                realized[currency] += proceeds - qty * avg_cost - fee - tax
                position["realized_pnl"] = _decimal(position["realized_pnl"]) + proceeds - qty * avg_cost - fee - tax
                position["quantity"] = current_qty - qty
                position["cost_basis"] = max(ZERO, current_cost - qty * avg_cost)
                cash[currency] += proceeds - fee - tax
            else:
                # Adjustment quantity is signed. A positive adjustment uses the
                # supplied amount as cost; a negative one removes average cost.
                if qty >= ZERO:
                    position["quantity"] = current_qty + qty
                    position["cost_basis"] = current_cost + (amount if amount > ZERO else qty * price)
                else:
                    removed = min(current_qty, abs(qty))
                    position["quantity"] = current_qty - removed
                    position["cost_basis"] = max(ZERO, current_cost - removed * avg_cost)

            if _decimal(position["quantity"]) <= ZERO:
                positions.pop(key, None)

    holdings: list[dict[str, Any]] = []
    for (market, symbol, currency), position in positions.items():
        quantity = _decimal(position["quantity"])
        cost_basis = _decimal(position["cost_basis"])
        avg_cost = cost_basis / quantity if quantity else ZERO
        quote = quote_map.get(_quote_key(market, symbol, currency), quote_map.get(_quote_key(market, symbol), {}))
        raw_price = quote.get("price") if isinstance(quote, Mapping) else None
        latest_price = _decimal(raw_price) if raw_price is not None else None
        market_value = latest_price * quantity if latest_price is not None else None
        unrealized = market_value - cost_basis if market_value is not None else None
        change_pct = _decimal(quote.get("change_pct")) if isinstance(quote, Mapping) and quote.get("change_pct") is not None else None
        daily_pnl = market_value * change_pct / (Decimal("100") + change_pct) if market_value is not None and change_pct is not None and change_pct != Decimal("-100") else None
        holdings.append({
            "symbol": symbol,
            "market": market,
            "asset_type": position.get("asset_type", "equity"),
            "currency": currency,
            "name": quote.get("name") or symbol,
            "quantity": format(quantity, "f"),
            "avg_cost": format(avg_cost, "f"),
            "cost_basis": format(cost_basis, "f"),
            "latest_price": format(latest_price, "f") if latest_price is not None else None,
            "market_value": format(market_value, "f") if market_value is not None else None,
            "unrealized_pnl": format(unrealized, "f") if unrealized is not None else None,
            "unrealized_pnl_pct": format(unrealized / cost_basis * 100, "f") if unrealized is not None and cost_basis else None,
            "daily_pnl": format(daily_pnl, "f") if daily_pnl is not None else None,
            "change_pct": format(change_pct, "f") if change_pct is not None else None,
            "price_status": quote.get("status", "unavailable") if isinstance(quote, Mapping) else "unavailable",
            "price_source": quote.get("source") if isinstance(quote, Mapping) else None,
            "price_updated_at": quote.get("updated_at") if isinstance(quote, Mapping) else None,
        })

    by_currency: dict[str, dict[str, Any]] = {}
    for currency in sorted(currencies | set(cash) | set(net_contributed) | {item["currency"] for item in holdings}):
        rows = [item for item in holdings if item["currency"] == currency]
        valued = [Decimal(item["market_value"]) for item in rows if item["market_value"] is not None]
        total_market_value = sum(valued, ZERO)
        current_realized = realized[currency]
        current_dividends = dividends[currency]
        current_fees = fees[currency]
        current_taxes = taxes[currency]
        current_unrealized = sum((Decimal(item["unrealized_pnl"]) for item in rows if item["unrealized_pnl"] is not None), ZERO)
        current_daily = sum((Decimal(item["daily_pnl"]) for item in rows if item["daily_pnl"] is not None), ZERO)
        total_return = current_realized + current_unrealized + current_dividends - other_expenses[currency]
        for item in rows:
            if total_market_value:
                item["weight"] = format(Decimal(item["market_value"] or "0") / total_market_value * 100, "f")
            else:
                item["weight"] = "0"
        total_assets = cash[currency] + total_market_value
        by_currency[currency] = {
            "currency": currency,
            "cash": format(cash[currency], "f"),
            "holdings_value": format(total_market_value, "f"),
            "total_assets": format(total_assets, "f"),
            "net_contributed": format(net_contributed[currency], "f"),
            "realized_pnl": format(current_realized, "f"),
            "unrealized_pnl": format(current_unrealized, "f"),
            "daily_pnl": format(current_daily, "f"),
            "dividends": format(current_dividends, "f"),
            "fees": format(current_fees, "f"),
            "taxes": format(current_taxes, "f"),
            "total_return": format(total_return, "f"),
            "return_pct": format(total_return / net_contributed[currency] * 100, "f") if net_contributed[currency] else None,
            "holdings_count": len(rows),
        }

    return {
        "currencies": by_currency,
        "holdings": sorted(holdings, key=lambda item: (item["currency"], item["market"], item["symbol"])),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
