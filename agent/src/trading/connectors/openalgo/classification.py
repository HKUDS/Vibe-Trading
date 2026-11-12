"""Curated OpenAlgo operations; unsupported or unknown calls never become reads.

Keys are the connector's own operation names. ``place_order``/``cancel_order``
always refuse before any network call (see ``sdk.py``) but stay pinned WRITE so
the live gate fails closed if a future caller reaches them another way.
"""

from __future__ import annotations

from src.live.classification import ToolClass

OPENALGO_TOOL_CLASS: dict[str, ToolClass] = {
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
