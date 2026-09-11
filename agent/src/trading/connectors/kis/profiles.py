"""Built-in Korea Investment & Securities (KIS) connector profiles.

KIS (https://apiportal.koreainvestment.com) is a Korean broker with free API
access and a REAL structural paper/live discriminator: paper (모의투자) and
live (실전투자) accounts are reached through entirely different hosts, each
with its own OAuth token. Unlike Dhan/Upbit, the paper profile here places
GENUINE orders against KIS's own paper-trading server — not a local
simulation — because the host separation makes that safe.

This initial contribution deliberately ships paper (read + trade) and
live-readonly only, mirroring the Dhan/Shoonya precedent for a first
connector into a new market: no live order placement, even though KIS's host
separation would technically support a mandate-gated live-trade profile like
Alpaca's. Wiring that up would need a new ``AssetClass.KR_EQUITY`` in the
mandate model (``src/live/mandate/model.py``) and is left for a follow-up.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

KIS_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="kis-paper-sdk",
        connector="kis",
        label="KIS Paper · REST (Korea)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads a genuine KIS 모의투자 (paper) account via KIS's own paper "
            "host — a real sandbox, not local simulation."
        ),
    ),
    TradingProfile(
        id="kis-paper-trade",
        connector="kis",
        label="KIS Paper · REST Trade (Korea)",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Places orders against KIS's own 모의투자 (paper) trading server — "
            "a real broker-side sandbox account, not a local simulation. No "
            "real money is at risk; the paper host is structurally separate "
            "from the live host."
        ),
    ),
    TradingProfile(
        id="kis-live-sdk-readonly",
        connector="kis",
        label="KIS Live · REST Read-Only (Korea)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a live KIS account (account, positions, orders, quotes, "
            "history). Order placement is not exposed in this profile."
        ),
    ),
)
