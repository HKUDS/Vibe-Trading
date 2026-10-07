"""MT5 connector facade — the module ``service._sdk_module("mt5")`` imports.

Re-exports the full duck-typed ``broker_sdk`` surface from the split
implementation modules (kept under the repo's file-size ceiling). Tests
monkeypatch one seam — ``_client._require_mt5`` — and the whole connector
runs against the injected fake.
"""

from __future__ import annotations

from src.trading.connectors.mt5._client import (
    CONFIG_FILENAME,
    GUARD_MARKER,
    PROFILE_ENVIRONMENTS,
    MT5Config,
    MT5ConfigError,
    MT5ConnectionError,
    MT5DependencyError,
    MT5ProfileMismatchError,
    build_config,
    config_path,
    load_config,
    mt5_available,
    save_config,
)
from src.trading.connectors.mt5.orders import (
    cancel_order,
    close_position,
    place_order,
    quantity_notional_usd,
)
from src.trading.connectors.mt5.reads import (
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
    "MT5Config",
    "MT5ConfigError",
    "MT5ConnectionError",
    "MT5DependencyError",
    "MT5ProfileMismatchError",
    "build_config",
    "config_path",
    "load_config",
    "mt5_available",
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
