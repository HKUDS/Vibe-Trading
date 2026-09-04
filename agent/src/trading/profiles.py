"""Trading connector profile registry and selected-profile storage."""

from __future__ import annotations

import json
from pathlib import Path

from src.config.paths import get_runtime_root
from src.trading.connectors.alpaca.profiles import ALPACA_PROFILES
from src.trading.connectors.binance.profiles import BINANCE_PROFILES
from src.trading.connectors.dhan.profiles import DHAN_PROFILES
from src.trading.connectors.futu.profiles import FUTU_PROFILES
from src.trading.connectors.ibkr.profiles import IBKR_PROFILES
from src.trading.connectors.longbridge.profiles import LONGBRIDGE_PROFILES
from src.trading.connectors.mt5.profiles import MT5_PROFILES
from src.trading.connectors.okx.profiles import OKX_PROFILES
from src.trading.connectors.robinhood.profiles import ROBINHOOD_PROFILES
from src.trading.connectors.shoonya.profiles import SHOONYA_PROFILES
from src.trading.connectors.tiger.profiles import TIGER_PROFILES
from src.trading.connectors.etoro.profiles import ETORO_PROFILES
from src.trading.connectors.trading212.profiles import TRADING212_PROFILES
from src.trading.connectors.zerodha.profiles import ZERODHA_PROFILES
from src.trading.types import TradingProfile

CONFIG_FILENAME = "trading-connections.json"
DEFAULT_PROFILE_ID = "ibkr-paper-local"

BUILTIN_PROFILES: tuple[TradingProfile, ...] = (
    *IBKR_PROFILES,
    *ROBINHOOD_PROFILES,
    *TIGER_PROFILES,
    *LONGBRIDGE_PROFILES,
    *ALPACA_PROFILES,
    *OKX_PROFILES,
    *BINANCE_PROFILES,
    *FUTU_PROFILES,
    *DHAN_PROFILES,
    *SHOONYA_PROFILES,
    *TRADING212_PROFILES,
    *MT5_PROFILES,
    *ETORO_PROFILES,
    *ZERODHA_PROFILES,
)


def config_path() -> Path:
    """Return the trading connector config path."""
    return get_runtime_root() / CONFIG_FILENAME


def list_profiles() -> list[TradingProfile]:
    """Return built-in profiles plus operator-installed local read-only plugins.

    Returns:
        The built-in profiles, followed by the profile of every valid plugin
        installed under the user's plugin root. A plugin never shadows a
        built-in profile id, and an invalid manifest is skipped rather than
        breaking the registry.
    """
    from src.trading.local_plugins import discover_plugins

    plugins, _ = discover_plugins()
    built_in_ids = {profile.id for profile in BUILTIN_PROFILES}
    local_profiles = [
        plugin.profile for plugin in plugins if plugin.profile.id not in built_in_ids
    ]
    return [*BUILTIN_PROFILES, *local_profiles]


def profile_by_id(profile_id: str | None = None) -> TradingProfile:
    """Resolve a profile id or the saved selected profile.

    Args:
        profile_id: Optional explicit profile id.

    Returns:
        Matching profile.

    Raises:
        ValueError: If the profile id is unknown.
    """
    target = (profile_id or load_selected_profile_id()).strip().lower()
    for profile in list_profiles():
        if profile.id == target:
            return profile
    raise ValueError(f"unknown trading connector profile: {target}")


def load_selected_profile_id() -> str:
    """Load the selected trading profile id."""
    path = config_path()
    if not path.exists():
        return DEFAULT_PROFILE_ID
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PROFILE_ID
    selected = str(payload.get("selected_profile") or DEFAULT_PROFILE_ID).strip().lower()
    return selected or DEFAULT_PROFILE_ID


def save_selected_profile_id(profile_id: str) -> Path:
    """Persist the selected trading profile id."""
    profile = profile_by_id(profile_id)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"selected_profile": profile.id}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
