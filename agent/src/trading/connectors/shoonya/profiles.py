"""Built-in Shoonya (Finvasia) connector profiles.

Shoonya (https://shoonya.com) by Finvasia offers ZERO brokerage on all
segments — the cheapest Indian broker for algorithmic trading.

Supports NSE/BSE equities, F&O (NIFTY/BANKNIFTY options), currency, and
commodity. The API uses a TOTP-based login flow (vendor code + TOTP secret
required alongside user/password).

Paper trading is simulated locally — Shoonya has no sandbox.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

SHOONYA_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="shoonya-paper-sdk",
        connector="shoonya",
        label="Shoonya Paper · NorenApi (India, ₹0 brokerage)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads real-time Indian market data (NSE/BSE) via Shoonya's free API. "
            "Paper trades are simulated locally. Zero brokerage on all segments. "
            "Supports equities, F&O (NIFTY/BANKNIFTY options), currency, commodity."
        ),
    ),
    TradingProfile(
        id="shoonya-live-sdk-readonly",
        connector="shoonya",
        label="Shoonya Live · NorenApi Read-Only (India, ₹0 brokerage)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a live Shoonya account (fund limits, positions, orders, "
            "quotes, history). No order placement. Zero brokerage."
        ),
    ),
    TradingProfile(
        id="shoonya-paper-trade",
        connector="shoonya",
        label="Shoonya Paper · NorenApi Trade (India, ₹0 brokerage)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Paper trades on Indian markets using real Shoonya market data. "
            "Orders are simulated locally — no real money at risk. "
            "Zero brokerage. Supports NIFTY/BANKNIFTY options."
        ),
    ),
    TradingProfile(
        id="shoonya-live-trade",
        connector="shoonya",
        label="Shoonya Live · NorenApi Trade (India, ₹0 brokerage)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place.requires_mandate",),
        readonly=False,
        config={"profile": "live"},
        notes=(
            "Reads and places orders on a live Shoonya/Finvasia account. "
            "ZERO brokerage on all segments (equities, F&O, currency, commodity). "
            "Requires TOTP-based login (vendor code + TOTP secret). "
            "Placement on live funds requires an authorized mandate."
        ),
    ),
)
