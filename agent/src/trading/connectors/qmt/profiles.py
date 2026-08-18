"""Generic QMT/MiniQMT connector profiles.

QMT is a terminal/API family rather than a single broker.  The selected
profile supplies the safety intent; ``qmt.json`` supplies the broker-specific
MiniQMT userdata path and account identity.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

QMT_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="qmt-paper-sdk",
        connector="qmt",
        label="QMT Paper / MiniQMT Read-Only",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper", "account_type": "STOCK", "readonly": True},
        notes=(
            "Reads a local MiniQMT paper/simulation account through the generic "
            "XtQuant API. Configure the broker-provided userdata_mini path and "
            "account_id in ~/.vibe-trading/qmt.json."
        ),
    ),
    TradingProfile(
        id="qmt-paper-trade",
        connector="qmt",
        label="QMT Paper / MiniQMT Trading",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper", "account_type": "STOCK", "readonly": False},
        notes=(
            "Places orders on a MiniQMT simulation account through XtQuant. "
            "The connector refuses non-paper profiles before any SDK call."
        ),
    ),
    TradingProfile(
        id="qmt-live-sdk-readonly",
        connector="qmt",
        label="QMT Live / MiniQMT Read-Only",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly", "account_type": "STOCK", "readonly": True},
        notes=(
            "Reads a local MiniQMT live account only. Live order placement is "
            "not exposed until a runtime paper/live identity discriminator is "
            "available from the installed QMT build."
        ),
    ),
)
