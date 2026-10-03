"""Built-in mStock connector profiles.

mStock exposes one production REST host and no paper/sandbox environment, so
there is no runtime paper/live discriminator to protect. Its settled tier is
therefore bounded live under the mandate gate, following the Robinhood,
Scalable, and KIS line. This first cut registers only the read-only Type B
profile; the subsequent HTTP read path will map holdings into the shared
portfolio shape before account data is advertised as usable.
"""

from __future__ import annotations

from src.trading.types import TradingProfile

#: Only the two capabilities required for portfolio-connection eligibility.
#: Order discovery/history and market data deliberately wait for their HTTP
#: read mapping in a reviewed follow-up; no order-path capability is declared.
MSTOCK_READ_CAPABILITIES = ("account.read", "positions.read")

MSTOCK_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="mstock-live-rest-readonly",
        connector="mstock",
        label="mStock Live · REST Read-Only (India)",
        environment="live",
        transport="broker_sdk",
        capabilities=MSTOCK_READ_CAPABILITIES,
        readonly=True,
        config={"auth_flavor": "typeb"},
        notes=(
            "Registry-only first cut for mStock's production Type B REST API; "
            "no credentials are stored here and the HTTP read mapper is a "
            "follow-up. This profile exposes no order path."
        ),
    ),
)
