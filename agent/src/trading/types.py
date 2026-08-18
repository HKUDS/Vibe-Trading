"""Shared trading connector data types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Environment = Literal["paper", "live"]
Transport = Literal["local_tws", "remote_mcp", "broker_sdk"]

READ_CAPABILITIES = (
    "account.read",
    "positions.read",
    "orders.read",
    "quotes.read",
    "history.read",
)

# Capability strings for connector-specific extended read endpoints that are
# exposed by some connectors (Futu today; could be added to others later) but
# not by the shared broker_sdk baseline. Connnectors that implement any of
# these should append them — never ``READ_CAPABILITIES`` — to the profile's
# ``capabilities`` tuple. Service-layer wrappers fall back to a clean
# "unsupported" response when the capability is missing, so omitting them
# from ``READ_CAPABILITIES`` keeps the capability list honest.
FUTU_EXTENDED_READ_CAPABILITIES = (
    "rehab.read",
    "capital_flow.read",
    "capital_distribution.read",
    "history_deals.read",
    "acc_cash_flow.read",
    "financials.read",
    "earnings_calendar.read",
)


@dataclass(frozen=True)
class TradingProfile:
    """A user-selectable trading connector profile.

    Args:
        id: Stable profile id used by CLI/tools.
        connector: Broker/connector key, e.g. ``ibkr`` or ``robinhood``.
        label: Human-readable display label.
        environment: Paper or live account environment.
        transport: How Vibe-Trading reaches the connector.
        capabilities: Capability strings exposed by this profile.
        readonly: Whether every operation in this profile is read-only.
        config: Connector-specific defaults.
        notes: User-facing caveats.
    """

    id: str
    connector: str
    label: str
    environment: Environment
    transport: Transport
    capabilities: tuple[str, ...]
    readonly: bool
    config: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self, *, selected: bool = False) -> dict[str, Any]:
        """Return a JSON-serializable profile snapshot."""
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        payload["selected"] = selected
        return payload

