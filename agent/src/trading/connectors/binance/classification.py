"""Curated read/write classification for supported Binance ccxt operations.

Keys are the ccxt unified method names this connector uses. Order-mutating ccxt
calls are pinned WRITE so the live gate never treats them as plain reads;
anything unlisted and not a known read is treated as WRITE (fail-closed) by the
gate.
"""

from __future__ import annotations

from src.live.classification import ToolClass

#: Binance ccxt operation read/write catalog, including two USD-M signed reads.
BINANCE_TOOL_CLASS: dict[str, ToolClass] = {
    # READ
    "fetch_balance": ToolClass.READ,
    "fetch_open_orders": ToolClass.READ,
    "fetch_my_trades": ToolClass.READ,
    "fetch_ticker": ToolClass.READ,
    "fetch_ohlcv": ToolClass.READ,
    "load_markets": ToolClass.READ,
    "fapiprivatev2_get_account": ToolClass.READ,
    "fapiprivatev3_get_positionrisk": ToolClass.READ,
    # WRITE
    "create_order": ToolClass.WRITE,
    "cancel_order": ToolClass.WRITE,
}
