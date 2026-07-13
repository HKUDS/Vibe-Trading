"""ICICI Direct Breeze connector profile (read-only)."""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

ICICI_BREEZE_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="icici-breeze-live-sdk-readonly",
        connector="icici_breeze",
        label="ICICI Direct Breeze · Live Read-Only",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads ICICI Direct funds, Demat holdings, open positions, "
            "orders, quotes, and historical bars through the official "
            "Breeze SDK. Order placement and cancellation are not exposed."
        ),
    ),
)
