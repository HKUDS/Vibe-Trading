"""Exness connector facade — the module ``service._sdk_module("exness")`` imports.

Re-exports the duck-typed ``broker_sdk`` surface from the split implementation
modules. Tests inject one seam — ``_client.set_client_factory`` — and the whole
connector runs against a fake transport.
"""

from __future__ import annotations

from src.trading.connectors.exness._client import (
    CONFIG_FILENAME,
    GUARD_MARKER,
    PROFILE_ENVIRONMENTS,
    ExnessAPIError,
    ExnessConfig,
    ExnessConfigError,
    _OVERRIDE_KEYS,
    build_config,
    config_path,
    credential_source,
    load_config,
    public_config,
    save_config,
)
from src.trading.connectors.exness.orders import (
    cancel_order,
    close_position,
    place_order,
    quantity_notional_usd,
)
from src.trading.connectors.exness.reads import (
    check_status,
    get_account_snapshot,
    get_historical_bars,
    get_open_orders,
    get_positions,
    get_quote,
    search_instruments,
)

__all__ = [
    "CONFIG_FILENAME",
    "GUARD_MARKER",
    "PROFILE_ENVIRONMENTS",
    "ExnessAPIError",
    "ExnessConfig",
    "ExnessConfigError",
    "_OVERRIDE_KEYS",
    "build_config",
    "config_path",
    "credential_source",
    "load_config",
    "public_config",
    "save_config",
    "cancel_order",
    "close_position",
    "place_order",
    "quantity_notional_usd",
    "check_status",
    "get_account_snapshot",
    "get_historical_bars",
    "get_open_orders",
    "get_positions",
    "get_quote",
    "search_instruments",
]
