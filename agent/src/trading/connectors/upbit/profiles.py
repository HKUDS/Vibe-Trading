"""Built-in Upbit connector profiles.

Upbit (https://upbit.com) is Korea's largest KRW crypto exchange with free
API access.

Paper-only by design: Upbit exposes no sandbox and no runtime paper/live
discriminator — a single Access/Secret Key pair reads the same account
whether the profile is declared ``paper`` or ``live``. Following the
Dhan/Longbridge precedent, this connector therefore ships a read-only live
profile plus a locally simulated paper-trade profile, and exposes NO live
order placement. Paper vs live is operator-declared (config-trust); the
connector's order path is structurally capped at paper (see
``sdk.place_order``).
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

UPBIT_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="upbit-paper-sdk",
        connector="upbit",
        label="Upbit Paper · REST (Korea)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads real-time KRW crypto market data via Upbit's free public "
            "API. Paper vs live is operator-declared (the API exposes no "
            "runtime discriminator)."
        ),
    ),
    TradingProfile(
        id="upbit-paper-trade",
        connector="upbit",
        label="Upbit Paper · REST Trade (Korea)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Places PAPER orders simulated locally using a live Upbit quote "
            "— no real money at risk. Paper-only by design: Upbit exposes no "
            "runtime paper/live discriminator, so live order placement is "
            "not supported."
        ),
    ),
    TradingProfile(
        id="upbit-live-sdk-readonly",
        connector="upbit",
        label="Upbit Live · REST Read-Only (Korea)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a live Upbit account (account, positions, orders, quotes, "
            "history). Order placement is not exposed in this profile."
        ),
    ),
)
