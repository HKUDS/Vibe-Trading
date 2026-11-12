"""Read-only OpenAlgo REST books; portfolio valuation is not yet mapped."""

from __future__ import annotations

from src.trading.types import TradingProfile

# Funds, holdings and net positions can be read, but OpenAlgo's funds object is
# margin/limit data rather than cash or net liquidation, and holdings overlap
# with delivery net positions. Withhold account.read so portfolio eligibility
# stays false, as for mStock.
OPENALGO_READ_CAPABILITIES = (
    "positions.read",
    "orders.read",
    "quotes.read",
    "history.read",
)

OPENALGO_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="openalgo-live-rest-readonly",
        connector="openalgo",
        label="OpenAlgo · REST Read-Only (India, self-hosted)",
        environment="live",
        transport="broker_sdk",
        capabilities=OPENALGO_READ_CAPABILITIES,
        readonly=True,
        config={"api_version": "v1"},
        notes=(
            "Reads funds, holdings, net positions, orders, trades, quotes and history "
            "from a self-hosted OpenAlgo server with its API key. Every account book "
            "reports whether the server answered from analyzer (sandbox) or live mode. "
            "Funds are margin limits, not net assets; portfolio aggregation is "
            "unavailable. All order operations are disabled."
        ),
    ),
)
