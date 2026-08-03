"""MCP read-only trading-connector tools.

No order-placing or order-cancelling tool is ever surfaced via MCP; every
trading_* tool here is a read-only account / position / order / quote / history
query scoped to a selected connector profile.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from src.mcp_tools._shared import get_registry


def _trading_common_args(
    *,
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Build shared optional trading connector arguments."""
    payload: dict[str, Any] = {}
    if connection:
        payload["connection"] = connection
    if host:
        payload["host"] = host
    if port is not None:
        payload["port"] = port
    if client_id is not None:
        payload["client_id"] = client_id
    if account:
        payload["account"] = account
    return payload


def trading_connections() -> str:
    """List selectable trading connector profiles.

    The connector is the first-level choice. Paper/live is an attribute of each
    profile under that connector.
    """
    registry = get_registry()
    return registry.execute("trading_connections", {})


def trading_select_connection(connection: str) -> str:
    """Select the default trading connector profile for later trading_* calls.

    Args:
        connection: Profile id, e.g. ``ibkr-paper-local`` or ``robinhood-live-mcp``.
    """
    registry = get_registry()
    return registry.execute("trading_select_connection", {"connection": connection})


def trading_check(
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> str:
    """Check whether a trading connector profile is configured and reachable.

    This never places orders. For local profiles, it checks the user's local
    app/socket. For remote MCP profiles, it reports config and OAuth-token
    presence without returning secrets.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
    """
    registry = get_registry()
    return registry.execute(
        "trading_check",
        _trading_common_args(connection=connection, host=host, port=port, client_id=client_id, account=account),
    )


def trading_account(
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> str:
    """Read account data from the selected trading connector profile.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
    """
    registry = get_registry()
    return registry.execute(
        "trading_account",
        _trading_common_args(connection=connection, host=host, port=port, client_id=client_id, account=account),
    )


def trading_positions(
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> str:
    """Read positions from the selected trading connector profile.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
    """
    registry = get_registry()
    return registry.execute(
        "trading_positions",
        _trading_common_args(connection=connection, host=host, port=port, client_id=client_id, account=account),
    )


def trading_orders(
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    include_executions: bool = False,
) -> str:
    """Read open orders from the selected trading connector profile.

    Read-only: this tool does not place, cancel, modify, or replace orders.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
        include_executions: Include recent executions when available.
    """
    params = _trading_common_args(connection=connection, host=host, port=port, client_id=client_id, account=account)
    params["include_executions"] = include_executions
    registry = get_registry()
    return registry.execute("trading_orders", params)


def trading_quote(
    symbol: str,
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
) -> str:
    """Read a quote snapshot from the selected trading connector profile.

    Args:
        symbol: Symbol such as AAPL.
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
        exchange: Exchange routing, default SMART.
        currency: Contract currency, default USD.
        sec_type: Security type, default STK.
    """
    params = _trading_common_args(connection=connection, host=host, port=port, client_id=client_id, account=account)
    params.update({"symbol": symbol, "exchange": exchange, "currency": currency, "sec_type": sec_type})
    registry = get_registry()
    return registry.execute("trading_quote", params)


def trading_history(
    symbol: str,
    connection: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    duration: str = "30 D",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> str:
    """Read historical bars from the selected trading connector profile.

    Args:
        symbol: Symbol such as AAPL.
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
        exchange: Exchange routing, default SMART.
        currency: Contract currency, default USD.
        sec_type: Security type, default STK.
        duration: IBKR duration string, default 30 D.
        bar_size: IBKR bar size, default 1 day.
        what_to_show: Data type, default TRADES.
        use_rth: Use regular trading hours.
    """
    params = _trading_common_args(connection=connection, host=host, port=port, client_id=client_id, account=account)
    params.update(
        {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "sec_type": sec_type,
            "duration": duration,
            "bar_size": bar_size,
            "what_to_show": what_to_show,
            "use_rth": use_rth,
        }
    )
    registry = get_registry()
    return registry.execute("trading_history", params)


def register(mcp: FastMCP) -> None:
    """Register the read-only trading connector tools with the FastMCP instance."""
    mcp.tool()(trading_connections)
    mcp.tool()(trading_select_connection)
    mcp.tool()(trading_check)
    mcp.tool()(trading_account)
    mcp.tool()(trading_positions)
    mcp.tool()(trading_orders)
    mcp.tool()(trading_quote)
    mcp.tool()(trading_history)
