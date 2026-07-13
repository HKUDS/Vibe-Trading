"""ICICI Direct Breeze connector profiles."""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

ICICI_BREEZE_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="icici-breeze-paper-trade",
        connector="icici_breeze",
        label="ICICI Direct Breeze · Local Paper Trading",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={
            "profile": "paper",
            "paper_starting_cash": 100000.0,
        },
        notes=(
            "Uses live Breeze quotations but stores every order, fill, "
            "position, and cash movement only in a local paper ledger. "
            "No Breeze place_order or cancel_order method is called."
        ),
    ),
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
