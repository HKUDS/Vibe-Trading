"""Curated read/write classification for Exness Trader API operations.

Keys are the OpenAPI ``operationId`` values the connector touches plus its own
public order methods. Anything not listed resolves to WRITE (fail-closed) when
the live gate consults this map.
"""

from __future__ import annotations

from src.live.classification import ToolClass

EXNESS_TOOL_CLASS: dict[str, ToolClass] = {
    # READ
    "getAccountDetails": ToolClass.READ,
    "getAvailableInstrumentList": ToolClass.READ,
    "getInstrumentCondition": ToolClass.READ,
    "getLimits": ToolClass.READ,
    "getTradingStateSnapshot": ToolClass.READ,
    "getOperationStatus": ToolClass.READ,
    "getOrdersHistory": ToolClass.READ,
    "getDealsHistory": ToolClass.READ,
    "getCandleHistory": ToolClass.READ,
    # WRITE
    "openPosition": ToolClass.WRITE,
    "placePendingOrder": ToolClass.WRITE,
    "modifyOrder": ToolClass.WRITE,
    "cancelPendingOrder": ToolClass.WRITE,
    "closePosition": ToolClass.WRITE,
    "place_order": ToolClass.WRITE,
    "cancel_order": ToolClass.WRITE,
    "close_position": ToolClass.WRITE,
}
