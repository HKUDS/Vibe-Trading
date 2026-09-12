"""Built-in Toss Securities (토스증권) connector profiles.

Toss Invest's Open API (https://developers.tossinvest.com) documents no
sandbox and no runtime paper/live discriminator, and applying for API access
requires a real brokerage account — following the Trading 212 precedent, this
connector is therefore fully read-only: ``place_order``/``cancel_order``
hard-refuse for every profile, paper included.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

TOSS_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="toss-live-sdk-readonly",
        connector="toss",
        label="Toss Securities · REST Read-Only (Korea)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a live Toss Securities account (holdings, order history, "
            "quotes, candles) for KR and US equities. Order placement and "
            "cancellation hard-refuse: Toss documents no sandbox this "
            "connector can verify."
        ),
    ),
)
