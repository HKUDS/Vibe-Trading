"""Robinhood MCP reply builders, taken from the shapes posted on #1428.

Every builder reproduces the adapter envelope ``MCPServerAdapter.call_tool``
returns around a Robinhood reply: the broker payload ``{"data": ..., "guide":
...}`` sits under both ``structured_content`` and ``data``. So the records a
test cares about are at ``structured_content.data.<key>``, one level deeper than
the ``data.positions`` the live path used to read (#1442).

Field names and types come from balu1866's posts: observed ``get_accounts`` and
``get_portfolio`` replies (2026-09-14) and the advertised
``get_equity_positions`` ``outputSchema`` (2026-09-16). Values are invented.
"""

from __future__ import annotations

from typing import Any

#: Required ``get_equity_positions`` item fields other than symbol / quantity / type.
_POSITION_SHARE_FIELDS = (
    "intraday_quantity",
    "shares_available_for_sells",
    "shares_held_for_sells",
    "shares_held_for_stock_grants",
    "shares_held_for_options_events",
    "shares_held_for_asset_transfer",
    "shares_pending_from_options_events",
)


def envelope(tool: str, data: Any, *, guide: str = "Values are strings.") -> dict[str, Any]:
    """Wrap a broker ``data`` object the way the MCP adapter returns it."""
    structured = {"data": data, "guide": guide}
    return {
        "status": "ok",
        "data": structured,
        "structured_content": structured,
        "server": "robinhood",
        "remote_tool": tool,
        "tool": tool,
    }


def position(symbol: str, quantity: str, *, average_buy_price: str | None = "100.00") -> dict[str, Any]:
    """Return one ``get_equity_positions`` item with every required field."""
    # The meaning and values of `type` are unobserved, so tests never depend on it.
    row: dict[str, Any] = {"symbol": symbol, "quantity": quantity, "type": "unobserved"}
    row.update({field: "0" for field in _POSITION_SHARE_FIELDS})
    row["shares_available_for_sells"] = quantity
    if average_buy_price is not None:
        row["average_buy_price"] = average_buy_price
    return row


def positions(rows: list[dict[str, Any]] | None, *, next_page: str | None = None) -> dict[str, Any]:
    """Return a ``get_equity_positions`` envelope."""
    data: dict[str, Any] = {"positions": rows}
    if next_page is not None:
        data["next"] = next_page
    return envelope("get_equity_positions", data)


def portfolio(
    *,
    total_value: str = "5000.00",
    cash: str = "5000.00",
    buying_power: str = "5000.00",
    currency: str = "USD",
    **values: str,
) -> dict[str, Any]:
    """Return a ``get_portfolio`` envelope; non-equity values default to zero."""
    data: dict[str, Any] = {
        "total_value": total_value,
        "equity_value": "0.00",
        "options_value": "0.00",
        "futures_value": "0.00",
        "event_contracts_value": "0.00",
        "crypto_value": "0.00",
        "cash": cash,
        "pending_deposits": "0.00",
        "mutual_funds_value": "0.00",
        "fixed_income_value": "0.00",
        "currency": currency,
        "buying_power": {
            "buying_power": buying_power,
            "unleveraged_buying_power": buying_power,
            "display_currency": currency,
        },
        "crypto_buying_power": {"buying_power": "0.00"},
    }
    data.update(values)
    return envelope("get_portfolio", data)


def account(
    number: str,
    *,
    nickname: str | None = None,
    is_default: bool = False,
    agentic_allowed: bool = True,
    deactivated: bool = False,
) -> dict[str, Any]:
    """Return one ``get_accounts`` item."""
    row: dict[str, Any] = {
        "account_number": number,
        "affiliate": "rhf",
        "agentic_allowed": agentic_allowed,
        "brokerage_account_type": "individual",
        "deactivated": deactivated,
        "is_default": is_default,
        "management_type": "self_directed",
        "option_level": "option_level_2",
        "permanently_deactivated": False,
        "rhs_account_number": f"rhs-{number}",
        "state": "active",
        "type": "cash",
        "unsettled_funds": "0.00",
    }
    if nickname is not None:
        row["nickname"] = nickname
    return row


def accounts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a ``get_accounts`` envelope."""
    return envelope("get_accounts", {"accounts": rows})
