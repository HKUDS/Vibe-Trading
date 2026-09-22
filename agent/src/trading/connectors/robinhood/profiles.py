"""Built-in Robinhood connector profiles."""

from __future__ import annotations

from src.trading.types import TradingProfile

ROBINHOOD_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="robinhood-live-mcp",
        connector="robinhood",
        label="Robinhood Live · Agentic MCP",
        environment="live",
        transport="remote_mcp",
        capabilities=(
            "account.read",
            "positions.read",
            "orders.read",
            "quotes.read",
            "orders.place.requires_mandate",
            "runner.manage.requires_mandate",
        ),
        readonly=False,
        config={"server": "robinhood", "account_selection": "required"},
        notes="Reads via Robinhood MCP; execution stays behind OAuth, mandate, guard, audit, and halt.",
    ),
    # The portfolio view of the same MCP server and OAuth grant. It declares no
    # quotes.read: the get_equity_quotes reply shape has not been observed, so
    # positions are listed unpriced rather than priced off a guessed field.
    TradingProfile(
        id="robinhood-live-mcp-readonly",
        connector="robinhood",
        label="Robinhood Live · Agentic MCP Read-Only",
        environment="live",
        transport="remote_mcp",
        capabilities=("account.read", "positions.read"),
        readonly=True,
        config={"server": "robinhood", "account_selection": "required"},
        notes=(
            "Reads get_portfolio and get_equity_positions for one selected account. "
            "Positions are unpriced until the quote reply is mapped; an account holding "
            "options, crypto, futures, event contracts, mutual funds or fixed income is "
            "reported as an error instead of an equity-only view."
        ),
    ),
)

