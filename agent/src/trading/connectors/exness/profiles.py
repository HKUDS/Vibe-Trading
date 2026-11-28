"""Built-in Exness Trader API connector profiles.

Live-only by design (Robinhood/Scalable precedent): the Exness Trader API has
no paper environment and no runtime demo/real discriminator, so there is no
paper profile whose permission could leak into a real-money account. Every
account is treated as real money: the trade profile declares
``orders.place.requires_mandate``, so each order passes the live mandate gate
and kill switch even when the key happens to target a demo account.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

EXNESS_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="exness-live-api-readonly",
        connector="exness",
        label="Exness Live · Trader API Read-Only",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads an Exness account through the hosted Trader API (API key + Ed25519 "
            "request signing; no MT5 terminal, any OS). Account, positions, orders, "
            "deals, candles and an M1-candle quote. Forex/metals/crypto CFDs only — "
            "stocks and indices are not offered by the API. No order placement."
        ),
    ),
    TradingProfile(
        id="exness-live-api-trade",
        connector="exness",
        label="Exness Live · Trader API Trading",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place.requires_mandate",),
        readonly=False,
        config={"profile": "live"},
        notes=(
            "Places orders through the Exness Trader API. The API exposes no demo/real "
            "discriminator, so every account is treated as REAL money: orders are gated "
            "behind the live mandate (forex/cfd allowances, lot-aware USD notional caps) "
            "and the kill switch, plus connector size guards. Orders are asynchronous "
            "(an unconfirmed acceptance reports order_state=pending). Hedging accounts "
            "OPEN a hedge on an opposite-side order; close positions by id via cancel."
        ),
    ),
)
