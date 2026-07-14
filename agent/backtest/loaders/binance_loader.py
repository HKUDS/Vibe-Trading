"""Binance spot / USD-M perpetual OHLCV loader (via CCXT).

Dedicated source name ``binance`` so it can sit **alongside** ``okx`` in the
crypto auto-fallback chain — not as a replacement. Public market data only;
no API key required.

Use explicitly with ``source="binance"``, or let ``source="auto"`` fall through
to Binance when OKX is unavailable.
"""

from __future__ import annotations

from typing import Any

from backtest.loaders.ccxt_loader import (
    _CCXT_TIMEOUT_MS,
    _ccxt_proxy_config,
)
from backtest.loaders.ccxt_loader import DataLoader as CcxtDataLoader
from backtest.loaders.registry import register


@register
class DataLoader(CcxtDataLoader):
    """Binance-only crypto OHLCV loader (public REST via CCXT)."""

    name = "binance"
    markets = {"crypto"}
    requires_auth = False

    def _get_exchange(self, instrument_type: str = "spot") -> Any:
        """Always use Binance spot or Binance USD-M (swap), ignore CCXT_EXCHANGE."""
        import ccxt

        if instrument_type == "swap":
            exchange_cls = ccxt.binanceusdm
        else:
            exchange_cls = ccxt.binance

        config: dict[str, Any] = {"enableRateLimit": True, "timeout": _CCXT_TIMEOUT_MS}
        proxies = _ccxt_proxy_config()
        if proxies:
            config["proxies"] = proxies
        return exchange_cls(config)
