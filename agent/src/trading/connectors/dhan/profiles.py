"""Built-in Dhan connector profiles.

Dhan (https://dhan.co) is an Indian discount broker with free API access.
Supports NSE/BSE equities, F&O (NIFTY/BANKNIFTY options), currency, and
commodity segments.

Paper trading is NOT natively supported by Dhan — the paper profile simulates
trades locally using real market data from Dhan's API. The live profile
connects directly to Dhan's production API for real order placement.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

DHAN_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="dhan-paper-sdk",
        connector="dhan",
        label="Dhan Paper · dhanhq (India)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads real-time Indian market data (NSE/BSE) via Dhan's free API. "
            "Paper trades are simulated locally — Dhan does not provide a sandbox. "
            "Supports equities, F&O (NIFTY/BANKNIFTY options), currency, commodity."
        ),
    ),
    TradingProfile(
        id="dhan-live-sdk-readonly",
        connector="dhan",
        label="Dhan Live · dhanhq Read-Only (India)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a live Dhan account (account, positions, orders, quotes, "
            "history). Order placement is not exposed in this profile."
        ),
    ),
    TradingProfile(
        id="dhan-paper-trade",
        connector="dhan",
        label="Dhan Paper · dhanhq Trade (India)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Paper trades on Indian markets using real Dhan market data. "
            "Orders are simulated locally — no real money at risk. "
            "Supports NSE equities and F&O (NIFTY/BANKNIFTY options)."
        ),
    ),
    TradingProfile(
        id="dhan-live-trade",
        connector="dhan",
        label="Dhan Live · dhanhq Trade (India)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place.requires_mandate",),
        readonly=False,
        config={"profile": "live"},
        notes=(
            "Reads and places orders on a live Dhan account (NSE/BSE). "
            "F&O segment must be enabled on the Dhan account. "
            "Placement on live funds requires an authorized mandate; "
            "the caller enforces it. Brokerage: ₹20/order or plan-based."
        ),
    ),
)
