"""Curated read/write classification for Toss Securities SDK operations.

Keys are the connector's own operation names. Order-mutating SDK calls are
pinned WRITE so the live gate never treats them as plain reads; anything
unlisted and not a known read is treated as WRITE (fail-closed) by the gate.
``place_order``/``cancel_order`` always refuse (see ``sdk.py``), but stay
classified WRITE for defense in depth.
"""

from __future__ import annotations

from src.live.classification import ToolClass

#: Toss Securities REST operation read/write catalog.
TOSS_TOOL_CLASS: dict[str, ToolClass] = {
    # READ
    "get_account_snapshot": ToolClass.READ,
    "get_positions": ToolClass.READ,
    "get_open_orders": ToolClass.READ,
    "get_quote": ToolClass.READ,
    "get_historical_bars": ToolClass.READ,
    # WRITE (always refused, see sdk.place_order/cancel_order)
    "place_order": ToolClass.WRITE,
    "cancel_order": ToolClass.WRITE,
}
