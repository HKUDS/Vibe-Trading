"""Curated read/write classification for KIS SDK operations.

Keys are the connector's own operation names. Order-mutating SDK calls are
pinned WRITE so the live gate never treats them as plain reads; anything
unlisted and not a known read is treated as WRITE (fail-closed) by the gate.
"""

from __future__ import annotations

from src.live.classification import ToolClass

#: KIS REST operation read/write catalog.
KIS_TOOL_CLASS: dict[str, ToolClass] = {
    # READ
    "get_account_snapshot": ToolClass.READ,
    "get_positions": ToolClass.READ,
    "get_open_orders": ToolClass.READ,
    "get_quote": ToolClass.READ,
    "get_historical_bars": ToolClass.READ,
    # WRITE
    "place_order": ToolClass.WRITE,
    "cancel_order": ToolClass.WRITE,
}
