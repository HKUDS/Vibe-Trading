"""Auto-discovery for built-in channel modules and external plugins."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from collections.abc import Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_INTERNAL = frozenset({"base", "bus", "config", "manager", "pairing", "registry", "runtime", "utils"})

_INSTALL_HINTS: dict[str, str] = {
    "dingtalk": "pip install 'vibe-trading-ai[dingtalk]'",
    "discord": "pip install 'vibe-trading-ai[discord]'",
    "email": "No extra Python package required; configure channels.email in the agent config.",
    "feishu": "pip install 'vibe-trading-ai[feishu]'",
    "matrix": "pip install 'vibe-trading-ai[matrix]'",
    "mochat": "pip install 'vibe-trading-ai[mochat]'",
    "msteams": "pip install 'vibe-trading-ai[msteams]'",
    "napcat": "pip install 'vibe-trading-ai[napcat]'",
    "qq": "pip install 'vibe-trading-ai[qq]'",
    "signal": "No extra Python package required; install and run signal-cli-rest-api separately.",
    "slack": "pip install 'vibe-trading-ai[slack]'",
    "telegram": "pip install 'vibe-trading-ai[telegram]'",
    "wecom": "pip install 'vibe-trading-ai[wecom]'",
    "weixin": "No extra Python package required; configure channels.weixin in the agent config.",
    "whatsapp": "pip install 'vibe-trading-ai[whatsapp]'",
    "websocket": "pip install 'vibe-trading-ai[channels]'",
}

_AVAILABILITY_FLAGS: dict[str, tuple[str, ...]] = {
    "dingtalk": ("DINGTALK_AVAILABLE",),
    "discord": ("DISCORD_AVAILABLE",),
    "feishu": ("FEISHU_AVAILABLE",),
    "msteams": ("MSTEAMS_AVAILABLE",),
    "qq": ("QQ_AVAILABLE",),
    "wecom": ("WECOM_AVAILABLE",),
}

_LAZY_IMPORT_PACKAGES: dict[str, tuple[str, ...]] = {
    "whatsapp": ("neonize",),
}


@dataclass(frozen=True)
class ChannelAvailability:
    """Import-time availability for a channel adapter."""

    name: str
    available: bool
    display_name: str
    error: str = ""
    install_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable availability payload."""
        return {
            "name": self.name,
            "available": self.available,
            "display_name": self.display_name,
            "error": self.error,
            "install_hint": self.install_hint,
        }


def discover_channel_names() -> list[str]:
    """Return all built-in channel module names by scanning the package (zero imports)."""
    import src.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]


def _channel_class_from_module(module: ModuleType, module_name: str) -> type[BaseChannel]:
    """Return the first BaseChannel subclass defined in *module*."""
    from src.channels.base import BaseChannel as _Base

    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in src.channels.{module_name}")


def _missing_optional_dependency(name: str, module: ModuleType) -> str:
    """Return a dependency status error for lazily imported adapter SDKs."""
    for flag in _AVAILABILITY_FLAGS.get(name, ()):
        if getattr(module, flag, True) is False:
            return f"missing optional dependency for {name}"
    missing_packages = [
        package
        for package in _LAZY_IMPORT_PACKAGES.get(name, ())
        if importlib.util.find_spec(package) is None
    ]
    if missing_packages:
        return "missing optional dependency: " + ", ".join(missing_packages)
    return ""


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """Import *module_name* and return the first BaseChannel subclass found."""
    mod = importlib.import_module(f"src.channels.{module_name}")
    return _channel_class_from_module(mod, module_name)


def inspect_channel(name: str) -> ChannelAvailability:
    """Inspect one channel module without raising dependency errors.

    Args:
        name: Built-in or plugin channel name.

    Returns:
        Availability metadata that surfaces install guidance for optional SDKs.
    """
    try:
        mod = importlib.import_module(f"src.channels.{name}")
        cls = _channel_class_from_module(mod, name)
        display = getattr(cls, "display_name", name)
        missing = _missing_optional_dependency(name, mod)
        if missing:
            return ChannelAvailability(
                name=name,
                available=False,
                display_name=str(display),
                error=missing,
                install_hint=_INSTALL_HINTS.get(name, f"pip install 'vibe-trading-ai[{name}]'"),
            )
        return ChannelAvailability(name=name, available=True, display_name=str(display))
    except Exception as exc:  # noqa: BLE001 - status API must report every adapter
        return ChannelAvailability(
            name=name,
            available=False,
            display_name=name.replace("_", " ").title(),
            error=f"{type(exc).__name__}: {exc}",
            install_hint=_INSTALL_HINTS.get(name, f"pip install 'vibe-trading-ai[{name}]'"),
        )


def _section_enabled(section: Any) -> bool:
    if section is None:
        return False
    if isinstance(section, Mapping):
        return bool(section.get("enabled", False))
    return bool(getattr(section, "enabled", False))


def _config_section(config: Any, name: str) -> Any:
    if isinstance(config, Mapping):
        return config.get(name)
    return getattr(config, name, None)


def inspect_channels(config: Any | None = None) -> dict[str, dict[str, Any]]:
    """Inspect all built-in channels and annotate configured/enabled state.

    Args:
        config: Optional channels config map or model. Extra keys are included
            so external plugin configs are visible in status output.

    Returns:
        Mapping from channel name to JSON-serializable status metadata.
    """
    names = set(discover_channel_names())
    if isinstance(config, Mapping):
        names.update(str(key) for key in config.keys())
    elif config is not None:
        names.update(
            key
            for key in dir(config)
            if not key.startswith("_") and key not in {"model_config", "model_fields"}
        )

    statuses: dict[str, dict[str, Any]] = {}
    for name in sorted(names):
        section = _config_section(config, name) if config is not None else None
        availability = inspect_channel(name).to_dict()
        availability.update(
            {
                "configured": section is not None,
                "enabled": _section_enabled(section),
                "loaded": False,
                "running": False,
            }
        )
        statuses[name] = availability
    return statuses


def discover_plugins(
    enabled_names: set[str] | None = None,
) -> dict[str, type[BaseChannel]]:
    """Discover external channel plugins registered via entry_points."""
    from importlib.metadata import entry_points

    plugins: dict[str, type[BaseChannel]] = {}
    for ep in entry_points(group="vibe_trading.channels"):
        if enabled_names is not None and ep.name not in enabled_names:
            continue
        try:
            cls = ep.load()
            plugins[ep.name] = cls
        except Exception:
            logger.warning("Failed to load channel plugin '%s': %s", ep.name, exc_info=True)
    return plugins


def discover_enabled(
    enabled_names: set[str],
    *,
    _names: list[str] | None = None,
    _include_all_external: bool = False,
) -> dict[str, type[BaseChannel]]:
    """Return channels whose module names are in *enabled_names*.

    Uses cheap ``pkgutil.iter_modules`` to list names, then imports only
    those that match — skipping the heavy third-party SDK imports of
    unneeded channels.
    """
    names = _names if _names is not None else discover_channel_names()
    result: dict[str, type[BaseChannel]] = {}
    for modname in names:
        if modname not in enabled_names:
            continue
        try:
            result[modname] = load_channel_class(modname)
        except ImportError:
            logger.debug("Skipping built-in channel '%s': %s", modname, exc_info=True)

    external = discover_plugins(None if _include_all_external else enabled_names)
    shadowed = set(external) & set(result)
    if shadowed:
        logger.warning("Plugin(s) shadowed by built-in channels (ignored): %s", shadowed)
    if _include_all_external:
        result.update({k: v for k, v in external.items() if k not in shadowed})
    else:
        result.update(
            {k: v for k, v in external.items() if k not in shadowed and k in enabled_names}
        )

    return result


def discover_all() -> dict[str, type[BaseChannel]]:
    """Return all channels: built-in (pkgutil) merged with external (entry_points).

    Built-in channels take priority — an external plugin cannot shadow a built-in name.
    """
    names = discover_channel_names()
    return discover_enabled(set(names), _names=names, _include_all_external=True)
