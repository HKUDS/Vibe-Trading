"""Built-in Zerodha (Kite Connect) connector profiles.

Zerodha (https://zerodha.com) is India's largest retail broker. Kite Connect
offers historical OHLCV, quotes, positions, and order placement via a clean
REST SDK (``kiteconnect`` on PyPI). Free API access for personal use; equity
delivery is ₹0 brokerage, intraday is 0.03% / ₹20 flat.

Paper-only by design: Kite exposes no sandbox and no runtime paper/live
discriminator — an access token reaches the real account whether the profile is
declared ``paper`` or ``live``. Following the Shoonya/Longbridge precedent, this
connector ships read-only paper/live profiles plus a locally simulated
paper-trade profile, and exposes NO live order placement (see ``sdk.place_order``).
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

ZERODHA_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="zerodha-paper-sdk",
        connector="zerodha",
        label="Zerodha Paper · KiteConnect (India, ₹0 delivery)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads Indian market data (NSE/BSE equities, F&O) via Kite Connect. "
            "Paper vs live is operator-declared (the API exposes no runtime "
            "discriminator). Equity delivery ₹0 brokerage; intraday 0.03%/₹20 flat. "
            "Historical data capped at 2000 days/request (connector paginates)."
        ),
    ),
    TradingProfile(
        id="zerodha-paper-trade",
        connector="zerodha",
        label="Zerodha Paper · KiteConnect Trade (India)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Places PAPER orders simulated locally using real Zerodha market "
            "data — no real money at risk. Paper-only by design: Kite exposes no "
            "runtime paper/live discriminator, so live order placement is not "
            "supported."
        ),
    ),
    TradingProfile(
        id="zerodha-live-sdk-readonly",
        connector="zerodha",
        label="Zerodha Live · KiteConnect Read-Only (India)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a live Zerodha account (positions, holdings, orders, quotes, "
            "history). No order placement. Equity delivery ₹0 brokerage."
        ),
    ),
)
