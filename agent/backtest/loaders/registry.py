"""Loader registry with market-level fallback chains.

Loaders self-register via the ``@register`` decorator when their module is
first imported.  The ``_ensure_registered()`` helper lazily imports every
known loader module so that callers of ``resolve_loader`` /
``get_loader_cls_with_fallback`` never see an empty registry — regardless
of import order.
"""

from __future__ import annotations

import logging
from typing import Any, Type

from backtest.loaders.base import NoAvailableSourceError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global registry: source_name -> loader class
# ---------------------------------------------------------------------------

LOADER_REGISTRY: dict[str, Type[Any]] = {}

_registered = False

# Canonical set of accepted data-source names: every registered loader plus the
# ``"auto"`` cross-market selector. Single source of truth shared by the backtest
# config schema (``backtest.runner.BacktestConfigSchema``) and the agent-facing
# backtest tool (``src.tools.backtest_tool``) so the two can never drift apart.
# Keep in sync with ``_loader_modules`` below — the regression test
# ``test_valid_sources_covers_all_registered_loaders`` enforces full coverage.
VALID_SOURCES: set[str] = {
    "tushare",
    "okx",
    "yfinance",
    "akshare",
    "baostock",
    "tencent",
    "mootdx",
    "ccxt",
    "futu",
    "auto",
}


def register(cls: Type[Any]) -> Type[Any]:
    """Class decorator: register a loader into the global registry.

    The class must have a ``name`` class attribute.
    """
    LOADER_REGISTRY[cls.name] = cls
    return cls


def _ensure_registered() -> None:
    """Import every known loader module so ``@register`` decorators fire.

    Safe to call multiple times — only runs the imports once.
    Loaders whose dependencies are missing (e.g. ``akshare`` not installed)
    are silently skipped.
    """
    global _registered
    if _registered:
        return
    _registered = True

    _loader_modules = [
        "backtest.loaders.tushare",
        "backtest.loaders.okx",
        "backtest.loaders.yfinance_loader",
        "backtest.loaders.akshare_loader",
        "backtest.loaders.baostock_loader",
        "backtest.loaders.tencent_loader",
        "backtest.loaders.mootdx_loader",
        "backtest.loaders.ccxt_loader",
        "backtest.loaders.futu",
    ]
    import importlib
    for mod in _loader_modules:
        try:
            importlib.import_module(mod)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Fallback chains: market_type -> ordered list of source names
# ---------------------------------------------------------------------------

FALLBACK_CHAINS: dict[str, list[str]] = {
    "a_share":   ["tushare", "mootdx", "baostock", "tencent", "akshare"],
    "us_equity": ["yfinance", "akshare"],
    "hk_equity": ["yfinance", "futu", "akshare"],
    "crypto":    ["okx", "ccxt", "yfinance"],
    "futures":   ["tushare", "akshare"],
    "fund":      ["tushare", "akshare"],
    "macro":     ["akshare", "tushare"],
    "forex":     ["akshare", "yfinance"],
}


def resolve_loader(market: str) -> Any:
    """Return the first *available* loader instance for *market*.

    Walks the fallback chain and returns the first loader whose
    ``is_available()`` returns ``True``.

    Args:
        market: Market type key (e.g. ``"a_share"``, ``"crypto"``).

    Returns:
        A loader instance.

    Raises:
        NoAvailableSourceError: If every candidate is unavailable.
    """
    _ensure_registered()
    chain = FALLBACK_CHAINS.get(market, [])
    tried: list[str] = []
    for name in chain:
        if name not in LOADER_REGISTRY:
            continue
        tried.append(name)
        # Issue #50 — some loaders (e.g. Tushare) call into the SDK during
        # __init__ and raise on missing credentials. Treat that the same as
        # is_available()=False so the fallback chain keeps walking.
        try:
            loader = LOADER_REGISTRY[name]()
        except Exception as exc:
            logger.debug("loader %s failed to construct: %s", name, exc)
            continue
        if loader.is_available():
            return loader
    raise NoAvailableSourceError(
        f"No available data source for market '{market}'. "
        f"Tried: {tried or chain}. Check network and API token config."
    )


def get_loader_cls_with_fallback(source: str) -> Type[Any]:
    """Return a loader *class* for *source*, falling back if unavailable.

    Args:
        source: Requested data source name.

    Returns:
        A DataLoader class (not instance).

    Raises:
        NoAvailableSourceError: If the source and all fallbacks are unavailable.
    """
    _ensure_registered()
    if source not in LOADER_REGISTRY:
        raise NoAvailableSourceError(f"Unknown data source: {source}")

    loader_cls = LOADER_REGISTRY[source]
    try:
        instance = loader_cls()
    except Exception as exc:
        logger.debug("loader %s failed to construct: %s", source, exc)
        instance = None
    if instance is not None and instance.is_available():
        return loader_cls

    # Source unavailable — try same-market fallback
    for market in loader_cls.markets:
        try:
            fallback = resolve_loader(market)
            logger.warning(
                "%s is unavailable, falling back to %s for market %s",
                source, fallback.name, market,
            )
            return type(fallback)
        except NoAvailableSourceError:
            continue

    raise NoAvailableSourceError(
        f"Data source '{source}' is unavailable and no fallback found."
    )
